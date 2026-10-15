// Look C: Showcase. Registers how this look draws the library (see registerSkin in app.js).
// The library is an art-first home: the selected game fills the screen, the whole library sits in
// one shelf of square tiles below it. Moving the controller focus or the pointer onto a tile
// selects that game; pressing the selected tile opens its page.
(function () {
  "use strict";

  let selected = null;      // package shown in the hero; kept across re-renders
  let ctxLast = null;       // the last library context, for in-place hero updates
  let moved = null;         // where the tab bar lived before this look moved it into the header
  let clockTimer = null;
  let listeners = null;

  const $ = (sel, root = document) => root.querySelector(sel);

  // ---------------------------------------------------------------- choosing the hero game
  function pick(games) {
    if (!games.length) return null;
    const keep = selected && games.find(g => g.package === selected);
    if (keep) return keep;
    const running = games.find(g => g.is_running);
    if (running) return running;
    const recent = games.filter(g => g.last_played).sort((a, b) => b.last_played - a.last_played)[0];
    return recent || games[0];
  }

  function level(g) {
    return (g.compat && g.compat.level) || "";
  }

  // Long titles get a smaller size so the copy block never reaches the top bar.
  function titleScale(title) {
    const n = (title || "").length;
    return n <= 12 ? 1 : n <= 18 ? 0.86 : n <= 28 ? 0.7 : 0.56;
  }

  // ---------------------------------------------------------------- the hero
  function eyebrow(ctx, g) {
    if (g.is_running) return `<p class="c-eyebrow live"><i></i>Playing now</p>`;
    if (level(g) === "needs_port") return `<p class="c-eyebrow warn"><i></i>Needs porting</p>`;
    if (level(g) === "blocked") return `<p class="c-eyebrow bad"><i></i>Cannot run here</p>`;
    if (g.last_played) return `<p class="c-eyebrow">Last played ${ctx.esc(ctx.ago(g.last_played))}</p>`;
    return `<p class="c-eyebrow">Not played yet</p>`;
  }

  function meta(ctx, g) {
    const parts = [`<b>${g.is_vr ? "VR" : "2D"}</b>`];
    const time = ctx.playtime(g.playtime_seconds);
    if (time) parts.push(`<span>${ctx.esc(time)}</span>`);
    const lv = level(g);
    if (lv === "needs_port") {
      parts.push(`<span class="warn">${ctx.icon("port")}${g.port_failed ? "Porting failed, try again" : "Needs porting for Steam Frame"}</span>`);
    } else if (lv === "blocked") {
      parts.push(`<span class="bad">${ctx.esc((g.compat && g.compat.label) || "Cannot run on Steam Frame")}</span>`);
    } else if (g.framebridge) {
      parts.push(`<span>${ctx.icon("check")}Ported for Steam Frame</span>`);
    } else if (g.compat && g.compat.label) {
      parts.push(`<span>${ctx.icon("check")}${ctx.esc(g.compat.label)}</span>`);
    }
    if (g.is_external) parts.push(`<span>${ctx.icon("drive")}${ctx.esc(g.device_name || "External drive")}</span>`);
    if (ctx.updateFor(g)) parts.push(`<span class="upd">${ctx.icon("update")}Update available</span>`);
    return parts.join("");
  }

  function buttons(ctx, g) {
    const pkg = ctx.arg(g.package);
    const lv = level(g);
    const out = [];
    if (g.is_running) {
      // A VR game resumes by closing Steam's menu over it (Show); a 2D app is a window of its own.
      out.push(g.is_vr ? ctx.showButton(g, "c-play", { short: true, icon: ctx.icon("play") })
        : `<button type="button" class="c-play" onclick="launchGame(${pkg})">${ctx.icon("play")}Resume</button>`);
      out.push(`<button type="button" class="c-glass" onclick="stopGame(${pkg})">${ctx.icon("stop")}Stop</button>`);
    } else if (lv === "needs_port" && g.kind === "quest") {
      out.push(g.port_failed
        ? `<button type="button" class="c-play" onclick="portGame(${pkg})">${ctx.icon("port")}Port again</button>`
        : `<button type="button" class="c-play" title="Ports the game for the Steam Frame, then starts it" onclick="launchGame(${pkg})">${ctx.icon("play")}Port &amp; Play</button>`);
    } else {
      out.push(`<button type="button" class="c-play" onclick="launchGame(${pkg})">${ctx.icon("play")}Play</button>`);
    }
    if (ctx.updateFor(g) && !g.is_running) {
      out.push(`<button type="button" class="c-glass" onclick="updateGame(${pkg})">${ctx.icon("update")}Update</button>`);
    }
    out.push(`<button type="button" class="c-glass" onclick="openSettingsModal(${pkg})">${ctx.icon("settings")}Settings</button>`);
    out.push(`<button type="button" class="c-glass c-round" onclick="openGameModal(${pkg}, 'installed')" aria-label="More about ${ctx.esc(g.title)}" title="Game page">${ctx.icon("dots")}</button>`);
    return out.join("");
  }

  function copyHtml(ctx, g) {
    return `
      ${eyebrow(ctx, g)}
      <h2 class="c-title" style="--c-scale:${titleScale(g.title)}">${ctx.esc(g.title || g.package)}</h2>
      <div class="c-meta">${meta(ctx, g)}</div>
      <div class="c-btns">${buttons(ctx, g)}</div>`;
  }

  // Downloaded artwork is shown as it is. A drawn placeholder is only a blur of the app's icon,
  // so the sharp icon stands in front of it as the key art.
  function keyArt(g) {
    return !(g.artwork && g.artwork.cover);
  }

  function colours(g) {
    const c = (g.artwork && g.artwork.colors) || [];
    return `--c-top:${c[0] || "#2a1640"};--c-bottom:${c[1] || "#07080d"}`;
  }

  function artHtml(ctx, g) {
    return `
      <img class="c-art-bg" src="${ctx.esc(ctx.art(g, "hero"))}" alt="" draggable="false" decoding="async" onerror="this.style.visibility='hidden'">
      ${keyArt(g) ? `<img class="c-art-key" src="${ctx.esc(ctx.art(g, "icon"))}" alt="" draggable="false" decoding="async" onerror="this.remove()">` : ""}`;
  }

  // ---------------------------------------------------------------- the shelf
  function badge(ctx, g) {
    if (level(g) === "needs_port") return `<i class="port">Port</i>`;
    if (level(g) === "blocked") return `<i class="bad">Blocked</i>`;
    if (ctx.updateFor(g)) return `<i class="upd">Update</i>`;
    if (!g.is_vr) return `<i>2D</i>`;
    return "";
  }

  function tileHtml(ctx, g, on) {
    return `
      <button type="button" class="c-tile${on ? " on" : ""}${g.is_running ? " running" : ""}" data-pkg="${ctx.esc(g.package)}"
        aria-label="${ctx.esc(g.title)}${g.is_running ? ", playing now" : ""}" aria-current="${on ? "true" : "false"}">
        <img src="${ctx.esc(ctx.art(g, "icon"))}" alt="" draggable="false" decoding="async" loading="lazy"
          onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
        ${g.is_running ? `<b class="c-live" aria-hidden="true"></b>` : ""}${badge(ctx, g)}
      </button>`;
  }

  function hintsHtml() {
    return `
      <div class="c-hints" aria-hidden="true">
        <span><b>A</b>Select</span><span><b>B</b>Back</span><span><b>Y</b>Search</span><span><b>LB</b><b>RB</b>Sections</span>
      </div>`;
  }

  function library(ctx) {
    ctxLast = ctx;
    const g = pick(ctx.games);
    if (!g) return;
    selected = g.package;

    // Keep the controller where it was when the library is redrawn (a game started or stopped).
    const nav = window.gamepadNav;
    const had = nav && nav.focusedElement && ctx.root.contains(nav.focusedElement) ? focusKey(nav.focusedElement) : null;
    const shelfScroll = ($(".c-row", ctx.root) || {}).scrollLeft || 0;

    ctx.root.innerHTML = `
      <div class="c-show${g.is_running ? " c-hero-running" : ""}" style="${colours(g)}">
        <div class="c-art" aria-hidden="true">${artHtml(ctx, g)}</div>
        <div class="c-stage"><div class="c-copy" aria-live="polite">${copyHtml(ctx, g)}</div></div>
        <section class="c-shelf" aria-label="Your library">
          <div class="c-shelf-head">
            <h2>Your library <span>${ctx.games.length < ctx.state.installed.length ? `${ctx.games.length} of ${ctx.state.installed.length}` : ctx.state.installed.length}</span></h2>
            <div class="c-shelf-tools">
              <button type="button" class="c-arrow" data-shelf="-1" aria-label="Scroll the shelf left">${ctx.icon("chevron")}</button>
              <button type="button" class="c-arrow" data-shelf="1" aria-label="Scroll the shelf right">${ctx.icon("chevron")}</button>
              ${ctx.sortSelect()}
              <button type="button" class="c-pill" onclick="checkForUpdates(true)">${ctx.icon("update")}<span>Check for updates</span></button>
            </div>
          </div>
          <div class="c-row" role="list">${ctx.games.map(x => tileHtml(ctx, x, x.package === g.package)).join("")}</div>
        </section>
        ${hintsHtml()}
      </div>`;

    const row = $(".c-row", ctx.root);
    if (row) {
      row.scrollLeft = shelfScroll;
      row.addEventListener("scroll", syncArrows, { passive: true });
      requestAnimationFrame(syncArrows);
      // The shelf's width can change after this draw (this look's stylesheet still loading after a
      // switch, a resize, the selected tile growing), so the arrows follow the row's size.
      if (listeners && window.ResizeObserver) {
        if (listeners.sizes) listeners.sizes.disconnect();
        listeners.sizes = new ResizeObserver(syncArrows);
        listeners.sizes.observe(row);
        const first = row.firstElementChild;
        if (first) listeners.sizes.observe(first);
      }
    }
    if (had) {
      const again = ctx.root.querySelector(had);
      if (again) nav.setFocus(again);
    }
  }

  function focusKey(el) {
    if (el.dataset && el.dataset.pkg) return `.c-tile[data-pkg="${CSS.escape(el.dataset.pkg)}"]`;
    if (el.dataset && el.dataset.shelf) return `[data-shelf="${el.dataset.shelf}"]`;
    if (el.classList.contains("c-play")) return ".c-play";
    if (el.tagName === "SELECT") return "select";
    return null;
  }

  function syncArrows() {
    const row = $(".c-row");
    if (!row) return;
    const max = row.scrollWidth - row.clientWidth;
    const left = $('[data-shelf="-1"]'), right = $('[data-shelf="1"]');
    const fits = max <= 2;
    [left, right].forEach(b => { if (b) b.hidden = fits; });
    if (left) left.disabled = row.scrollLeft <= 1;
    if (right) right.disabled = row.scrollLeft >= max - 1;
  }

  // Shows another game in the hero without redrawing the shelf (the focus stays where it is).
  function select(pkg) {
    if (!ctxLast || pkg === selected) return;
    const g = ctxLast.games.find(x => x.package === pkg);
    const show = $(".c-show");
    if (!g || !show) return;
    selected = pkg;
    show.classList.toggle("c-hero-running", !!g.is_running);
    show.setAttribute("style", colours(g));
    $(".c-art", show).innerHTML = artHtml(ctxLast, g);
    $(".c-copy", show).innerHTML = copyHtml(ctxLast, g);
    show.querySelectorAll(".c-tile").forEach(t => {
      const on = t.dataset.pkg === pkg;
      t.classList.toggle("on", on);
      t.setAttribute("aria-current", on ? "true" : "false");
    });
    if (window.gamepadNav) window.gamepadNav.updateFocusables();
  }

  function onFocusIn(e) {
    const tile = e.target.closest && e.target.closest(".c-tile");
    if (!tile) return;
    select(tile.dataset.pkg);
    // The selected tile grows; keep all of it on screen.
    requestAnimationFrame(() => tile.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" }));
  }

  // The controller's focus is a class set by gamepad.js; focus events do not always follow it
  // (a window without keyboard focus), so the class itself is watched too.
  function onClassChange(records) {
    for (const r of records) {
      const t = r.target;
      if (t.classList && t.classList.contains("c-tile") && t.classList.contains("gamepad-focused") && t.dataset.pkg !== selected) {
        onFocusIn({ target: t });
        return;
      }
    }
  }

  function onPointerOver(e) {
    const tile = e.target.closest && e.target.closest(".c-tile");
    if (tile) select(tile.dataset.pkg);
  }

  function onClick(e) {
    const arrow = e.target.closest && e.target.closest("[data-shelf]");
    if (arrow) {
      const row = $(".c-row");
      if (row) row.scrollBy({ left: Number(arrow.dataset.shelf) * row.clientWidth * 0.8, behavior: "smooth" });
      return;
    }
    const tile = e.target.closest && e.target.closest(".c-tile");
    if (!tile) return;
    if (tile.dataset.pkg === selected) openGameModal(tile.dataset.pkg, "installed");
    else select(tile.dataset.pkg);
  }

  function empty(ctx) {
    return `
      <div class="c-show c-empty">
        <div class="c-art" aria-hidden="true"></div>
        <div class="c-stage"><div class="c-copy">
          <p class="c-eyebrow">Welcome to FrameLoad</p>
          <h2 class="c-title" style="--c-scale:0.7">Your library is empty</h2>
          <p class="c-lede">Install something from Browse, or a file you already have. Everything you install appears here and in your Steam library.</p>
          <div class="c-btns">
            <button type="button" class="c-play" onclick="goToTab('catalog')">${ctx.icon("search")}Browse apps</button>
            <button type="button" class="c-glass" onclick="goToTab('sideload')">${ctx.icon("download")}Install a file</button>
          </div>
        </div></div>
        ${hintsHtml()}
      </div>`;
  }

  // ---------------------------------------------------------------- top bar: activity, battery, clock
  function clock() {
    const el = document.getElementById("c-clock");
    if (!el) return;
    const now = new Date();
    el.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    el.setAttribute("datetime", now.toISOString());
  }

  // Rebuilt only when an item comes or goes; the figures change in place, so a button the
  // controller is on keeps its focus through the updates every few seconds.
  function status(ctx) {
    const box = document.getElementById("c-status");
    if (!box) return;
    const act = ctx.activity.port || ctx.activity.download;
    const pct = act ? (act.queued ? 0 : Math.round(act.percent)) : 0;
    const label = act ? `${act.label}${act.queued ? ", waiting" : `, ${pct}%`}` : "";
    const dev = ctx.device;
    const shape = [!!act, dev.freeGb != null, dev.cpu != null, dev.ramUsedGb != null, dev.battery != null].join();
    if (box.dataset.shape !== shape || !box.firstElementChild) {
      box.dataset.shape = shape;
      box.innerHTML = `
        ${act ? `<button type="button" class="c-act" onclick="openActivity()"><span class="c-ring"></span><span data-f="act"></span></button>` : ""}
        ${dev.freeGb == null ? "" : `<button type="button" class="c-stat c-free" onclick="openStorageTab()" title="Free space · open Storage">${ctx.icon("drive")}<span data-f="free"></span></button>`}
        ${dev.cpu == null ? "" : `<button type="button" class="c-stat" data-f="perf" onclick="openPerformanceCard()">${ctx.icon("cpu")}<span data-f="cpu"></span>${dev.ramUsedGb == null ? "" : `<span class="c-ram">${ctx.icon("memory")}<span data-f="ram"></span></span>`}</button>`}
        ${dev.battery == null ? "" : `<span class="c-bat">${ctx.icon("battery")}<span data-f="bat"></span></span>`}
        <time class="c-clock" id="c-clock"></time>`;
    }
    const set = (key, text) => { const el = box.querySelector(`[data-f="${key}"]`); if (el && el.textContent !== text) el.textContent = text; };
    if (act) {
      const button = box.querySelector(".c-act");
      button.title = label;
      button.setAttribute("aria-label", label);
      box.querySelector(".c-ring").style.setProperty("--p", act.queued ? 100 : pct);
      set("act", act.queued ? "Waiting" : pct + "%");
    }
    if (dev.freeGb != null) set("free", `${Math.round(dev.freeGb)} GB`);
    if (dev.cpu != null) {
      set("cpu", `${dev.cpu}%`);
      if (dev.ramUsedGb != null) set("ram", `${dev.ramUsedGb} GB`);
      box.querySelector('[data-f="perf"]').title = `CPU ${dev.cpu}%` +
        (dev.ramUsedGb == null ? "" : ` · RAM ${dev.ramUsedGb} of ${dev.ramTotalGb} GB used`);
    }
    if (dev.battery != null) {
      set("bat", `${dev.battery}%`);
      box.querySelector(".c-bat").title = `Battery${dev.plugged ? ", charging" : ""}`;
    }
    clock();
  }

  function mount() {
    const header = $(".app-header");
    const nav = $(".nav-tabs");
    // One top bar: the tabs sit between the wordmark and the search, as on a console home.
    if (header && nav && nav.parentNode !== header) {
      moved = { nav, parent: nav.parentNode, next: nav.nextSibling };
      header.insertBefore(nav, $(".search-wrapper", header));
    }
    const bar = $(".telemetry-bar");
    if (bar && !document.getElementById("c-status")) {
      const box = document.createElement("div");
      box.id = "c-status";
      box.className = "c-status";
      bar.appendChild(box);
    }
    const root = document.getElementById("library-view");
    if (root && !listeners) {
      listeners = { root, focusin: onFocusIn, mouseover: onPointerOver, click: onClick };
      root.addEventListener("focusin", onFocusIn);
      root.addEventListener("mouseover", onPointerOver);
      root.addEventListener("click", onClick);
      listeners.observer = new MutationObserver(onClassChange);
      listeners.observer.observe(root, { subtree: true, attributes: true, attributeFilter: ["class"] });
    }
    window.addEventListener("resize", syncArrows);
    clearInterval(clockTimer);
    clockTimer = setInterval(clock, 15000);
  }

  function unmount() {
    if (moved) {
      if (moved.next && moved.next.parentNode === moved.parent) moved.parent.insertBefore(moved.nav, moved.next);
      else moved.parent.appendChild(moved.nav);
      moved = null;
    }
    const box = document.getElementById("c-status");
    if (box) box.remove();
    if (listeners) {
      listeners.root.removeEventListener("focusin", listeners.focusin);
      listeners.root.removeEventListener("mouseover", listeners.mouseover);
      listeners.root.removeEventListener("click", listeners.click);
      listeners.observer.disconnect();
      if (listeners.sizes) listeners.sizes.disconnect();
      listeners = null;
    }
    window.removeEventListener("resize", syncArrows);
    clearInterval(clockTimer);
    clockTimer = null;
    ctxLast = null;
  }

  registerSkin("c", { library, empty, status, mount, unmount });
})();
