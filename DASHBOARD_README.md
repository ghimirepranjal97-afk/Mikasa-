# Mikasa Guard Web Dashboard

Nuke Guard–style command center for **features already in Mikasa.py**.  
No bot commands were changed. `Mikasa.py` already calls `start_dashboard(bot)` from `main()`.

## Files to deploy (same service as the bot)

```
Mikasa.py                 # existing bot (unchanged)
web_dashboard.py          # dashboard server
dashboard/
  templates/
    authorize.html        # OAuth landing page
    dashboard.html        # main UI
  static/
    style.css
    app.js
```

## Render setup

1. **Web service** (not Background Worker) so `PORT` is open for health checks + the UI.
2. Start command (example):
   ```bash
   python Mikasa.py
   ```
3. Environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `TOKEN` | Yes | Bot token (already used by Mikasa) |
| `DISCORD_CLIENT_ID` | Yes | Discord application Client ID |
| `DISCORD_CLIENT_SECRET` | Yes | Discord application Client Secret |
| `DISCORD_REDIRECT_URI` | Yes | `https://YOUR-SERVICE.onrender.com/callback` |
| `DASHBOARD_SECRET` | Recommended | Random string for session isolation |
| `PUBLIC_BASE_URL` | Optional | `https://YOUR-SERVICE.onrender.com` |
| `PORT` | Auto | Set by Render |

4. Discord Developer Portal → your application → **OAuth2**:
   - Add redirect: `https://YOUR-SERVICE.onrender.com/callback`
   - Scopes used: `identify`, `guilds`

## What the dashboard shows (bot features only)

- **Overview** — gateway latency, uptime, member/channel counts, protection summary  
- **Anti-Raid** — RaidWatch on/off + threshold  
- **Anti-Nuke** — enabled state, whitelist counts, alert channel  
- **Risk Watchlist** — Anti-Alt settings  
- **Quarantine** — anti-alt quarantine role  
- **Verification** — `verifysetup` panel status  
- **Anti-Bot** — antibot + allow lists  
- **AutoMod** — enabled + filters  
- **Members** — live counts from bot cache  
- **Warnings** — stored warning totals  
- **Logs** — unified / security / antinuke log channels  

Toggles write the same `data/*.json` files the bot already uses (`server_settings`, `anti_alt_settings`, `paidbot_automod`, etc.).

## Access control

- User must complete Discord OAuth.
- Only servers where the user has **Manage Server** (or Administrator / owner) **and** Mikasa is present are listed.
- Bot owners / co-owners can open those guilds as well when resolvable.

## Local test

```bash
export TOKEN=...
export DISCORD_CLIENT_ID=...
export DISCORD_CLIENT_SECRET=...
export DISCORD_REDIRECT_URI=http://localhost:8080/callback
export PORT=8080
python Mikasa.py
```

Open `http://localhost:8080` → **Authorize with Discord**.
