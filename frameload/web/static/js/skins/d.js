// Look D: Neon. The original FrameLoad look, refined: a Recently Played shelf of wide cards over a
// grid of square game cards that lead with each game's own icon. Registers through registerSkin.
(function () {
  "use strict";
  let appState = null;  // app.js's state, kept from the last call so unmount() can restore the chips

  // Same rounding as app.js's gb(), so the chip reads the same in every look.
  const gb = bytes => (bytes / 1024 ** 3).toFixed(bytes >= 10 * 1024 ** 3 ? 0 : 1);
  function perfText(state) {
    const snap = state && state.perf && state.perf.last;
    if (!snap || typeof snap.cpu_percent !== "number" || !snap.memory) return null;
    return { cpu: `CPU ${Math.round(snap.cpu_percent)}%`, ram: `RAM ${gb(snap.memory.used)}/${gb(snap.memory.total)} GB`,
             cpuShort: `${Math.round(snap.cpu_percent)}%`, ramShort: `${gb(snap.memory.used)} GB` };
  }

  // The battery and storage chips in the header get icons in this look. app.js writes its own
  // text into them on every telemetry update and then calls status(), so they are redrawn here.
  function drawHeaderChips(ctx) {
    const dev = ctx.device;
    const bat = document.getElementById("header-battery");
    if (bat) {
      if (dev.battery == null) {
        bat.hidden = !!ctx.state.system;  // a machine without a battery has nothing to show
        if (!ctx.state.system) bat.innerHTML = `${ctx.icon("battery")}<span>--%</span>`;
      } else {
        bat.hidden = false;
        const low = dev.battery <= 20 && !dev.plugged;
        bat.classList.toggle("nd-low", low);
        bat.title = `Battery ${dev.battery}%${dev.plugged ? ", charging" : ""}`;
        bat.innerHTML = `${ctx.icon("battery")}<span>${dev.battery}%</span>${dev.plugged ? '<span class="nd-plug" aria-label="charging">&#9889;</span>' : ""}`;
      }
    }
    const drive = document.getElementById("header-storage");
    if (drive && dev.freeGb != null) {
      drive.innerHTML = `${ctx.icon("drive")}<span class="nd-long">${dev.freeGb} GB free</span><span class="nd-short">${Math.round(dev.freeGb)} GB</span>`;
      drive.title = `${dev.freeGb} GB free · open Storage`;
    }
    // Long and short figures: narrower windows show the short ones (.nd-short), see d.css.
    const perf = document.getElementById("header-perf");
    const text = perfText(ctx.state);
    if (perf && text) {
      perf.innerHTML = `<span class="nd-long">${text.cpu} · ${text.ram}</span><span class="nd-short">${text.cpuShort}${ctx.icon("memory")}${text.ramShort}</span>`;
      perf.title = `${text.cpu} · ${text.ram}`;
    }
  }

  // Puts the chips back the way app.js writes them, for the next look.
  function restoreHeaderChips(state) {
    const sys = (state && state.system) || {};
    const bat = document.getElementById("header-battery");
    if (bat) {
      bat.hidden = false;
      bat.classList.remove("nd-low");
      bat.removeAttribute("title");
      bat.innerHTML = sys.battery
        ? `<span class="pulse-dot"></span> ${sys.battery.percent}% ${sys.battery.plugged ? "⚡" : ""}`
        : '<span class="pulse-dot"></span> --%';
    }
    const drive = document.getElementById("header-storage");
    if (drive) {
      drive.textContent = sys.storage ? `💾 ${sys.storage.free_gb} GB Free` : "💾 -- GB Free";
      drive.title = "Open Steam Storage Manager";
    }
    const perf = document.getElementById("header-perf");
    const text = perfText(state);
    if (perf) {
      perf.title = "CPU and memory use";
      if (text) perf.textContent = `${text.cpu} · ${text.ram}`;
    }
  }

  // An image that falls back to the game's library picture, then to the generic cover.
  function artImg(ctx, game, slot, cls) {
    const fallback = ctx.esc(ctx.art(game, "poster"));
    return `<img class="${cls}" src="${ctx.esc(ctx.art(game, slot))}" alt="" draggable="false" decoding="async" loading="lazy"
      onerror="if (this.dataset.f) { this.onerror = null; this.src = '/static/assets/fallback_cover.svg'; } else { this.dataset.f = 1; this.src = '${fallback}'; }">`;
  }

  function recentCard(ctx, game) {
    const total = ctx.playtime(game.playtime_seconds);
    const meta = `${ctx.played(game)}${total ? ` · ${total}` : ""}`;
    return `
      <div class="recent-card nd-rc${game.is_running ? " is-running" : ""}" draggable="false" onclick="openGameModal(${ctx.arg(game.package)}, 'installed')">
        <div class="recent-backdrop" style="background-image:url('${ctx.esc(ctx.art(game, "banner"))}'), url('${ctx.esc(ctx.art(game, "poster"))}')"></div>
        ${artImg(ctx, game, "icon", "recent-cover")}
        <div class="recent-info">
          <div class="recent-title" title="${ctx.esc(game.title)}">${ctx.esc(game.title)}</div>
          <div class="recent-meta" title="${ctx.esc(meta)}">${ctx.esc(meta)}</div>
          <div class="recent-actions">${ctx.showButton(game, "card-btn play", { short: true })}${ctx.primaryButton(game)}</div>
        </div>
      </div>`;
  }

  function gameCard(ctx, game) {
    const pkg = ctx.arg(game.package);
    const level = (game.compat && game.compat.level) || "";
    const attention = level === "needs_port" || level === "blocked";
    const update = ctx.updateFor(game);
    const where = game.is_external ? (game.device_name || "External") : "Internal";
    return `
      <div class="game-card nd-card${game.is_running ? " is-running" : ""}" data-package="${ctx.esc(game.package)}" draggable="false" onclick="openGameModal(${pkg}, 'installed')">
        <div class="card-poster">
          ${artImg(ctx, game, "icon", "nd-cover")}
          <div class="badge-overlay">
            <span class="badge ${game.is_vr ? "vr" : "flat"}">${game.is_vr ? "VR" : "2D"}</span>
            ${game.is_running ? '<span class="badge installed">Playing</span>' : ""}
          </div>
          <div class="badge-overlay nd-right">
            ${update ? '<span class="badge update" title="A newer version is on the mirror">Update</span>' : ""}
            ${attention ? `<span class="badge compat-${ctx.esc(level)}" title="${ctx.esc(game.compat.label || "")}">${level === "blocked" ? "Cannot run" : "Needs porting"}</span>` : ""}
            ${!attention && ctx.community(game) ? `<span class="badge community-${ctx.esc(ctx.community(game).status)}" title="${ctx.esc(ctx.community(game).note)}">${ctx.esc(ctx.community(game).label)}</span>` : ""}
          </div>
        </div>
        <div class="card-body">
          <div class="card-title" title="${ctx.esc(game.title)}">${ctx.esc(game.title)}</div>
          <div class="card-meta"><span>${ctx.esc(where)} · ${ctx.esc(ctx.played(game))}</span></div>
          <div class="card-actions${ctx.updateButton(game) ? " has-update" : ""}">
            ${ctx.primaryButton(game)}
            <button class="card-btn download" onclick="event.stopPropagation(); openSettingsModal(${pkg})">Settings</button>
            ${ctx.updateButton(game)}
          </div>
        </div>
      </div>`;
  }

  registerSkin("d", {
    library(ctx) {
      const recent = ctx.recent.length ? `
        <section class="library-recent nd-shelf" aria-label="Recently played">
          <h2 class="section-title">Recently Played</h2>
          <div class="recent-grid nd-recent">${ctx.recent.map(g => recentCard(ctx, g)).join("")}</div>
        </section>
        <h2 class="section-title nd-all">All Games</h2>` : "";
      ctx.root.innerHTML = `${recent}<div id="library-grid" class="games-grid nd-grid">${ctx.games.map(g => gameCard(ctx, g)).join("")}</div>`;
    },

    status(ctx) {
      appState = ctx.state;
      drawHeaderChips(ctx);
    },

    mount(ctx) {
      appState = ctx.state;
      drawHeaderChips(ctx);
    },

    unmount() {
      restoreHeaderChips(appState);
    },
  });
})();
