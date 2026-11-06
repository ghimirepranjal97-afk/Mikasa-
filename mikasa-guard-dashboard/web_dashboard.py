"""
Mikasa Guard — web dashboard (Render-compatible).

Started from Mikasa.py main() via: await start_dashboard(bot)

Uses the same data/*.json files the bot already reads/writes.
Only exposes features that exist in Mikasa.py (Anti-Nuke, RaidWatch,
Anti-Alt, Quarantine, Verification, Antibot, AutoMod, Warnings, Logs, etc.).

Env (Render):
  PORT                 — listen port (Render sets this)
  DISCORD_CLIENT_ID    — OAuth2 application client id
  DISCORD_CLIENT_SECRET
  DISCORD_REDIRECT_URI — e.g. https://your-app.onrender.com/callback
  DASHBOARD_SECRET     — session signing key (any long random string)
  PUBLIC_BASE_URL      — optional; used for redirect URI fallback
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from aiohttp import ClientSession, web

# ── Paths (same layout the bot uses) ─────────────────────────────────────
# DATA_DIR matches Mikasa's Path("data") so both share the same JSON files
# when the process CWD is the project root (normal on Render).
ROOT = Path(__file__).resolve().parent
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR = ROOT / "dashboard" / "static"
TEMPLATES_DIR = ROOT / "dashboard" / "templates"

# ── OAuth / session config ───────────────────────────────────────────────
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "").strip()
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
SESSION_SECRET = os.getenv("DASHBOARD_SECRET", secrets.token_hex(32))
PORT = int(os.getenv("PORT", "8080"))
SCOPES = "identify guilds"

# In-memory sessions: token → {user, guilds, expires}
_SESSIONS: dict[str, dict] = {}
# CSRF state → created_at
_OAUTH_STATES: dict[str, float] = {}

# Shared bot reference (set by start_dashboard)
_BOT = None


def _load_json(name: str) -> Any:
    p = DATA_DIR / f"{name}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(name: str, data: Any) -> None:
    p = DATA_DIR / f"{name}.json"
    try:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as ex:
        print(f"[dashboard save] {name}: {ex}")


def _gdata(settings: dict, guild_id: int | str) -> dict:
    key = str(guild_id)
    if key not in settings:
        settings[key] = {}
    return settings[key]


def _redirect_uri(request: web.Request) -> str:
    if REDIRECT_URI:
        return REDIRECT_URI
    if PUBLIC_BASE:
        return f"{PUBLIC_BASE}/callback"
    # Fallback from request host (works behind Render if Host is correct)
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}/callback"


def _session_from_request(request: web.Request) -> Optional[dict]:
    token = request.cookies.get("mikasa_session")
    if not token:
        return None
    sess = _SESSIONS.get(token)
    if not sess:
        return None
    if sess.get("expires", 0) < time.time():
        _SESSIONS.pop(token, None)
        return None
    return sess


def _require_session(request: web.Request) -> Optional[dict]:
    return _session_from_request(request)


def _owner_ids() -> set[int]:
    """Resolve owner IDs without requiring Mikasa to be importable as a module."""
    ids: set[int] = set()
    try:
        import __main__
        for name in ("OWNER_IDS", "CO_OWNER_IDS"):
            val = getattr(__main__, name, None)
            if isinstance(val, (set, list, tuple)):
                ids.update(int(x) for x in val)
    except Exception:
        pass
    if _BOT is not None:
        for name in ("OWNER_IDS", "CO_OWNER_IDS"):
            val = getattr(_BOT, name, None)
            if isinstance(val, (set, list, tuple)):
                ids.update(int(x) for x in val)
    return ids


def _user_can_manage_guild(sess: dict, guild_id: str) -> bool:
    for g in sess.get("guilds", []):
        if str(g.get("id")) == str(guild_id):
            # Manage Guild = 0x20, Administrator = 0x8
            perms = int(g.get("permissions", 0) or 0)
            return bool(perms & 0x20) or bool(perms & 0x8) or g.get("owner")
    try:
        uid = int(sess.get("user", {}).get("id", 0))
        if uid in _owner_ids():
            return True
    except Exception:
        pass
    return False


def _bot_guild_ids() -> set[str]:
    if _BOT is None:
        return set()
    return {str(g.id) for g in _BOT.guilds}


def _guild_object(guild_id: str):
    if _BOT is None:
        return None
    try:
        return _BOT.get_guild(int(guild_id))
    except Exception:
        return None


# ── HTML pages ───────────────────────────────────────────────────────────

def _read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"<!-- missing template {name} -->"


async def handle_index(request: web.Request) -> web.Response:
    sess = _session_from_request(request)
    if sess:
        raise web.HTTPFound("/dashboard")
    html = _read_template("authorize.html")
    return web.Response(text=html, content_type="text/html")


async def handle_login(request: web.Request) -> web.Response:
    if not CLIENT_ID:
        return web.Response(
            text="Dashboard OAuth is not configured. Set DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, and DISCORD_REDIRECT_URI on Render.",
            status=500,
        )
    state = secrets.token_urlsafe(24)
    _OAUTH_STATES[state] = time.time()
    # prune old states
    cutoff = time.time() - 600
    for k, t in list(_OAUTH_STATES.items()):
        if t < cutoff:
            _OAUTH_STATES.pop(k, None)
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "prompt": "consent",
    }
    url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    raise web.HTTPFound(url)


async def handle_callback(request: web.Request) -> web.Response:
    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state or state not in _OAUTH_STATES:
        raise web.HTTPFound("/?error=oauth")
    _OAUTH_STATES.pop(state, None)

    redirect = _redirect_uri(request)
    async with ClientSession() as session:
        # Token exchange
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
        }
        async with session.post(
            "https://discord.com/api/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(f"[dashboard oauth] token exchange failed: {resp.status} {body[:300]}")
                raise web.HTTPFound("/?error=token")
            token_data = await resp.json()

        access = token_data.get("access_token")
        if not access:
            raise web.HTTPFound("/?error=token")

        headers = {"Authorization": f"Bearer {access}"}
        async with session.get("https://discord.com/api/users/@me", headers=headers) as resp:
            user = await resp.json()
        async with session.get("https://discord.com/api/users/@me/guilds", headers=headers) as resp:
            guilds = await resp.json() if resp.status == 200 else []

    # Keep only guilds the bot is in and user can manage
    bot_ids = _bot_guild_ids()
    managed = []
    for g in guilds if isinstance(guilds, list) else []:
        gid = str(g.get("id", ""))
        if bot_ids and gid not in bot_ids:
            continue
        perms = int(g.get("permissions", 0) or 0)
        if not (perms & 0x20 or perms & 0x8 or g.get("owner")):
            continue
        managed.append({
            "id": gid,
            "name": g.get("name", "Unknown"),
            "icon": g.get("icon"),
            "owner": bool(g.get("owner")),
            "permissions": perms,
        })

    session_token = secrets.token_urlsafe(32)
    _SESSIONS[session_token] = {
        "user": {
            "id": str(user.get("id")),
            "username": user.get("username"),
            "global_name": user.get("global_name") or user.get("username"),
            "avatar": user.get("avatar"),
            "discriminator": user.get("discriminator", "0"),
        },
        "guilds": managed,
        "expires": time.time() + 60 * 60 * 12,  # 12h
    }

    response = web.HTTPFound("/dashboard")
    response.set_cookie(
        "mikasa_session",
        session_token,
        max_age=60 * 60 * 12,
        httponly=True,
        samesite="Lax",
        secure=True if PUBLIC_BASE.startswith("https") or REDIRECT_URI.startswith("https") else False,
        path="/",
    )
    raise response


async def handle_logout(request: web.Request) -> web.Response:
    token = request.cookies.get("mikasa_session")
    if token:
        _SESSIONS.pop(token, None)
    response = web.HTTPFound("/")
    response.del_cookie("mikasa_session", path="/")
    raise response


async def handle_dashboard(request: web.Request) -> web.Response:
    sess = _require_session(request)
    if not sess:
        raise web.HTTPFound("/")
    html = _read_template("dashboard.html")
    return web.Response(text=html, content_type="text/html")


# ── API ──────────────────────────────────────────────────────────────────

async def api_me(request: web.Request) -> web.Response:
    sess = _require_session(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    bot_ids = _bot_guild_ids()
    guilds = []
    for g in sess.get("guilds", []):
        if bot_ids and str(g["id"]) not in bot_ids:
            continue
        guild_obj = _guild_object(g["id"])
        icon_url = None
        if g.get("icon"):
            icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=64"
        elif guild_obj and guild_obj.icon:
            icon_url = str(guild_obj.icon.url)
        member_count = guild_obj.member_count if guild_obj else None
        guilds.append({
            "id": g["id"],
            "name": guild_obj.name if guild_obj else g["name"],
            "icon_url": icon_url,
            "member_count": member_count,
        })
    return web.json_response({
        "user": sess["user"],
        "guilds": guilds,
        "bot_online": _BOT is not None and getattr(_BOT, "is_ready", lambda: False)(),
    })


def _build_overview(guild_id: str) -> dict:
    settings = _load_json("server_settings")
    gs = _gdata(settings, guild_id) if isinstance(settings, dict) else {}
    anti_alt = _load_json("anti_alt_settings")
    aa = anti_alt.get(str(guild_id), {}) if isinstance(anti_alt, dict) else {}
    automod = _load_json("paidbot_automod")
    am = automod.get(str(guild_id), {}) if isinstance(automod, dict) else {}
    verify = _load_json("verification_settings")
    vf = verify.get(str(guild_id), {}) if isinstance(verify, dict) else {}

    guild = _guild_object(guild_id)
    latency_ms = None
    uptime_str = None
    if _BOT is not None:
        try:
            latency_ms = round(_BOT.latency * 1000)
        except Exception:
            pass
        start = getattr(_BOT, "_start_time", None)
        if start is not None:
            try:
                delta = time.time() - start.timestamp()
                h = int(delta // 3600)
                m = int((delta % 3600) // 60)
                uptime_str = f"{h}h {m}m"
            except Exception:
                pass

    antinuke_on = bool(gs.get("antinuke_enabled", False))
    raidwatch_on = bool(gs.get("raidwatch_enabled", False))
    raidwatch_threshold = int(gs.get("raidwatch_threshold", 8) or 8)
    antibot_on = bool(gs.get("antibot_enabled", True))
    antialt_on = bool(aa.get("enabled", True)) if aa else True
    antialt_minage = int(aa.get("min_account_days", 3) if aa else 3)
    antialt_action = str(aa.get("action", "alert") if aa else "alert")
    quarantine_role_id = aa.get("quarantine_role_id") if aa else None
    automod_on = bool(am.get("enabled", False)) if am else False
    verify_on = bool(vf.get("enabled", False)) if isinstance(vf, dict) else False

    log_ch = (
        gs.get("mikasa_all_logs_channel")
        or gs.get("security_log_channel")
        or gs.get("antinuke_channel")
        or gs.get("antinuke_alert_channel")
    )

    # Whitelist counts
    wl = gs.get("antinuke_whitelist", {})
    if isinstance(wl, list):
        wl_users = len(wl)
        wl_roles = 0
    elif isinstance(wl, dict):
        wl_users = len(wl)
        role_wl = gs.get("antinuke_role_whitelist", {})
        wl_roles = len(role_wl) if isinstance(role_wl, dict) else 0
    else:
        wl_users = wl_roles = 0

    # Warnings count for guild
    warnings = _load_json("warnings")
    warn_count = 0
    if isinstance(warnings, dict):
        gwarn = warnings.get(str(guild_id), {})
        if isinstance(gwarn, dict):
            warn_count = sum(len(v) if isinstance(v, list) else 0 for v in gwarn.values())

    channel_count = len(guild.channels) if guild else None
    role_count = len(guild.roles) - 1 if guild else None  # exclude @everyone
    member_count = guild.member_count if guild else None

    return {
        "guild_id": guild_id,
        "guild_name": guild.name if guild else "Unknown",
        "member_count": member_count,
        "channel_count": channel_count,
        "role_count": role_count,
        "gateway_ms": latency_ms,
        "uptime": uptime_str,
        "antinuke": {
            "enabled": antinuke_on,
            "whitelist_users": wl_users,
            "whitelist_roles": wl_roles,
        },
        "raidwatch": {
            "enabled": raidwatch_on,
            "threshold": raidwatch_threshold,
        },
        "antibot": {"enabled": antibot_on},
        "antialt": {
            "enabled": antialt_on,
            "min_account_days": antialt_minage,
            "action": antialt_action,
            "quarantine_role_id": str(quarantine_role_id) if quarantine_role_id else None,
        },
        "automod": {"enabled": automod_on},
        "verification": {"enabled": verify_on},
        "logs": {
            "channel_id": str(log_ch) if log_ch else None,
        },
        "warnings_total": warn_count,
        "emergency_lockdown": bool(gs.get("emergency_lockdown_active", False)),
    }


async def api_guild_overview(request: web.Request) -> web.Response:
    sess = _require_session(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    guild_id = request.match_info["guild_id"]
    if not _user_can_manage_guild(sess, guild_id):
        return web.json_response({"error": "forbidden"}, status=403)
    if _bot_guild_ids() and guild_id not in _bot_guild_ids():
        return web.json_response({"error": "bot_not_in_guild"}, status=404)
    return web.json_response(_build_overview(guild_id))


async def api_guild_section(request: web.Request) -> web.Response:
    """Detailed section data for sidebar pages."""
    sess = _require_session(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    guild_id = request.match_info["guild_id"]
    section = request.match_info["section"]
    if not _user_can_manage_guild(sess, guild_id):
        return web.json_response({"error": "forbidden"}, status=403)

    settings = _load_json("server_settings")
    gs = _gdata(settings, guild_id) if isinstance(settings, dict) else {}
    guild = _guild_object(guild_id)

    if section == "antinuke":
        wl = gs.get("antinuke_whitelist", {})
        role_wl = gs.get("antinuke_role_whitelist", {})
        return web.json_response({
            "enabled": bool(gs.get("antinuke_enabled", False)),
            "whitelist": wl if isinstance(wl, dict) else {},
            "role_whitelist": role_wl if isinstance(role_wl, dict) else {},
            "alert_channel_id": str(gs.get("antinuke_channel") or gs.get("antinuke_alert_channel") or "") or None,
            "description": (
                "Protects against mass channel/role deletes, mass bans/kicks, "
                "webhook abuse, and unauthorized server edits. "
                "Configure with ,antinuke on|off|status|whitelist in Discord."
            ),
        })

    if section == "raidwatch":
        return web.json_response({
            "enabled": bool(gs.get("raidwatch_enabled", False)),
            "threshold": int(gs.get("raidwatch_threshold", 8) or 8),
            "description": (
                "Join-burst alerts when many members join in a short window. "
                "Use ,raidwatch on|off|status and ,raidwatch threshold <5-25>."
            ),
        })

    if section == "antialt":
        anti_alt = _load_json("anti_alt_settings")
        aa = anti_alt.get(str(guild_id), {}) if isinstance(anti_alt, dict) else {}
        return web.json_response({
            "enabled": bool(aa.get("enabled", True)) if aa else True,
            "min_account_days": int(aa.get("min_account_days", 3) if aa else 3),
            "action": str(aa.get("action", "alert") if aa else "alert"),
            "log_channel_id": str(aa.get("log_channel_id") or "") or None,
            "quarantine_role_id": str(aa.get("quarantine_role_id") or "") or None,
            "description": (
                "Flags new Discord accounts under the age threshold. "
                "Default action is alert-only. Configure with ,antialt."
            ),
        })

    if section == "quarantine":
        anti_alt = _load_json("anti_alt_settings")
        aa = anti_alt.get(str(guild_id), {}) if isinstance(anti_alt, dict) else {}
        role_id = aa.get("quarantine_role_id")
        role_name = None
        if guild and role_id:
            role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
            role_name = role.name if role else None
        return web.json_response({
            "quarantine_role_id": str(role_id) if role_id else None,
            "quarantine_role_name": role_name,
            "antialt_action": str(aa.get("action", "alert") if aa else "alert"),
            "description": (
                "Quarantine role is assigned when anti-alt action is set to quarantine. "
                "Set with ,antialt quarantine @role and ,antialt action quarantine."
            ),
        })

    if section == "verification":
        verify = _load_json("verification_settings")
        vf = verify.get(str(guild_id), {}) if isinstance(verify, dict) else {}
        role_id = vf.get("role_id") or vf.get("verified_role_id")
        channel_id = vf.get("channel_id")
        role_name = channel_name = None
        if guild:
            if role_id and str(role_id).isdigit():
                r = guild.get_role(int(role_id))
                role_name = r.name if r else None
            if channel_id and str(channel_id).isdigit():
                c = guild.get_channel(int(channel_id))
                channel_name = c.name if c else None
        return web.json_response({
            "enabled": bool(vf.get("enabled", False)) if isinstance(vf, dict) else False,
            "role_id": str(role_id) if role_id else None,
            "role_name": role_name,
            "channel_id": str(channel_id) if channel_id else None,
            "channel_name": channel_name,
            "description": "Persistent verification panel. Configure with ,verifysetup @role #channel.",
        })

    if section == "antibot":
        allowed_bots = gs.get("allowed_bots") or []
        allowed_users = gs.get("bot_allowed_users") or []
        return web.json_response({
            "enabled": bool(gs.get("antibot_enabled", True)),
            "allowed_bots": [str(x) for x in allowed_bots],
            "allowed_inviters": [str(x) for x in allowed_users],
            "description": (
                "Kicks unknown bots on join when anti-nuke is also enabled. "
                "Use ,antibot on|off|status and ,botallow / ,allowbot."
            ),
        })

    if section == "automod":
        automod = _load_json("paidbot_automod")
        am = automod.get(str(guild_id), {}) if isinstance(automod, dict) else {}
        filters = am.get("filters", {}) if isinstance(am.get("filters"), dict) else {}
        return web.json_response({
            "enabled": bool(am.get("enabled", False)),
            "filters": filters,
            "log_channel_id": str(am.get("log_channel_id") or "") or None,
            "bad_words_count": len(am.get("bad_words", []) or []),
            "allowed_domains_count": len(am.get("allowed_domains", []) or []),
            "description": "Message filters for caps, invites, bad words, links, mentions, zalgo, spam. Use ,automod.",
        })

    if section == "warnings":
        warnings = _load_json("warnings")
        gwarn = warnings.get(str(guild_id), {}) if isinstance(warnings, dict) else {}
        rows = []
        if isinstance(gwarn, dict):
            for uid, entries in list(gwarn.items())[:50]:
                if not isinstance(entries, list):
                    continue
                member_name = uid
                if guild:
                    m = guild.get_member(int(uid)) if str(uid).isdigit() else None
                    if m:
                        member_name = str(m)
                rows.append({"user_id": uid, "user": member_name, "count": len(entries)})
        rows.sort(key=lambda x: x["count"], reverse=True)
        return web.json_response({
            "entries": rows,
            "total_warned_users": len(rows),
            "description": "Moderation warnings stored by the bot. Use ,warn and ,warnings in Discord.",
        })

    if section == "members":
        if not guild:
            return web.json_response({"error": "guild_unavailable", "member_count": None})
        # Lightweight stats only — no full member dump
        bots = sum(1 for m in guild.members if m.bot)
        humans = guild.member_count - bots if guild.member_count else len([m for m in guild.members if not m.bot])
        return web.json_response({
            "member_count": guild.member_count,
            "humans": humans,
            "bots": bots,
            "roles": len(guild.roles) - 1,
            "channels": len(guild.channels),
            "description": "Live counts from the bot's cache for this server.",
        })

    if section == "logs":
        return web.json_response({
            "mikasa_all_logs_channel": str(gs.get("mikasa_all_logs_channel") or "") or None,
            "security_log_channel": str(gs.get("security_log_channel") or "") or None,
            "antinuke_channel": str(gs.get("antinuke_channel") or gs.get("antinuke_alert_channel") or "") or None,
            "description": "Unified and security log channels. Use ,setalllogs #channel or ,setlog #channel.",
        })

    return web.json_response({"error": "unknown_section"}, status=404)


async def api_toggle(request: web.Request) -> web.Response:
    """Toggle settings that the bot already supports via JSON files."""
    sess = _require_session(request)
    if not sess:
        return web.json_response({"error": "unauthorized"}, status=401)
    guild_id = request.match_info["guild_id"]
    if not _user_can_manage_guild(sess, guild_id):
        return web.json_response({"error": "forbidden"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)

    feature = str(body.get("feature", "")).lower()
    enabled = body.get("enabled")
    if enabled is None:
        return web.json_response({"error": "missing_enabled"}, status=400)
    enabled = bool(enabled)

    settings = _load_json("server_settings")
    if not isinstance(settings, dict):
        settings = {}
    gs = _gdata(settings, guild_id)

    if feature == "antinuke":
        gs["antinuke_enabled"] = enabled
        _save_json("server_settings", settings)
        return web.json_response({"ok": True, "feature": feature, "enabled": enabled})

    if feature == "raidwatch":
        gs["raidwatch_enabled"] = enabled
        _save_json("server_settings", settings)
        return web.json_response({"ok": True, "feature": feature, "enabled": enabled})

    if feature == "antibot":
        gs["antibot_enabled"] = enabled
        _save_json("server_settings", settings)
        return web.json_response({"ok": True, "feature": feature, "enabled": enabled})

    if feature == "antialt":
        anti_alt = _load_json("anti_alt_settings")
        if not isinstance(anti_alt, dict):
            anti_alt = {}
        cfg = anti_alt.get(str(guild_id), {})
        if not isinstance(cfg, dict):
            cfg = {}
        cfg["enabled"] = enabled
        anti_alt[str(guild_id)] = cfg
        _save_json("anti_alt_settings", anti_alt)
        return web.json_response({"ok": True, "feature": feature, "enabled": enabled})

    if feature == "automod":
        automod = _load_json("paidbot_automod")
        if not isinstance(automod, dict):
            automod = {}
        am = automod.get(str(guild_id), {})
        if not isinstance(am, dict):
            am = {}
        am["enabled"] = enabled
        automod[str(guild_id)] = am
        _save_json("paidbot_automod", automod)
        return web.json_response({"ok": True, "feature": feature, "enabled": enabled})

    if feature == "raidwatch_threshold":
        try:
            value = int(body.get("value", 8))
        except (TypeError, ValueError):
            return web.json_response({"error": "invalid_value"}, status=400)
        value = max(5, min(25, value))
        gs["raidwatch_threshold"] = value
        _save_json("server_settings", settings)
        return web.json_response({"ok": True, "feature": feature, "value": value})

    return web.json_response({"error": "unsupported_feature"}, status=400)


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "bot_ready": bool(_BOT and getattr(_BOT, "is_ready", lambda: False)()),
        "guilds": len(_BOT.guilds) if _BOT else 0,
    })


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/login", handle_login)
    app.router.add_get("/callback", handle_callback)
    app.router.add_get("/logout", handle_logout)
    app.router.add_get("/dashboard", handle_dashboard)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/guild/{guild_id}/overview", api_guild_overview)
    app.router.add_get("/api/guild/{guild_id}/section/{section}", api_guild_section)
    app.router.add_post("/api/guild/{guild_id}/toggle", api_toggle)
    if STATIC_DIR.exists():
        app.router.add_static("/static/", path=str(STATIC_DIR), name="static")
    return app


async def start_dashboard(bot) -> Optional[web.AppRunner]:
    """Called from Mikasa main(). Starts aiohttp on PORT for Render health checks."""
    global _BOT
    _BOT = bot

    if not CLIENT_ID or not CLIENT_SECRET:
        print(
            "[dashboard] DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET not set — "
            "authorize page will show a config message. Bot still runs."
        )

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[dashboard] listening on 0.0.0.0:{PORT}")
    return runner
