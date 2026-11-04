"""
Mikasa web dashboard — runs in the same process as the Discord bot.
Serves a status UI on $PORT so Render health checks stay green.
Protect sensitive pages with DASHBOARD_SECRET (optional but recommended).
"""
from __future__ import annotations

import os
import time
import json
import hmac
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional

from aiohttp import web

# ── Config ──────────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "10000")))
DASHBOARD_SECRET = (os.getenv("DASHBOARD_SECRET") or "").strip()
DASHBOARD_TITLE = os.getenv("DASHBOARD_TITLE", "Mikasa Dashboard")
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
_STARTED_AT = time.monotonic()
_BOT_REF = None  # set by attach_bot()


def attach_bot(bot) -> None:
    """Call once after the discord.Client/Bot is created."""
    global _BOT_REF
    _BOT_REF = bot


def _uptime_text() -> str:
    seconds = max(0, int(time.monotonic() - _STARTED_AT))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _load_json(name: str) -> Any:
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _economy_summary() -> dict:
    data = _load_json("economy")
    if not isinstance(data, dict):
        return {"accounts": 0, "wallet": 0, "bank": 0, "total": 0}
    accounts = wallet = bank = 0
    for row in data.values():
        if not isinstance(row, dict):
            continue
        accounts += 1
        try:
            wallet += max(0, int(row.get("balance", 0) or 0))
            bank += max(0, int(row.get("bank", 0) or 0))
        except (TypeError, ValueError):
            pass
    return {"accounts": accounts, "wallet": wallet, "bank": bank, "total": wallet + bank}


def _check_auth(request: web.Request) -> bool:
    """If DASHBOARD_SECRET is set, require ?key= or Authorization: Bearer."""
    if not DASHBOARD_SECRET:
        return True
    key = request.rel_url.query.get("key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    cookie = request.cookies.get("mikasa_dash")
    if key and hmac.compare_digest(key, DASHBOARD_SECRET):
        return True
    if cookie and hmac.compare_digest(cookie, _cookie_token()):
        return True
    return False


def _cookie_token() -> str:
    return hashlib.sha256(f"mikasa:{DASHBOARD_SECRET}".encode()).hexdigest()[:48]


def _bot_snapshot() -> dict:
    bot = _BOT_REF
    if bot is None:
        return {
            "ready": False,
            "user": None,
            "latency_ms": None,
            "guilds": 0,
            "users": 0,
            "commands": 0,
            "guild_list": [],
        }
    guilds = list(getattr(bot, "guilds", []) or [])
    users = sum(getattr(g, "member_count", 0) or len(getattr(g, "members", [])) for g in guilds)
    try:
        cmd_count = len(list(bot.walk_commands()))
    except Exception:
        cmd_count = 0
    latency = None
    try:
        if bot.latency is not None:
            latency = round(bot.latency * 1000)
    except Exception:
        pass
    user = None
    if bot.user:
        user = {
            "id": str(bot.user.id),
            "name": str(bot.user),
            "avatar": str(bot.user.display_avatar.url) if bot.user.display_avatar else None,
        }
    guild_list = []
    for g in sorted(guilds, key=lambda x: (x.member_count or 0), reverse=True)[:40]:
        guild_list.append({
            "id": str(g.id),
            "name": g.name,
            "members": g.member_count or len(g.members),
            "channels": len(g.channels),
            "owner_id": str(g.owner_id) if g.owner_id else None,
        })
    return {
        "ready": bool(bot.is_ready()),
        "user": user,
        "latency_ms": latency,
        "guilds": len(guilds),
        "users": users,
        "commands": cmd_count,
        "guild_list": guild_list,
    }


async def handle_health(request: web.Request) -> web.Response:
    """Render / platform health probe — always 200 once the process is up."""
    return web.json_response({
        "status": "ok",
        "service": "mikasa",
        "uptime": _uptime_text(),
        "bot_ready": bool(_BOT_REF and _BOT_REF.is_ready()),
    })


async def handle_api_status(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    snap = _bot_snapshot()
    eco = _economy_summary()
    return web.json_response({
        "title": DASHBOARD_TITLE,
        "uptime": _uptime_text(),
        "bot": snap,
        "economy": eco,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def handle_login(request: web.Request) -> web.Response:
    if not DASHBOARD_SECRET:
        raise web.HTTPFound("/")
    if request.method == "POST":
        data = await request.post()
        key = str(data.get("key", "")).strip()
        if key and hmac.compare_digest(key, DASHBOARD_SECRET):
            resp = web.HTTPFound("/")
            resp.set_cookie("mikasa_dash", _cookie_token(), max_age=60 * 60 * 24 * 14, httponly=True, samesite="Lax")
            raise resp
        return web.Response(text=_login_html(error=True), content_type="text/html")
    return web.Response(text=_login_html(error=False), content_type="text/html")


async def handle_dashboard(request: web.Request) -> web.Response:
    if DASHBOARD_SECRET and not _check_auth(request):
        raise web.HTTPFound("/login")
    # Allow ?key= to set cookie once
    key = request.rel_url.query.get("key")
    if key and DASHBOARD_SECRET and hmac.compare_digest(key, DASHBOARD_SECRET):
        resp = web.HTTPFound("/")
        resp.set_cookie("mikasa_dash", _cookie_token(), max_age=60 * 60 * 24 * 14, httponly=True, samesite="Lax")
        raise resp
    return web.Response(text=_dashboard_html(), content_type="text/html")


def _login_html(error: bool = False) -> str:
    err = '<p class="err">Invalid key. Try again.</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Login · {DASHBOARD_TITLE}</title>
<style>{_CSS}</style></head>
<body class="center">
<form class="card login" method="post" action="/login">
  <h1>🛡️ Mikasa</h1>
  <p class="muted">Enter your dashboard secret to continue.</p>
  {err}
  <input type="password" name="key" placeholder="DASHBOARD_SECRET" autofocus required/>
  <button type="submit">Unlock dashboard</button>
</form>
</body></html>"""


def _dashboard_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{DASHBOARD_TITLE}</title>
<style>{_CSS}</style></head>
<body>
<header class="top">
  <div class="brand">
    <span class="logo">🛡️</span>
    <div>
      <strong id="title">{DASHBOARD_TITLE}</strong>
      <div class="muted" id="bot-name">Connecting…</div>
    </div>
  </div>
  <div class="top-meta">
    <span class="pill" id="status-pill">…</span>
    <span class="muted" id="clock"></span>
  </div>
</header>

<main>
  <section class="grid stats" id="stats">
    <div class="card stat"><div class="label">Latency</div><div class="value" id="s-latency">—</div></div>
    <div class="card stat"><div class="label">Uptime</div><div class="value" id="s-uptime">—</div></div>
    <div class="card stat"><div class="label">Servers</div><div class="value" id="s-guilds">—</div></div>
    <div class="card stat"><div class="label">Members</div><div class="value" id="s-users">—</div></div>
    <div class="card stat"><div class="label">Commands</div><div class="value" id="s-cmds">—</div></div>
    <div class="card stat"><div class="label">Economy accounts</div><div class="value" id="s-eco">—</div></div>
  </section>

  <section class="grid two">
    <div class="card">
      <h2>Economy overview</h2>
      <div class="row"><span>Wallet total</span><strong id="eco-wallet">—</strong></div>
      <div class="row"><span>Bank total</span><strong id="eco-bank">—</strong></div>
      <div class="row"><span>Combined</span><strong id="eco-total">—</strong></div>
      <p class="muted tiny">Virtual in-bot currency only. No real-money value.</p>
    </div>
    <div class="card">
      <h2>Bot identity</h2>
      <div class="identity">
        <img id="bot-avatar" alt="" width="64" height="64"/>
        <div>
          <div id="bot-display">—</div>
          <div class="muted mono" id="bot-id">—</div>
          <div class="muted" id="bot-ready">—</div>
        </div>
      </div>
    </div>
  </section>

  <section class="card">
    <div class="table-head">
      <h2>Servers</h2>
      <span class="muted" id="guild-count"></span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Name</th><th>Members</th><th>Channels</th><th>ID</th></tr></thead>
        <tbody id="guild-body"><tr><td colspan="4" class="muted">Loading…</td></tr></tbody>
      </table>
    </div>
  </section>
</main>

<footer>
  <span>Mikasa · Render dashboard</span>
  <span class="muted" id="refresh-note">Auto-refresh every 15s</span>
</footer>

<script>
const fmt = n => (n == null || n === undefined) ? '—' : Number(n).toLocaleString();
async function refresh() {{
  try {{
    const r = await fetch('/api/status', {{ credentials: 'same-origin' }});
    if (r.status === 401) {{ window.location = '/login'; return; }}
    const d = await r.json();
    document.getElementById('title').textContent = d.title || 'Mikasa Dashboard';
    const b = d.bot || {{}};
    const eco = d.economy || {{}};
    const ready = !!b.ready;
    const pill = document.getElementById('status-pill');
    pill.textContent = ready ? 'Online' : 'Starting';
    pill.className = 'pill ' + (ready ? 'ok' : 'warn');
    document.getElementById('s-latency').textContent = b.latency_ms != null ? (b.latency_ms + ' ms') : '—';
    document.getElementById('s-uptime').textContent = d.uptime || '—';
    document.getElementById('s-guilds').textContent = fmt(b.guilds);
    document.getElementById('s-users').textContent = fmt(b.users);
    document.getElementById('s-cmds').textContent = fmt(b.commands);
    document.getElementById('s-eco').textContent = fmt(eco.accounts);
    document.getElementById('eco-wallet').textContent = fmt(eco.wallet);
    document.getElementById('eco-bank').textContent = fmt(eco.bank);
    document.getElementById('eco-total').textContent = fmt(eco.total);
    if (b.user) {{
      document.getElementById('bot-name').textContent = b.user.name;
      document.getElementById('bot-display').textContent = b.user.name;
      document.getElementById('bot-id').textContent = 'ID ' + b.user.id;
      const av = document.getElementById('bot-avatar');
      if (b.user.avatar) {{ av.src = b.user.avatar; av.style.display = 'block'; }}
    }}
    document.getElementById('bot-ready').textContent = ready ? 'Gateway connected' : 'Waiting for Discord gateway…';
    const body = document.getElementById('guild-body');
    const list = b.guild_list || [];
    document.getElementById('guild-count').textContent = list.length + ' shown';
    if (!list.length) {{
      body.innerHTML = '<tr><td colspan="4" class="muted">No servers yet</td></tr>';
    }} else {{
      body.innerHTML = list.map(g =>
        '<tr><td>' + escapeHtml(g.name) + '</td><td>' + fmt(g.members) + '</td><td>' + fmt(g.channels) +
        '</td><td class="mono">' + g.id + '</td></tr>'
      ).join('');
    }}
    document.getElementById('clock').textContent = new Date(d.timestamp || Date.now()).toLocaleString();
  }} catch (e) {{
    document.getElementById('status-pill').textContent = 'Error';
    document.getElementById('status-pill').className = 'pill err';
  }}
}}
function escapeHtml(s) {{
  return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
}}
refresh();
setInterval(refresh, 15000);
</script>
</body></html>"""


_CSS = """
:root {
  --bg: #0f1115;
  --panel: #171a21;
  --panel2: #1e2330;
  --border: #2a3142;
  --text: #e8eaf0;
  --muted: #8b93a7;
  --accent: #5865f2;
  --ok: #3ba55d;
  --warn: #faa61a;
  --err: #ed4245;
  --radius: 14px;
  --font: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh;
  background: radial-gradient(1200px 600px at 10% -10%, #1a2150 0%, transparent 50%),
              radial-gradient(900px 500px at 100% 0%, #1a2a22 0%, transparent 45%),
              var(--bg);
  color: var(--text); font-family: var(--font);
}
body.center { display:flex; align-items:center; justify-content:center; padding: 24px; }
.top {
  display:flex; justify-content:space-between; align-items:center; gap:16px;
  padding: 18px 22px; border-bottom: 1px solid var(--border);
  background: rgba(23,26,33,.85); backdrop-filter: blur(10px);
  position: sticky; top: 0; z-index: 10;
}
.brand { display:flex; gap:12px; align-items:center; }
.logo { font-size: 28px; }
.top-meta { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
main { max-width: 1100px; margin: 0 auto; padding: 22px 18px 48px; }
.grid { display:grid; gap: 14px; margin-bottom: 14px; }
.stats { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.two { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.card {
  background: linear-gradient(180deg, var(--panel2), var(--panel));
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px 18px; box-shadow: 0 10px 30px rgba(0,0,0,.25);
}
.stat .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.stat .value { font-size: 26px; font-weight: 700; margin-top: 6px; }
h1,h2 { margin: 0 0 12px; font-size: 18px; }
.muted { color: var(--muted); }
.tiny { font-size: 12px; margin-top: 10px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.pill {
  display:inline-flex; align-items:center; gap:6px;
  padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
  background: #2a3142; color: var(--text);
}
.pill.ok { background: rgba(59,165,93,.2); color: #6ddf8f; }
.pill.warn { background: rgba(250,166,26,.15); color: #ffc857; }
.pill.err { background: rgba(237,66,69,.18); color: #ff8b8e; }
.row { display:flex; justify-content:space-between; gap:12px; padding: 8px 0; border-bottom: 1px solid var(--border); }
.row:last-of-type { border-bottom: none; }
.identity { display:flex; gap:14px; align-items:center; }
#bot-avatar { border-radius: 50%; display:none; background:#2a3142; }
.table-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom: 8px; }
.table-wrap { overflow:auto; max-height: 420px; }
table { width:100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align:left; padding: 10px 8px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; }
footer {
  max-width: 1100px; margin: 0 auto; padding: 0 18px 28px;
  display:flex; justify-content:space-between; gap:12px; color: var(--muted); font-size: 13px;
}
.login { width: min(380px, 100%); text-align:center; }
.login input {
  width:100%; margin: 12px 0; padding: 12px 14px; border-radius: 10px;
  border: 1px solid var(--border); background: #0f1115; color: var(--text); font-size: 15px;
}
.login button {
  width:100%; padding: 12px; border:0; border-radius: 10px; cursor:pointer;
  background: var(--accent); color: white; font-weight: 600; font-size: 15px;
}
.login button:hover { filter: brightness(1.08); }
.err { color: #ff8b8e; }
@media (max-width: 600px) {
  .stat .value { font-size: 22px; }
  .top { flex-direction: column; align-items: flex-start; }
}
"""


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/healthz", handle_health)
    app.router.add_get("/api/status", handle_api_status)
    app.router.add_get("/login", handle_login)
    app.router.add_post("/login", handle_login)
    app.router.add_get("/", handle_dashboard)
    return app


async def start_dashboard(bot=None) -> web.AppRunner:
    """Start the HTTP server; returns the runner (keep a reference)."""
    if bot is not None:
        attach_bot(bot)
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[dashboard] Listening on 0.0.0.0:{PORT}  (health: /health  ui: /)")
    return runner
