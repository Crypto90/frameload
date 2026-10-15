// Look A: Big Picture. Draws the library like SteamOS: a Recent games shelf (one wide card for the
// running or last game, then capsules) and a grid of 2:3 capsules. mount() adds the clock and status
// to the top bar and the library count to its tab; unmount() takes all of it away again.
(function () {
  const added = [];          // elements this look put into the shared page
  let clockTimer = null;
  let shelfObserver = null;
  let realOpenGameModal = null;
  let appState = null;

  const RUN_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.2v13.6L19 12z" fill="currentColor"/></svg>';
  const REFRESH_SVG = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.3-4.6L4 8.5M4 4v4.5h4.5M4 13a8 8 0 0 0 14.3 4.6L20 15.5M20 20v-4.5h-4.5"/></svg>';

  function twoDigits(n) { return String(n).padStart(2, "0"); }

  function tickClock() {
    const el = document.getElementById("a-clock");
    if (!el) return;
    const now = new Date();
    el.textContent = `${twoDigits(now.getHours())}:${twoDigits(now.getMinutes())}`;
    el.setAttribute("datetime", now.toISOString());
  }

  function renderStatus(ctx) {
    const box = document.getElementById("a-status");
    if (!box) return;
    const dev = ctx.device || {};
    const online = navigator.onLine !== false;
    const wifi = box.querySelector(".a-st-wifi");
    wifi.classList.toggle("off", !online);
    wifi.title = online ? "Connected" : "Offline";
    const bat = box.querySelector(".a-st-bat");
    if (dev.battery == null) {
      bat.hidden = true;
    } else {
      bat.hidden = false;
      bat.classList.toggle("low", dev.battery <= 15 && !dev.plugged);
      bat.title = dev.plugged ? "Charging" : "Battery";
      bat.querySelector("span").textContent = `${dev.battery}%${dev.plugged ? " +" : ""}`;
    }
  }

  function setLibraryCount(ctx) {
    const badge = document.getElementById("a-lib-count");
    if (!badge) return;
    const n = (ctx.state.installed || []).length;
    badge.textContent = n;
    badge.hidden = !n;
  }

  // Most recent first: what is running, then last played, then last installed.
  function byRecent(a, b) {
    return (b.is_running - a.is_running) || ((b.last_played || 0) - (a.last_played || 0))
      || ((b.installed_time || 0) - (a.installed_time || 0));
  }

  function flagFor(ctx, g) {
    const level = (g.compat && g.compat.level) || "";
    if (g.is_running) return '<span class="a-flag run">Playing</span>';
    if (level === "blocked") return '<span class="a-flag bad">Cannot run</span>';
    if (ctx.updateFor(g)) return '<span class="a-flag update">Update</span>';
    if (level === "needs_port" && g.kind === "quest") {
      return g.port_failed ? '<span class="a-flag bad">Port failed</span>' : '<span class="a-flag port">Port &amp; Play</span>';
    }
    return "";
  }

  function metaFor(ctx, g) {
    if (g.is_running) return "Playing now";
    const parts = [];
    if (g.is_external) parts.push("External");
    if (g.last_played) {
      const ago = ctx.ago(g.last_played);
      parts.push(ago.charAt(0).toUpperCase() + ago.slice(1));
      const time = ctx.playtime(g.playtime_seconds).replace(/ played$/, "");
      if (time) parts.push(time);
    } else {
      parts.push("Not played yet");
    }
    return parts.join(" · ");
  }

  function img(ctx, g, slot, cls) {
    const fallback = ctx.esc(ctx.art(g, "poster"));
    return `<img class="${cls}" src="${ctx.esc(ctx.art(g, slot))}" alt="" draggable="false" loading="lazy" decoding="async"
      onerror="this.onerror=null; this.src='${slot === "poster" ? "/static/assets/fallback_cover.svg" : fallback}';">`;
  }

  // The wide card: the running game (Resume, Stop) or the last one played (Play).
  function leadCard(ctx, g) {
    const pkg = ctx.arg(g.package);
    const kind = g.is_vr ? "VR" : "2D";
    const level = (g.compat && g.compat.level) || "";
    const state = g.is_running ? `Playing now · ${kind}`
      : g.last_played ? `Last played ${ctx.ago(g.last_played)} · ${kind}` : `Recently added · ${kind}`;
    let primary;
    if (g.is_running) {
      // A VR game resumes by closing Steam's menu over it (Show); a 2D app is a window of its own.
      primary = `${g.is_vr ? ctx.showButton(g, "a-play", { short: true, icon: RUN_SVG })
        : `<button type="button" class="a-play" onclick="event.stopPropagation(); launchGame(${pkg})">${RUN_SVG}Resume</button>`}
        <button type="button" class="a-ghost" onclick="event.stopPropagation(); stopGame(${pkg})">Stop</button>`;
    } else if (ctx.updateFor(g)) {
      primary = `<button type="button" class="a-play a-blue" onclick="event.stopPropagation(); updateGame(${pkg})">Update</button>`;
    } else if (level === "needs_port" && g.kind === "quest") {
      primary = `<button type="button" class="a-play" onclick="event.stopPropagation(); ${g.port_failed ? "portGame" : "launchGame"}(${pkg})">${RUN_SVG}${g.port_failed ? "Port again" : "Port &amp; Play"}</button>`;
    } else if (level === "blocked") {
      primary = "";
    } else {
      primary = `<button type="button" class="a-play" onclick="event.stopPropagation(); launchGame(${pkg})">${RUN_SVG}Play</button>`;
    }
    const time = ctx.playtime(g.playtime_seconds);
    return `
      <div class="a-lead${g.is_running ? " running" : ""}" role="button" tabindex="0" data-package="${ctx.esc(g.package)}"
           aria-label="${ctx.esc(g.title)}, ${ctx.esc(state)}" onclick="openGameModal(${pkg}, 'installed')">
        ${img(ctx, g, "hero", "a-lead-art")}
        <div class="a-lead-info">
          <span class="a-lead-state">${ctx.esc(state)}</span>
          <span class="a-lead-title">${ctx.esc(g.title)}</span>
          ${time ? `<span class="a-lead-meta">${ctx.esc(time)}</span>` : ""}
          <div class="a-lead-row">
            ${primary}
            ${g.is_running ? "" : `<button type="button" class="a-ghost" onclick="event.stopPropagation(); openSettingsModal(${pkg})">Settings</button>`}
          </div>
        </div>
      </div>`;
  }

  function capsule(ctx, g) {
    return `
      <div class="a-cap" role="button" tabindex="0" data-package="${ctx.esc(g.package)}" title="${ctx.esc(g.title)}"
           aria-label="${ctx.esc(g.title)}" onclick="openGameModal(${ctx.arg(g.package)}, 'installed')">
        ${img(ctx, g, "poster", "a-cap-art")}
        ${g.is_running ? '<span class="a-flag run">Playing</span>' : ""}
      </div>`;
  }

  function tile(ctx, g) {
    const flag = flagFor(ctx, g);
    return `
      <div class="game-card a-tile" tabindex="0" role="button" data-package="${ctx.esc(g.package)}" draggable="false"
           aria-label="${ctx.esc(g.title)}" onclick="openGameModal(${ctx.arg(g.package)}, 'installed')">
        <div class="a-poster">
          ${img(ctx, g, "poster", "a-poster-art")}
          ${flag || `<span class="a-kind">${g.is_vr ? "VR" : "2D"}</span>`}
        </div>
        <div class="a-name" title="${ctx.esc(g.title)}">${ctx.esc(g.title)}</div>
        <div class="a-meta">${ctx.esc(metaFor(ctx, g))}</div>
      </div>`;
  }

  // The shelf holds exactly one row: the wide card spans three columns and the capsules fill the rest.
  function fitShelf() {
    const shelf = document.querySelector("#library-view .a-shelf");
    if (!shelf) return;
    const cols = getComputedStyle(shelf).gridTemplateColumns.split(" ").filter(Boolean).length || 1;
    const narrow = cols < 5;
    shelf.classList.toggle("narrow", narrow);
    const room = narrow ? cols : cols - 3;
    const caps = shelf.querySelectorAll(".a-cap");
    let changed = false;
    caps.forEach((cap, i) => {
      const hide = i >= room;
      if (cap.hidden !== hide) { cap.hidden = hide; changed = true; }
    });
    if (changed && window.gamepadNav) window.gamepadNav.updateFocusables();
  }

  function library(ctx) {
    setLibraryCount(ctx);
    const all = ctx.state.installed || [];
    const searching = !!(ctx.query && ctx.query.trim());
    let shelf = "";
    if (!searching && ctx.recent.length) {
      const lead = ctx.recent[0];
      const rest = all.filter(g => g.package !== lead.package).sort(byRecent).slice(0, 9);
      shelf = `
        <section class="a-section" aria-label="Recent games">
          <div class="a-h"><h2>Recent games</h2></div>
          <div class="a-shelf">${leadCard(ctx, lead)}${rest.map(g => capsule(ctx, g)).join("")}</div>
        </section>`;
    }
    const title = searching ? `Results for “${ctx.esc(ctx.query.trim())}”` : "All games and apps";
    ctx.root.innerHTML = `
      ${shelf}
      <section class="a-section" aria-label="All games and apps">
        <div class="a-h">
          <h2>${title} <span class="a-count">${ctx.games.length}</span></h2>
          <div class="a-tools">
            <label class="a-sort"><span>Sort</span>${ctx.sortSelect()}</label>
            <button type="button" class="a-tool" onclick="checkForUpdates(true)" title="Look for new versions of your games">${REFRESH_SVG}<span>Check for updates</span></button>
          </div>
        </div>
        <div class="a-grid">${ctx.games.map(g => tile(ctx, g)).join("")}</div>
      </section>`;
    fitShelf();
  }

  function empty(ctx) {
    setLibraryCount(ctx);
    return `
      <div class="a-empty">
        <h3>Your library is empty</h3>
        <p>Install a game from Browse, or a file you already have. Everything you install shows up here and in your Steam library.</p>
        <div class="empty-actions">
          <button class="btn-primary" onclick="goToTab('catalog')">Browse</button>
          <button class="btn-secondary" onclick="goToTab('sideload')">Install a file</button>
        </div>
      </div>`;
  }

  // The game page leads with the wide hero picture instead of the square cover.
  function heroOpenGameModal(id, mode) {
    const result = realOpenGameModal.apply(this, arguments);
    const cover = document.getElementById("modal-game-cover");
    const banner = document.getElementById("modal-cover-banner");
    if (banner) banner.classList.toggle("a-hero", mode === "installed");
    if (cover && mode === "installed") {
      const game = ((appState && appState.installed) || []).find(g => g.package === id);
      if (game) {
        const fallback = cover.src;
        cover.onerror = () => { cover.onerror = null; cover.src = fallback; };
        cover.src = `/api/installed/artwork/${encodeURIComponent(game.package)}?slot=hero`;
      }
    }
    return result;
  }

  function mount(ctx) {
    appState = ctx.state;
    const header = document.querySelector(".app-header");
    if (header && !document.getElementById("a-status")) {
      const box = document.createElement("div");
      box.id = "a-status";
      box.className = "a-status";
      box.innerHTML = `
        <span class="a-st-wifi" role="img" aria-label="Network">${ctx.icon("wifi")}</span>
        <span class="a-st-bat" hidden>${ctx.icon("battery")}<span></span></span>
        <a class="a-st-kofi" href="https://ko-fi.com/K3K314GUP" target="_blank" rel="noopener noreferrer" title="Support FrameLoad on Ko-fi" aria-label="Support FrameLoad on Ko-fi"><svg class="ic" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 20.5s-7.5-4.6-7.5-10.1A4.4 4.4 0 0 1 12 7.3a4.4 4.4 0 0 1 7.5 3.1c0 5.5-7.5 10.1-7.5 10.1z"/></svg></a>
        <time class="a-st-clock" id="a-clock"></time>`;
      header.appendChild(box);
      added.push(box);
    }
    const libTab = document.querySelector('.tab-btn[data-tab="library"]');
    if (libTab && !document.getElementById("a-lib-count")) {
      const badge = document.createElement("span");
      badge.id = "a-lib-count";
      badge.className = "tab-badge a-lib-count";
      badge.hidden = true;
      libTab.appendChild(badge);
      added.push(badge);
    }
    tickClock();
    clockTimer = setInterval(tickClock, 10000);
    window.addEventListener("online", onNetwork);
    window.addEventListener("offline", onNetwork);
    const view = document.getElementById("library-view");
    if (view && window.ResizeObserver) {
      shelfObserver = new ResizeObserver(fitShelf);
      shelfObserver.observe(view);
    }
    if (typeof window.openGameModal === "function" && !realOpenGameModal) {
      realOpenGameModal = window.openGameModal;
      window.openGameModal = heroOpenGameModal;
    }
    renderStatus(ctx);
    setLibraryCount(ctx);
  }

  function onNetwork() {
    if (typeof window.renderShellStatus === "function") window.renderShellStatus();
    else {
      const wifi = document.querySelector("#a-status .a-st-wifi");
      if (wifi) wifi.classList.toggle("off", navigator.onLine === false);
    }
  }

  function unmount() {
    added.splice(0).forEach(el => el.remove());
    clearInterval(clockTimer);
    clockTimer = null;
    window.removeEventListener("online", onNetwork);
    window.removeEventListener("offline", onNetwork);
    if (shelfObserver) { shelfObserver.disconnect(); shelfObserver = null; }
    if (realOpenGameModal) {
      window.openGameModal = realOpenGameModal;
      realOpenGameModal = null;
    }
    const banner = document.getElementById("modal-cover-banner");
    if (banner) banner.classList.remove("a-hero");
  }

  registerSkin("a", {
    library,
    empty,
    status(ctx) { renderStatus(ctx); setLibraryCount(ctx); },
    mount,
    unmount,
  });
})();
