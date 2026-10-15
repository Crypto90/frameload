// Look E: Command Center. A side bar (sections, recent games, activity, device status) and a
// sortable library list beside a detail panel for the selected game. See registerSkin in app.js.
(function () {
  const TAB_NAMES = { library: "Library", catalog: "Browse", sideload: "Install file", downloads: "Downloads", storage: "Storage", system: "System" };
  const FILTERS = [["all", "All"], ["vr", "VR"], ["2d", "2D"], ["attention", "Attention"]];
  // Column headers that sort; the app's sort keys (setLibrarySort).
  const SORTABLE = { name: "name", size: "size", last: "recent" };

  const view = { selected: null, filter: "all", moreOpen: false, ctx: null, onNav: null };

  const esc = (s) => (view.ctx ? view.ctx.esc(s) : String(s == null ? "" : s));
  const arg = (v) => view.ctx.arg(v);
  const ic = (name, cls) => view.ctx.icon(name, cls);
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const narrow = () => window.matchMedia("(max-width: 760px)").matches;
  const allGames = () => (view.ctx && view.ctx.state.installed) || [];
  const findGame = (pkg) => allGames().find((g) => g.package === pkg);
  const bytes = (n) => (typeof formatBytes === "function" ? formatBytes(n) : `${Math.round((n || 0) / 1048576)} MB`);

  const isVr = (g) => !!g.is_vr;
  const level = (g) => (g.compat && g.compat.level) || "";
  const isLepton = (g) => g.kind === "quest" || g.kind === "flat";
  const needsPort = (g) => g.kind === "quest" && level(g) === "needs_port";
  const needsAttention = (g) => g.port_failed || level(g) === "needs_port" || level(g) === "blocked" || !!view.ctx.updateFor(g);

  function passes(g, filter) {
    if (filter === "vr") return isVr(g);
    if (filter === "2d") return !isVr(g);
    if (filter === "attention") return needsAttention(g);
    return true;
  }

  function counts(games) {
    const c = { all: games.length, vr: 0, "2d": 0, attention: 0 };
    games.forEach((g) => {
      if (isVr(g)) c.vr++; else c["2d"]++;
      if (needsAttention(g)) c.attention++;
    });
    return c;
  }

  function iconImg(g, cls) {
    const fallback = esc(view.ctx.art(g, "poster"));
    return `<img class="${cls}" src="${esc(view.ctx.art(g, "icon"))}" alt="" draggable="false" decoding="async" loading="lazy" onerror="this.onerror=null; this.src='${fallback}';">`;
  }

  function hoursText(g) {
    const s = Number(g.playtime_seconds) || 0;
    if (s < 60) return "";
    if (s < 3600) return `${Math.round(s / 60)} min`;
    return `${(s / 3600).toFixed(s < 36000 ? 1 : 0)} h`;
  }

  function lastText(g) {
    if (g.is_running) return "Now";
    return g.last_played ? cap(view.ctx.ago(g.last_played)) : "Never";
  }

  function driveShort(g) {
    if (!g.is_external) return "Internal";
    return g.device_name || "External";
  }

  function chip(g) {
    if (g.is_running) return '<span class="e-chip ok"><i></i>Playing</span>';
    if (g.port_failed) return '<span class="e-chip bad">Port failed</span>';
    if (level(g) === "blocked") return '<span class="e-chip bad">Cannot run</span>';
    if (level(g) === "needs_port") return '<span class="e-chip warn">Needs porting</span>';
    if (view.ctx.updateFor(g)) return '<span class="e-chip info">Update</span>';
    return "";
  }

  // --- Library list -------------------------------------------------------------------------
  function rowHtml(g) {
    const pkg = esc(g.package);
    const on = g.package === view.selected;
    const hours = hoursText(g);
    return `
      <div class="e-row${on ? " on" : ""}${g.is_running ? " live" : ""}" role="button" tabindex="0" data-e-key="row:${pkg}" data-package="${pkg}"
           aria-pressed="${on}" aria-label="${esc(g.title)}" onclick="eLook.pick(${arg(g.package)})" onkeydown="eLook.key(event, ${arg(g.package)})">
        <span class="e-art">${iconImg(g, "")}</span>
        <span class="e-nm"><b>${esc(g.title)}</b><small><i class="e-k">${isVr(g) ? "VR" : "2D"}</i>${hours ? `${hours} played` : g.last_played ? "Play time not recorded" : "Not played yet"}</small></span>
        <span class="e-c e-size">${g.apk_size ? bytes(g.apk_size) : "&ndash;"}</span>
        <span class="e-c e-drive">${esc(driveShort(g))}</span>
        <span class="e-c e-last">${esc(lastText(g))}</span>
        <span class="e-c e-status">${chip(g)}</span>
      </div>`;
  }

  function headHtml() {
    const sort = view.ctx.state.librarySort;
    const col = (key, label, cls) => {
      const on = SORTABLE[key] === sort;
      return `<button type="button" class="e-hc ${cls}${on ? " on" : ""}" aria-pressed="${on}" data-e-key="sort:${key}" onclick="setLibrarySort('${SORTABLE[key]}')">${label}${on ? ic("chevron", "e-sorted") : ""}</button>`;
    };
    return `
      <div class="e-head" role="row">
        ${col("name", "Name", "e-hn")}
        ${col("size", "Size", "e-size r")}
        <span class="e-hc e-drive static">Drive</span>
        ${col("last", "Last played", "e-last")}
        <span class="e-hc e-status static">Status</span>
      </div>`;
  }

  function footHtml(shown) {
    const total = shown.reduce((sum, g) => sum + (Number(g.apk_size) || 0), 0);
    const added = view.ctx.state.librarySort === "installed";
    return `
      <div class="e-lfoot">
        <span class="e-sum"><b>${shown.length} ${shown.length === 1 ? "title" : "titles"}</b> &middot; ${bytes(total)} of apps</span>
        <button type="button" class="e-tbtn${added ? " on" : ""}" aria-pressed="${added}" data-e-key="sort:installed" onclick="setLibrarySort('installed')">Newest installs first</button>
        <button type="button" class="e-tbtn" data-e-key="foot:updates" onclick="checkForUpdates(true)">Check for updates</button>
        <span class="e-hints" aria-hidden="true">
          <span><b class="e-key">A</b>Select, again to open</span>
          <span><b class="e-key">LB</b><b class="e-key">RB</b>Sections</span>
        </span>
      </div>`;
  }

  // --- Detail panel -------------------------------------------------------------------------
  function controlsText(g) {
    if (!isVr(g)) return "Pointer and gamepad";
    if (!g.framebridge) return "As the game asks";
    const mode = (g.settings && g.settings.hand_input) || "auto";
    if (mode === "hands") return "Hands (finger sensors)";
    if (mode === "controllers") return "Touch controllers";
    return g.hand_tracking === "required" ? "Automatic: hands" : "Automatic: controllers";
  }

  function portingHtml(g) {
    const okLine = (text) => `<b class="ok">${ic("check")}${esc(text)}</b>`;
    if (g.port_failed) return `<b class="bad">Port failed</b>`;
    if (level(g) === "blocked") return `<b class="bad">Cannot run on the Frame</b>`;
    if (level(g) === "needs_port") return `<b class="warn">Needs porting</b>`;
    if (!isVr(g)) return okLine("Not needed");
    if (g.framebridge) return okLine("Ported by FramePort");
    if (level(g) === "ready") return okLine("Runs as it is");
    return `<b>${esc((g.compat && g.compat.label) || "Unknown")}</b>`;
  }

  function primaryHtml(g) {
    const pkg = arg(g.package);
    // A running VR game resumes by closing Steam's menu over it (Show); a 2D app is a window of its own.
    if (g.is_running && g.is_vr) {
      return `<button type="button" class="e-btn pri" data-e-key="det:pri" title="Close Steam's menu so ${esc(g.title)} is in front" aria-label="Show ${esc(g.title)}" onclick="showGame(${pkg})">${ic("play")}Show</button>`;
    }
    if (g.is_running) return `<button type="button" class="e-btn pri" data-e-key="det:pri" onclick="launchGame(${pkg})">${ic("play")}Resume</button>`;
    if (view.ctx.updateFor(g)) return `<button type="button" class="e-btn pri" data-e-key="det:pri" onclick="updateGame(${pkg})">${ic("update")}Update</button>`;
    if (needsPort(g)) {
      return g.port_failed
        ? `<button type="button" class="e-btn pri warn" data-e-key="det:pri" onclick="portGame(${pkg})">${ic("port")}Port again</button>`
        : `<button type="button" class="e-btn pri warn" data-e-key="det:pri" onclick="launchGame(${pkg})">${ic("port")}Port &amp; Play</button>`;
    }
    return `<button type="button" class="e-btn pri" data-e-key="det:pri" onclick="launchGame(${pkg})">${ic("play")}${isVr(g) ? "Play" : "Open"}</button>`;
  }

  function detailHtml(g) {
    if (!g) return "";
    const pkg = arg(g.package);
    const ctx = view.ctx;
    const session = g.is_running && g.last_played ? Math.max(1, Math.round((Date.now() / 1000 - g.last_played) / 60)) : 0;
    const sessionText = session ? (session < 60 ? `${session} min` : `${(session / 60).toFixed(1)} h`) : "";
    const added = g.installed_time ? new Date(g.installed_time * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
    const drive = g.device_name || (g.is_external ? "External drive" : "Internal storage");
    const hours = hoursText(g);
    const version = [g.version_name ? `${g.version_name}` : "", added ? `added ${added}` : ""].filter(Boolean).join(" · ");
    const fallback = esc(ctx.art(g, "poster"));
    const lepton = isLepton(g);
    return `
      <div class="e-hero">
        <img src="${esc(ctx.art(g, "banner"))}" alt="" draggable="false" decoding="async" onerror="this.onerror=null; this.src='${fallback}';">
        ${g.is_running ? `<span class="e-live"><i></i>Playing${sessionText ? ` &middot; ${sessionText}` : ""}</span>` : ""}
      </div>
      <div class="e-dbody">
        <h3 class="e-title" title="${esc(g.title)}">${esc(g.title)}</h3>
        <div class="e-sub"><i class="e-k">${isVr(g) ? "VR" : "2D"}</i><span>${esc(g.package)}</span></div>
        <div class="e-acts">
          ${primaryHtml(g)}
          ${g.is_running ? `<button type="button" class="e-btn stop" data-e-key="det:stop" onclick="stopGame(${pkg})">${ic("stop")}Stop</button>` : ""}
          ${lepton ? `<button type="button" class="e-btn${g.is_running ? " e-sq" : ""}" data-e-key="det:settings" onclick="openSettingsModal(${pkg})" aria-label="Settings" title="Settings">${ic("settings")}<span>Settings</span></button>` : ""}
        </div>
        ${needsPort(g) && g.port_failed && g.port_error ? `<p class="e-note warn">${esc(g.port_error)}</p>` : ""}
        <div class="e-stats">
          <div><span class="e-label">Play time</span><b>${hours || "&ndash;"}</b></div>
          <div><span class="e-label">Last played</span><b>${esc(lastText(g))}</b></div>
        </div>
        <dl class="e-dl">
          <div><dt>Drive</dt><dd>${esc(drive)}</dd></div>
          <div><dt>Size</dt><dd>${g.apk_size ? bytes(g.apk_size) : "&ndash;"}</dd></div>
          <div><dt>Porting</dt><dd>${portingHtml(g)}</dd></div>
          <div><dt>Controls</dt><dd>${esc(controlsText(g))}</dd></div>
          <div><dt>Version</dt><dd>${version ? esc(version) : "&ndash;"}</dd></div>
        </dl>
      </div>
      <div class="e-more${view.moreOpen ? " open" : ""}" id="e-more">
        ${lepton ? `<button type="button" class="e-mi" onclick="openLogModal(${pkg})">Launch log</button>` : ""}
        ${lepton && g.last_session && g.last_session.abnormal ? `<button type="button" class="e-mi" onclick="eLook.more(false); openSessionDialog(${pkg})">What happened</button>` : ""}
        <button type="button" class="e-mi" onclick="backupSaves(${pkg})">Back up saves</button>
        <button type="button" class="e-mi danger" onclick="eLook.more(false); uninstallGame(${pkg})">Uninstall</button>
      </div>
      <div class="e-dfoot">
        <button type="button" class="e-btn sm" data-e-key="det:open" onclick="openGameModal(${pkg}, 'installed')">${ic("arrow")}Open page</button>
        <button type="button" class="e-btn sm e-sq e-push${view.moreOpen ? " on" : ""}" data-e-key="det:more" aria-expanded="${view.moreOpen}" aria-label="More actions" title="More actions" onclick="eLook.more()">${ic("dots")}</button>
      </div>`;
  }

  function renderDetail() {
    const box = document.getElementById("e-det");
    if (!box) return;
    box.innerHTML = detailHtml(findGame(view.selected));
  }

  // --- Header: page title, the library's filters, refresh -----------------------------------
  function activeTab() {
    const tab = document.querySelector(".tab-btn.active");
    return (tab && tab.dataset.tab) || "library";
  }

  function renderHeader() {
    const title = document.getElementById("e-htitle");
    const label = document.querySelector(".tab-btn.active .tab-label");
    if (title) title.textContent = (label && label.textContent.trim()) || TAB_NAMES[activeTab()] || "";
    const all = allGames();
    const words = ((view.ctx && view.ctx.state.libraryQuery) || "").toLowerCase().split(/\s+/).filter(Boolean);
    const games = all.filter((g) => words.every((w) => `${g.title || ""} ${g.package || ""}`.toLowerCase().includes(w)));
    const c = counts(games);
    const count = document.getElementById("e-hcount");
    if (count) count.textContent = games.length === all.length ? String(all.length) : `${games.length} of ${all.length}`;
    const seg = document.getElementById("e-seg");
    if (seg) {
      seg.innerHTML = FILTERS.map(([key, label]) => {
        const on = view.filter === key;
        const n = key === "all" ? "" : `<em class="${key === "attention" && c.attention ? "warn" : ""}">${c[key]}</em>`;
        return `<button type="button" class="${on ? "on" : ""}" aria-pressed="${on}" onclick="eLook.filter('${key}')">${label}${n}</button>`;
      }).join("");
    }
    const navCount = document.querySelector('.tab-btn[data-tab="library"] .e-navcount');
    if (navCount) navCount.textContent = all.length ? String(all.length) : "";
  }

  // --- Side bar: recent games, activity, device ---------------------------------------------
  function ensureSide(nav) {
    if (!nav) return null;
    if (!nav.querySelector(".e-side")) {
      nav.innerHTML = `
        <div class="e-side">
          <div class="e-label e-sl" id="e-recent-label">Recent</div>
          <div class="e-recent" id="e-recent"></div>
          <div class="e-label e-sl">Activity</div>
          <div class="e-activity" id="e-activity"></div>
          <div class="e-dev" id="e-dev"></div>
        </div>`;
    }
    return nav;
  }

  function renderRecent() {
    const box = document.getElementById("e-recent");
    if (!box) return;
    const recent = allGames().filter((g) => g.last_played || g.is_running)
      .sort((a, b) => (b.is_running - a.is_running) || (b.last_played - a.last_played)).slice(0, 4);
    const label = document.getElementById("e-recent-label");
    if (label) label.hidden = !recent.length;
    box.hidden = !recent.length;
    box.innerHTML = recent.map((g) => `
      <button type="button" class="e-ritem" onclick="eLook.open(${arg(g.package)})" title="${esc(g.title)}">
        <span class="e-ra">${iconImg(g, "")}</span><em>${esc(g.title)}</em>${g.is_running ? '<i class="e-dot" aria-label="Running"></i>' : ""}
      </button>`).join("");
  }

  function renderActivity(ctx) {
    const box = document.getElementById("e-activity");
    if (box) {
      const jobs = [];
      const port = ctx.activity && ctx.activity.port;
      const dl = ctx.activity && ctx.activity.download;
      const job = (cls, onclick, label, percent, value, detail) => `
        <button type="button" class="e-job ${cls}" onclick="${onclick}"${detail ? ` title="${esc(detail)}"` : ""}>
          <span class="e-jt"><b>${esc(label)}</b><em>${esc(value)}</em></span>
          <span class="e-bar"><s style="width:${percent}%"></s></span>
        </button>`;
      if (port) jobs.push(job("port", "openPortingModal()", port.label, port.queued ? 100 : port.percent, port.queued ? "Waiting" : `${port.percent}%`));
      if (dl) jobs.push(job("dl", "goToTab('downloads')", dl.label, dl.percent, `${dl.percent}%`, dl.detail));
      box.innerHTML = jobs.length ? `<div class="e-jobs">${jobs.join("")}</div>` : '<p class="e-idle">Nothing downloading or porting.</p>';
    }
    const dev = document.getElementById("e-dev");
    if (dev) {
      const d = ctx.device || {};
      const cell = (value, label, extra = "") => `<span class="e-dcell"${extra}><b>${value == null ? "&ndash;" : value}</b><small>${label}</small></span>`;
      dev.innerHTML = `
        ${cell(d.battery == null ? null : `${d.battery}%`, d.plugged ? "Charging" : "Battery")}
        <button type="button" class="e-dcell" onclick="openStorageTab()" title="Storage"><b>${d.freeGb == null ? "&ndash;" : `${Math.round(d.freeGb)} GB`}</b><small>Free</small></button>
        <button type="button" class="e-dcell" onclick="openPerformanceCard()" title="Performance"><b>${d.cpu == null ? "&ndash;" : `${d.cpu}%`}</b><small>CPU</small></button>`;
    }
  }

  // --- Focus that survives a redraw ---------------------------------------------------------
  function rememberFocus(root) {
    const nav = window.gamepadNav;
    const el = nav && nav.focusedElement;
    return el && root.contains(el) ? el.getAttribute("data-e-key") : null;
  }

  function restoreFocus(root, key) {
    if (!key || !window.gamepadNav) return;
    const el = root.querySelector(`[data-e-key="${CSS.escape(key)}"]`);
    if (el) window.gamepadNav.setFocus(el);
  }

  // --- The view ------------------------------------------------------------------------------
  function library(ctx) {
    view.ctx = ctx;
    const root = ctx.root;
    const shown = ctx.games.filter((g) => passes(g, view.filter));
    if (!shown.some((g) => g.package === view.selected)) {
      const pick = shown.find((g) => g.is_running) || shown[0];
      view.selected = pick ? pick.package : null;
      view.moreOpen = false;
    }
    const focusKey = rememberFocus(root);
    const label = (FILTERS.find(([k]) => k === view.filter) || FILTERS[0])[1];
    root.innerHTML = `
      <div class="e-lib">
        <section class="e-list" aria-label="Library">
          ${headHtml()}
          <div class="e-rows">
            ${shown.length ? shown.map(rowHtml).join("") : `
              <div class="e-none">
                <b>Nothing under ${esc(label)}</b>
                <span>${view.filter === "attention" ? "Every game is ready to play." : "No game in your library matches this filter."}</span>
                <button type="button" class="e-btn sm" onclick="eLook.filter('all')">Show all</button>
              </div>`}
          </div>
          ${footHtml(shown)}
        </section>
        <aside class="e-det" id="e-det" aria-label="Selected game">${detailHtml(findGame(view.selected))}</aside>
      </div>`;
    restoreFocus(root, focusKey);
    renderHeader();
    renderRecent();
  }

  function empty(ctx) {
    view.ctx = ctx;
    renderHeader();
    renderRecent();
    return `
      <div class="e-empty">
        <span class="e-empty-mark">${ctx.icon("download")}</span>
        <h3>Your library is empty</h3>
        <p>Install something from Browse, or a file you already have. Everything you install appears here and in your Steam library.</p>
        <div class="e-empty-acts">
          <button type="button" class="e-btn pri" onclick="goToTab('catalog')">Browse apps</button>
          <button type="button" class="e-btn" onclick="goToTab('sideload')">Install a file</button>
        </div>
      </div>`;
  }

  function status(ctx) {
    view.ctx = view.ctx || ctx;
    if (!ensureSide(ctx.navExtra)) return;
    renderActivity(ctx);
    if (!document.getElementById("e-recent").childElementCount) renderRecent();
  }

  function mount(ctx) {
    view.ctx = ctx;
    const header = document.querySelector(".app-header");
    if (header && !header.querySelector(".e-hl")) {
      const hl = document.createElement("div");
      hl.className = "e-hl";
      hl.innerHTML = `<h1 class="e-htitle"><span id="e-htitle">Library</span><small id="e-hcount"></small></h1><div class="e-seg" id="e-seg" role="group" aria-label="Show"></div>`;
      header.insertBefore(hl, header.firstChild);
      const ht = document.createElement("div");
      ht.className = "e-ht";
      ht.innerHTML = `
        <button type="button" class="e-ibtn" onclick="loadInstalled()" title="Refresh the library" aria-label="Refresh the library">${ctx.icon("port")}</button>`;
      const search = header.querySelector(".search-wrapper");
      header.insertBefore(ht, search ? search.nextSibling : null);
    }
    const libTab = document.querySelector('.tab-btn[data-tab="library"]');
    if (libTab && !libTab.querySelector(".e-navcount")) {
      const n = document.createElement("b");
      n.className = "e-navcount";
      libTab.appendChild(n);
    }
    view.onNav = () => setTimeout(renderHeader, 0);
    document.querySelectorAll(".tab-btn").forEach((t) => t.addEventListener("click", view.onNav));
    const search = document.getElementById("search-input");
    if (search) search.addEventListener("input", view.onNav);
    ensureSide(ctx.navExtra);
    renderActivity(ctx);
    renderHeader();
  }

  function unmount() {
    document.querySelectorAll(".e-hl, .e-ht, .e-navcount").forEach((el) => el.remove());
    if (view.onNav) {
      document.querySelectorAll(".tab-btn").forEach((t) => t.removeEventListener("click", view.onNav));
      const search = document.getElementById("search-input");
      if (search) search.removeEventListener("input", view.onNav);
    }
    view.onNav = null;
    const nav = document.getElementById("nav-extra");
    if (nav) nav.innerHTML = "";
    view.moreOpen = false;
  }

  // Called from the markup.
  window.eLook = {
    // A first press selects a row, a second opens its page. On a phone there is no side panel.
    pick(pkg) {
      if (narrow() || view.selected === pkg) {
        openGameModal(pkg, "installed");
        return;
      }
      view.selected = pkg;
      view.moreOpen = false;
      document.querySelectorAll("#library-view .e-row").forEach((row) => {
        const on = row.dataset.package === pkg;
        row.classList.toggle("on", on);
        row.setAttribute("aria-pressed", on);
      });
      renderDetail();
      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    },
    key(event, pkg) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.pick(pkg);
      }
    },
    open(pkg) {
      view.selected = pkg;
      if (activeTab() !== "library") goToTab("library");
      if (view.ctx && typeof renderInstalledGrid === "function") renderInstalledGrid();
      const row = document.querySelector(`#library-view .e-row[data-package="${CSS.escape(pkg)}"]`);
      if (row) row.scrollIntoView({ block: "nearest" });
    },
    filter(key) {
      view.filter = key;
      if (typeof renderInstalledGrid === "function") renderInstalledGrid();
      renderHeader();
    },
    more(force) {
      view.moreOpen = typeof force === "boolean" ? force : !view.moreOpen;
      const box = document.getElementById("e-more");
      if (box) box.classList.toggle("open", view.moreOpen);
      const btn = document.querySelector('#e-det [data-e-key="det:more"]');
      if (btn) {
        btn.classList.toggle("on", view.moreOpen);
        btn.setAttribute("aria-expanded", view.moreOpen);
      }
      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    },
  };

  registerSkin("e", { library, empty, status, mount, unmount });
})();
