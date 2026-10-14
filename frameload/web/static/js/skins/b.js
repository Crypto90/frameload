// Look B: Spatial. Registers how this look draws the library (see registerSkin in app.js).
// The Library is a big title, a segmented filter, a "Jump back in" row of wide cards and a grid of
// app icons with their names below, like a headset's home screen.
(function () {
  const FILTERS = [
    ["all", "All"],
    ["vr", "VR games"],
    ["flat", "2D apps"],
    ["attention", "Needs attention"],
  ];
  let filter = "all";   // kept across re-renders (search, sort, running state)

  function level(game) {
    return (game.compat && game.compat.level) || "";
  }

  function needsAttention(ctx, game) {
    const l = level(game);
    return l === "needs_port" || l === "blocked" || !!game.port_failed || !!ctx.updateFor(game);
  }

  function inFilter(ctx, game, id) {
    if (id === "vr") return !!game.is_vr;
    if (id === "flat") return !game.is_vr;
    if (id === "attention") return needsAttention(ctx, game);
    return true;
  }

  function plural(n, one, many) {
    return `${n} ${n === 1 ? one : many}`;
  }

  // The status shown on an icon, most important first.
  function pip(ctx, game) {
    const l = level(game);
    if (game.is_running) return { cls: "run", text: "Playing", say: "playing now" };
    if (l === "blocked") return { cls: "blocked", text: "Can't run", say: "cannot run on the Steam Frame" };
    if (game.port_failed) return { cls: "", text: "Port failed", say: "porting failed" };
    if (l === "needs_port") return { cls: "", text: "Port", say: "needs porting" };
    if (ctx.updateFor(game)) return { cls: "update", text: "Update", say: "update ready" };
    return null;
  }

  // The round button on a Jump back in card: the same choice as the standard Play button.
  function roundButton(ctx, game) {
    const pkg = ctx.arg(game.package);
    const name = ctx.esc(game.title || game.package);
    const l = level(game);
    if (game.is_running) {
      return `<button type="button" class="sp-round stop" aria-label="Stop ${name}" title="Stop" onclick="event.stopPropagation(); stopGame(${pkg})">${ctx.icon("stop")}</button>`;
    }
    if (ctx.updateFor(game)) {
      return `<button type="button" class="sp-round update" aria-label="Update ${name}" title="Update" onclick="event.stopPropagation(); updateGame(${pkg})">${ctx.icon("update")}</button>`;
    }
    if (l === "blocked") return "";
    if (l === "needs_port" && game.kind === "quest") {
      const fn = game.port_failed ? "portGame" : "launchGame";
      const label = game.port_failed ? "Port again" : "Port and play";
      return `<button type="button" class="sp-round" aria-label="${label}: ${name}" title="${label}" onclick="event.stopPropagation(); ${fn}(${pkg})">${ctx.icon("port")}</button>`;
    }
    return `<button type="button" class="sp-round" aria-label="Play ${name}" title="Play" onclick="event.stopPropagation(); launchGame(${pkg})">${ctx.icon("play")}</button>`;
  }

  function cardHtml(ctx, game) {
    const pkg = ctx.arg(game.package);
    const title = ctx.esc(game.title || game.package);
    const total = ctx.playtime(game.playtime_seconds);
    const status = game.is_running
      ? `<span class="sp-dot" aria-hidden="true"></span>Playing now${total ? ` · ${ctx.esc(total)}` : ""}`
      : `${ctx.esc(ctx.played(game))}${total ? ` · ${ctx.esc(total)}` : ""}`;
    // The hero has no title painted into it (a banner usually does), so the card's own title and
    // the app's icon read cleanly on top of it.
    const banner = ctx.esc(ctx.art(game, "banner"));
    return `
      <div class="sp-card" role="button" tabindex="0" data-sp-key="card:${ctx.esc(game.package)}"
           aria-label="${title}" onclick="openGameModal(${pkg}, 'installed')"
           onkeydown="if (event.target === this && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); this.click(); }">
        <img class="sp-card-art" src="${ctx.esc(ctx.art(game, "hero"))}" alt="" draggable="false" decoding="async"
             onerror="this.onerror=null; this.src='${banner}';">
        <span class="sp-card-icon"><img src="${ctx.esc(ctx.art(game, "icon"))}" alt="" draggable="false" decoding="async"
             onerror="this.onerror=null; this.src='${ctx.esc(ctx.art(game, "apk_icon"))}';"></span>
        <div class="sp-card-info"><b>${title}</b><small>${status}</small></div>
        ${roundButton(ctx, game)}
      </div>`;
  }

  function appHtml(ctx, game) {
    const pkg = ctx.arg(game.package);
    const title = ctx.esc(game.title || game.package);
    const p = pip(ctx, game);
    const kind = game.is_vr ? "VR game" : "2D app";
    const apk = ctx.esc(ctx.art(game, "apk_icon"));
    return `
      <button type="button" class="sp-app" data-sp-key="app:${ctx.esc(game.package)}"
              aria-label="${title}, ${kind}${p ? `, ${p.say}` : ""}" title="${title}"
              onclick="openGameModal(${pkg}, 'installed')">
        <span class="sp-icon">
          <img src="${ctx.esc(ctx.art(game, "icon"))}" alt="" draggable="false" decoding="async" loading="lazy"
               onerror="if (this.dataset.tried) { this.onerror = null; this.src = '/static/assets/fallback_cover.svg'; } else { this.dataset.tried = '1'; this.src = '${apk}'; }">
          ${p ? `<i class="sp-pip ${p.cls}">${p.text}</i>` : ""}
        </span>
        <span class="sp-name">${title}</span>
      </button>`;
  }

  function headHtml(ctx) {
    const all = ctx.state.installed || [];
    const parts = [];
    if (ctx.query) {
      parts.push(`${ctx.games.length} of ${all.length} match &ldquo;${ctx.esc(ctx.query)}&rdquo;`);
    } else {
      parts.push(plural(all.length, "game or app", "games and apps"));
      const running = all.filter(g => g.is_running).length;
      const updates = all.filter(g => ctx.updateFor(g)).length;
      const ports = all.filter(g => level(g) === "needs_port").length;
      if (running) parts.push(`${running} playing`);
      if (updates) parts.push(plural(updates, "update ready", "updates ready"));
      if (ports) parts.push(`${ports} to port`);
    }
    return `<header class="sp-head"><h2>Library</h2><p>${parts.map(t => `<span>${t}</span>`).join(" · ")}</p></header>`;
  }

  function segHtml(ctx) {
    return `
      <div class="sp-seg" role="group" aria-label="Show">
        ${FILTERS.map(([id, label]) => {
          const n = ctx.games.filter(g => inFilter(ctx, g, id)).length;
          const count = id === "attention"
            ? (n ? `<small class="sp-alert">${n}</small>` : "")
            : `<small>${n}</small>`;
          return `<button type="button" class="${filter === id ? "on" : ""}" aria-pressed="${filter === id}"
                    data-sp-key="seg:${id}" onclick="SpatialLook.filter('${id}')">${label}${count}</button>`;
        }).join("")}
      </div>`;
  }

  function noneHtml(id) {
    const what = { vr: "VR games", flat: "2D apps", attention: "games that need attention" }[id] || "games";
    const text = id === "attention"
      ? "Every game is ported, up to date and ready to play."
      : `Nothing in your library is one of the ${what}.`;
    return `
      <div class="sp-none">
        <h3>No ${what} here</h3>
        <p>${text}</p>
        <div class="empty-actions"><button type="button" class="btn-secondary" onclick="SpatialLook.filter('all')">Show Everything</button></div>
      </div>`;
  }

  function library(ctx) {
    const root = ctx.root;
    const nav = window.gamepadNav;
    const held = nav && nav.focusedElement && root.contains(nav.focusedElement) ? nav.focusedElement.dataset.spKey : null;

    const shown = ctx.games.filter(g => inFilter(ctx, g, filter));
    const recent = filter === "all" ? ctx.recent : [];
    root.innerHTML = `
      ${headHtml(ctx)}
      ${segHtml(ctx)}
      ${recent.length ? `
        <h3 class="sp-label">Jump back in</h3>
        <div class="sp-continue">${recent.map(g => cardHtml(ctx, g)).join("")}</div>
        <h3 class="sp-label">All games and apps</h3>` : ""}
      ${shown.length ? `<div class="sp-grid">${shown.map(g => appHtml(ctx, g)).join("")}</div>` : noneHtml(filter)}`;

    // A re-render (running state, artwork) keeps the controller on the same tile.
    if (held && nav) {
      const again = root.querySelector(`[data-sp-key="${CSS.escape(held)}"]`);
      if (again) {
        nav.focusedElement = again;
        again.classList.add("gamepad-focused");
      }
    }
  }

  function empty(ctx) {
    return `
      <header class="sp-head"><h2>Library</h2><p>Nothing installed yet</p></header>
      <div class="sp-none">
        <h3>Your library is empty</h3>
        <p>Install something from Browse, or a file you already have. Everything you install appears here and in your Steam library.</p>
        <div class="empty-actions">
          <button type="button" class="btn-primary" onclick="goToTab('catalog')">Browse Apps</button>
          <button type="button" class="btn-secondary" onclick="goToTab('sideload')">Install a File</button>
        </div>
      </div>`;
  }

  window.SpatialLook = {
    filter(id) {
      if (!FILTERS.some(([f]) => f === id)) return;
      const nav = window.gamepadNav;
      const root = document.getElementById("library-view");
      const fromSeg = (nav && nav.focusedElement && root && root.contains(nav.focusedElement)) ||
                      (root && root.contains(document.activeElement));
      filter = id;
      renderInstalledGrid();
      if (!fromSeg || !root) return;
      const btn = root.querySelector(`[data-sp-key="seg:${id}"]`);
      if (!btn) return;
      if (nav) nav.setFocus(btn);
      else btn.focus({ preventScroll: true });
    },
  };

  registerSkin("b", {
    library,
    empty,
    unmount() {
      filter = "all";
    },
  });
})();
