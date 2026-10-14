// Look F: Daylight. A white sidebar (sections, jobs in progress, controller keys), a page header with
// a short status sentence and a device readout, and a library made of a now-playing card, a recently
// played list and a filterable grid. Registers with registerSkin (see app.js).
(function () {
  "use strict";

  const BUSY = ["downloading", "decompressing", "installing"];
  const FILTERS = {
    all: () => true,
    vr: g => !!g.is_vr,
    flat: g => !g.is_vr,
    attention: (g, ctx) => needsAttention(g, ctx),
  };
  const PAGE = {
    library: "Library",
    catalog: "Browse",
    sideload: "Install a file",
    downloads: "Downloads",
    storage: "Storage",
    system: "System",
  };

  let filter = "all";      // the library's segmented filter, kept across re-renders
  let lastCtx = null;      // newest context, for the page header when only the tab changes
  let observer = null;     // follows the active tab
  let jobsShape = "";      // which jobs the sidebar shows; rebuilt only when that changes
  let readShape = "";
  let realOpenGameModal = null; // app.js's game page, wrapped while this look is active

  const $ = id => document.getElementById(id);

  function needsAttention(g, ctx) {
    const level = (g.compat && g.compat.level) || "";
    return level === "needs_port" || level === "blocked" || !!g.port_failed || !!(ctx && ctx.updateFor(g));
  }

  function kindLabel(g) {
    return g.is_vr ? "VR" : "2D app";
  }

  function activeDownload(state) {
    const t = (state.downloads || []).find(d => BUSY.includes(d.status));
    if (!t) return null;
    return {
      pkg: (t.game && t.game.package_name) || "",
      name: (t.game && t.game.name) || "",
      percent: Math.max(0, Math.min(100, Math.round(Number(t.progress_percent) || 0))),
      task: t,
    };
  }

  function portJob(state) {
    const st = state.porting && state.porting.status;
    return st && st.job ? st.job : null;
  }

  // The package a running port job works on: from the porting status, or from the activity label.
  function portingPackage(ctx) {
    const job = portJob(ctx.state);
    if (job && job.package) return job.package;
    const act = ctx.activity && ctx.activity.port;
    if (!act) return "";
    const game = (ctx.state.installed || []).find(g => act.label === `Porting ${g.title}`);
    return game ? game.package : "";
  }

  function gbText(gb) {
    if (gb == null) return "--";
    return gb >= 100 ? `${Math.round(gb)} GB` : `${(+gb).toFixed(1)} GB`;
  }

  function minutesLeft(seconds) {
    const s = Number(seconds) || 0;
    if (s <= 0) return "";
    if (s < 60) return `${Math.round(s)}s left`;
    if (s < 90) return "1 min left";
    if (s < 3600) return `${Math.round(s / 60)} min left`;
    return `${(s / 3600).toFixed(1)} h left`;
  }

  // ---------------------------------------------------------------- page header
  function activeTab() {
    const tab = document.querySelector(".tab-btn.active");
    return (tab && tab.dataset.tab) || "library";
  }

  function librarySentence(state) {
    const games = state.installed || [];
    const parts = [];
    const running = games.filter(g => g.is_running).map(g => g.title);
    if (running.length) parts.push(`${running.join(", ")} running`);
    const busy = (state.downloads || []).filter(t => BUSY.includes(t.status));
    const updates = busy.filter(t => games.some(g => t.game && g.package === t.game.package_name)).length;
    if (updates) parts.push(`${updates} update${updates > 1 ? "s" : ""} downloading`);
    if (busy.length - updates) parts.push(`${busy.length - updates} download${busy.length - updates > 1 ? "s" : ""} in progress`);
    const port = games.filter(g => g.compat && g.compat.level === "needs_port").length;
    if (port) parts.push(`${port} need${port > 1 ? "" : "s"} porting`);
    if (!parts.length) parts.push(games.length ? `${games.length} games and apps installed` : "Nothing installed yet");
    return parts.join(" · ");
  }

  function pageSentence(tab, ctx) {
    const state = ctx.state;
    if (tab === "library") return librarySentence(state);
    if (tab === "catalog") return "Games and apps from your mirror";
    if (tab === "sideload") return "An APK, bundle, EXE or AppImage";
    if (tab === "downloads") {
      const all = state.downloads || [];
      const busy = all.filter(t => BUSY.includes(t.status));
      const waiting = all.filter(t => t.status === "queued" || t.status === "pending").length;
      if (!busy.length && !waiting) return all.length ? "Nothing is downloading right now." : "Downloads and installs from Browse show up here.";
      const parts = [];
      if (busy.length) parts.push(`${busy.length} downloading${busy[0].speed_formatted ? ` at ${busy[0].speed_formatted}` : ""}`);
      if (waiting) parts.push(`${waiting} waiting`);
      return parts.join(" · ");
    }
    if (tab === "storage") {
      const free = ctx.device && ctx.device.freeGb;
      return free == null ? "Move games between drives and free up space" : `${gbText(free)} free on this headset`;
    }
    if (tab === "system") return "Looks, runtime and maintenance";
    return "";
  }

  function renderHead(ctx) {
    const head = $("f-pagehead");
    if (!head || !ctx) return;
    const tab = activeTab();
    const h1 = head.querySelector("h1");
    const p = head.querySelector("p");
    const title = PAGE[tab] || "";
    if (h1.textContent !== title) h1.textContent = title;
    const text = pageSentence(tab, ctx);
    if (p.textContent !== text) { p.textContent = text; p.title = text; }
  }

  // ---------------------------------------------------------------- device readout (header)
  function renderReadout(ctx) {
    const box = $("f-readout");
    if (!box) return;
    const d = ctx.device || {};
    const shape = `${d.battery != null}`;
    if (shape !== readShape) {
      readShape = shape;
      box.innerHTML = `
        ${d.battery != null ? `<span class="f-read-seg" title="Battery">${ctx.icon("battery")}<b data-f="bat"></b><em data-f="plug"></em></span><i aria-hidden="true"></i>` : ""}
        <button type="button" class="f-read-seg" onclick="openStorageTab()" title="Open Storage">${ctx.icon("drive")}<b data-f="free"></b><em>free</em></button><i aria-hidden="true"></i>
        <button type="button" class="f-read-seg" onclick="openPerformanceCard()" title="CPU and memory">${ctx.icon("cpu")}<em>CPU</em><b data-f="cpu"></b></button>`;
    }
    const set = (key, text) => { const el = box.querySelector(`[data-f="${key}"]`); if (el && el.textContent !== text) el.textContent = text; };
    if (d.battery != null) {
      set("bat", `${d.battery}%`);
      set("plug", d.plugged ? "charging" : "");
    }
    set("free", gbText(d.freeGb));
    set("cpu", d.cpu == null ? "--" : `${d.cpu}%`);
  }

  // ---------------------------------------------------------------- sidebar: jobs + keys
  function jobInfo(ctx) {
    const act = ctx.activity || {};
    const jobs = [];
    if (act.port) {
      const job = portJob(ctx.state);
      let detail = act.queued ? "Waiting for another job" : "Running in the background";
      if (job && Array.isArray(job.steps) && job.steps.length && !act.queued) {
        const i = Math.max(0, Math.min(job.steps.length - 1, job.step || 0));
        detail = `Step ${i + 1} of ${job.steps.length} · ${job.steps[i]}`;
      }
      jobs.push({ key: "port", action: "openPortingModal()", label: act.port.label, percent: act.port.queued ? 0 : act.port.percent, pct: act.port.queued ? "Waiting" : `${act.port.percent}%`, detail });
    }
    if (act.download) {
      const dl = activeDownload(ctx.state);
      const installed = dl && (ctx.state.installed || []).find(g => g.package === dl.pkg);
      const t = dl && dl.task;
      const label = installed ? `${installed.title} update` : act.download.label;
      let detail = act.download.detail || "";
      if (t && t.status === "downloading" && t.total_formatted) {
        detail = [`${t.downloaded_formatted} of ${t.total_formatted}`, minutesLeft(t.eta_seconds)].filter(Boolean).join(" · ");
      } else if (t && t.status !== "downloading") {
        detail = t.status === "installing" ? "Installing" : "Unpacking";
      }
      jobs.push({ key: "dl", action: "goToTab('downloads')", label, percent: act.download.percent, pct: `${act.download.percent}%`, detail });
    }
    return jobs;
  }

  function renderSidebar(ctx) {
    const nav = ctx.navExtra;
    if (!nav) return;
    const jobs = jobInfo(ctx);
    const shape = jobs.map(j => j.key).join("|");
    if (shape !== jobsShape || !nav.querySelector(".f-keys")) {
      jobsShape = shape;
      nav.innerHTML = `
        ${jobs.length ? `<div class="f-jobs">
          <div class="f-cap">In progress</div>
          ${jobs.map(j => `
            <button type="button" class="f-job" data-job="${j.key}" onclick="${j.action}">
              <span class="f-job-top"><b data-f="label"></b><em data-f="pct"></em></span>
              <span class="f-track"><span data-f="bar"></span></span>
              <small data-f="detail"></small>
            </button>`).join("")}
        </div>` : ""}
        <div class="f-keys" aria-label="Controller buttons">
          <div><kbd>LB</kbd><kbd>RB</kbd><span>Switch section</span></div>
          <div><kbd>Y</kbd><span>Search</span><kbd>B</kbd><span>Back</span></div>
        </div>`;
      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    }
    jobs.forEach(j => {
      const el = nav.querySelector(`.f-job[data-job="${j.key}"]`);
      if (!el) return;
      const set = (key, text) => { const n = el.querySelector(`[data-f="${key}"]`); if (n.textContent !== text) n.textContent = text; };
      set("label", j.label);
      set("pct", j.pct);
      set("detail", j.detail);
      el.querySelector('[data-f="bar"]').style.width = `${j.percent}%`;
      el.setAttribute("aria-label", `${j.label}, ${j.pct}`);
    });
  }

  function setLibraryCount(n) {
    const el = $("f-libcount");
    if (el) el.textContent = n ? String(n) : "";
  }

  // ---------------------------------------------------------------- library
  function actionFor(g, ctx) {
    const level = (g.compat && g.compat.level) || "";
    if (g.is_running) return { label: "Stop", call: "stopGame", icon: "stop" };
    if (ctx.updateFor(g)) return { label: "Update", call: "updateGame", icon: "update" };
    if (level === "needs_port" && g.kind === "quest") {
      return g.port_failed ? { label: "Port again", call: "portGame", icon: "port" } : { label: "Port and play", call: "launchGame", icon: "port" };
    }
    return { label: g.is_vr ? "Play" : "Open", call: "launchGame", icon: "play" };
  }

  function pillFor(g, ctx, dl, portPkg) {
    const level = (g.compat && g.compat.level) || "";
    if (g.is_running) return '<span class="f-pill f-on"><i></i>Playing</span>';
    if (portPkg && portPkg === g.package) {
      const act = ctx.activity.port;
      return `<span class="f-pill f-port"><i></i>Porting <em>${act && !act.queued ? act.percent + "%" : ""}</em></span>`;
    }
    if (dl && dl.pkg === g.package) return `<span class="f-pill f-up"><i></i>Updating <em>${dl.percent}%</em></span>`;
    if (ctx.updateFor(g)) return '<span class="f-pill f-up"><i></i>Update ready</span>';
    if (level === "blocked") return '<span class="f-pill f-bad"><i></i>Cannot run</span>';
    if (level === "needs_port") return g.port_failed ? '<span class="f-pill f-bad"><i></i>Port failed</span>' : '<span class="f-pill f-port"><i></i>Needs porting</span>';
    return "";
  }

  // The app's own launcher icon; Steam's square icon when the APK had none.
  function iconImg(ctx, g, cls) {
    const fallback = ctx.esc(ctx.art(g, "icon"));
    return `<img class="${cls}" src="${ctx.esc(ctx.art(g, "apk_icon"))}" alt="" draggable="false" decoding="async" loading="lazy" onerror="this.onerror=null; this.src='${fallback}';">`;
  }

  // Wide art: the hero picture as a soft backdrop with the app's icon on it, so a title never
  // appears twice and a cropped banner never cuts one off.
  function art(ctx, g) {
    return `<img class="f-art-bg" src="${ctx.esc(ctx.art(g, "hero"))}" alt="" draggable="false" decoding="async" loading="lazy" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">${iconImg(ctx, g, "f-art-ic")}`;
  }

  function nowCard(g, ctx) {
    const pkg = ctx.arg(g.package);
    const act = actionFor(g, ctx);
    const total = ctx.playtime(g.playtime_seconds);
    let line;
    if (g.is_running) {
      const started = g.last_played ? new Date(g.last_played * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
      line = [total, started && `started ${started}`].filter(Boolean).join(" · ") || "Started just now";
    } else {
      line = [ctx.played(g), total].filter(Boolean).join(" · ");
    }
    return `
      <article class="f-panel f-now" aria-label="${g.is_running ? "Playing now" : "Last played"}">
        <div class="f-now-art">${art(ctx, g)}</div>
        <div class="f-now-info">
          <div class="f-live${g.is_running ? "" : " f-idle"}"><i></i>${g.is_running ? "Playing now" : "Last played"} · ${kindLabel(g)}</div>
          <h2 title="${ctx.esc(g.title)}">${ctx.esc(g.title)}</h2>
          <p>${ctx.esc(line)}</p>
          <div class="f-acts">
            <button type="button" class="f-btn" onclick="${act.call}(${pkg})">${ctx.icon(act.icon)}${act.label}</button>
            <button type="button" class="f-btn f-ghost" onclick="openGameModal(${pkg}, 'installed')">${ctx.icon("dots")}Details</button>
          </div>
        </div>
      </article>`;
  }

  function recentRow(g, ctx) {
    const pkg = ctx.arg(g.package);
    const act = actionFor(g, ctx);
    const meta = [kindLabel(g), g.last_played ? ctx.ago(g.last_played) : "", ctx.playtime(g.playtime_seconds)].filter(Boolean).join(" · ");
    return `
      <div class="f-row" tabindex="0" role="button" onclick="openGameModal(${pkg}, 'installed')" onkeydown="if (event.key === 'Enter') this.click()">
        ${iconImg(ctx, g, "f-row-ic")}
        <span class="f-row-txt"><b>${ctx.esc(g.title)}</b><small>${ctx.esc(meta)}</small></span>
        <button type="button" class="f-row-go" aria-label="${ctx.esc(act.label)} ${ctx.esc(g.title)}" title="${ctx.esc(act.label)}" onclick="event.stopPropagation(); ${act.call}(${pkg})">${ctx.icon(act.icon)}</button>
      </div>`;
  }

  function card(g, ctx, dl, portPkg) {
    const pkg = ctx.arg(g.package);
    const act = actionFor(g, ctx);
    const meta = [kindLabel(g), g.is_external ? "External drive" : "", ctx.played(g)].filter(Boolean).join(" · ");
    return `
      <div class="game-card f-card" data-package="${ctx.esc(g.package)}" draggable="false" onclick="openGameModal(${pkg}, 'installed')">
        <div class="f-art">${art(ctx, g)}${pillFor(g, ctx, dl, portPkg)}</div>
        <div class="f-body">
          <b title="${ctx.esc(g.title)}">${ctx.esc(g.title)}</b>
          <small class="f-meta">${ctx.esc(meta)}</small>
          <span class="f-hint"><kbd>X</kbd>${act.label}</span>
        </div>
        <button type="button" class="card-btn f-act" tabindex="-1" onclick="event.stopPropagation(); ${act.call}(${pkg})">${act.label}</button>
      </div>`;
  }

  function library(ctx) {
    lastCtx = ctx;
    const state = ctx.state;
    const installed = state.installed || [];
    setLibraryCount(installed.length);
    const searching = !!(ctx.query || "").trim();
    const all = ctx.games;
    const counts = {};
    Object.keys(FILTERS).forEach(k => { counts[k] = all.filter(g => FILTERS[k](g, ctx)).length; });
    const shown = all.filter(g => FILTERS[filter](g, ctx));
    const dl = activeDownload(state);
    const portPkg = portingPackage(ctx);

    let top = "";
    if (!searching) {
      const featured = installed.find(g => g.is_running) || ctx.recent[0] || null;
      const recent = installed.filter(g => g.last_played && g !== featured)
        .sort((a, b) => (b.is_running - a.is_running) || (b.last_played - a.last_played)).slice(0, 3);
      if (featured) {
        top = `
          <div class="f-top${recent.length ? "" : " f-solo"}">
            ${nowCard(featured, ctx)}
            ${recent.length ? `<section class="f-panel f-recent" aria-label="Recently played"><h3>Recently played</h3><div class="f-rows">${recent.map(g => recentRow(g, ctx)).join("")}</div></section>` : ""}
          </div>`;
      }
    }

    const seg = [["all", "All"], ["vr", "VR games"], ["flat", "2D apps"], ["attention", "Needs attention"]]
      .filter(([k]) => k === "all" || counts[k] || filter === k)
      .map(([k, label]) => `<button type="button" class="${filter === k ? "on" : ""}" data-filter="${k}" aria-pressed="${filter === k}" onclick="daylightFilter('${k}')">${label}${k === "attention" && counts[k] ? `<b>${counts[k]}</b>` : ""}</button>`).join("");

    const heading = searching ? `Results for “${ctx.esc(ctx.query.trim())}”` : "All games and apps";
    const none = {
      vr: "No VR games here.", flat: "No 2D apps here.", attention: "Nothing needs your attention. Every game is ready to play.",
    }[filter] || "Nothing to show.";

    ctx.root.innerHTML = `
      ${top}
      <div class="f-libhead">
        <h2>${heading} <em>${shown.length}</em></h2>
        <div class="f-seg" role="group" aria-label="Show">${seg}</div>
        <label class="f-sort"><span>Sort</span>${ctx.sortSelect()}</label>
        <button type="button" class="f-iconbtn" onclick="checkForUpdates(true)" title="Check for updates" aria-label="Check for updates">${ctx.icon("port")}</button>
      </div>
      <div class="f-grid">
        ${shown.length ? shown.map(g => card(g, ctx, dl, portPkg)).join("") : `
          <div class="f-none"><p>${none}</p><button type="button" class="btn-secondary compact" onclick="daylightFilter('all')">Show everything</button></div>`}
      </div>`;
    renderHead(ctx);
  }

  function empty(ctx) {
    lastCtx = ctx;
    setLibraryCount(0);
    renderHead(ctx);
    return `
      <div class="f-panel f-empty">
        <div class="f-empty-mark">${ctx.icon("download")}</div>
        <h3>Your library is empty</h3>
        <p>Install something from Browse, or a file you already have. Everything you install appears here and in your Steam library.</p>
        <div class="f-empty-acts">
          <button type="button" class="btn-primary" onclick="goToTab('catalog')">Browse games and apps</button>
          <button type="button" class="btn-secondary" onclick="goToTab('sideload')">Install a file</button>
        </div>
      </div>`;
  }

  // Changing the filter redraws the library; the controller's focus stays on the chosen button.
  window.daylightFilter = function (key) {
    if (!FILTERS[key]) return;
    const nav = window.gamepadNav;
    const hadFocus = nav && nav.focusedElement && nav.focusedElement.closest && nav.focusedElement.closest(".f-seg, .f-none");
    filter = key;
    if (typeof renderInstalledGrid === "function") renderInstalledGrid();
    const btn = document.querySelector(`.f-seg button[data-filter="${key}"]`);
    if (btn && hadFocus && nav.setFocus) nav.setFocus(btn);
  };

  // The game page of an installed game leads with the same art as its card: the hero picture
  // with the app's own icon on it, instead of the square icon cropped to a wide banner.
  function heroOpenGameModal(id, mode) {
    const result = realOpenGameModal.apply(this, arguments);
    const banner = $("modal-cover-banner");
    const cover = $("modal-game-cover");
    if (!banner || !cover) return result;
    const old = banner.querySelector(".f-modal-ic");
    if (old) old.remove();
    const game = mode === "installed" && lastCtx ? (lastCtx.state.installed || []).find(g => g.package === id) : null;
    banner.classList.toggle("f-hero", !!game);
    if (game) {
      const fallback = cover.src;
      cover.onerror = () => { cover.onerror = null; cover.src = fallback; };
      cover.src = lastCtx.art(game, "hero");
      const ic = document.createElement("img");
      ic.className = "f-modal-ic";
      ic.alt = "";
      ic.draggable = false;
      ic.onerror = () => { ic.onerror = null; ic.src = lastCtx ? lastCtx.art(game, "icon") : ""; };
      ic.src = lastCtx.art(game, "apk_icon");
      cover.insertAdjacentElement("afterend", ic);
    }
    return result;
  }

  // ---------------------------------------------------------------- status, mount, unmount
  function status(ctx) {
    lastCtx = ctx;
    renderSidebar(ctx);
    renderReadout(ctx);
    renderHead(ctx);
    syncPills(ctx);
  }

  // Downloads and porting move on between library renders: the status pills on the art follow
  // them in place, so the grid is never rebuilt under the controller's focus.
  function syncPills(ctx) {
    const cards = document.querySelectorAll(".f-card[data-package]");
    if (!cards.length) return;
    const dl = activeDownload(ctx.state);
    const portPkg = portingPackage(ctx);
    const byPkg = new Map((ctx.state.installed || []).map(g => [g.package, g]));
    cards.forEach(cardEl => {
      const g = byPkg.get(cardEl.dataset.package);
      const box = cardEl.querySelector(".f-art");
      if (!g || !box) return;
      const html = pillFor(g, ctx, dl, portPkg);
      const old = box.querySelector(".f-pill");
      if ((old ? old.outerHTML : "") === html) return;
      if (old) old.remove();
      if (html) box.insertAdjacentHTML("beforeend", html);
    });
  }

  function mount(ctx) {
    lastCtx = ctx;
    const header = document.querySelector(".app-header");
    if (header && !$("f-pagehead")) {
      const head = document.createElement("div");
      head.id = "f-pagehead";
      head.className = "f-pagehead";
      head.innerHTML = "<h1></h1><p></p>";
      header.insertBefore(head, header.firstChild);
    }
    const bar = document.querySelector(".telemetry-bar");
    if (bar && !$("f-readout")) {
      const read = document.createElement("div");
      read.id = "f-readout";
      read.className = "f-readout";
      bar.insertBefore(read, bar.firstChild);
    }
    const libTab = document.querySelector('.tab-btn[data-tab="library"]');
    if (libTab && !$("f-libcount")) {
      const count = document.createElement("em");
      count.id = "f-libcount";
      count.className = "f-count";
      libTab.appendChild(count);
      setLibraryCount((ctx.state.installed || []).length);
    }
    if (!observer && window.MutationObserver) {
      observer = new MutationObserver(() => renderHead(lastCtx));
      document.querySelectorAll(".tab-btn").forEach(t => observer.observe(t, { attributes: true, attributeFilter: ["class"] }));
    }
    if (typeof window.openGameModal === "function" && !realOpenGameModal) {
      realOpenGameModal = window.openGameModal;
      window.openGameModal = heroOpenGameModal;
    }
    readShape = "";
    jobsShape = "";
    renderHead(ctx);
  }

  function unmount() {
    ["f-pagehead", "f-readout", "f-libcount"].forEach(id => { const el = $(id); if (el) el.remove(); });
    if (realOpenGameModal) {
      if (window.openGameModal === heroOpenGameModal) window.openGameModal = realOpenGameModal;
      realOpenGameModal = null;
    }
    const banner = $("modal-cover-banner");
    if (banner) {
      banner.classList.remove("f-hero");
      const ic = banner.querySelector(".f-modal-ic");
      if (ic) ic.remove();
    }
    if (observer) observer.disconnect();
    observer = null;
    jobsShape = "";
    readShape = "";
    lastCtx = null;
  }

  registerSkin("f", { library, empty, status, mount, unmount });
})();
