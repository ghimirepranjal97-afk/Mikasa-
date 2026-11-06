(() => {
  const state = {
    user: null,
    guilds: [],
    guildId: localStorage.getItem("mikasa_guild_id") || null,
    section: "overview",
    overview: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const content = $("#content");
  const serverName = $("#serverName");
  const serverIcon = $("#serverIcon");
  const serverDropdown = $("#serverDropdown");
  const pageTitle = $("#pageTitle");
  const pageSubtitle = $("#pageSubtitle");
  const statusPill = $("#statusPill");
  const statusText = $("#statusText");
  const userName = $("#userName");

  const SECTION_META = {
    overview: {
      title: "Overview",
      subtitle: "High-level metrics and protection status for this community.",
    },
    raidwatch: {
      title: "Anti-Raid",
      subtitle: "Join-burst monitoring (RaidWatch) from Mikasa.",
    },
    antinuke: {
      title: "Anti-Nuke",
      subtitle: "Mass-action protection, whitelist, and alert channel status.",
    },
    antialt: {
      title: "Risk Watchlist",
      subtitle: "New-account risk review (Anti-Alt).",
    },
    quarantine: {
      title: "Quarantine",
      subtitle: "Quarantine role used by anti-alt when action is quarantine.",
    },
    verification: {
      title: "Verification",
      subtitle: "Persistent verification panel configuration.",
    },
    antibot: {
      title: "Anti-Bot",
      subtitle: "Unknown bot join protection and allow lists.",
    },
    automod: {
      title: "AutoMod",
      subtitle: "Message filters configured via Mikasa AutoMod.",
    },
    members: {
      title: "Members",
      subtitle: "Live member counts from the bot cache.",
    },
    warnings: {
      title: "Warnings",
      subtitle: "Stored moderation warnings for this server.",
    },
    logs: {
      title: "Logs",
      subtitle: "Security and unified log channel routing.",
    },
  };

  async function api(path, options = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (res.status === 401) {
      window.location.href = "/";
      throw new Error("unauthorized");
    }
    return res.json();
  }

  function badge(on, onLabel = "Armed", offLabel = "Off") {
    return on
      ? `<span class="badge on">${onLabel}</span>`
      : `<span class="badge off">${offLabel}</span>`;
  }

  function metric(label, valueHtml) {
    return `<div class="metric"><span>${label}</span><span class="metric-value">${valueHtml}</span></div>`;
  }

  function switchBtn(feature, enabled) {
    return `<button class="switch ${enabled ? "on" : ""}" data-toggle="${feature}" data-enabled="${enabled ? "1" : "0"}" title="Toggle"></button>`;
  }

  function setStatusFromOverview(ov) {
    if (!ov) return;
    const armed = ov.antinuke?.enabled || ov.raidwatch?.enabled;
    statusPill.classList.toggle("warn", !armed);
    if (ov.raidwatch?.enabled) {
      statusText.textContent = "Anti-raid is armed and watching";
    } else if (ov.antinuke?.enabled) {
      statusText.textContent = "Anti-nuke is armed";
    } else {
      statusText.textContent = "Protection idle — enable Anti-Nuke or RaidWatch";
    }
  }

  function renderOverview(ov) {
    const checked = new Date().toLocaleString();
    content.innerHTML = `
      <div class="card">
        <div class="card-head">
          <div>
            <h2>Server health &amp; readiness</h2>
            <div class="desc">Read-only checks and recorded activity for this server.</div>
          </div>
          <button class="btn-ghost" id="refreshBtn">Refresh</button>
        </div>
        <div class="meta-line">
          Checked ${checked}
          ${ov.member_count != null ? ` · ${ov.member_count} members` : ""}
          ${ov.channel_count != null ? ` · ${ov.channel_count} channels` : ""}
          ${ov.role_count != null ? ` · ${ov.role_count} roles` : ""}
        </div>
        ${metric("Gateway heartbeat", ov.gateway_ms != null ? `${ov.gateway_ms} ms` : "—")}
        ${metric("Uptime", ov.uptime || "—")}
        ${metric("Anti-raid (RaidWatch)", `<span class="${ov.raidwatch.enabled ? "on" : "off"}">${ov.raidwatch.enabled ? "Armed" : "Off"}</span>`)}
        ${metric("Anti-nuke", `<span class="${ov.antinuke.enabled ? "on" : "off"}">${ov.antinuke.enabled ? "Armed" : "Off"}</span>`)}
        ${metric("Anti-bot", ov.antibot.enabled ? "On" : "Off")}
        ${metric("Anti-alt", ov.antialt.enabled ? `On · ${ov.antialt.min_account_days}d` : "Off")}
        ${metric("AutoMod", ov.automod.enabled ? "On" : "Off")}
        ${metric("Verification", ov.verification.enabled ? "Configured" : "Not set")}
        ${metric("Warnings on record", String(ov.warnings_total ?? 0))}
      </div>
      <div class="grid-2">
        <div class="card">
          <h2>Protection summary</h2>
          <div class="desc">Toggles write the same settings files Mikasa uses in Discord.</div>
          <div class="toggle-row"><span>Anti-Nuke</span>${switchBtn("antinuke", ov.antinuke.enabled)}</div>
          <div class="toggle-row"><span>RaidWatch</span>${switchBtn("raidwatch", ov.raidwatch.enabled)}</div>
          <div class="toggle-row"><span>Anti-Bot</span>${switchBtn("antibot", ov.antibot.enabled)}</div>
          <div class="toggle-row"><span>Anti-Alt</span>${switchBtn("antialt", ov.antialt.enabled)}</div>
          <div class="toggle-row"><span>AutoMod</span>${switchBtn("automod", ov.automod.enabled)}</div>
        </div>
        <div class="card">
          <h2>Quick facts</h2>
          <div class="desc">From live bot cache and server_settings.</div>
          ${metric("RaidWatch threshold", `${ov.raidwatch.threshold} joins / window`)}
          ${metric("Anti-nuke whitelist users", String(ov.antinuke.whitelist_users))}
          ${metric("Anti-alt action", ov.antialt.action)}
          ${metric("Log channel", ov.logs.channel_id ? `<code>${ov.logs.channel_id}</code>` : "Not configured")}
          ${metric("Emergency lockdown", ov.emergency_lockdown ? "Active" : "Inactive")}
        </div>
      </div>
      <div class="note">
        Full configuration (thresholds, whitelist targets, quarantine role, verification panel)
        is still managed with Mikasa commands in Discord when needed.
        This dashboard only surfaces and toggles features that already exist in the bot.
      </div>
    `;
    $("#refreshBtn")?.addEventListener("click", () => loadOverview(true));
    wireToggles();
  }

  function renderSection(section, data) {
    const meta = SECTION_META[section] || { title: section, subtitle: "" };
    pageTitle.textContent = meta.title;
    pageSubtitle.textContent = meta.subtitle;

    if (section === "overview") {
      renderOverview(data);
      return;
    }

    let body = `<div class="card"><h2>${meta.title}</h2><div class="desc">${data.description || ""}</div>`;

    if (section === "raidwatch") {
      body += `
        <div class="toggle-row"><span>Enabled</span>${switchBtn("raidwatch", data.enabled)}</div>
        ${metric("Join threshold", `${data.threshold} (range 5–25)`)}
        <div class="note">Change threshold in Discord with <code>,raidwatch threshold 8</code>.</div>
      `;
    } else if (section === "antinuke") {
      body += `
        <div class="toggle-row"><span>Enabled</span>${switchBtn("antinuke", data.enabled)}</div>
        ${metric("Alert channel", data.alert_channel_id ? `<code>${data.alert_channel_id}</code>` : "Not set")}
        ${metric("Whitelisted users", Object.keys(data.whitelist || {}).length)}
        ${metric("Whitelisted roles", Object.keys(data.role_whitelist || {}).length)}
        <div class="note">Manage whitelist with <code>,antinuke whitelist</code> / <code>,whitelist</code> in Discord.</div>
      `;
    } else if (section === "antialt") {
      body += `
        <div class="toggle-row"><span>Enabled</span>${switchBtn("antialt", data.enabled)}</div>
        ${metric("Min account age", `${data.min_account_days} days`)}
        ${metric("Action", data.action)}
        ${metric("Log channel", data.log_channel_id ? `<code>${data.log_channel_id}</code>` : "Not set")}
        ${metric("Quarantine role", data.quarantine_role_id ? `<code>${data.quarantine_role_id}</code>` : "Not set")}
      `;
    } else if (section === "quarantine") {
      body += `
        ${metric("Quarantine role", data.quarantine_role_name || data.quarantine_role_id || "Not set")}
        ${metric("Anti-alt action", data.antialt_action)}
      `;
    } else if (section === "verification") {
      body += `
        ${metric("Enabled", data.enabled ? "Yes" : "No")}
        ${metric("Verified role", data.role_name || data.role_id || "Not set")}
        ${metric("Panel channel", data.channel_name || data.channel_id || "Not set")}
      `;
    } else if (section === "antibot") {
      body += `
        <div class="toggle-row"><span>Enabled</span>${switchBtn("antibot", data.enabled)}</div>
        ${metric("Allowed bots", (data.allowed_bots || []).length)}
        ${metric("Approved inviters", (data.allowed_inviters || []).length)}
      `;
    } else if (section === "automod") {
      const filters = data.filters || {};
      body += `
        <div class="toggle-row"><span>Enabled</span>${switchBtn("automod", data.enabled)}</div>
        ${metric("Bad words", data.bad_words_count ?? 0)}
        ${metric("Allowed domains", data.allowed_domains_count ?? 0)}
        ${metric("Log channel", data.log_channel_id ? `<code>${data.log_channel_id}</code>` : "Not set")}
        <div class="desc" style="margin-top:12px">Filter flags</div>
        ${Object.keys(filters).length
          ? Object.entries(filters).map(([k, v]) => metric(k, v ? "On" : "Off")).join("")
          : `<div class="muted">No per-filter flags stored yet.</div>`}
      `;
    } else if (section === "members") {
      body += `
        ${metric("Members", data.member_count ?? "—")}
        ${metric("Humans", data.humans ?? "—")}
        ${metric("Bots", data.bots ?? "—")}
        ${metric("Roles", data.roles ?? "—")}
        ${metric("Channels", data.channels ?? "—")}
      `;
    } else if (section === "warnings") {
      const rows = data.entries || [];
      body += `
        ${metric("Warned users", data.total_warned_users ?? rows.length)}
        ${rows.length ? `
          <table class="table">
            <thead><tr><th>Member</th><th>Warnings</th></tr></thead>
            <tbody>
              ${rows.slice(0, 30).map((r) => `<tr><td>${escapeHtml(r.user)}</td><td>${r.count}</td></tr>`).join("")}
            </tbody>
          </table>` : `<div class="muted">No warnings stored for this server.</div>`}
      `;
    } else if (section === "logs") {
      body += `
        ${metric("Unified logs", data.mikasa_all_logs_channel ? `<code>${data.mikasa_all_logs_channel}</code>` : "Not set")}
        ${metric("Security log", data.security_log_channel ? `<code>${data.security_log_channel}</code>` : "Not set")}
        ${metric("Anti-nuke alerts", data.antinuke_channel ? `<code>${data.antinuke_channel}</code>` : "Not set")}
      `;
    }

    body += `</div>`;
    content.innerHTML = body;
    wireToggles();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function wireToggles() {
    document.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!state.guildId) return;
        const feature = btn.getAttribute("data-toggle");
        const currentlyOn = btn.getAttribute("data-enabled") === "1";
        const next = !currentlyOn;
        btn.disabled = true;
        try {
          const res = await api(`/api/guild/${state.guildId}/toggle`, {
            method: "POST",
            body: JSON.stringify({ feature, enabled: next }),
          });
          if (res.ok) {
            await loadSection(state.section);
            if (state.section !== "overview") await loadOverview(false);
          } else {
            alert(res.error || "Could not update setting");
          }
        } catch (e) {
          console.error(e);
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  async function loadOverview(render) {
    if (!state.guildId) return;
    const ov = await api(`/api/guild/${state.guildId}/overview`);
    state.overview = ov;
    setStatusFromOverview(ov);
    if (render || state.section === "overview") {
      pageTitle.textContent = SECTION_META.overview.title;
      pageSubtitle.textContent = SECTION_META.overview.subtitle;
      renderOverview(ov);
    }
  }

  async function loadSection(section) {
    state.section = section;
    document.querySelectorAll(".nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.section === section);
    });
    if (!state.guildId) {
      content.innerHTML = `<div class="card"><p class="muted">Select a server to continue.</p></div>`;
      return;
    }
    content.innerHTML = `<div class="loading">Loading…</div>`;
    if (section === "overview") {
      await loadOverview(true);
      return;
    }
    const data = await api(`/api/guild/${state.guildId}/section/${section}`);
    renderSection(section, data);
  }

  function selectGuild(g) {
    state.guildId = g.id;
    localStorage.setItem("mikasa_guild_id", g.id);
    serverName.textContent = g.name;
    if (g.icon_url) {
      serverIcon.src = g.icon_url;
      serverIcon.style.display = "block";
    } else {
      serverIcon.removeAttribute("src");
      serverIcon.style.display = "none";
    }
    serverDropdown.classList.add("hidden");
    loadSection(state.section);
  }

  function renderGuildList() {
    serverDropdown.innerHTML = state.guilds
      .map(
        (g) => `
      <button class="server-option" data-id="${g.id}">
        ${g.icon_url ? `<img src="${g.icon_url}" alt="" />` : `<span class="server-icon"></span>`}
        <span>${escapeHtml(g.name)}</span>
      </button>`
      )
      .join("") || `<div class="muted" style="padding:12px">No manageable servers found where Mikasa is present.</div>`;

    serverDropdown.querySelectorAll(".server-option").forEach((btn) => {
      btn.addEventListener("click", () => {
        const g = state.guilds.find((x) => x.id === btn.dataset.id);
        if (g) selectGuild(g);
      });
    });
  }

  async function init() {
    const me = await api("/api/me");
    state.user = me.user;
    state.guilds = me.guilds || [];
    userName.textContent = me.user.global_name || me.user.username || "User";

    renderGuildList();

    const saved = state.guilds.find((g) => g.id === state.guildId) || state.guilds[0];
    if (saved) selectGuild(saved);
    else {
      content.innerHTML = `<div class="card"><p class="muted">Mikasa is not in any server you can manage, or the bot is still starting.</p></div>`;
      statusText.textContent = "No server selected";
      statusPill.classList.add("warn");
    }

    $("#serverSwitch").addEventListener("click", () => {
      serverDropdown.classList.toggle("hidden");
    });
    document.addEventListener("click", (e) => {
      if (!$("#serverSwitch").contains(e.target) && !serverDropdown.contains(e.target)) {
        serverDropdown.classList.add("hidden");
      }
    });
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => loadSection(btn.dataset.section));
    });
  }

  init().catch((err) => {
    console.error(err);
    content.innerHTML = `<div class="card"><p class="muted">Failed to load dashboard. Try signing in again.</p></div>`;
  });
})();
