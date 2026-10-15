/**
 * FrameLoad Web Application Core
 * Connects frontend dashboard to backend REST API.
 */

const state = {
  catalog: {
    items: [],
    page: 1,
    totalPages: 1,
    totalCount: 0,
    query: "",
    sortBy: "downloads",
    sortOrder: "desc",
    kind: "vr"
  },
  installed: [],
  downloads: [],
  system: null,
  storage: {
    data: null,
    activeDeviceId: "internal",
    selectedPackages: new Set(),
    searchQuery: "",
    sortBy: "size_desc"
  },
  updates: {
    app: null,
    games: []
  },
  activeTab: "library",
  selectedGame: null
};

// --- API Helpers ---
async function apiError(res) {
  const text = await res.text();
  if (res.status === 401) { location.reload(); }
  if (res.status === 403 && /refused/i.test(text)) showHostRefused();
  try {
    return new Error(JSON.parse(text).error || text || `HTTP ${res.status}`);
  } catch (_) {
    return new Error(text || `HTTP ${res.status}`);
  }
}

async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function apiPost(url, data = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

// The server answers 403 when the dashboard was opened under a host name it does not trust.
function showHostRefused() {
  const banner = document.getElementById("host-refused-banner");
  const command = document.getElementById("host-refused-command");
  if (command) command.textContent = `frameload allow-host ${location.hostname}`;
  if (banner) banner.style.display = "block";
}

// Catalog names, app titles and paths are third-party text: never put them into HTML unescaped.
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// A value as a JavaScript string literal that is safe inside an inline event-handler attribute.
function jsArg(value) {
  return escapeHtml(JSON.stringify(String(value ?? "")));
}

// --- Steam Frame On-Screen Keyboard Integration ---
window.SteamOSK = {
  enabled: true,
  lastTrigger: 0,
  supported: true,

  async init() {
    const local = localStorage.getItem("frameload_osk_auto");
    if (local !== null) {
      this.enabled = local === "true";
    }

    try {
      const res = await apiGet("/api/system/keyboard");
      if (res) {
        this.supported = !!res.supported;
        if (local === null && typeof res.auto_trigger === "boolean") {
          this.enabled = res.auto_trigger;
        }
      }
    } catch (e) {
      // Offline fallback
    }

    this.updateUI();

    // Automatically trigger Steam Frame keyboard on focusin for text fields
    document.addEventListener("focusin", (e) => {
      if (!this.enabled) return;
      const el = e.target;
      if (!el) return;
      const tag = el.tagName ? el.tagName.toUpperCase() : "";
      const type = (el.type || "text").toLowerCase();
      const isInput = (tag === "INPUT" && ["text", "search", "url", "number", "password"].includes(type)) || tag === "TEXTAREA";
      if (isInput) {
        this.trigger("show");
      }
    });

    // Dismiss keyboard on Escape key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        this.trigger("hide");
      }
    });
  },

  updateUI() {
    const check = document.getElementById("osk-auto-trigger-check");
    if (check) check.checked = this.enabled;
    const badge = document.getElementById("sys-keyboard-badge");
    if (badge) {
      if (this.enabled) {
        badge.textContent = "Auto-Trigger Active";
        badge.style.background = "rgb(var(--ok-rgb) / 0.15)";
        badge.style.color = "var(--accent-emerald)";
      } else {
        badge.textContent = "Manual Only (Steam + X)";
        badge.style.background = "rgb(var(--fg-rgb) / 0.1)";
        badge.style.color = "var(--text-muted)";
      }
    }
  },

  setEnabled(val) {
    this.enabled = !!val;
    localStorage.setItem("frameload_osk_auto", this.enabled ? "true" : "false");
    this.updateUI();
    apiPost("/api/system/keyboard", { auto_trigger: this.enabled }).catch(() => {});
    if (window.showToast) {
      window.showToast(this.enabled ? "⌨️ Steam Frame Keyboard: Auto-trigger on focus enabled" : "⌨️ Steam Frame Keyboard: Auto-trigger disabled (Manual mode)", "info");
    }
  },

  async trigger(action = "show") {
    const now = Date.now();
    // Debounce rapid focus triggers within 700ms
    if (action === "show" && now - this.lastTrigger < 700) return;
    this.lastTrigger = now;

    const btn = document.getElementById("btn-search-osk");
    if (btn) {
      btn.classList.add("active");
      setTimeout(() => btn.classList.remove("active"), 350);
    }

    try {
      const res = await apiPost("/api/system/keyboard", { action: action });
      console.log("[SteamOSK]", action, res);
    } catch (err) {
      console.warn("[SteamOSK] Error:", err);
    }
  },

  toggle() {
    this.trigger("show");
  }
};

function toggleOSKAutoTrigger(enabled) {
  if (window.SteamOSK) {
    window.SteamOSK.setEnabled(enabled);
  }
}
window.toggleOSKAutoTrigger = toggleOSKAutoTrigger;

function setupSteamOSK() {
  if (window.SteamOSK) {
    window.SteamOSK.init();
  }
}

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupSearch();
  setupModals();
  setupSideloadForm();
  setupStorage();
  setupSteamOSK();

  // Initial loads
  loadCatalog();
  loadInstalled();
  loadStorageOverview();
  loadSystemTelemetry();
  checkForUpdates(false);
  checkHealthOnce();
  startPollingDownloads();
  setInterval(loadSystemTelemetry, 8000);
  setInterval(refreshRunningGames, 8000);
  setInterval(() => checkForUpdates(false), 6 * 3600 * 1000);
  loadSteamStatus();
});

// --- Tab Switching ---
const SEARCH_HINTS = { library: "Search your library...", catalog: "Search games and apps..." };

function syncSearchBox() {
  const input = document.getElementById("search-input");
  if (!input) return;
  input.placeholder = SEARCH_HINTS[state.activeTab] || SEARCH_HINTS.catalog;
  input.value = state.activeTab === "library" ? (state.libraryQuery || "")
    : state.activeTab === "catalog" ? (state.catalog.query || "") : "";
}

function goToTab(name) {
  const tab = document.querySelector(`.tab-btn[data-tab="${name}"]`);
  if (tab && !tab.classList.contains("active")) tab.click();
}
window.goToTab = goToTab;

function setupTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = tab.dataset.tab;
      // Pressing the tab you are already on is the quick way back to the top of a long list.
      if (tab.classList.contains("active")) {
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      state.activeTab = targetId;

      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      tab.scrollIntoView({ block: "nearest", inline: "nearest" });

      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      const targetPanel = document.getElementById(`tab-${targetId}`);
      if (targetPanel) targetPanel.classList.add("active");
      window.scrollTo(0, 0);  // a new tab starts at its top, not where the last one was left
      try { history.replaceState(null, "", `#${targetId}`); } catch (e) { /* file:// or sandboxed */ }
      syncSearchBox();
      if (targetId !== "system" && typeof stopControllerTest === "function") stopControllerTest();

      if (targetId === "catalog") loadCatalog();
      else if (targetId === "library") { loadInstalled(); loadSteamStatus(); }
      else if (targetId === "storage") loadStorageOverview();
      else if (targetId === "system") { loadSystemTelemetry(); loadHandStatus(); loadPortingStatus(); loadAccess(); loadGuard(); loadKeepAwake(); }
      if (targetId === "system") startPerfLive(); else stopPerfLive();

      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    });
  });

  // Handle URL hash on load (e.g. #library, #system, #downloads)
  const hash = window.location.hash.replace("#", "");
  if (hash) goToTab(hash);
  syncSearchBox();
}

// --- Search & Filters ---
function setupSearch() {
  const searchInput = document.getElementById("search-input");
  let debounceTimeout = null;

  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounceTimeout);
      const value = e.target.value;
      if (state.activeTab === "library") {  // the search box searches what you are looking at
        state.libraryQuery = value;
        renderInstalledGrid();
        return;
      }
      debounceTimeout = setTimeout(() => {
        state.catalog.query = value;
        state.catalog.page = 1;
        if (state.activeTab !== "catalog") goToTab("catalog");  // loads the catalog itself
        else loadCatalog();
      }, 350);
    });
  }

  const sortSelect = document.getElementById("sort-select");
  if (sortSelect) {
    sortSelect.addEventListener("change", (e) => {
      const val = e.target.value;
      if (val === "downloads_desc") { state.catalog.sortBy = "downloads"; state.catalog.sortOrder = "desc"; }
      else if (val === "downloads_asc") { state.catalog.sortBy = "downloads"; state.catalog.sortOrder = "asc"; }
      else if (val === "date_desc") { state.catalog.sortBy = "date"; state.catalog.sortOrder = "desc"; }
      else if (val === "rating_desc") { state.catalog.sortBy = "rating"; state.catalog.sortOrder = "desc"; }
      else if (val === "name_asc") { state.catalog.sortBy = "name"; state.catalog.sortOrder = "asc"; }
      else if (val === "name_desc") { state.catalog.sortBy = "name"; state.catalog.sortOrder = "desc"; }
      else if (val === "size_desc") { state.catalog.sortBy = "size"; state.catalog.sortOrder = "desc"; }
      else if (val === "size_asc") { state.catalog.sortBy = "size"; state.catalog.sortOrder = "asc"; }
      state.catalog.page = 1;
      loadCatalog();
    });
  }

  const kindSelect = document.getElementById("catalog-kind-select");
  if (kindSelect) {
    kindSelect.addEventListener("change", (e) => {
      state.catalog.kind = e.target.value;
      state.catalog.page = 1;
      applyCatalogKind();
      loadCatalog();
    });
  }

  const categorySelect = document.getElementById("catalog-category-select");
  if (categorySelect) {
    categorySelect.addEventListener("change", (e) => {
      state.catalog.category = e.target.value;
      state.catalog.page = 1;
      loadCatalog();
    });
  }
  applyCatalogKind();

  const syncBtn = document.getElementById("sync-catalog-btn");
  if (syncBtn) {
    syncBtn.addEventListener("click", syncCatalog);
  }

  initCatalogInfiniteScroll();
}

// The two catalogs differ: F-Droid has categories but no download counts or ratings.
function applyCatalogKind() {
  const isFlat = state.catalog.kind === "flat";
  const categorySelect = document.getElementById("catalog-category-select");
  const sortSelect = document.getElementById("sort-select");
  const hint = document.getElementById("catalog-source-hint");
  const search = document.getElementById("search-input");
  if (categorySelect) categorySelect.style.display = isFlat ? "" : "none";
  if (hint) hint.textContent = isFlat ? "Free and open-source Android apps from F-Droid, shown as 2D windows" : "Browse public VR mirror";
  SEARCH_HINTS.catalog = isFlat ? "Search apps..." : "Search games and apps...";
  if (search) search.placeholder = SEARCH_HINTS[state.activeTab] || SEARCH_HINTS.catalog;
  if (sortSelect) {
    Array.from(sortSelect.options).forEach(opt => {
      const unsupported = isFlat && /^(downloads|rating)_/.test(opt.value);
      opt.hidden = unsupported;
      opt.disabled = unsupported;
    });
    if (isFlat && /^(downloads|rating)_/.test(sortSelect.value)) {
      sortSelect.value = "date_desc";
      state.catalog.sortBy = "date";
      state.catalog.sortOrder = "desc";
    }
  }
  if (isFlat) { loadCatalogCategories(); loadAppUpdates(); }
  else { const btn = document.getElementById("fdroid-updates-btn"); if (btn) btn.style.display = "none"; }
}

async function loadAppUpdates() {
  const btn = document.getElementById("fdroid-updates-btn");
  if (!btn) return;
  try {
    const data = await apiGet("/api/catalog/updates");
    const count = (data.updates || []).length;
    btn.style.display = count && state.catalog.kind === "flat" ? "" : "none";
    btn.textContent = count === 1 ? "Update 1 App" : `Update ${count} Apps`;
    btn.title = (data.updates || []).map(u => `${u.title}: ${u.installed_version} -> ${u.new_version}`).join("\n");
  } catch (e) {
    btn.style.display = "none";
  }
}

async function updateAllApps() {
  try {
    const res = await apiPost("/api/catalog/update-all", {});
    showToast(res.queued ? `Updating ${res.queued} app(s)...` : "Everything is up to date.", "info");
    loadAppUpdates();
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.updateAllApps = updateAllApps;

async function loadCatalogCategories() {
  const select = document.getElementById("catalog-category-select");
  if (!select) return;
  try {
    const data = await apiGet("/api/catalog/categories");
    const current = state.catalog.category || "";
    select.innerHTML = '<option value="">All categories</option>' + (data.categories || []).map(c =>
      `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)} (${c.count})</option>`).join("");
    select.value = current;
  } catch (e) {
    console.error("Error loading categories:", e);
  }
}

// --- Progressive Infinite Catalog Loading ---
function buildGameCardHTML(game, installedPkgs) {
  const isFlat = game.kind === "flat";
  const isInstalled = game.is_installed || installedPkgs.has(game.package_name);
  const thumbUrl = game.thumbnail_url || `/api/thumbnail/${encodeURIComponent(game.package_name)}`;
  const version = game.version_name || (game.version_code ? "v" + game.version_code : "");
  const meta = game.downloads ? `${Number(game.downloads).toLocaleString()} downloads` : version;

  let action = `<button class="card-btn download" onclick="event.stopPropagation(); queueDownload(${jsArg(game.id)})">${isFlat ? "Install" : "Download"}</button>`;
  if (isInstalled && game.update_available) {
    action = `<button class="card-btn update" onclick="event.stopPropagation(); queueDownload(${jsArg(game.id)})">Update</button>`;
  } else if (isInstalled) {
    action = `<button class="card-btn play" onclick="event.stopPropagation(); launchGame(${jsArg(game.package_name)})">${isFlat ? "Open" : "Play"}</button>`;
  }

  return `
    <div class="game-card${isFlat ? " app-card" : ""}" data-id="${escapeHtml(game.id)}" draggable="false" onclick="openGameModal(${jsArg(game.id)}, 'catalog')">
      <div class="card-poster">
        <img src="${escapeHtml(thumbUrl)}" alt="" draggable="false" loading="lazy" decoding="async" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
        <div class="badge-overlay">
          <span class="badge ${isFlat ? "flat" : "vr"}">${isFlat ? "2D" : "VR"}</span>
          ${isInstalled ? '<span class="badge installed">Installed</span>' : ""}
        </div>
      </div>
      <div class="card-body">
        <div class="card-title" title="${escapeHtml(game.name)}">${escapeHtml(game.name)}</div>
        ${isFlat && game.summary ? `<div class="card-summary">${escapeHtml(game.summary)}</div>` : ""}
        <div class="card-meta">
          <span>${escapeHtml(game.size_formatted)}</span>
          <span>${escapeHtml(meta)}</span>
        </div>
        <div class="card-actions">${action}</div>
      </div>
    </div>
  `;
}

async function loadCatalog(page = 1, append = false) {
  const container = document.getElementById("catalog-grid");
  const loader = document.getElementById("catalog-infinite-loader");
  if (!container) return;

  if (!append) {
    state.catalog.page = 1;
    state.catalog.items = [];
    state.catalog.hasMore = true;
    container.innerHTML = `<div class="loading-state">${state.catalog.kind === "flat" ? "Loading apps..." : "Scanning VR mirror catalog..."}</div>`;
  }

  try {
    const params = new URLSearchParams({
      page: page,
      per_page: 40,
      q: state.catalog.query,
      sort_by: state.catalog.sortBy,
      sort_order: state.catalog.sortOrder,
      kind: state.catalog.kind
    });
    if (state.catalog.kind === "flat" && state.catalog.category) {
      params.set("category", state.catalog.category);
    }

    const res = await fetch(`/api/catalog?${params}`);
    const data = await res.json();

    const newItems = data.items || [];
    state.catalog.page = data.page || 1;
    state.catalog.totalPages = data.total_pages || 1;
    state.catalog.totalCount = data.total_count || 0;
    state.catalog.hasMore = state.catalog.page < state.catalog.totalPages;

    const installedPkgs = new Set((state.installed || []).map(g => g.package));

    if (append) {
      state.catalog.items = state.catalog.items.concat(newItems);
      if (newItems.length > 0) {
        container.insertAdjacentHTML("beforeend", catalogPageHTML(newItems, installedPkgs));
      }
    } else {
      state.catalog.items = newItems;
      if (newItems.length === 0) {
        container.innerHTML = `<div class="empty-state">${catalogEmptyMessage(data)}</div>`;
      } else {
        container.innerHTML = catalogPageHTML(newItems, installedPkgs);
      }
    }

    if (window.gamepadNav) window.gamepadNav.updateFocusables();
  } catch (err) {
    if (!append) {
      container.innerHTML = `<div class="error-state">Could not load the catalog. Check that FrameLoad is still running.</div>`;
    }
    console.error("Error loading catalog:", err);
  } finally {
    state.catalog.loadingMore = false;
    if (loader) loader.style.display = "none";
  }
}

function catalogEmptyMessage(data) {
  if (state.catalog.kind !== "flat") {
    return 'No VR titles match your query. Click "Sync Catalog" to refresh mirror metadata.';
  }
  if (!data.last_sync) {
    return 'The F-Droid app catalog has not been downloaded yet. Press "Sync Catalog" to fetch it (about 10 MB).';
  }
  return "No apps match your search.";
}

async function loadMoreCatalog() {
  if (state.catalog.loadingMore || !state.catalog.hasMore) return;
  state.catalog.loadingMore = true;

  const loader = document.getElementById("catalog-infinite-loader");
  if (loader) loader.style.display = "flex";

  const nextPage = (state.catalog.page || 1) + 1;
  await loadCatalog(nextPage, true);
  // The observer only reports changes: when a short page leaves the end of the list in view, keep going.
  requestAnimationFrame(() => {
    const sentinel = document.getElementById("catalog-sentinel");
    if (sentinel && state.activeTab === "catalog" && state.catalog.hasMore
        && sentinel.getBoundingClientRect().top < window.innerHeight + 350) loadMoreCatalog();
  });
}

function initCatalogInfiniteScroll() {
  const sentinel = document.getElementById("catalog-sentinel");
  if (!sentinel) return;

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && state.activeTab === "catalog") {
          loadMoreCatalog();
        }
      });
    }, { rootMargin: "350px 0px" });
    observer.observe(sentinel);
  } else {
    // Without IntersectionObserver: check once per frame at most (reading the page height on every
    // scroll event forces a layout of the whole grid).
    let queued = false;
    window.addEventListener("scroll", () => {
      if (queued || state.activeTab !== "catalog") return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const doc = document.documentElement;
        if (doc.scrollHeight - (window.scrollY + window.innerHeight) < 450) loadMoreCatalog();
      });
    }, { passive: true });
  }
}

function renderCatalogGrid() {
  const container = document.getElementById("catalog-grid");
  if (!container) return;
  if (!state.catalog.items || state.catalog.items.length === 0) {
    container.innerHTML = `<div class="empty-state">No VR titles match your query. Click "Sync Catalog" to refresh mirror metadata.</div>`;
    return;
  }
  const installedPkgs = new Set((state.installed || []).map(g => g.package));
  const pages = [];
  for (let i = 0; i < state.catalog.items.length; i += 40) {
    pages.push(catalogPageHTML(state.catalog.items.slice(i, i + 40), installedPkgs));
  }
  container.innerHTML = pages.join("");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

// Each loaded page is a small grid of its own. Pages off screen are skipped whole by the browser
// (content-visibility), so scrolling stays smooth however many pages are loaded; one big grid of
// thousands of cards was laid out again as cards came into view.
function catalogPageHTML(items, installedPkgs) {
  return `<div class="catalog-page games-grid">${items.map(game => buildGameCardHTML(game, installedPkgs)).join("")}</div>`;
}

async function syncCatalog() {
  const btn = document.getElementById("sync-catalog-btn");
  const isFlat = state.catalog.kind === "flat";
  if (btn) { btn.classList.add("spinning"); btn.disabled = true; }
  showToast(isFlat ? "Downloading the F-Droid app catalog..." : "Syncing the VR catalog from the mirror...", "info");

  try {
    const data = await apiPost("/api/catalog/sync", { kind: state.catalog.kind });
    if (data.success) {
      showToast(isFlat ? (data.message || `${data.total_games} apps available.`) : `Catalog synced: ${data.total_games} games available.`, "success");
      if (isFlat) loadCatalogCategories();
      loadCatalog(1, false);
    } else {
      showToast(data.message || "Could not download the catalog. Check the network connection.", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    if (btn) { btn.classList.remove("spinning"); btn.disabled = false; }
  }
}

// --- Download Queue Controls ---
async function queueDownload(gameId) {
  const game = (state.catalog.items || []).find(g => g.id === gameId)
    || (state.selectedGame && state.selectedGame.id === gameId ? state.selectedGame : null);
  // An update goes where the game already is; a new game goes where the player says.
  const installed = game && (state.installed || []).find(g => g.package === game.package_name);
  let deviceId = installed ? (installed.device_id || "internal") : undefined;
  if (!installed) {
    deviceId = await chooseInstallDrive(game ? game.name : "this game", game ? game.size_bytes : 0);
    if (deviceId === null) return;  // cancelled
  }
  showToast("Adding game to download queue...", "info");
  try {
    const res = await fetch("/api/downloads/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(deviceId ? { game_id: gameId, device_id: deviceId } : { game_id: gameId })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Download queued.", "success");
      pollDownloadsOnce();
    } else {
      showToast(data.error || "Failed to queue download", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}

async function cancelDownload(taskId) {
  try {
    await fetch("/api/downloads/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId })
    });
    showToast("Task cancelled", "info");
    pollDownloadsOnce();
  } catch (err) {
    console.error(err);
  }
}

async function pauseDownload(taskId) {
  try {
    await fetch("/api/downloads/pause", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId })
    });
    showToast("Download paused.", "info");
    pollDownloadsOnce();
  } catch (err) {
    console.error(err);
  }
}

async function resumeDownload(taskId) {
  try {
    await fetch("/api/downloads/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId })
    });
    showToast("Download resumed.", "info");
    pollDownloadsOnce();
  } catch (err) {
    console.error(err);
  }
}

async function removeDownload(taskId) {
  try {
    await fetch("/api/downloads/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId })
    });
    pollDownloadsOnce();
  } catch (err) {
    console.error(err);
  }
}

async function clearCompletedDownloads() {
  try {
    const res = await fetch("/api/downloads/clear", { method: "POST" });
    const data = await res.json();
    showToast(`Cleared ${data.cleared || 0} finished downloads.`, "info");
    pollDownloadsOnce();
  } catch (err) {
    console.error(err);
  }
}

function toggleActiveDownloadPause() {
  const active = state.downloads.find(t => t.status === "downloading" || t.status === "paused");
  if (!active) return;
  if (active.status === "downloading") {
    pauseDownload(active.id);
  } else if (active.status === "paused") {
    resumeDownload(active.id);
  }
}

function startPollingDownloads() {
  setInterval(pollDownloadsOnce, 1200);
}

const knownCompletedTaskIds = new Set();

async function pollDownloadsOnce() {
  try {
    const res = await fetch("/api/downloads");
    const data = await res.json();
    state.downloads = data.tasks || [];
    noteDownloadActivity();
    renderDownloadsBadge();
    notePortingJob(data.porting_job);
    renderDownloadsDrawer();
    renderDownloadsTab();
    offerPendingLink(data.pending_links || []);

    // Check for newly completed tasks to alert user and refresh installed library
    state.downloads.forEach(t => {
      if (t.status === "completed" && !knownCompletedTaskIds.has(t.id)) {
        knownCompletedTaskIds.add(t.id);
        showToast(`${t.game.name} is installed.`, "success");
        loadInstalled();
        loadSteamStatus();
        if (state.catalog.kind === "flat") loadAppUpdates();
      }
    });
  } catch (err) {
    // Silent polling error
  }
}

function renderDownloadsDrawer() {
  const drawer = document.getElementById("downloads-drawer");
  if (!drawer) return;

  const activeTask = state.downloads.find(t => 
    t.status === "downloading" || t.status === "decompressing" || t.status === "installing" || t.status === "paused"
  );

  if (!activeTask) {
    drawer.classList.remove("visible");
    return;
  }

  drawer.classList.add("visible");
  const titleEl = document.getElementById("drawer-title");
  const statusEl = document.getElementById("drawer-status");
  const progressEl = document.getElementById("drawer-progress");
  const pauseBtn = document.getElementById("drawer-pause-btn");

  if (titleEl) titleEl.textContent = activeTask.game.name;

  if (progressEl) {
    progressEl.className = "progress-fill";
    if (activeTask.status === "decompressing") progressEl.classList.add("extracting");
    else if (activeTask.status === "installing") progressEl.classList.add("installing");
    else if (activeTask.status === "completed") progressEl.classList.add("completed");
    progressEl.style.width = `${activeTask.status === 'completed' ? 100 : activeTask.progress_percent}%`;
  }

  if (statusEl) {
    if (activeTask.status === "decompressing") {
      statusEl.textContent = `EXTRACTING • ${activeTask.status_detail || (activeTask.progress_percent + '%')}`;
    } else if (activeTask.status === "installing") {
      statusEl.textContent = `INSTALLING • ${activeTask.status_detail || 'Setting up Lepton container...'}`;
    } else if (activeTask.status === "paused") {
      statusEl.textContent = `PAUSED • ${activeTask.downloaded_formatted} / ${activeTask.total_formatted}`;
    } else {
      statusEl.textContent = `DOWNLOADING • ${activeTask.speed_formatted} • ${activeTask.downloaded_formatted} / ${activeTask.total_formatted} • ETA: ${activeTask.eta_seconds}s`;
    }
  }

  if (pauseBtn) {
    if (activeTask.status === "downloading") {
      pauseBtn.style.display = "inline-flex";
      pauseBtn.textContent = "Pause";
      pauseBtn.onclick = () => pauseDownload(activeTask.id);
    } else if (activeTask.status === "paused") {
      pauseBtn.style.display = "inline-flex";
      pauseBtn.textContent = "Resume";
      pauseBtn.onclick = () => resumeDownload(activeTask.id);
    } else {
      pauseBtn.style.display = "none";
    }
  }
}

function formatDuration(seconds) {
  const sec = Math.max(0, Math.round(Number(seconds) || 0));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, "0")}s`;
  return `${Math.floor(sec / 3600)}h ${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}m`;
}

function downloadState(t) {
  const percent = t.status === "completed" ? 100 : Math.max(0, Math.min(100, Number(t.progress_percent) || 0));
  switch (t.status) {
    case "downloading":
      return { label: "Downloading", fill: "", percent,
        detail: `${t.downloaded_formatted} of ${t.total_formatted} · ${t.speed_formatted}${t.eta_seconds ? ` · ${formatDuration(t.eta_seconds)} left` : ""}` };
    case "decompressing":
      return { label: "Unpacking", fill: "extracting", percent, detail: t.status_detail || `${percent}%` };
    case "installing":
      return { label: "Installing", fill: "installing", percent, detail: t.status_detail || "Setting up the game" };
    case "completed":
      return { label: "Installed", fill: "completed", percent, detail: "Ready to play" };
    case "paused":
      return { label: "Paused", fill: "", percent, detail: `${t.downloaded_formatted} of ${t.total_formatted}` };
    case "error":
      return { label: "Failed", fill: "error", percent, detail: t.error_message || "The download failed" };
    case "queued":
      return { label: "Waiting", fill: "", percent, detail: "Starts when the current download is done" };
    default:
      return { label: t.status ? t.status.charAt(0).toUpperCase() + t.status.slice(1) : "", fill: "", percent, detail: t.status_detail || "" };
  }
}

function downloadActions(t) {
  const id = jsArg(t.id);
  if (t.status === "downloading") {
    return `<button class="btn-secondary compact" onclick="pauseDownload(${id})">Pause</button>
            <button class="btn-secondary compact" onclick="cancelDownload(${id})">Cancel</button>`;
  }
  if (t.status === "paused") {
    return `<button class="btn-primary compact" onclick="resumeDownload(${id})">Resume</button>
            <button class="btn-secondary compact" onclick="cancelDownload(${id})">Cancel</button>`;
  }
  if (t.status === "completed") {
    const pkg = (t.game && t.game.package_name) || "";
    return `${pkg ? `<button class="btn-primary compact" onclick="launchGame(${jsArg(pkg)})">Play</button>` : ""}
            <button class="btn-secondary compact" onclick="removeDownload(${id})">Dismiss</button>`;
  }
  if (t.status === "error") {
    return `<button class="btn-primary compact" onclick="resumeDownload(${id})">Retry</button>
            <button class="btn-secondary compact" onclick="removeDownload(${id})">Dismiss</button>`;
  }
  return `<button class="btn-secondary compact" onclick="cancelDownload(${id})">Cancel</button>`;
}

// Cards are updated in place: rebuilding the list on every poll (1.2 s) reloaded each cover and
// could swallow a click that landed while the button was being replaced.
function renderDownloadsTab() {
  const container = document.getElementById("downloads-list");
  if (!container) return;

  if (state.downloads.length === 0) {
    if (container.dataset.empty !== "1") {
      container.dataset.empty = "1";
      container.innerHTML = `
        <div class="empty-state">
          <h3>Nothing is downloading</h3>
          <p>Games and apps you install from Browse show their progress here.</p>
          <div class="empty-actions"><button class="btn-primary" onclick="goToTab('catalog')">Browse Apps</button></div>
        </div>`;
      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    }
    return;
  }
  if (container.dataset.empty === "1") {
    container.innerHTML = "";
    delete container.dataset.empty;
  }

  let changed = false;
  const keep = new Set();
  state.downloads.forEach((t, index) => {
    keep.add(t.id);
    let card = Array.from(container.children).find(c => c.dataset.id === t.id);
    if (!card) {
      const pkg = (t.game && t.game.package_name) || "";
      const owned = pkg && (state.installed || []).find(g => g.package === pkg);
      const thumb = owned ? artUrl(owned, "icon") : (t.game && t.game.thumbnail_url) || (pkg ? `/api/thumbnail/${encodeURIComponent(pkg)}` : "");
      card = document.createElement("div");
      card.className = "download-item-card";
      card.dataset.id = t.id;
      card.innerHTML = `
        <img class="download-thumb" src="${escapeHtml(thumb || "/static/assets/fallback_cover.svg")}" alt="" draggable="false"
             onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
        <div class="download-body">
          <div class="download-head">
            <h3 class="download-title"></h3>
            <span class="download-state"></span>
          </div>
          <p class="download-detail"></p>
          <div class="progress-track"><div class="progress-fill"></div></div>
        </div>
        <div class="download-actions"></div>`;
      changed = true;
    }
    if (container.children[index] !== card) {
      container.insertBefore(card, container.children[index] || null);
    }
    const st = downloadState(t);
    card.querySelector(".download-title").textContent = (t.game && t.game.name) || t.id;
    const badge = card.querySelector(".download-state");
    badge.textContent = st.label;
    badge.className = `download-state ${t.status}`;
    card.querySelector(".download-detail").textContent = st.detail;
    const fill = card.querySelector(".progress-fill");
    fill.className = `progress-fill ${st.fill}`;
    fill.style.width = `${st.percent}%`;
    if (card.dataset.status !== t.status) {  // the buttons change only with the state
      card.dataset.status = t.status;
      card.querySelector(".download-actions").innerHTML = downloadActions(t);
      changed = true;
    }
  });
  Array.from(container.children).forEach(card => {
    if (!keep.has(card.dataset.id)) { card.remove(); changed = true; }
  });
  if (changed && window.gamepadNav) window.gamepadNav.updateFocusables();
}

// --- Installed Library API ---
async function loadInstalled() {
  setTimeout(() => composePendingArtwork(), 1500);
  const container = document.getElementById("library-view");
  if (!container) return;

  try {
    const res = await fetch("/api/installed");
    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }
    const data = await res.json();
    state.installed = Array.isArray(data.games) ? data.games : [];
    renderInstalledGrid();
    renderStopChip();
  } catch (err) {
    console.error("Error loading installed library:", err);
    container.innerHTML = `
      <div class="error-state" style="padding:40px; text-align:center;">
        <p style="margin-bottom:12px; font-weight:600;">Failed to load installed library: ${err.message}</p>
        <button class="btn-primary compact" onclick="loadInstalled()">Try Again</button>
      </div>
    `;
  }
}

// Global window bindings
window.pauseDownload = pauseDownload;
window.resumeDownload = resumeDownload;
window.removeDownload = removeDownload;
window.clearCompletedDownloads = clearCompletedDownloads;
window.toggleActiveDownloadPause = toggleActiveDownloadPause;
window.cancelDownload = cancelDownload;
window.loadCatalog = loadCatalog;
window.loadMoreCatalog = loadMoreCatalog;
window.loadInstalled = loadInstalled;

function renderInstalledGrid() {
  const view = document.getElementById("library-view");
  if (!view) return;

  const count = document.getElementById("library-count");
  if (count) {
    count.textContent = state.installed.length;
    count.style.display = state.installed.length ? "" : "none";
  }

  const words = (state.libraryQuery || "").toLowerCase().split(/\s+/).filter(Boolean);
  const games = state.installed.filter(game => {
    const text = `${game.title || ""} ${game.package || ""}`.toLowerCase();
    return words.every(word => text.includes(word));
  });
  sortLibrary(games);
  const ctx = Object.assign(skinContext(), { games, query: state.libraryQuery || "", recent: recentGames(words.length ? [] : state.installed) });
  const skin = SKIN_VIEWS[currentSkin()];

  if (state.installed.length === 0) {
    view.innerHTML = skin && skin.empty ? skin.empty(ctx) : `
      <div class="empty-state">
        <h3>Your library is empty</h3>
        <p>Install something from Browse, or a file you already have. Everything you install appears here and in your Steam library.</p>
        <div class="empty-actions">
          <button class="btn-primary" onclick="goToTab('catalog')">Browse Apps</button>
          <button class="btn-secondary" onclick="goToTab('sideload')">Install a File</button>
        </div>
      </div>`;
  } else if (games.length === 0) {
    view.innerHTML = skin && skin.noMatch ? skin.noMatch(ctx) : `
      <div class="empty-state">
        <h3>Nothing in your library matches &ldquo;${escapeHtml(state.libraryQuery)}&rdquo;</h3>
        <div class="empty-actions">
          <button class="btn-secondary" onclick="clearLibrarySearch()">Clear Search</button>
          <button class="btn-primary" onclick="searchCatalogInstead()">Search Browse Instead</button>
        </div>
      </div>`;
  } else if (skin && skin.library) {
    skin.library(ctx);
  } else {
    defaultLibraryView(ctx);
  }
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

// The neon look's library (also used by any look that does not draw its own): a Recently Played
// shelf and a grid of cards.
function defaultLibraryView(ctx) {
  ctx.root.innerHTML = `
    ${ctx.recent.length ? `
      <section class="library-recent" aria-label="Recently played">
        <h2 class="section-title">Recently Played</h2>
        <div class="recent-grid">${ctx.recent.map(recentCardHtml).join("")}</div>
        <h2 class="section-title">All Games</h2>
      </section>` : ""}
    <div id="library-grid" class="games-grid">${ctx.games.map(libraryCardHtml).join("")}</div>`;
}

function libraryCardHtml(game) {
  const pkg = jsArg(game.package);
  const level = (game.compat && game.compat.level) || "";
  const needsAttention = level === "needs_port" || level === "blocked";
  const updateInfo = libraryUpdateFor(game);
  return `
    <div class="game-card" data-package="${escapeHtml(game.package)}" draggable="false" onclick="openGameModal(${pkg}, 'installed')">
      <div class="card-poster">
        <img src="${escapeHtml(libraryArt(game))}" alt="" draggable="false" decoding="async" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
        <div class="badge-overlay">
          <span class="badge ${game.is_vr ? 'vr' : 'flat'}">${game.is_vr ? 'VR' : '2D'}</span>
          ${game.is_external ? '<span class="badge badge-external" title="Installed on a microSD card or USB drive">External</span>' : ''}
          ${game.is_running ? '<span class="badge installed">Running</span>' : ''}
          ${updateInfo ? '<span class="badge update" title="New update available on mirror">Update Available</span>' : ''}
          ${needsAttention ? `<span class="badge compat-${escapeHtml(level)}" title="${escapeHtml(game.compat.label)}">${level === "blocked" ? "Cannot run" : "Needs porting"}</span>` : ''}
        </div>
      </div>
      <div class="card-body">
        <div class="card-title" title="${escapeHtml(game.title)}">${escapeHtml(game.title)}</div>
        <div class="card-meta">
          <span>${game.is_external ? 'External' : 'Internal'}</span>
          <span>${escapeHtml(playedLabel(game))}</span>
        </div>
        <div class="card-actions">
          ${libraryPrimaryButton(game)}
          <button class="card-btn download" onclick="event.stopPropagation(); openSettingsModal(${pkg})">Settings</button>
        </div>
      </div>
    </div>`;
}

function recentCardHtml(game) {
  const art = escapeHtml(libraryArt(game));
  const total = formatPlaytime(game.playtime_seconds);
  return `
    <div class="recent-card" draggable="false" onclick="openGameModal(${jsArg(game.package)}, 'installed')">
      <div class="recent-backdrop" style="background-image:url('${art}')"></div>
      <img class="recent-cover" src="${art}" alt="" draggable="false" decoding="async" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
      <div class="recent-info">
        <div class="recent-title" title="${escapeHtml(game.title)}">${escapeHtml(game.title)}</div>
        <div class="recent-meta">${escapeHtml(playedLabel(game))}${total ? ` · ${escapeHtml(total)}` : ""}</div>
        <div class="recent-actions">${libraryPrimaryButton(game)}</div>
      </div>
    </div>`;
}

// The last games played, the running one first.
function recentGames(games, n = 3) {
  return games.filter(g => g.last_played || g.is_running)
    .sort((a, b) => (b.is_running - a.is_running) || (b.last_played - a.last_played))
    .slice(0, n);
}

function libraryUpdateFor(game) {
  return (state.updates && Array.isArray(state.updates.games))
    ? state.updates.games.find(u => u.package === game.package) : null;
}

// The one button a game's card leads with: Stop while it runs, otherwise what starts it.
function libraryPrimaryButton(game) {
  const pkg = jsArg(game.package);
  const level = (game.compat && game.compat.level) || "";
  if (game.is_running) {
    return `<button class="card-btn stop" onclick="event.stopPropagation(); stopGame(${pkg})">Stop</button>`;
  }
  if (libraryUpdateFor(game)) {
    return `<button class="card-btn update" title="1-Click Update" onclick="event.stopPropagation(); updateGame(${pkg})">Update</button>`;
  }
  if (level === "needs_port" && game.kind === "quest") {
    return `<button class="card-btn play" title="Ports the game for the Steam Frame, then starts it" onclick="event.stopPropagation(); ${game.port_failed ? "portGame" : "launchGame"}(${pkg})">${game.port_failed ? "Port Again" : "Port & Play"}</button>`;
  }
  return `<button class="card-btn play" onclick="event.stopPropagation(); launchGame(${pkg})">Play</button>`;
}

function timeAgo(epochSeconds) {
  const seconds = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes ago`;
  if (seconds < 86400) {
    const hours = Math.round(seconds / 3600);
    return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  }
  const days = Math.floor(seconds / 86400);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString();
}

function formatPlaytime(seconds) {
  const s = Number(seconds) || 0;
  if (s < 60) return "";
  if (s < 3600) return `${Math.round(s / 60)} min played`;
  return `${(s / 3600).toFixed(s < 36000 ? 1 : 0)} h played`;
}

function playedLabel(game) {
  if (game.is_running) return "Playing now";
  return game.last_played ? `Played ${timeAgo(game.last_played)}` : "Not played yet";
}

state.librarySort = (() => {
  try { return localStorage.getItem("frameload.librarySort") || "recent"; } catch (e) { return "recent"; }
})();

function setLibrarySort(value) {
  state.librarySort = value;
  try { localStorage.setItem("frameload.librarySort", value); } catch (e) { /* private window */ }
  renderInstalledGrid();
}
window.setLibrarySort = setLibrarySort;

function sortLibrary(games) {
  const byName = (a, b) => (a.title || a.package).localeCompare(b.title || b.package, undefined, { sensitivity: "base" });
  const order = {
    recent: (a, b) => (b.is_running - a.is_running) || ((b.last_played || 0) - (a.last_played || 0)) || byName(a, b),
    name: byName,
    installed: (a, b) => ((b.installed_time || 0) - (a.installed_time || 0)) || byName(a, b),
    size: (a, b) => ((b.apk_size || 0) - (a.apk_size || 0)) || byName(a, b),
  }[state.librarySort] || byName;
  const select = document.getElementById("library-sort");
  if (select && select.value !== state.librarySort) select.value = state.librarySort;
  return games.sort(order);
}


async function launchGame(pkg) {
  const game = (state.installed || []).find(g => g.package === pkg);
  const name = game ? game.title : pkg;
  showToast(`Starting ${name}...`, "info");
  try {
    const data = await apiPost("/api/installed/launch", { package: pkg });
    const port = data.porting;
    if (port && port.started) {
      // Built for Meta's runtime: it is ported first and started as soon as that is done.
      state.porting.jobId = port.job.id;
      state.porting.launchAfter = pkg;
      openPortingModal();
      showToast(port.reason === "setting_up"
        ? `${name} has to be ported first. Getting the porting tools (one time), then porting and starting it...`
        : `${name} has to be ported first. Porting it now, then starting it...`, "info");
    } else if (port && port.reason === "failed") {
      showToast(`${name} could not be ported: ${port.error || "see its launch log"}. Open the game and press Port Again to retry.`, "error");
    } else if (port && port.needed) {
      showToast(`${name} needs porting before it can start. Open the game and press Port & Play.`, "warning");
    } else if (data.success) {
      showToast(data.launched_via_steam ? "Starting through Steam..."
        : data.in_steam_library === false ? "Starting directly: Steam has not loaded this game yet. Use Stop in FrameLoad to close it."
        : "Starting...", "success");
      loadInstalled();
      [4000, 12000, 25000].forEach(delay => setTimeout(refreshRunningGames, delay));
    } else {
      showToast(data.error || "Failed to launch game", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}

// A game FrameLoad started itself has no "exit" in Steam, so the dashboard always offers Stop.
function renderStopChip() {
  const chip = document.getElementById("header-stop-game");
  if (!chip) return;
  const running = (state.installed || []).filter(g => g.is_running);
  chip.style.display = running.length ? "" : "none";
  chip.textContent = running.length === 1 ? `Stop ${running[0].title}` : `Stop ${running.length} Games`;
}

async function refreshRunningGames() {
  try {
    const data = await apiGet("/api/installed");
    const games = Array.isArray(data.games) ? data.games : [];
    const before = (state.installed || []).filter(g => g.is_running).map(g => g.package).join(",");
    const after = games.filter(g => g.is_running).map(g => g.package).join(",");
    state.installed = games;
    if (before !== after) renderInstalledGrid();  // only redraw when something started or stopped
    renderStopChip();
  } catch (e) {
    /* next round */
  }
}

async function stopGame(pkg) {
  const game = (state.installed || []).find(g => g.package === pkg);
  showToast(`Stopping ${game ? game.title : pkg}...`, "info");
  try {
    const res = await apiPost("/api/installed/stop", { package: pkg });
    showToast(res.success ? (res.stopped ? "Stopped." : res.message) : res.error, res.success ? "success" : "error");
  } catch (e) {
    showToast(e.message, "error");
  }
  refreshRunningGames();
}

async function stopRunningGames() {
  showToast("Stopping...", "info");
  try {
    const res = await apiPost("/api/installed/stop-all", {});
    showToast(res.success ? `Stopped ${res.stopped} game(s).` : "Some games could not be stopped.", res.success ? "success" : "error");
  } catch (e) {
    showToast(e.message, "error");
  }
  refreshRunningGames();
}
window.stopGame = stopGame;
window.stopRunningGames = stopRunningGames;

async function uninstallGame(pkg, keepSaves = true) {
  const target = (state.installed || []).find(g => g.package === pkg);
  if (!await confirmDialog(`Uninstall ${target ? target.title : pkg}?`,
    keepSaves ? "It is removed from this headset and from your Steam library. Its save data is kept."
      : "It is removed from this headset and from your Steam library, together with its save data.",
    { yes: "Uninstall", danger: true })) return;

  showToast(`Removing ${pkg}...`, "info");
  try {
    const res = await fetch("/api/installed/uninstall", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg, keep_saves: keepSaves })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Game uninstalled and removed from Steam library.", "success");
      closeModal();
      loadInstalled();
    } else {
      showToast(data.error || "Failed to uninstall", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}

// --- System Telemetry ---
async function loadSystemTelemetry() {
  try {
    const res = await fetch("/api/system");
    if (res.status === 403) showHostRefused();
    const data = await res.json();
    state.system = data;

    // Header chips
    const batChip = document.getElementById("header-battery");
    if (batChip && data.battery) {
      batChip.innerHTML = `<span class="pulse-dot"></span> ${data.battery.percent}%${data.battery.plugged ? ' charging' : ''}`;
    }

    const storageChip = document.getElementById("header-storage");
    if (storageChip && data.storage) {
      storageChip.textContent = `${data.storage.free_gb} GB free`;
    }

    // The header shows Lepton only when something is wrong with it.
    const lepChip = document.getElementById("header-lepton");
    if (lepChip) {
      const isReady = data.lepton && data.lepton.installed;
      lepChip.style.display = isReady ? "none" : "";
      lepChip.textContent = "Lepton Not Found";
      lepChip.title = "Lepton ships with the Steam Frame. It was not found in any Steam library on this machine.";
    }
    noteGuardEvent(data.guard_event);

    renderSystemTab(data);
    renderShellStatus();
  } catch (err) {
    console.error("Telemetry error", err);
  }
}

function renderSystemTab(sys) {
  const panel = document.getElementById("tab-system");
  if (!panel || !sys) return;

  // Lepton ships with the Steam Frame; offering a reinstall only makes sense if it has gone missing.
  const leptonHtml = sys.lepton.installed
    ? `<span style="color:var(--accent-emerald);">Ready</span> <code style="font-size:0.75rem; word-break:break-all;">${escapeHtml(sys.lepton.path)}</code>`
    : `<span style="color:var(--accent-amber);">Not found on this system.</span> ${sys.is_steam_frame ? '<button class="btn-secondary compact" onclick="installLepton()">Ask Steam to reinstall it</button>' : ''}`;

  const protonHtml = sys.proton.has_proton
    ? `<span style="color:var(--accent-emerald);">${escapeHtml(sys.proton.installed_tools.join(', '))}</span>`
    : `<span style="color:var(--accent-amber);">No Proton ARM64 tool detected</span>`;

  document.getElementById("sys-os").textContent = `${sys.os_name} ${sys.os_version} (${sys.arch})`;
  document.getElementById("sys-lepton").innerHTML = leptonHtml;
  document.getElementById("sys-proton").innerHTML = protonHtml;
  document.getElementById("sys-storage").textContent = `${sys.storage.free_gb} GB free / ${sys.storage.total_gb} GB (${sys.storage.percent_used}% used)`;
  const notFrame = document.getElementById("sys-not-frame-note");
  if (notFrame) notFrame.style.display = sys.is_steam_frame ? "none" : "block";
}

async function loadHandStatus() {
  const summary = document.getElementById("hand-status-summary");
  const list = document.getElementById("hand-status-games");
  if (!summary || !list) return;
  try {
    const data = await apiGet("/api/tuning/hand-tracking");
    summary.textContent = data.summary;
    const labels = { hands: "Hands", controllers: "Controllers", game: "Game default" };
    const games = (data.games || []).filter(g => g.requirement !== "none" || g.mode !== "auto");
    list.innerHTML = games.length
      ? games.map(g => `
          <button type="button" class="hand-game-row" onclick="openTuningModal(${jsArg(g.package)})">
            <span class="hand-game-title">${escapeHtml(g.title || g.package)}</span>
            <span class="hand-game-meta">${g.requirement === "required" ? "requires hands" : g.requirement === "optional" ? "supports hands" : "no hand tracking"}</span>
            <span class="badge ${g.effective === "hands" ? "installed" : ""}">${labels[g.effective] || g.effective}${g.framebridge ? "" : " *"}</span>
          </button>`).join("") + (games.some(g => !g.framebridge)
            ? `<p class="tuning-micro-note" style="margin-top:8px;">* Not a FramePort-ported build: the Frame's runtime decides, FrameLoad's switch has no effect.</p>` : "")
      : `<p class="tuning-micro-note">None of your installed games ask for hand tracking.</p>`;
  } catch (e) {
    summary.textContent = "Could not load hand tracking status.";
  }
}
window.loadHandStatus = loadHandStatus;

async function installLepton() {
  showToast("Requesting Lepton runtime installation via Steam...", "info");
  try {
    await fetch("/api/system/install_lepton", { method: "POST" });
    showToast("Steam install dialog triggered. Confirm in headset!", "success");
  } catch (err) {
    showToast("Error requesting Lepton install", "error");
  }
}

async function fixKeyring() {
  try {
    const res = await fetch("/api/system/fix_keyring", { method: "POST" });
    const data = await res.json();
    showToast("Podman keyring fix applied!", "success");
  } catch (err) {
    showToast("Error applying keyring fix", "error");
  }
}

// --- Modals ---
function setupModals() {
  const backdrop = document.getElementById("game-modal");
  const closeBtn = document.getElementById("modal-close-btn");
  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  if (backdrop) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeModal();
    });
  }
}

function closeModal() {
  const modal = document.getElementById("game-modal");
  if (modal) modal.classList.remove("open");
}

function openGameModal(id, mode = "catalog") {
  const modal = document.getElementById("game-modal");
  if (!modal) return;

  let game = null;
  if (mode === "catalog") {
    game = state.catalog.items.find(g => g.id === id);
  } else {
    game = state.installed.find(g => g.package === id);
  }

  if (!game) return;
  state.selectedGame = game;

  const pkg = game.package_name || game.package;
  const thumbUrl = game.thumbnail_url || `/api/thumbnail/${pkg}`;
  const installedGame = (state.installed || []).find(g => g.package === pkg);

  // Picture strip: an installed game's wide hero art (made for this shape), then its cover.
  const coverEl = document.getElementById("modal-game-cover");
  if (coverEl) {
    const chain = [installedGame ? artUrl(installedGame, "hero") : null, thumbUrl, "/static/assets/fallback_cover.svg"].filter(Boolean);
    let step = 0;
    coverEl.onerror = () => {
      step += 1;
      if (step < chain.length) coverEl.src = chain[step];
      else coverEl.onerror = null;
    };
    coverEl.src = chain[0];
  }

  // Badges: Kind & Installed
  const isInstalled = (mode === "installed") || (state.installed.some(g => g.package === pkg));
  const kindBadge = document.getElementById("modal-badge-kind");
  if (kindBadge) {
    kindBadge.className = `badge ${game.kind === 'flat' ? 'flat' : 'vr'}`;
    kindBadge.textContent = game.kind === 'flat' ? '2D App' : 'VR';
  }
  const instBadge = document.getElementById("modal-badge-installed");
  if (instBadge) {
    instBadge.style.display = isInstalled ? "inline-block" : "none";
  }

  // Rating & downloads
  const ratingEl = document.getElementById("modal-game-rating");
  if (ratingEl) {
    ratingEl.textContent = (game.rating && game.rating > 0) ? `${Number(game.rating).toFixed(1)} / 5` : "Community";
  }
  const downloadsEl = document.getElementById("modal-game-downloads");
  if (downloadsEl) {
    downloadsEl.textContent = game.downloads ? Number(game.downloads).toLocaleString() : "Active";
  }

  // Version and Last Updated
  const versionEl = document.getElementById("modal-game-version");
  if (versionEl) {
    versionEl.textContent = game.version_name || (game.version_code ? `v${game.version_code}` : (game.version || "1.0"));
  }
  const updatedEl = document.getElementById("modal-game-updated");
  if (updatedEl) {
    updatedEl.textContent = game.last_updated || "N/A";
  }

  document.getElementById("modal-game-title").textContent = game.name || game.title;
  document.getElementById("modal-game-pkg").textContent = pkg;
  document.getElementById("modal-game-size").textContent = game.size_formatted || `${Math.round((game.apk_size || 0)/(1024*1024))} MB`;

  const dlEl = document.getElementById("modal-game-downloads");
  if (dlEl) {
    dlEl.textContent = (game.downloads !== undefined && game.downloads !== null && game.downloads > 0)
      ? `${game.downloads.toLocaleString()} downloads`
      : (mode === "catalog" ? "N/A" : "Installed");
  }

  const media = document.getElementById("modal-media");
  if (media) { media.style.display = "none"; media.innerHTML = ""; }

  // Release Notes / Instructions section
  const notesSection = document.getElementById("modal-notes-section");
  const notesText = document.getElementById("modal-game-notes");
  if (notesSection && notesText) {
    const notesHeading = notesSection.querySelector("span");
    if (notesHeading) notesHeading.textContent = game.source === "fdroid" ? "About this app" : "💡 Release Notes & Headset Instructions";
    if (game.source === "fdroid") {
      const about = [game.summary, (game.categories || []).join(", "), game.license ? `License: ${game.license}` : "",
        (game.anti_features || []).length ? `F-Droid notes: ${game.anti_features.join(", ")}` : ""].filter(Boolean).join("\n");
      notesText.textContent = about;
      notesSection.style.display = about ? "block" : "none";
      fetch(`/api/catalog/game/${encodeURIComponent(game.id)}`)
        .then(res => res.json())
        .then(data => {
          if (state.selectedGame !== game || !data.game) return;
          renderAppMedia(data.game);
          if (!data.game.description) return;
          // F-Droid descriptions contain simple HTML; show them as plain text.
          const plain = new DOMParser().parseFromString(data.game.description, "text/html").body.textContent || "";
          notesText.textContent = [about, plain.trim()].filter(Boolean).join("\n\n");
          notesSection.style.display = "block";
        })
        .catch(() => {});
    } else if (game.notes && game.notes.trim()) {
      notesText.textContent = game.notes.trim();
      notesSection.style.display = "block";
    } else {
      notesSection.style.display = "none";
      if (mode === "catalog" && (game.id || pkg)) {
        fetch(`/api/catalog/notes/${game.id || pkg}`)
          .then(res => res.json())
          .then(data => {
            if (data.notes && data.notes.trim()) {
              notesText.textContent = data.notes.trim();
              notesSection.style.display = "block";
            }
          })
          .catch(() => {});
      }
    }
  }

  const driveEl = document.getElementById("modal-game-drive");
  const moveBtn = document.getElementById("modal-game-move-btn");
  if (driveEl) {
    driveEl.textContent = game.device_name || (game.is_external ? "MicroSD Card" : "Internal Storage");
  }
  if (moveBtn) {
    const hasMultipleDrives = state.storage.data && state.storage.data.devices && state.storage.data.devices.length > 1;
    if (mode === "installed" && hasMultipleDrives) {
      moveBtn.style.display = "inline-flex";
    } else {
      moveBtn.style.display = "none";
    }
  }

  // Runtime platform & OpenXR details
  const platformEl = document.getElementById("modal-game-platform");
  const openxrEl = document.getElementById("modal-game-openxr");
  if (platformEl) {
    if (game.install_type === "windows_proton") {
      platformEl.textContent = "Steam Frame (Proton ARM64 via FEX-Emu)";
    } else if (game.install_type === "linux_native") {
      platformEl.textContent = "Steam Frame (Linux Native ARM64)";
    } else if (game.kind === "flat") {
      platformEl.textContent = "Lepton (Android), shown as a 2D window";
    } else {
      platformEl.textContent = "Lepton (Android VR)";
    }
  }
  if (openxrEl) {
    if (game.install_type === "windows_proton") {
      openxrEl.textContent = game.is_vr ? "WineOpenXR -> SteamVR" : "Disabled (Flat Desktop App)";
    } else if (game.install_type === "linux_native") {
      openxrEl.textContent = game.is_vr ? "Monado / SteamVR Native OpenXR" : "Disabled (Flat Native App)";
    } else if (game.kind === "flat") {
      openxrEl.textContent = "Not used (2D app)";
    } else if (mode === "installed") {
      const runtimes = { framebridge: "SteamVR via FrameBridge (FramePort port)", openxr: "SteamVR (native OpenXR)",
        meta: "Built for Meta's runtime - not ported", vrapi: "Legacy VrApi - not ported" };
      openxrEl.textContent = runtimes[game.xr_runtime] || "SteamVR";
    } else {
      openxrEl.textContent = "Checked when installed";
    }
  }

  // Mods & Custom Content section
  const modsSection = document.getElementById("modal-mods-section");
  if (modsSection) {
    if (mode === "installed") {
      modsSection.style.display = "block";
      loadModalMods(game.package || game.package_name);
    } else {
      modsSection.style.display = "none";
    }
  }

  renderCompatNotice(document.getElementById("modal-compat"), mode === "installed" ? game.compat : null);

  const actionContainer = document.getElementById("modal-actions");
  if (mode === "catalog") {
    const verb = isInstalled ? (game.update_available ? "Update" : "Reinstall") : (game.kind === "flat" ? "Install" : "Download to Steam Frame");
    actionContainer.innerHTML = `
      <button class="btn-primary" onclick="queueDownload(${jsArg(game.id)}); closeModal();">${verb}</button>
      ${isInstalled ? `<button class="btn-secondary" onclick="launchGame(${jsArg(pkg)}); closeModal();">Open</button>` : ""}
    `;
  } else {
    const arg = jsArg(game.package);
    const lepton = game.kind === "quest" || game.kind === "flat";
    const needsPort = game.kind === "quest" && game.compat && game.compat.level === "needs_port";
    const primary = game.is_running
      ? `<button class="btn-danger" onclick="closeModal(); stopGame(${arg})">Stop</button>`
      : needsPort
      ? (game.port_failed
          ? `<button class="btn-primary" onclick="closeModal(); portGame(${arg})">Port Again</button>`
          : `<button class="btn-primary" onclick="closeModal(); launchGame(${arg})">Port &amp; Play</button>`)
      : `<button class="btn-primary" onclick="launchGame(${arg}); closeModal();">${game.is_vr ? "Launch in VR" : "Open"}</button>`;
    actionContainer.innerHTML = `
      ${primary}
      ${lepton ? `<button class="btn-secondary" onclick="openTuningModal(${arg})">Settings</button>` : ""}
      ${needsPort && game.port_failed && game.port_error ? `<span class="tuning-micro-note" style="flex-basis:100%; color:var(--accent-amber);">Last port failed: ${escapeHtml(game.port_error)}</span>` : ""}
      ${lepton ? `<button class="btn-secondary" onclick="openLogModal(${arg})">Launch Log</button>` : ""}
      <button class="btn-secondary" onclick="backupSaves(${arg})">Backup Saves</button>
      <button class="btn-secondary" style="color:var(--accent-danger);" onclick="uninstallGame(${arg})">Uninstall</button>
    `;
  }

  modal.classList.add("open");
}

async function moveCurrentModalGame() {
  if (!state.selectedGame) return;
  const pkg = state.selectedGame.package || state.selectedGame.package_name;
  const devices = (state.storage.data && state.storage.data.devices) || [];
  const currentDev = state.selectedGame.device_id || "internal";
  const otherDevices = devices.filter(d => d.id !== currentDev);

  if (otherDevices.length === 0) {
    showToast("No other storage drives available to move to.", "warning");
    return;
  }

  const targetDev = otherDevices[0];
  if (!await confirmDialog(`Move ${state.selectedGame.title || pkg} to ${targetDev.name}?`,
    "Its Steam shortcut is updated to the new place.", { yes: "Move" })) {
    return;
  }

  showToast(`Moving ${state.selectedGame.title || pkg} to ${targetDev.name}...`, "info");
  closeModal();

  try {
    const res = await fetch("/api/storage/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg, target_device_id: targetDev.id })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Game successfully moved to ${targetDev.name}!`, "success");
      loadInstalled();
      loadStorageOverview();
    } else {
      showToast(data.error || "Failed to move game", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}
window.moveCurrentModalGame = moveCurrentModalGame;

async function backupSaves(pkg) {
  showToast(`Creating save archive for ${pkg}...`, "info");
  try {
    const res = await fetch("/api/installed/backup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Backup saved: ${data.filename}`, "success");
    } else {
      showToast(data.error || "Backup failed", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}

// Shows an APK's Steam Frame verdict (from /api/local/inspect or an installed game's record).
function renderCompatNotice(el, compat) {
  if (!el) return;
  if (!compat || !compat.level) {
    el.style.display = "none";
    el.innerHTML = "";
    return;
  }
  const issues = (compat.issues || []).map(i =>
    `<li class="compat-issue ${escapeHtml(i.severity)}">${escapeHtml(i.message)}</li>`).join("");
  el.className = `compat-notice compat-${compat.level}`;
  el.innerHTML = `<div class="compat-title">${escapeHtml(compat.label)}</div>${issues ? `<ul>${issues}</ul>` : ""}`;
  el.style.display = "block";
}

// --- Sideload Form ---
async function inspectSideloadPath() {
  const input = document.getElementById("sideload-apk-path");
  const preview = document.getElementById("sideload-inspect-preview");
  const titleEl = document.getElementById("inspect-title");
  const pkgEl = document.getElementById("inspect-pkg");
  const metaEl = document.getElementById("inspect-meta");
  const badgeEl = document.getElementById("inspect-badge");
  const titleInput = document.getElementById("sideload-title");

  const p = input ? input.value.trim() : "";
  if (!p) {
    showToast("Please enter a file or folder path first.", "warning");
    return;
  }

  showToast("Inspecting package...", "info");
  try {
    const res = await fetch("/api/local/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_path: p })
    });
    const data = await res.json();
    if (data.success && data.inspection) {
      const insp = data.inspection;
      if (preview) preview.style.display = "block";
      if (titleEl) titleEl.textContent = insp.title || insp.package_name;
      if (pkgEl) pkgEl.textContent = `${insp.package_name} • Type: ${insp.source_type} ${insp.format ? '(' + insp.format + ')' : ''}`;
      if (metaEl) metaEl.textContent = `Size: ${formatBytes(insp.size_bytes || 0)} • OBB: ${insp.has_obb ? 'Included' : 'None'}`;
      if (badgeEl) {
        if (insp.source_type === "windows_proton") {
          badgeEl.textContent = insp.is_vr ? "Proton VR" : "Proton Windows";
          badgeEl.style.background = insp.is_vr ? "var(--accent-cyan)" : "#a370f7";
        } else if (insp.source_type === "linux_native") {
          badgeEl.textContent = insp.is_vr ? "Linux VR" : "Linux Native";
          badgeEl.style.background = insp.is_vr ? "var(--accent-cyan)" : "#2ec4b6";
        } else {
          badgeEl.textContent = insp.is_vr === null ? "Android" : (insp.is_vr ? "Android VR" : "2D App");
          badgeEl.style.background = insp.is_vr ? "var(--accent-cyan)" : "var(--accent-amber)";
        }
        badgeEl.style.color = "#000";
      }
      if (titleInput && !titleInput.value) {
        titleInput.value = insp.title || "";
      }
      renderCompatNotice(document.getElementById("inspect-compat"), insp.compat);
      const flatCheck = document.getElementById("sideload-flat");
      if (flatCheck && insp.is_vr === false && (insp.source_type === "apk" || insp.source_type === "directory")) {
        flatCheck.checked = true;
      }
    } else {
      showToast(data.error || "Could not inspect source path", "error");
    }
  } catch (err) {
    showToast(`Inspection failed: ${err.message}`, "error");
  }
}
window.inspectSideloadPath = inspectSideloadPath;

function toggleFlatWindowPreset() {}
window.toggleFlatWindowPreset = toggleFlatWindowPreset;

function setupSideloadForm() {
  const form = document.getElementById("sideload-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sourcePath = document.getElementById("sideload-apk-path").value.trim();
    const title = document.getElementById("sideload-title").value.trim();
    const forceFlat = document.getElementById("sideload-flat").checked;
    const targetDriveSelect = document.getElementById("sideload-target-drive");
    const deviceId = targetDriveSelect ? targetDriveSelect.value : "internal";

    showToast("Installing package onto Steam Frame...", "info");
    const submitBtn = document.getElementById("sideload-submit-btn");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Installing...";
    }

    try {
      const res = await fetch("/api/local/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          source_path: sourcePath,
          title: title,
          force_flat: forceFlat,
          device_id: deviceId
        })
      });
      const data = await res.json();
      if (data.success) {
        const level = data.compat && data.compat.level;
        const port = data.porting || {};
        if (port.started) {
          // Built for Meta's runtime: the port starts on its own, and its progress is shown.
          state.porting.jobId = port.job.id;
          openPortingModal();
          showToast(port.reason === "setting_up"
            ? "Installed. Getting the porting tools first (one time), then porting it..."
            : "Installed. Porting it for the Steam Frame now...", "info");
        } else if (port.needed && port.reason === "not_set_up") {
          showToast("Installed. It needs porting before it starts: switch on the automatic tool download under System > Quest Game Porting, or press Set Up Now there.", "warning");
        } else if (level === "needs_port" || level === "blocked") {
          showToast(`Installed, but: ${data.compat.label}. Open it in the library for details.`, "warning");
        } else {
          showToast("Installed and added to your Steam library. Restart Steam to see the new shortcut.", "success");
        }
        form.reset();
        loadSteamStatus();
        const preview = document.getElementById("sideload-inspect-preview");
        if (preview) preview.style.display = "none";
        loadInstalled();
        loadStorageOverview();
      } else {
        showToast(data.error || "Installation failed", "error");
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, "error");
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Install and Add to Steam Library";
      }
    }
  });
}

// --- Mods & Custom Content Management ---
async function loadModalMods(pkg) {
  const container = document.getElementById("modal-mods-list");
  const countEl = document.getElementById("modal-mods-count");
  if (!container) return;

  container.innerHTML = `<p style="color:var(--text-muted); font-size:0.8rem;">Loading mods and custom songs...</p>`;

  try {
    const res = await fetch(`/api/installed/mods?pkg=${encodeURIComponent(pkg)}`);
    const data = await res.json();
    const mods = data.mods || [];
    if (countEl) countEl.textContent = `${mods.length} item${mods.length === 1 ? '' : 's'}`;

    if (mods.length === 0) {
      container.innerHTML = `<p style="color:var(--text-muted); font-style:italic;">No custom songs or mods installed.</p>`;
      return;
    }

    container.innerHTML = mods.map(m => `
      <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid rgb(var(--fg-rgb) / 0.05);">
        <div>
          <span style="font-weight:600; color:var(--text-strong);">${escapeHtml(m.name)}</span>
          <span style="font-size:0.75rem; color:var(--text-muted); margin-left:6px;">(${m.type === 'custom_song' ? '🎵 Song' : '📦 Mod'} • ${m.size_formatted})</span>
        </div>
        <button class="btn-secondary compact" style="color:var(--accent-danger); font-size:0.75rem; padding:2px 8px;" onclick="deleteModalMod('${pkg}', '${m.id}')">Delete</button>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<p style="color:var(--accent-danger); font-size:0.8rem;">Failed to load mods: ${err.message}</p>`;
  }
}
window.loadModalMods = loadModalMods;

async function injectModFromModal() {
  if (!state.selectedGame) return;
  const pkg = state.selectedGame.package || state.selectedGame.package_name;
  const input = document.getElementById("modal-inject-path");
  const p = input ? input.value.trim() : "";
  if (!p) {
    showToast("Please enter path to a mod .zip or folder", "warning");
    return;
  }

  showToast(`Injecting custom content into ${state.selectedGame.title || pkg}...`, "info");
  try {
    const res = await fetch("/api/installed/mods/inject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg, source_path: p })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Injected ${data.files_injected} files successfully!`, "success");
      if (input) input.value = "";
      loadModalMods(pkg);
    } else {
      showToast(data.error || "Failed to inject mod", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}
window.injectModFromModal = injectModFromModal;

async function deleteModalMod(pkg, modId) {
  if (!await confirmDialog("Delete this item?", "The file is removed from the game's folder.", { yes: "Delete", danger: true })) return;
  showToast("Removing mod...", "info");
  try {
    const res = await fetch("/api/installed/mods/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg, mod_id: modId })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Mod removed successfully.", "success");
      loadModalMods(pkg);
    } else {
      showToast(data.error || "Failed to delete mod", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}
window.deleteModalMod = deleteModalMod;

// --- Toast Notifications ---
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container || !message) return;
  const text = String(message);

  // The same message again replaces its toast instead of stacking; four at most stay on screen.
  Array.from(container.children).filter(t => t.dataset.text === text).forEach(t => t.remove());
  while (container.children.length >= 4) container.firstElementChild.remove();

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.dataset.text = text;
  toast.setAttribute("role", type === "error" ? "alert" : "status");
  toast.title = "Dismiss";
  const mark = document.createElement("span");
  mark.className = "toast-mark";
  const body = document.createElement("span");
  body.textContent = text;
  toast.append(mark, body);
  container.appendChild(toast);

  const dismiss = () => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  };
  toast.addEventListener("click", dismiss);
  // Problems stay long enough to be read in a headset; long messages get extra time.
  const base = type === "error" ? 9000 : type === "warning" ? 7000 : 4000;
  setTimeout(dismiss, base + Math.min(6000, text.length * 35));
}
window.showToast = showToast;

// ==========================================================================
// Steam Storage Manager Implementation
// ==========================================================================

function openStorageTab() {
  const tab = document.querySelector('.tab-btn[data-tab="storage"]');
  if (tab) tab.click();
}
window.openStorageTab = openStorageTab;

function setupStorage() {
  const searchInput = document.getElementById("storage-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      state.storage.searchQuery = e.target.value.toLowerCase().trim();
      renderStorageGames();
    });
  }

  const sortSelect = document.getElementById("storage-sort-select");
  if (sortSelect) {
    sortSelect.addEventListener("change", (e) => {
      state.storage.sortBy = e.target.value;
      renderStorageGames();
    });
  }

  // Close dropdown on outside click
  document.addEventListener("click", (e) => {
    const menu = document.getElementById("storage-dropdown-menu");
    const btn = document.getElementById("storage-menu-btn");
    if (menu && menu.classList.contains("open")) {
      if (!menu.contains(e.target) && !btn.contains(e.target)) {
        menu.classList.remove("open");
      }
    }
  });
}

function toggleStorageMenu() {
  const menu = document.getElementById("storage-dropdown-menu");
  if (menu) menu.classList.toggle("open");
}
window.toggleStorageMenu = toggleStorageMenu;

async function loadStorageOverview(deviceId = state.storage.activeDeviceId) {
  try {
    const res = await fetch(`/api/storage?device=${encodeURIComponent(deviceId || 'internal')}`);
    const data = await res.json();
    state.storage.data = data;
    if (data.active_device) {
      state.storage.activeDeviceId = data.active_device.id;
    }

    // Current Anchor Path Display
    const currentPath = document.getElementById("storage-current-path");
    if (currentPath) {
      currentPath.textContent = data.anchor_dir || (data.active_device ? data.active_device.path : "Internal Storage");
    }

    // Cache Size in Options Menu
    const menuCache = document.getElementById("menu-cache-size");
    if (menuCache && data.cache) {
      menuCache.textContent = data.cache.formatted;
    }

    // Visualizer Multi-Color Segmented Progress Bar
    const bd = data.breakdown || {};
    const barGames = document.getElementById("seg-bar-games");
    const barSaves = document.getElementById("seg-bar-saves");
    const barShaders = document.getElementById("seg-bar-shaders");
    const barOther = document.getElementById("seg-bar-other");
    const barFree = document.getElementById("seg-bar-free");

    if (barGames) {
      barGames.style.width = `${bd.games_percent || 0}%`;
      barGames.title = `Games: ${bd.games_formatted} (${bd.games_percent}%)`;
    }
    if (barSaves) {
      barSaves.style.width = `${bd.saves_percent || 0}%`;
      barSaves.title = `Saves & Data: ${bd.saves_formatted} (${bd.saves_percent}%)`;
    }
    if (barShaders) {
      const shadersCombinedPct = (bd.shaders_percent || 0) + (bd.cache_percent || 0);
      barShaders.style.width = `${shadersCombinedPct}%`;
      barShaders.title = `Shaders & Cache: ${bd.shaders_formatted} (${bd.shaders_percent}%)`;
    }
    if (barOther) {
      barOther.style.width = `${bd.other_percent || 0}%`;
      barOther.title = `Other / System: ${bd.other_formatted} (${bd.other_percent}%)`;
    }
    if (barFree) {
      barFree.style.width = `${bd.free_percent || 0}%`;
      barFree.title = `Free Space: ${bd.free_formatted} (${bd.free_percent}%)`;
    }

    // Legend
    const legGames = document.getElementById("leg-games-val");
    if (legGames) legGames.textContent = bd.games_formatted || "0 B";
    const legSaves = document.getElementById("leg-saves-val");
    if (legSaves) legSaves.textContent = bd.saves_formatted || "0 B";
    const legShaders = document.getElementById("leg-shaders-val");
    if (legShaders) legShaders.textContent = bd.shaders_formatted || "0 B";
    const legOther = document.getElementById("leg-other-val");
    if (legOther) legOther.textContent = bd.other_formatted || "0 B";
    const legFree = document.getElementById("leg-free-val");
    if (legFree) legFree.textContent = bd.free_formatted || "0 B";

    // Header Count Badge
    const countBadge = document.getElementById("storage-games-count");
    if (countBadge) countBadge.textContent = data.games_count || 0;

    // Render Drive Switcher Cards
    renderStorageDrives(data.devices || [], data.active_device);

    // Render Games List
    renderStorageGames();

    // Update Bottom Batch Action Bar
    updateStorageBatchBar();

  } catch (err) {
    console.error("Error loading storage overview:", err);
  }
}
window.loadStorageOverview = loadStorageOverview;

function renderStorageDrives(devices, activeDev) {
  const container = document.getElementById("storage-drives-list");
  if (!container) return;

  // Also populate the Install File tab's drive dropdown with the drives that can hold games
  const sideloadSelect = document.getElementById("sideload-target-drive");
  if (sideloadSelect) {
    const currentVal = sideloadSelect.value;
    const usable = devices.filter(dev => dev.supports_lepton !== false);
    sideloadSelect.innerHTML = usable.map(dev => `
      <option value="${escapeHtml(dev.id)}" ${(currentVal ? dev.id === currentVal : dev.is_default) ? 'selected' : ''}>
        ${escapeHtml(dev.name)} (${escapeHtml(dev.free_formatted)} free)${dev.is_default ? ' - default' : ''}
      </option>
    `).join("");
    const row = sideloadSelect.closest("div");
    if (row) row.style.display = usable.length > 1 ? "" : "none";  // one drive: nothing to choose
  }

  container.innerHTML = devices.map(dev => {
    const isActive = activeDev && activeDev.id === dev.id;
    const isSd = dev.is_sd_card;
    const badgeHtml = isSd 
      ? `<span class="badge" style="background:#27ae60; color:var(--text-strong); font-size:0.7rem; padding:2px 6px; border-radius:4px; margin-left:6px;">MicroSD</span>`
      : `<span class="badge" style="background:rgb(var(--fg-rgb) / 0.1); color:#ccc; font-size:0.7rem; padding:2px 6px; border-radius:4px; margin-left:6px;">SSD</span>`;
    return `
      <div class="storage-drive-card ${isActive ? 'active' : ''}" onclick="selectStorageDrive('${dev.id}')">
        <div class="drive-icon-box">
          ${isSd ? `
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M6 2h9l5 5v15H6z"></path>
              <path d="M10 2v4h4"></path>
              <line x1="9" y1="10" x2="9" y2="12"></line>
              <line x1="12" y1="10" x2="12" y2="12"></line>
              <line x1="15" y1="10" x2="15" y2="12"></line>
            </svg>
          ` : `
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect>
              <rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect>
              <line x1="6" y1="6" x2="6.01" y2="6"></line>
              <line x1="6" y1="18" x2="6.01" y2="18"></line>
            </svg>
          `}
        </div>
        <div class="drive-meta">
          <div class="drive-name">
            ${dev.name} ${badgeHtml} ${dev.is_default ? '<span class="drive-star" title="Default Install Drive">★</span>' : ''}
          </div>
          <div class="drive-caption">${dev.free_formatted} FREE OF ${dev.total_formatted}</div>
        </div>
      </div>
    `;
  }).join("");
}

function selectStorageDrive(devId) {
  state.storage.activeDeviceId = devId;
  state.storage.selectedPackages.clear();
  loadStorageOverview(devId);
}
window.selectStorageDrive = selectStorageDrive;

function renderStorageGames() {
  const container = document.getElementById("storage-games-list");
  if (!container) return;

  if (!state.storage.data || !state.storage.data.games) {
    container.innerHTML = `<div class="loading-state">Scanning storage telemetry...</div>`;
    return;
  }

  let games = [...state.storage.data.games];

  // Search filter
  const q = state.storage.searchQuery;
  if (q) {
    games = games.filter(g => 
      (g.title && g.title.toLowerCase().includes(q)) ||
      (g.package && g.package.toLowerCase().includes(q))
    );
  }

  // Sorting
  const sortBy = state.storage.sortBy;
  if (sortBy === "size_desc") {
    games.sort((a, b) => (b.total_bytes || 0) - (a.total_bytes || 0));
  } else if (sortBy === "size_asc") {
    games.sort((a, b) => (a.total_bytes || 0) - (b.total_bytes || 0));
  } else if (sortBy === "name_asc") {
    games.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
  } else if (sortBy === "saves_desc") {
    games.sort((a, b) => (b.saves_bytes || 0) - (a.saves_bytes || 0));
  } else if (sortBy === "date_desc") {
    games.sort((a, b) => (b.installed_time || 0) - (a.installed_time || 0));
  }

  if (games.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding:48px 20px; color:var(--text-muted); background:var(--bg-card); border-radius:var(--radius-md); border:1px solid var(--border-subtle);">
        <p style="font-size:1.05rem; font-weight:600; color:var(--text-strong); margin-bottom:6px;">No installed games match your search</p>
        <p style="font-size:0.85rem;">Clear search filter or install games from the Catalog tab.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = games.map(game => {
    const isSelected = state.storage.selectedPackages.has(game.package);
    const thumbUrl = game.thumbnail_url || "";
    const thumbHtml = thumbUrl
      ? `<img src="${thumbUrl}" class="storage-game-thumb" alt="" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">`
      : `<div class="storage-game-thumb" style="display:flex; align-items:center; justify-content:center; color:var(--accent-cyan);">
           <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
             <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
             <polyline points="2 17 12 22 22 17"></polyline>
             <polyline points="2 12 12 17 22 12"></polyline>
           </svg>
         </div>`;

    return `
      <div class="storage-game-row ${isSelected ? 'selected' : ''}" 
           data-package="${game.package}"
           tabindex="0"
           role="checkbox"
           aria-checked="${isSelected}"
           onclick="toggleStorageGameSelection('${game.package}')">
        <div class="storage-game-left">
          ${thumbHtml}
          <div class="storage-game-info">
            <div class="storage-game-title">${escapeHtml(game.title)}</div>
            <div class="storage-game-meta">
              <span class="storage-game-badge ${game.is_vr ? 'vr' : ''}">${game.is_vr ? 'Quest VR' : 'Flat'}</span>
              <span>•</span>
              <span class="storage-game-breakdown">
                App: ${game.app_formatted} • Saves: ${game.saves_formatted} • Shaders: ${game.shaders_formatted}
              </span>
              <span>•</span>
              <span>${game.installed_formatted}</span>
            </div>
          </div>
        </div>

        <div class="storage-game-right">
          <div class="storage-game-size">${game.total_formatted}</div>
          <div class="steam-checkbox-box" title="Select for uninstall">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </div>
        </div>
      </div>
    `;
  }).join("");

  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

function toggleStorageGameSelection(pkg) {
  if (state.storage.selectedPackages.has(pkg)) {
    state.storage.selectedPackages.delete(pkg);
  } else {
    state.storage.selectedPackages.add(pkg);
  }

  // Update DOM row
  const row = document.querySelector(`.storage-game-row[data-package="${pkg}"]`);
  if (row) {
    const isSelected = state.storage.selectedPackages.has(pkg);
    row.classList.toggle("selected", isSelected);
    row.setAttribute("aria-checked", isSelected ? "true" : "false");
  }

  updateStorageBatchBar();
}
window.toggleStorageGameSelection = toggleStorageGameSelection;

function toggleSelectAllStorageGames() {
  if (!state.storage.data || !state.storage.data.games) return;
  const games = state.storage.data.games;

  if (state.storage.selectedPackages.size === games.length) {
    state.storage.selectedPackages.clear();
  } else {
    games.forEach(g => state.storage.selectedPackages.add(g.package));
  }

  renderStorageGames();
  updateStorageBatchBar();
}
window.toggleSelectAllStorageGames = toggleSelectAllStorageGames;

function deselectAllStorageGames() {
  state.storage.selectedPackages.clear();
  document.querySelectorAll(".storage-game-row").forEach(r => {
    r.classList.remove("selected");
    r.setAttribute("aria-checked", "false");
  });
  updateStorageBatchBar();
}
window.deselectAllStorageGames = deselectAllStorageGames;

function updateStorageBatchBar() {
  const bar = document.getElementById("storage-batch-bar");
  const countEl = document.getElementById("batch-selected-count");
  const sizeEl = document.getElementById("batch-selected-size");
  const btnCount = document.getElementById("batch-uninstall-btn-count");
  const uninstallBtn = document.getElementById("batch-uninstall-btn");

  const count = state.storage.selectedPackages.size;
  let totalBytes = 0;

  if (state.storage.data && state.storage.data.games) {
    for (const g of state.storage.data.games) {
      if (state.storage.selectedPackages.has(g.package)) {
        totalBytes += (g.total_bytes || 0);
      }
    }
  }

  const formattedSize = formatBytes(totalBytes);

  if (countEl) countEl.textContent = count;
  if (sizeEl) sizeEl.textContent = formattedSize;
  if (btnCount) btnCount.textContent = count;

  if (bar) {
    bar.classList.toggle("visible", count > 0);
  }

  if (uninstallBtn) {
    uninstallBtn.disabled = count === 0;
  }

  // Multi-Drive Batch Move Group
  const moveGroup = document.getElementById("batch-move-group");
  const moveSelect = document.getElementById("batch-move-target");
  if (moveGroup && moveSelect && state.storage.data && state.storage.data.devices) {
    const devices = state.storage.data.devices;
    const currentDevId = state.storage.activeDeviceId || "internal";
    const otherDevices = devices.filter(d => d.id !== currentDevId);
    if (otherDevices.length > 0 && count > 0) {
      moveGroup.style.display = "inline-flex";
      moveSelect.innerHTML = otherDevices.map(d => `
        <option value="${d.id}">Move to ${d.name}</option>
      `).join("");
    } else {
      moveGroup.style.display = "none";
    }
  }
}

async function executeBatchMove() {
  const count = state.storage.selectedPackages.size;
  if (count === 0) return;

  const targetSelect = document.getElementById("batch-move-target");
  const targetDeviceId = targetSelect ? targetSelect.value : "";
  if (!targetDeviceId) return;

  const packages = Array.from(state.storage.selectedPackages);
  showToast(`Moving ${packages.length} game(s) to destination drive...`, "info");

  try {
    const res = await fetch("/api/storage/batch-move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ packages: packages, target_device_id: targetDeviceId })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Successfully moved ${data.moved_count} games (${data.total_formatted})!`, "success");
      state.storage.selectedPackages.clear();
      loadStorageOverview(targetDeviceId);
      loadInstalled();
    } else {
      showToast(`Batch move completed with errors: ${data.errors ? data.errors.map(e => e.error).join(', ') : 'Unknown error'}`, "error");
      loadStorageOverview();
    }
  } catch (err) {
    showToast(`Error moving games: ${err.message}`, "error");
  }
}
window.executeBatchMove = executeBatchMove;

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function openBatchUninstallModal() {
  const count = state.storage.selectedPackages.size;
  if (count === 0) return;

  const modal = document.getElementById("batch-uninstall-modal");
  const preview = document.getElementById("modal-batch-games-preview");
  const countEl = document.getElementById("modal-batch-count");
  const reclaimEl = document.getElementById("modal-batch-reclaim");

  if (!modal || !state.storage.data) return;

  const selectedGames = state.storage.data.games.filter(g => state.storage.selectedPackages.has(g.package));
  const totalBytes = selectedGames.reduce((acc, g) => acc + (g.total_bytes || 0), 0);

  if (countEl) countEl.textContent = count;
  if (reclaimEl) reclaimEl.textContent = formatBytes(totalBytes);

  if (preview) {
    preview.innerHTML = selectedGames.map(g => `
      <div class="batch-preview-row">
        <span class="batch-preview-row-title">${escapeHtml(g.title)}</span>
        <span class="batch-preview-row-size">${g.total_formatted}</span>
      </div>
    `).join("");
  }

  modal.classList.add("open");
}
window.openBatchUninstallModal = openBatchUninstallModal;

function closeBatchModal() {
  const modal = document.getElementById("batch-uninstall-modal");
  if (modal) modal.classList.remove("open");
}
window.closeBatchModal = closeBatchModal;

async function executeBatchUninstall() {
  const packages = Array.from(state.storage.selectedPackages);
  if (packages.length === 0) return;

  const keepSaves = document.getElementById("modal-confirm-keep-saves").checked;
  const btn = document.getElementById("modal-batch-confirm-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Uninstalling...";
  }

  showToast(`Uninstalling ${packages.length} games...`, "info");

  try {
    const res = await fetch("/api/storage/batch-uninstall", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ packages: packages, keep_saves: keepSaves })
    });
    const data = await res.json();

    if (data.success) {
      showToast(`Successfully uninstalled ${data.uninstalled_count} games! Reclaimed ${data.reclaimed_formatted}.`, "success");
      closeBatchModal();
      deselectAllStorageGames();
      loadStorageOverview();
      loadInstalled();
      loadSystemTelemetry();
    } else {
      showToast(data.error || "Batch uninstall encountered issues", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Uninstall & Free Space";
    }
  }
}
window.executeBatchUninstall = executeBatchUninstall;

// Cache Cleaning Modals & Actions
function openCleanCacheModal() {
  const modal = document.getElementById("clean-cache-modal");
  const menu = document.getElementById("storage-dropdown-menu");
  if (menu) menu.classList.remove("open");

  if (!modal) return;
  const cacheData = state.storage.data ? state.storage.data.cache : null;
  const sizeEl = document.getElementById("clean-cache-size");
  if (sizeEl && cacheData) {
    sizeEl.textContent = `${cacheData.formatted} (${cacheData.file_count} files)`;
  }
  modal.classList.add("open");
}
window.openCleanCacheModal = openCleanCacheModal;

function closeCleanCacheModal() {
  const modal = document.getElementById("clean-cache-modal");
  if (modal) modal.classList.remove("open");
}
window.closeCleanCacheModal = closeCleanCacheModal;

async function executeCleanCache() {
  closeCleanCacheModal();
  showToast("Cleaning download cache...", "info");
  try {
    const res = await fetch("/api/storage/clean-cache", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_downloads: true, clear_shaders: false })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Cache cleaned! Reclaimed ${data.reclaimed_formatted}.`, "success");
      loadStorageOverview();
      loadSystemTelemetry();
    } else {
      showToast(data.error || "Failed to clean cache", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}
window.executeCleanCache = executeCleanCache;

async function cleanShaderCaches() {
  const menu = document.getElementById("storage-dropdown-menu");
  if (menu) menu.classList.remove("open");

  if (!await confirmDialog("Reset all shader caches?",
    "Every game rebuilds its shaders the next time it starts, so the first minutes may stutter.", { yes: "Reset" })) return;

  showToast("Resetting Lepton shader caches...", "info");
  try {
    const res = await fetch("/api/storage/clean-cache", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_downloads: false, clear_shaders: true })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Shader caches cleared! Reclaimed ${data.reclaimed_formatted}.`, "success");
      loadStorageOverview();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}
window.cleanShaderCaches = cleanShaderCaches;

// ==========================================================================
// Updates Management (1-Click OTA & Game Updates)
// ==========================================================================

async function checkForUpdates(userTriggered = false) {
  const checkBtn = document.getElementById("btn-check-updates");
  if (checkBtn && userTriggered) {
    checkBtn.disabled = true;
    checkBtn.textContent = "Checking...";
  }

  try {
    const res = await fetch(userTriggered ? "/api/updates?force=1" : "/api/updates");
    const data = await res.json();
    // The server sends games as {updates_count, games: [...]}; everything here works with the list.
    const gameUpdates = Array.isArray(data.games) ? data.games : ((data.games && data.games.games) || []);
    data.games = gameUpdates;
    state.updates = data;

    // 1. App Update Banner & Telemetry Chip
    const appUpdate = data.app || {};
    const alertChip = document.getElementById("header-update-alert");
    const alertTag = document.getElementById("header-update-tag");
    const sysBadge = document.getElementById("sys-update-badge");
    const sysUpdateBtn = document.getElementById("btn-system-update");
    const sysVersion = document.getElementById("sys-version");

    if (sysVersion && appUpdate.current_version) {
      sysVersion.textContent = `v${appUpdate.current_version}`;
    }

    const topBanner = document.getElementById("app-update-top-banner");
    const topBannerVer = document.getElementById("top-banner-version");

    if (appUpdate.has_update) {
      if (alertChip) {
        alertChip.style.display = "inline-flex";
        if (alertTag) alertTag.textContent = `v${appUpdate.latest_version}`;
      }
      if (topBanner && topBannerVer) {
        topBannerVer.textContent = `v${appUpdate.latest_version}`;
        const isDismissed = sessionStorage.getItem(`dismissed_update_${appUpdate.latest_version}`);
        if (!isDismissed) {
          topBanner.style.display = "flex";
        }
      }
      if (sysBadge) {
        sysBadge.style.background = "rgb(var(--warn-rgb) / 0.15)";
        sysBadge.style.color = "var(--accent-amber)";
        sysBadge.textContent = `Update: v${appUpdate.latest_version}`;
      }
      if (sysUpdateBtn) sysUpdateBtn.style.display = "inline-flex";
    } else {
      if (alertChip) alertChip.style.display = "none";
      if (topBanner) topBanner.style.display = "none";
      if (sysBadge) {
        sysBadge.style.background = "rgb(var(--ok-rgb) / 0.15)";
        sysBadge.style.color = "var(--accent-emerald)";
        sysBadge.textContent = "Up to Date";
      }
      if (sysUpdateBtn) sysUpdateBtn.style.display = "none";
    }

    // 2. Installed Game Updates Banner
    const updatesBanner = document.getElementById("library-updates-banner");
    const updatesCountEl = document.getElementById("library-updates-count");

    if (gameUpdates.length > 0) {
      if (updatesBanner) updatesBanner.style.display = "flex";
      if (updatesCountEl) updatesCountEl.textContent = gameUpdates.length;
    } else {
      if (updatesBanner) updatesBanner.style.display = "none";
    }

    // Refresh game cards to show badges and 1-click update buttons
    if (state.installed && state.installed.length > 0) {
      renderInstalledGrid();
    }

    if (userTriggered) {
      if (appUpdate.has_update || gameUpdates.length > 0) {
        showToast(`Updates available! (${gameUpdates.length} games, FrameLoad v${appUpdate.latest_version})`, "info");
      } else {
        showToast("FrameLoad and all installed games are up to date!", "success");
      }
    }

  } catch (err) {
    console.error("Error checking for updates:", err);
    if (userTriggered) showToast("Could not check for updates. Check internet connection.", "error");
  } finally {
    if (checkBtn && userTriggered) {
      checkBtn.disabled = false;
      checkBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="23 4 23 10 17 10"></polyline>
          <polyline points="1 20 1 14 7 14"></polyline>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
        </svg>
        Check for Updates
      `;
    }
  }
}
window.checkForUpdates = checkForUpdates;

function openUpdateModal() {
  const modal = document.getElementById("update-modal");
  if (!modal) return;

  const appUpdate = (state.updates && state.updates.app) ? state.updates.app : {};
  const curVerEl = document.getElementById("modal-update-cur-ver");
  const newVerEl = document.getElementById("modal-update-new-ver");
  const notesEl = document.getElementById("modal-update-notes");

  if (curVerEl) curVerEl.textContent = `v${appUpdate.current_version || '1.0.0'}`;
  if (newVerEl) newVerEl.textContent = `v${appUpdate.latest_version || '1.0.1'}`;
  if (notesEl) {
    notesEl.textContent = appUpdate.release_notes || "Bug fixes, stability enhancements, and performance optimizations.";
  }

  modal.classList.add("open");
}
window.openUpdateModal = openUpdateModal;

function closeUpdateModal() {
  const modal = document.getElementById("update-modal");
  if (modal) modal.classList.remove("open");
}
window.closeUpdateModal = closeUpdateModal;

function dismissUpdateBanner() {
  const topBanner = document.getElementById("app-update-top-banner");
  if (topBanner) topBanner.style.display = "none";
  if (state.updates && state.updates.app && state.updates.app.latest_version) {
    sessionStorage.setItem(`dismissed_update_${state.updates.app.latest_version}`, "true");
  }
}
window.dismissUpdateBanner = dismissUpdateBanner;

async function triggerAppUpdate() {
  const btn = document.getElementById("modal-update-confirm-btn");
  const sysBtn = document.getElementById("btn-system-update");

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Updating FrameLoad...";
  }
  if (sysBtn) {
    sysBtn.disabled = true;
    sysBtn.textContent = "Updating...";
  }

  showToast("Downloading FrameLoad update...", "info");

  try {
    const res = await fetch("/api/updates/app", { method: "POST" });
    const data = await res.json();

    if (data.success) {
      showToast("FrameLoad updated successfully! Restarting service and reloading page...", "success");
      setTimeout(() => {
        window.location.reload();
      }, 3500);
    } else {
      showToast(data.error || "Update failed. Check system logs.", "error");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Update and Restart";
      }
      if (sysBtn) {
        sysBtn.disabled = false;
        sysBtn.textContent = "Update Now";
      }
    }
  } catch (err) {
    showToast(`Update error: ${err.message}`, "error");
  }
}
window.triggerAppUpdate = triggerAppUpdate;

async function updateGame(pkg) {
  showToast(`Queuing 1-click update for ${pkg}...`, "info");
  try {
    const res = await fetch("/api/updates/game", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg })
    });
    const data = await res.json();

    if (data.success) {
      showToast("Game update added to download queue! Saves will be preserved.", "success");
      // Switch to downloads tab to see progress
      const dlTab = document.querySelector('.tab-btn[data-tab="downloads"]');
      if (dlTab) dlTab.click();
    } else {
      showToast(data.error || "Failed to queue game update", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}
window.updateGame = updateGame;

async function updateAllGames() {
  showToast("Queuing 1-click updates for all games...", "info");
  try {
    const res = await fetch("/api/updates/all-games", { method: "POST" });
    const data = await res.json();

    if (data.success) {
      showToast(`Queued ${data.queued_count} game updates!`, "success");
      const dlTab = document.querySelector('.tab-btn[data-tab="downloads"]');
      if (dlTab) dlTab.click();
    } else {
      showToast(data.error || "Failed to batch queue updates", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}
window.updateAllGames = updateAllGames;

// --- Clean Uninstallation of FrameLoad App ---
function openUninstallAppModal() {
  const modal = document.getElementById("uninstall-app-modal");
  if (!modal) return;
  const input = document.getElementById("uninst-confirm-input");
  const btn = document.getElementById("uninst-submit-btn");
  if (input) {
    input.value = "";
    input.oninput = () => {
      if (btn) btn.disabled = (input.value.trim().toUpperCase() !== "UNINSTALL");
    };
  }
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Confirm & Completely Remove";
  }
  modal.classList.add("open");
}
window.openUninstallAppModal = openUninstallAppModal;

function closeUninstallAppModal() {
  const modal = document.getElementById("uninstall-app-modal");
  if (modal) modal.classList.remove("open");
}
window.closeUninstallAppModal = closeUninstallAppModal;

async function executeUninstallApp() {
  const purgeGames = document.getElementById("uninst-purge-games")?.checked || false;
  const keepBackups = document.getElementById("uninst-keep-backups")?.checked || false;
  const btn = document.getElementById("uninst-submit-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Uninstalling & Cleaning...";
  }

  try {
    const res = await fetch("/api/system/uninstall-app", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirm: "UNINSTALL",
        purge_games: purgeGames,
        keep_backups: keepBackups
      })
    });
    const data = await res.json();
    if (data.success) {
      document.body.innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; background:var(--accent-ink); color:var(--text-strong); font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align:center; padding:24px;">
          <div style="font-size:3.5rem; margin-bottom:16px;">✨</div>
          <h1 style="color:var(--ok); font-size:2rem; font-weight:800; margin-bottom:14px;">FrameLoad Successfully Uninstalled</h1>
          <p style="color:#94a3b8; max-width:520px; line-height:1.6; margin-bottom:24px; font-size:1rem;">
            All system integrations have been removed from your Steam Frame: background systemd service stopped, desktop launcher deleted, Steam shortcuts &amp; grid artwork removed, and caches cleared.
          </p>
          <div style="background:rgb(var(--fg-rgb) / 0.04); border:1px solid rgb(var(--fg-rgb) / 0.1); border-radius:12px; padding:16px 24px; color:#cbd5e1; font-size:0.9rem; margin-bottom:20px;">
            ${keepBackups ? "Save game backups were kept in <code>~/.local/share/frameload/backups</code>." : "All data and caches were removed."}
          </div>
          <p style="color:#64748b; font-size:0.85rem;">You may now safely close this browser window.</p>
        </div>
      `;
    } else {
      showToast(data.error || "Uninstall failed", "error");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Confirm & Completely Remove";
      }
    }
  } catch (err) {
    // Daemon exited normally as part of uninstallation
    document.body.innerHTML = `
      <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; background:var(--accent-ink); color:var(--text-strong); font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align:center; padding:24px;">
        <div style="font-size:3.5rem; margin-bottom:16px;">✨</div>
        <h1 style="color:var(--ok); font-size:2rem; font-weight:800; margin-bottom:14px;">FrameLoad Successfully Uninstalled</h1>
        <p style="color:#94a3b8; max-width:520px; line-height:1.6; margin-bottom:24px; font-size:1rem;">
          The background daemon has shut down and all system integrations have been cleanly removed from your Steam Frame.
        </p>
        <p style="color:#64748b; font-size:0.85rem;">You may now safely close this browser tab.</p>
      </div>
    `;
  }
}
window.executeUninstallApp = executeUninstallApp;

// ============================================================
// Mirror Manager
// ============================================================

async function loadMirrorStatus() {
  try {
    const data = await apiGet("/api/mirrors");
    const badge = document.getElementById("mirror-status-badge");
    const text = document.getElementById("mirror-status-text");
    const url = document.getElementById("mirror-modal-url");
    const count = document.getElementById("mirror-modal-count");
    const clearBtn = document.getElementById("btn-clear-mirror");

    if (data.active_base_url) {
      if (badge) {
        badge.textContent = "vrSrc Mirror";
        badge.style.background = "rgb(var(--accent-rgb) / 0.12)";
        badge.style.color = "var(--accent-cyan)";
        badge.style.border = "1px solid rgb(var(--accent-rgb) / 0.3)";
      }
      if (text) text.textContent = `Mirror configured: ${data.active_base_url}`;
      if (url) url.textContent = data.active_base_url;
      if (clearBtn) clearBtn.style.display = "";
    } else {
      if (badge) {
        badge.textContent = "Built-in Catalog";
        badge.style.background = "rgb(var(--fg-rgb) / 0.08)";
        badge.style.color = "var(--text-muted)";
        badge.style.border = "none";
      }
      if (text) text.textContent = "Using FrameLoad built-in catalog. Configure a VRP-compatible mirror for full live game access.";
      if (url) url.textContent = "None (built-in catalog)";
      if (clearBtn) clearBtn.style.display = "none";
    }
    if (count) count.textContent = `${data.catalog_game_count.toLocaleString()} games`;
  } catch (e) {
    console.warn("Mirror status load failed:", e);
  }
}

function openMirrorModal() {
  const modal = document.getElementById("mirror-modal");
  if (modal) {
    modal.classList.add("open");
    loadMirrorStatus();
    checkRcloneStatus();
  }
}

function closeMirrorModal() {
  const modal = document.getElementById("mirror-modal");
  if (modal) modal.classList.remove("open");
}

async function checkRcloneStatus() {
  const statusText = document.getElementById("rclone-status-text");
  const installBtn = document.getElementById("btn-install-rclone");
  const bar = document.getElementById("rclone-status-bar");
  try {
    // Probe via mirrors endpoint which checks rclone implicitly
    const data = await apiGet("/api/mirrors");
    // We'll call a lightweight test to see if rclone is installed
    // For now just show ready state - rclone will be auto-installed on first sync
    if (statusText) statusText.textContent = "rclone: ready (installs itself on the first sync)";
    if (bar) {
      bar.style.background = "rgb(var(--accent-rgb) / 0.05)";
      bar.style.borderColor = "rgb(var(--accent-rgb) / 0.15)";
      statusText.style.color = "var(--accent-cyan)";
    }
    if (installBtn) installBtn.style.display = "none";
  } catch (e) {
    if (statusText) statusText.textContent = "⚙️ rclone status unknown";
    if (installBtn) installBtn.style.display = "";
  }
}

async function installRclone() {
  const btn = document.getElementById("btn-install-rclone");
  const statusText = document.getElementById("rclone-status-text");
  if (btn) { btn.disabled = true; btn.textContent = "Installing..."; }
  if (statusText) statusText.textContent = "⬇️ Downloading rclone...";
  try {
    const data = await apiPost("/api/mirrors/install-rclone", {});
    if (data.success) {
      if (statusText) statusText.textContent = "rclone installed.";
      if (btn) btn.style.display = "none";
      showToast("rclone installed successfully", "success");
    } else {
      if (statusText) statusText.textContent = `⚠️ Install failed: ${(data.messages || []).join("; ")}`;
      if (btn) { btn.disabled = false; btn.textContent = "Retry"; }
    }
  } catch (e) {
    if (statusText) statusText.textContent = `⚠️ Error: ${e.message}`;
    if (btn) { btn.disabled = false; btn.textContent = "Retry"; }
  }
}

async function applyMirrorConfig() {
  const input = document.getElementById("mirror-config-input");
  const btn = document.getElementById("btn-apply-mirror");
  const resultEl = document.getElementById("mirror-test-result");

  if (!input || !input.value.trim()) {
    showToast("Paste your vrp-public.json config first", "error");
    return;
  }

  let config;
  try {
    config = JSON.parse(input.value.trim());
  } catch (e) {
    showToast("Invalid JSON — check your config format", "error");
    return;
  }

  if (!config.baseUri) {
    showToast("Config must contain a 'baseUri' field", "error");
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = "Applying..."; }

  try {
    const data = await apiPost("/api/mirrors/apply", config);
    if (data.success) {
      showToast(`Mirror configured: ${data.base_url}`, "success");
      if (resultEl) {
        resultEl.style.display = "block";
        resultEl.style.background = "rgb(var(--accent-rgb) / 0.08)";
        resultEl.style.border = "1px solid rgb(var(--accent-rgb) / 0.3)";
        resultEl.style.color = "var(--accent-cyan)";
        resultEl.textContent = `${data.message} Press Sync Catalog in Browse to load the games.`;
      }
      loadMirrorStatus();
    } else {
      showToast(data.error || "Failed to apply config", "error");
      if (resultEl) {
        resultEl.style.display = "block";
        resultEl.style.background = "rgb(var(--danger-rgb) / 0.08)";
        resultEl.style.border = "1px solid rgb(var(--danger-rgb) / 0.3)";
        resultEl.style.color = "#ff8080";
        resultEl.textContent = `❌ ${data.error}`;
      }
    }
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Apply Config"; }
  }
}

async function testMirrorFromModal() {
  const resultEl = document.getElementById("mirror-test-result");
  const btn = document.getElementById("btn-modal-test");
  if (btn) { btn.disabled = true; btn.textContent = "Testing..."; }
  if (resultEl) { resultEl.style.display = "block"; resultEl.textContent = "⌛ Connecting..."; resultEl.style.background = "rgb(var(--warn-rgb) / 0.06)"; resultEl.style.border = "1px solid rgb(var(--warn-rgb) / 0.2)"; resultEl.style.color = "var(--accent-amber)"; }

  try {
    const data = await apiPost("/api/mirrors/test", {});
    if (data.success) {
      if (resultEl) {
        resultEl.style.background = "rgb(var(--accent-rgb) / 0.08)";
        resultEl.style.border = "1px solid rgb(var(--accent-rgb) / 0.3)";
        resultEl.style.color = "var(--accent-cyan)";
        resultEl.textContent = data.message;
      }
      showToast("Mirror connection OK!", "success");
    } else {
      if (resultEl) {
        resultEl.style.background = "rgb(var(--danger-rgb) / 0.08)";
        resultEl.style.border = "1px solid rgb(var(--danger-rgb) / 0.3)";
        resultEl.style.color = "#ff8080";
        resultEl.textContent = `❌ ${data.error}`;
      }
      showToast(data.error || "Connection failed", "error");
    }
  } catch (e) {
    if (resultEl) { resultEl.textContent = `❌ ${e.message}`; }
    showToast(`Error: ${e.message}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Test Connection"; }
  }
}

async function testMirrorConnection() {
  const btn = document.getElementById("btn-test-mirror");
  if (btn) { btn.disabled = true; btn.textContent = "Testing..."; }
  try {
    const data = await apiPost("/api/mirrors/test", {});
    showToast(data.success ? data.message : data.error, data.success ? "success" : "error");
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Test Connection"; }
  }
}

async function clearMirrorConfig() {
  if (!confirm("Reset to built-in catalog? This will remove your mirror config.")) return;
  try {
    const data = await apiPost("/api/mirrors/clear", {});
    showToast(data.message || "Mirror cleared", "success");
    loadMirrorStatus();
    const resultEl = document.getElementById("mirror-test-result");
    if (resultEl) resultEl.style.display = "none";
    closeMirrorModal();
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  }
}

// Load mirror status on init
document.addEventListener("DOMContentLoaded", () => {
  loadMirrorStatus();
});

// Expose globally
window.openMirrorModal = openMirrorModal;
window.closeMirrorModal = closeMirrorModal;
window.applyMirrorConfig = applyMirrorConfig;
window.testMirrorFromModal = testMirrorFromModal;
window.testMirrorConnection = testMirrorConnection;
window.installRclone = installRclone;
window.clearMirrorConfig = clearMirrorConfig;

// === Per-game settings (Lepton + FrameBridge) ===
// The dialog is built from the server's schema, so every control maps to a setting the headset reads.
state.tuningTarget = null;
state.tuningSchema = null;
state.tuningPresets = null;
state.tuningInfo = null;

async function loadTuningSchema() {
  if (state.tuningSchema) return;
  const data = await apiGet("/api/tuning/presets");
  state.tuningSchema = data.schema || [];
  state.tuningPresets = data.presets || {};
}

function tuningInputId(key) {
  return `tune-${key}`;
}

function formatTuningValue(spec, value) {
  if (spec.type === "range") return `${Number(value).toFixed(2)}${spec.unit || ""}`;
  if (spec.type === "bool") return value ? "On" : "Off";
  const choice = (spec.choices || []).find(c => String(c.value) === String(value));
  return choice ? choice.label : String(value);
}

function renderTuningControl(spec, value, inactive) {
  const id = tuningInputId(spec.key);
  let control = "";
  if (spec.type === "choice") {
    control = `<select id="${id}" class="select-styled" onchange="onTuningInput('${spec.key}')">` +
      spec.choices.map(c => `<option value="${escapeHtml(c.value)}" ${String(c.value) === String(value) ? "selected" : ""}>${escapeHtml(c.label)}</option>`).join("") +
      `</select>`;
  } else if (spec.type === "range") {
    control = `<input type="range" id="${id}" class="tuning-range-slider" min="${spec.min}" max="${spec.max}" step="${spec.step}" value="${escapeHtml(value)}" oninput="onTuningInput('${spec.key}')">`;
  } else {
    control = `<label class="tuning-toggle"><input type="checkbox" id="${id}" ${value ? "checked" : ""} onchange="onTuningInput('${spec.key}')"><span>Enabled</span></label>`;
  }
  return `
    <div class="tuning-card${inactive ? " inactive" : ""}" data-key="${spec.key}">
      <div class="tuning-card-header">
        <span class="tuning-card-title">${escapeHtml(spec.title)}</span>
        ${spec.type === "range" ? `<span id="${id}-val" class="tuning-card-val">${escapeHtml(formatTuningValue(spec, value))}</span>` : ""}
      </div>
      ${control}
      <p class="tuning-micro-note">${escapeHtml(spec.description)}</p>
    </div>`;
}

function readTuningValue(spec) {
  const el = document.getElementById(tuningInputId(spec.key));
  if (!el) return undefined;
  if (spec.type === "bool") return el.checked;
  if (spec.type === "range") return parseFloat(el.value);
  return typeof spec.default === "number" ? Number(el.value) : el.value;
}

function onTuningInput(key) {
  const spec = (state.tuningSchema || []).find(s => s.key === key);
  const label = document.getElementById(`${tuningInputId(key)}-val`);
  if (spec && label) label.textContent = formatTuningValue(spec, readTuningValue(spec));
  document.querySelectorAll(".tuning-preset-chip").forEach(chip => chip.classList.remove("active"));
}

function visibleTuningSpecs(info, isGlobal) {
  return (state.tuningSchema || []).filter(spec => isGlobal || spec.scope === (info.is_vr ? "vr" : "flat"));
}

async function openTuningModal(pkg) {
  const modal = document.getElementById("tuning-modal");
  const body = document.getElementById("tuning-body");
  if (!modal || !body) return;
  state.tuningTarget = pkg;
  const isGlobal = pkg === "__global__";

  let info;
  try {
    await loadTuningSchema();
    info = await apiGet(isGlobal ? "/api/tuning/global" : `/api/installed/tuning/${encodeURIComponent(pkg)}`);
  } catch (err) {
    showToast(`Could not load settings: ${err.message}`, "error");
    return;
  }
  state.tuningInfo = info;

  document.getElementById("tuning-modal-title").textContent = isGlobal ? "Default settings for all games" : `${info.title} - Settings`;
  document.getElementById("tuning-modal-subtitle").textContent = isGlobal ? "Used by every game that has no setting of its own" : pkg;
  const badge = document.getElementById("tuning-modal-engine-badge");
  if (badge) badge.textContent = isGlobal ? "Defaults" : (info.is_vr ? `${info.engine || "VR"}` : "2D app");

  if (!isGlobal && !info.configurable) {
    body.innerHTML = `<p class="tuning-micro-note">These settings apply to Android apps running in Lepton. Windows and Linux apps have none.</p>`;
    document.getElementById("tuning-presets").style.display = "none";
    document.getElementById("btn-save-tuning").style.display = "none";
    modal.classList.add("open");
    return;
  }
  document.getElementById("btn-save-tuning").style.display = "";

  const specs = visibleTuningSpecs(info, isGlobal);
  const bridgeSpecs = specs.filter(s => s.needs_framebridge);
  const leptonSpecs = specs.filter(s => !s.needs_framebridge);
  const bridgeInactive = !isGlobal && !info.framebridge;
  const requirement = info.hand_tracking_requirement || "none";

  let html = "";
  if (!isGlobal) {
    html += `<div id="tuning-compat"></div>`;
  }
  if (leptonSpecs.length) {
    html += `<h3 class="tuning-section-title">${isGlobal || info.is_vr ? "Lepton" : "Window"}</h3>
      <div class="tuning-grid">${leptonSpecs.map(s => renderTuningControl(s, info[s.key], false)).join("")}</div>`;
  }
  if (bridgeSpecs.length) {
    const note = isGlobal
      ? "Read by games ported with FramePort (they contain the FrameBridge adapter). Other games ignore them."
      : bridgeInactive
        ? "This build has no FrameBridge adapter, so nothing reads these settings. They take effect once you install a FramePort-ported build of the game."
        : requirement === "required"
          ? "This game requires hand tracking. On the Frame the hand skeleton comes from the controllers' finger sensors, so keep holding them."
          : "Read by the FrameBridge adapter inside this game.";
    html += `<h3 class="tuning-section-title">Game (FrameBridge)</h3>
      <p class="tuning-section-note${bridgeInactive ? " warn" : ""}">${escapeHtml(note)}</p>
      <div class="tuning-grid">${bridgeSpecs.map(s => renderTuningControl(s, info[s.key], bridgeInactive)).join("")}</div>`;
  }
  body.innerHTML = html;
  if (!isGlobal) renderCompatNotice(document.getElementById("tuning-compat"), info.compat);

  const presets = document.getElementById("tuning-presets");
  if (presets) {
    const show = bridgeSpecs.length > 0 && !bridgeInactive;
    presets.style.display = show ? "" : "none";
    presets.innerHTML = show ? Object.values(state.tuningPresets || {}).map(p =>
      `<button type="button" class="tuning-preset-chip" title="${escapeHtml(p.description)}" onclick="selectTuningPreset('${p.id}')">${escapeHtml(p.name)}</button>`).join("") : "";
  }

  modal.classList.add("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

function closeTuningModal() {
  const modal = document.getElementById("tuning-modal");
  if (modal) modal.classList.remove("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

function openGlobalTuningModal() {
  openTuningModal("__global__");
}

function selectTuningPreset(presetId) {
  const preset = (state.tuningPresets || {})[presetId];
  if (!preset) return;
  Object.entries(preset.settings).forEach(([key, value]) => {
    const spec = state.tuningSchema.find(s => s.key === key);
    const el = document.getElementById(tuningInputId(key));
    if (!spec || !el) return;
    if (spec.type === "bool") el.checked = !!value; else el.value = value;
    onTuningInput(key);
  });
  document.querySelectorAll(".tuning-preset-chip").forEach(chip =>
    chip.classList.toggle("active", chip.getAttribute("onclick").includes(`'${presetId}'`)));
}

async function saveGameTuningFromModal() {
  const btn = document.getElementById("btn-save-tuning");
  const isGlobal = state.tuningTarget === "__global__";
  const settings = {};
  visibleTuningSpecs(state.tuningInfo || {}, isGlobal).forEach(spec => {
    const value = readTuningValue(spec);
    if (value !== undefined) settings[spec.key] = value;
  });

  if (btn) { btn.disabled = true; btn.textContent = "Saving..."; }
  try {
    const res = isGlobal
      ? await apiPost("/api/tuning/global", { settings })
      : await apiPost("/api/installed/tuning", { package: state.tuningTarget, settings });
    if (res.success) {
      showToast(isGlobal ? "Default settings saved." : "Settings saved. They apply the next time the game starts.", "success");
      closeTuningModal();
      loadInstalled();
      loadHandStatus();
    } else {
      showToast(res.error || "Could not save settings", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Save"; }
  }
}

window.openTuningModal = openTuningModal;
window.closeTuningModal = closeTuningModal;
window.openSettingsModal = openTuningModal;
window.openGlobalTuningModal = openGlobalTuningModal;
window.selectTuningPreset = selectTuningPreset;
window.onTuningInput = onTuningInput;
window.saveGameTuningFromModal = saveGameTuningFromModal;

// === Quest game porting (FramePort on this headset) and self-test ===
state.porting = { status: null, jobId: null, timer: null, launchAfter: null };

async function loadPortingStatus() {
  const badge = document.getElementById("porting-badge");
  const detail = document.getElementById("porting-detail");
  const setupBtn = document.getElementById("btn-porting-setup");
  const logBtn = document.getElementById("btn-porting-log");
  if (!badge) return null;
  try {
    const st = await apiGet("/api/porting/status");
    state.porting.status = st;
    const ready = st.installed && st.tools_ready;
    const settingUp = st.job && st.job.kind !== "port";
    badge.textContent = settingUp ? (st.job.kind === "update" ? "Updating..." : "Setting up...")
      : st.job ? "Porting..." : ready ? "Ready" : st.setup_error ? "Setup failed" : st.auto_setup ? "Sets up by itself" : "Not set up";
    badge.style.color = ready ? "var(--accent-emerald)" : "var(--text-muted)";
    const waiting = (st.pending || []).map(g => g.title);
    const parts = [];
    if (st.installed) parts.push(`FramePort ${st.version}${ready ? " with Java, OVRPort and apksigner." : "; its tools still need to be downloaded."}`);
    if (st.limited) parts.push(st.limited);
    if (!ready && !st.job && st.setup_error) parts.push(`The last setup attempt failed: ${st.setup_error} FrameLoad tries again later, or press Set Up Now.`);
    else if (!ready && !st.job && st.auto_setup) parts.push("The tools are downloaded in the background shortly after FrameLoad starts, or as soon as a game needs them.");
    if (waiting.length) parts.push(`Waiting to be ported after setup: ${waiting.join(", ")}.`);
    if (detail) detail.textContent = parts.join(" ");
    const autoCheck = document.getElementById("porting-auto-check");
    if (autoCheck) autoCheck.checked = st.auto !== false;
    const setupCheck = document.getElementById("porting-setup-check");
    if (setupCheck) setupCheck.checked = st.auto_setup !== false;
    if (setupBtn) {
      setupBtn.style.display = ready ? "none" : "";
      setupBtn.disabled = !!st.job;
    }
    if (st.job) {
      state.porting.jobId = st.job.id;
      if (logBtn) logBtn.style.display = "";
    }
    return st;
  } catch (e) {
    badge.textContent = "Unavailable";
    return null;
  }
}

function openPortingModal() {
  const modal = document.getElementById("porting-modal");
  if (modal) modal.classList.add("open");
  pollPortingJob();
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

// Closing only hides the dialog: the job keeps running and FrameLoad keeps following it.
function closePortingModal() {
  const modal = document.getElementById("porting-modal");
  if (modal) modal.classList.remove("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

function formatElapsed(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function togglePortingDetails(show) {
  const log = document.getElementById("porting-modal-log");
  const btn = document.getElementById("porting-modal-details");
  if (!log) return;
  const open = typeof show === "boolean" ? show : log.style.display === "none";
  log.style.display = open ? "" : "none";
  if (btn) btn.textContent = open ? "Hide Details" : "Show Details";
  if (open) log.scrollTop = log.scrollHeight;
}
window.togglePortingDetails = togglePortingDetails;

function portingJobTitle(job) {
  if (job.kind === "setup") return "Getting the porting tools";
  if (job.kind === "update") return "Updating the porting tools";
  const game = (state.installed || []).find(g => g.package === job.package);
  return job.package ? `Porting ${game ? game.title : job.package}` : "Porting the games that need it";
}

function renderPortingJob(job) {
  const el = id => document.getElementById(`porting-modal-${id}`);
  if (!el("title")) return;
  const active = job.status === "running" || job.status === "queued";
  const percent = job.status === "done" ? 100 : Math.max(0, Math.min(99, job.progress || 0));
  const title = portingJobTitle(job);

  state.activity.port = active ? {
    label: `${job.kind === "port" ? "Porting" : "Getting porting tools"}${job.kind === "port" && job.package ? " " + ((state.installed || []).find(g => g.package === job.package) || {}).title || "" : ""}`.trim(),
    percent, queued: job.status === "queued",
  } : null;
  renderShellStatus();

  // The header chip shows the job while the dialog is closed.
  const chip = document.getElementById("header-porting");
  if (chip) {
    chip.style.display = active ? "" : "none";
    chip.textContent = job.status === "queued" ? "Porting: waiting"
      : `${job.kind === "port" ? "Porting" : "Porting tools"} ${percent}%`;
  }

  el("title").textContent = title;
  el("icon").className = `job-icon ${job.status}`;
  el("bar").className = `job-bar ${job.status}`;
  el("bar").setAttribute("aria-valuenow", percent);
  el("fill").style.width = `${job.status === "queued" ? 100 : percent}%`;
  el("percent").textContent = job.status === "queued" ? "Waiting" : `${percent}%`;
  el("elapsed").textContent = job.status === "queued" ? "" : formatElapsed(job.elapsed);
  el("close").textContent = active ? "Run in Background" : "Close";

  const ported = (job.result && job.result.ported) || [];
  const label = (job.result && job.result.compat && job.result.compat.label) || "Ready";
  el("status").textContent = job.status === "queued" ? "Waiting for another porting job to finish."
    : job.status === "running"
      ? (state.porting.launchAfter ? "The game starts by itself when this is done. You can close this window."
        : "This takes a few minutes. You can close this window; it keeps going.")
      : job.status === "error" ? "This did not work."
        : job.kind === "port" ? `${label}. The game is in your library.`
          : ported.length ? `The porting tools are ready, and ${ported.length} waiting game(s) were ported.`
            : "The porting tools are ready.";

  // Steps and result change rarely; rebuilding them on every poll would steal the focus.
  const signature = `${job.id}:${job.status}:${job.step}:${state.porting.launchAfter || ""}`;
  if (state.porting.rendered !== signature) {
    state.porting.rendered = signature;
    el("steps").innerHTML = (job.steps || []).map((text, i) => {
      const st = job.status === "done" ? "done" : job.status === "queued" ? "todo"
        : i < job.step ? "done" : i > job.step ? "todo" : job.status === "error" ? "failed" : "active";
      return `<li class="${st}"><span class="job-step-mark"></span><span>${escapeHtml(text)}</span></li>`;
    }).join("");

    const result = el("result");
    if (job.status === "error") {
      result.className = "job-result failed";
      result.innerHTML = `<strong>What went wrong</strong><span>${escapeHtml(job.error || "Unknown error")}</span>`;
      result.style.display = "";
      togglePortingDetails(true);
    } else if (job.status === "done" && job.kind === "port" && job.package && !state.porting.launchAfter) {
      result.className = "job-result done";
      result.innerHTML = `<span>Ported and installed.</span>
        <button type="button" class="btn-primary compact" onclick="closePortingModal(); launchGame(${jsArg(job.package)})">Play Now</button>`;
      result.style.display = "";
    } else {
      result.style.display = "none";
    }
    if (window.gamepadNav) window.gamepadNav.updateFocusables();
  }

  const log = el("log");
  const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
  log.textContent = (job.log || []).join("\n");
  if (atEnd) log.scrollTop = log.scrollHeight;
}

// The server names its running porting job with every downloads poll, so jobs it starts by itself
// (after an install, or the first setup) show up without anyone opening a dialog.
function notePortingJob(id) {
  if (!id || state.porting.watching === id) return;
  state.porting.jobId = id;
  pollPortingJob();
}

async function pollPortingJob() {
  clearTimeout(state.porting.timer);
  const id = state.porting.jobId;
  if (!id) return;
  try {
    const job = await apiGet(`/api/porting/jobs/${encodeURIComponent(id)}`);
    if (state.porting.jobId !== id) return;  // another job took over while this answer was on its way
    renderPortingJob(job);
    if (job.status === "running" || job.status === "queued") {
      state.porting.watching = id;
      state.porting.timer = setTimeout(pollPortingJob, 1000);
      return;
    }
    state.porting.watching = null;
    if (state.porting.announced === id) return;  // reopening the dialog only shows the result again
    state.porting.announced = id;
    showToast(job.status === "done" ? `${portingJobTitle(job)}: finished.` : `${portingJobTitle(job)} failed: ${job.error}`,
      job.status === "done" ? "success" : "error");
    loadPortingStatus();
    await loadInstalled();
    // Launch asked for this: start the game now that it is ported.
    const wanted = state.porting.launchAfter;
    if (wanted) {
      const ported = (job.kind === "port" && job.package === wanted) || (job.result && (job.result.ported || []).includes(wanted));
      if (job.status === "done" && ported) {
        state.porting.launchAfter = null;
        closePortingModal();
        launchGame(wanted);
      } else if (job.kind === "port" || job.status !== "done") {
        state.porting.launchAfter = null;
        renderPortingJob(job);
      } else if (state.porting.status && state.porting.status.job) {
        state.porting.jobId = state.porting.status.job.id;  // setup finished; the port itself is next
        state.porting.timer = setTimeout(pollPortingJob, 1000);
      }
    }
  } catch (e) {
    const status = document.getElementById("porting-modal-status");
    if (status) status.textContent = `Could not read progress: ${e.message}`;
    state.porting.watching = null;
  }
}

async function startPortingJob(url, body) {
  try {
    const res = await apiPost(url, body);
    state.porting.jobId = res.job.id;
    const logBtn = document.getElementById("btn-porting-log");
    if (logBtn) logBtn.style.display = "";
    openPortingModal();
    loadPortingStatus();
  } catch (e) {
    showToast(e.message, "error");
  }
}

async function setPortingAuto(enabled) {
  try {
    await apiPost("/api/porting/settings", { auto: !!enabled });
    showToast(enabled ? "Quest games are ported automatically after installing." : "Automatic porting is off. Port & Play on a game ports it when you ask.", "info");
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.setPortingAuto = setPortingAuto;

async function setPortingAutoSetup(enabled) {
  try {
    await apiPost("/api/porting/settings", { auto_setup: !!enabled });
    showToast(enabled ? "FrameLoad downloads and updates the porting tools by itself." : "Automatic download is off. Use Set Up Now when you want the tools.", "info");
    loadPortingStatus();
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.setPortingAutoSetup = setPortingAutoSetup;

function startPortingSetup() {
  return startPortingJob("/api/porting/setup", {});
}

async function portGame(pkg) {
  const st = state.porting.status || await loadPortingStatus();
  if (!st || !st.installed || !st.tools_ready) {
    // Not ready yet: fetch the tools now; the waiting game is ported when that finishes.
    showToast("Getting the porting tools first (one time). The game is ported right after.", "info");
    return startPortingJob("/api/porting/setup", { package: pkg });
  }
  return startPortingJob("/api/porting/port", { package: pkg });
}

// Nobody has to run the self-test by hand: it runs once when the dashboard opens, and the banner
// appears only for failures on a real Steam Frame.
function renderHealthBanner(report) {
  const banner = document.getElementById("health-banner");
  const list = document.getElementById("health-banner-list");
  if (!banner || !list) return;
  const failures = (report && report.on_frame) ? report.checks.filter(c => c.state === "fail") : [];
  list.innerHTML = failures.map(c => `<li class="compat-issue error">${escapeHtml(c.name)}: ${escapeHtml(c.detail)}</li>`).join("");
  banner.style.display = failures.length ? "block" : "none";
}

async function checkHealthOnce() {
  try {
    renderHealthBanner(await apiGet("/api/system/doctor"));
  } catch (e) {
    console.error("Self-test failed to run:", e);
  }
}
window.renderHealthBanner = renderHealthBanner;

async function runDoctor() {
  const badge = document.getElementById("doctor-badge");
  const results = document.getElementById("doctor-results");
  if (!results) return;
  if (badge) badge.textContent = "Running...";
  try {
    const report = await apiGet("/api/system/doctor");
    renderHealthBanner(report);
    const labels = { ok: "All good", warn: "Needs attention", fail: "Problems found" };
    if (badge) {
      badge.textContent = labels[report.state] || report.state;
      badge.style.color = report.state === "ok" ? "var(--accent-emerald)" : report.state === "warn" ? "var(--accent-amber)" : "var(--accent-danger)";
    }
    results.innerHTML = report.checks.map(c => `
      <div class="doctor-row">
        <span class="doctor-state ${escapeHtml(c.state)}">${escapeHtml(c.state)}</span>
        <span><span class="doctor-name">${escapeHtml(c.name)}</span><br><span class="doctor-detail">${escapeHtml(c.detail)}</span></span>
      </div>`).join("");
  } catch (e) {
    if (badge) badge.textContent = "Failed";
    results.textContent = e.message;
  }
}

window.loadPortingStatus = loadPortingStatus;
window.openPortingModal = openPortingModal;
window.closePortingModal = closePortingModal;
window.startPortingSetup = startPortingSetup;
window.portGame = portGame;
window.runDoctor = runDoctor;

// === Steam library state ===
async function loadSteamStatus() {
  const banner = document.getElementById("steam-banner");
  if (!banner) return;
  try {
    const st = await apiGet("/api/steam/status");
    const names = st.pending || [];
    banner.style.display = st.restart_needed ? "block" : "none";
    if (!st.restart_needed) return;
    document.getElementById("steam-banner-title").textContent =
      names.length === 1 ? "1 new game is not in your Steam library yet" : `${names.length} new games are not in your Steam library yet`;
    document.getElementById("steam-banner-text").textContent =
      `${names.join(", ")}. Steam loads new entries when it starts. You can already start them from FrameLoad's library with Launch.`;
    const btn = document.getElementById("steam-restart-btn");
    if (btn) btn.style.display = st.can_restart ? "" : "none";
  } catch (e) {
    banner.style.display = "none";
  }
}

async function restartSteam() {
  if (!await confirmDialog("Restart Steam now?",
    "This closes FrameLoad's window and any running game. Steam comes back by itself with the new games in your library.",
    { yes: "Restart Steam" })) return;
  try {
    const res = await apiPost("/api/steam/restart", {});
    showToast(res.success ? res.message : res.error, res.success ? "success" : "error");
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.restartSteam = restartSteam;

// === Phone & PC access ===
async function loadAccess() {
  const list = document.getElementById("access-devices");
  const button = document.getElementById("btn-access-code");
  const address = document.getElementById("access-address");
  if (!list) return;
  try {
    const data = await apiGet("/api/access/devices");
    if (button) button.style.display = data.local ? "" : "none";
    if (address) {
      address.textContent = data.local
        ? `On the other device, open http://<this headset's IP address>:${location.port || 80}. The IP address is shown in the headset's network settings.`
        : "You are connected from another device. New devices are approved on the headset.";
    }
    list.innerHTML = (data.devices || []).length
      ? data.devices.map(d => `
          <div class="doctor-row" style="grid-template-columns:1fr auto;">
            <span><span class="doctor-name">${escapeHtml(d.label)}</span><br><span class="doctor-detail">paired ${new Date(d.created * 1000).toLocaleDateString()}</span></span>
            ${data.local ? `<button class="btn-secondary compact" onclick="removePairedDevice(${jsArg(d.id)})">Remove</button>` : ""}
          </div>`).join("")
      : `<p class="tuning-micro-note">No other device is paired.</p>`;
  } catch (e) {
    list.textContent = "";
  }
}

async function showPairingCode() {
  try {
    const res = await apiPost("/api/access/code", {});
    document.getElementById("access-code").textContent = res.code;
    document.getElementById("access-code-box").style.display = "block";
    setTimeout(() => {
      const box = document.getElementById("access-code-box");
      if (box) box.style.display = "none";
      loadAccess();
    }, res.expires_in * 1000);
  } catch (e) {
    showToast(e.message, "error");
  }
}

async function removePairedDevice(id) {
  try {
    await apiPost("/api/access/revoke", { id });
    loadAccess();
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.loadAccess = loadAccess;
window.showPairingCode = showPairingCode;
window.removePairedDevice = removePairedDevice;

// === File browser and upload ===
state.files = { path: "" };

async function openFileBrowser(path = "") {
  const modal = document.getElementById("files-modal");
  const list = document.getElementById("files-list");
  if (!modal || !list) return;
  try {
    const data = await apiGet(`/api/files?path=${encodeURIComponent(path)}`);
    state.files.path = data.path;
    document.getElementById("files-path").textContent = data.path || "Places";
    document.getElementById("files-use-folder").style.display = data.path ? "" : "none";
    const rows = [];
    if (data.path) {
      rows.push(`<button type="button" class="file-row is-dir" onclick="openFileBrowser(${jsArg(data.parent || "")})"><span class="file-kind">Up</span><span class="file-name">..</span></button>`);
    }
    data.entries.forEach(e => {
      rows.push(e.is_dir
        ? `<button type="button" class="file-row is-dir" onclick="openFileBrowser(${jsArg(e.path)})"><span class="file-kind">Folder</span><span class="file-name">${escapeHtml(e.name)}</span></button>`
        : `<button type="button" class="file-row" onclick="chooseBrowsedFile(${jsArg(e.path)})"><span class="file-kind">${escapeHtml(e.name.split(".").pop())}</span><span class="file-name">${escapeHtml(e.name)}</span><span class="file-size">${formatBytes(e.size)}</span></button>`);
    });
    list.innerHTML = rows.join("") || `<p class="tuning-micro-note" style="padding:14px;">Nothing installable here.</p>`;
    if (data.truncated) list.insertAdjacentHTML("beforeend", `<p class="tuning-micro-note" style="padding:10px 14px;">Only the first 500 entries are shown.</p>`);
    modal.classList.add("open");
    if (window.gamepadNav) window.gamepadNav.updateFocusables();
  } catch (e) {
    showToast(e.message, "error");
  }
}

function closeFileBrowser() {
  const modal = document.getElementById("files-modal");
  if (modal) modal.classList.remove("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

function chooseBrowsedFile(path) {
  document.getElementById("sideload-apk-path").value = path;
  closeFileBrowser();
  inspectSideloadPath();
}

function chooseBrowsedFolder() {
  if (state.files.path) chooseBrowsedFile(state.files.path);
}

function uploadOneFile(session, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/upload?session=${session}&name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(event.loaded); };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) { /* not JSON */ }
      if (xhr.status === 200) resolve(data); else reject(new Error(data.error || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("The connection to the headset was lost."));
    xhr.send(file);
  });
}

async function uploadSelectedFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const status = document.getElementById("upload-status");
  const track = document.getElementById("upload-progress");
  const fill = document.getElementById("upload-progress-fill");
  const total = files.reduce((sum, f) => sum + f.size, 0);
  const session = Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, "0")).join("");
  let done = 0;
  let last = null;
  if (track) track.style.display = "block";
  try {
    for (const file of files) {
      last = await uploadOneFile(session, file, (loaded) => {
        const pct = Math.round(((done + loaded) / Math.max(total, 1)) * 100);
        if (fill) fill.style.width = `${pct}%`;
        if (status) status.textContent = `Uploading ${file.name}... ${pct}%`;
      });
      done += file.size;
    }
    if (status) status.textContent = `Received ${files.length} file(s), ${formatBytes(total)}.`;
    // One file: install that file. Several (an APK with its OBB): install the folder they landed in.
    document.getElementById("sideload-apk-path").value = files.length === 1 ? last.path : last.folder;
    inspectSideloadPath();
  } catch (e) {
    if (status) status.textContent = "";
    showToast(e.message, "error");
  } finally {
    if (track) track.style.display = "none";
    if (fill) fill.style.width = "0%";
    const input = document.getElementById("sideload-upload-input");
    if (input) input.value = "";
  }
}
window.openFileBrowser = openFileBrowser;
window.closeFileBrowser = closeFileBrowser;
window.chooseBrowsedFile = chooseBrowsedFile;
window.chooseBrowsedFolder = chooseBrowsedFolder;
window.uploadSelectedFiles = uploadSelectedFiles;

// === Launch log ===
async function openLogModal(pkg) {
  const modal = document.getElementById("log-modal");
  if (!modal) return;
  try {
    const log = await apiGet(`/api/installed/log/${encodeURIComponent(pkg)}`);
    const game = (state.installed || []).find(g => g.package === pkg);
    document.getElementById("log-modal-title").textContent = `${game ? game.title : pkg} - Launch Log`;
    document.getElementById("log-findings").innerHTML = (log.findings || []).map(f =>
      `<div class="log-finding ${escapeHtml(f.severity)}"><strong>${escapeHtml(f.title)}</strong><span>${escapeHtml(f.advice)}</span></div>`).join("");
    const lines = document.getElementById("log-lines");
    lines.style.display = log.exists ? "" : "none";
    lines.textContent = (log.truncated ? "(earlier lines not shown)\n" : "") + (log.lines || []).join("\n");
    modal.classList.add("open");
    lines.scrollTop = lines.scrollHeight;
    if (window.gamepadNav) window.gamepadNav.updateFocusables();
  } catch (e) {
    showToast(e.message, "error");
  }
}

function closeLogModal() {
  const modal = document.getElementById("log-modal");
  if (modal) modal.classList.remove("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}
window.openLogModal = openLogModal;
window.closeLogModal = closeLogModal;

// === Installs requested by a frameload:// link ===
state.link = { current: null, answered: new Set() };

function offerPendingLink(links) {
  const modal = document.getElementById("link-modal");
  if (!modal || state.link.current) return;
  const next = links.find(l => !state.link.answered.has(l.id));
  if (!next) return;
  state.link.current = next;
  document.getElementById("link-title").textContent = next.title;
  document.getElementById("link-source").textContent = next.kind === "download" ? `From ${next.host}: ${next.url}` : `File on this headset: ${next.path}`;
  modal.classList.add("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

async function answerLink(install) {
  const link = state.link.current;
  const modal = document.getElementById("link-modal");
  if (!link) return;
  state.link.answered.add(link.id);
  state.link.current = null;
  if (modal) modal.classList.remove("open");
  try {
    const res = await apiPost(install ? "/api/links/confirm" : "/api/links/dismiss", { id: link.id });
    if (install) {
      showToast(res.action === "sideload" ? "Installed." : "Download started.", "success");
      loadInstalled();
    }
  } catch (e) {
    showToast(e.message, "error");
  }
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}
window.answerLink = answerLink;

// === Dashboard behaviour shared by every tab ===

// Asks a yes/no question in the page. Resolves true for yes; Back, Cancel and a click outside mean no.
function confirmDialog(title, text = "", options = {}) {
  const modal = document.getElementById("confirm-modal");
  if (!modal) return Promise.resolve(window.confirm(text ? `${title}\n\n${text}` : title));
  const yes = document.getElementById("confirm-yes");
  const no = document.getElementById("confirm-no");
  document.getElementById("confirm-title").textContent = title;
  const body = document.getElementById("confirm-text");
  body.textContent = text;
  body.style.display = text ? "" : "none";
  yes.textContent = options.yes || "OK";
  no.textContent = options.no || "Cancel";
  yes.className = options.danger ? "btn-danger" : "btn-primary";
  return new Promise(resolve => {
    const finish = (answer) => {
      modal.classList.remove("open");
      yes.onclick = no.onclick = modal.onclick = null;
      if (window.gamepadNav) window.gamepadNav.updateFocusables();
      resolve(answer);
    };
    yes.onclick = () => finish(true);
    no.onclick = () => finish(false);
    modal.onclick = (e) => { if (e.target === modal) finish(false); };
    modal.classList.add("open");
    if (window.gamepadNav) window.gamepadNav.updateFocusables();
    (options.danger ? no : yes).focus({ preventScroll: true });
  });
}
window.confirmDialog = confirmDialog;

function clearLibrarySearch() {
  state.libraryQuery = "";
  syncSearchBox();
  renderInstalledGrid();
}
window.clearLibrarySearch = clearLibrarySearch;

function searchCatalogInstead() {
  state.catalog.query = state.libraryQuery || "";
  state.catalog.page = 1;
  state.libraryQuery = "";
  goToTab("catalog");
}
window.searchCatalogInstead = searchCatalogInstead;

function renderDownloadsBadge() {
  const badge = document.getElementById("tab-downloads-count");
  if (!badge) return;
  const finished = ["completed", "canceled", "cancelled", "failed", "error"];
  const busy = (state.downloads || []).filter(t => !finished.includes(t.status)).length;
  badge.textContent = busy;
  badge.style.display = busy ? "" : "none";
}

// The tab bar sticks right under the header, whose height changes when its chips wrap.
function syncHeaderHeight() {
  const header = document.querySelector(".app-header");
  if (header) document.documentElement.style.setProperty("--header-h", `${Math.round(header.getBoundingClientRect().height)}px`);
}

// --- System > Controller Test: what the controllers send to this page ---
state.inputTest = { timer: null };

function renderControllerTest() {
  const out = document.getElementById("input-test-output");
  if (!out || !window.FrameLoadInput) return;
  const snap = window.FrameLoadInput.snapshot();
  const ago = (event) => `${Math.max(0, (Date.now() - event.time) / 1000).toFixed(1)}s ago`;
  const row = (name, value) => `<div class="input-test-row"><span>${name}</span><span>${value}</span></div>`;
  const rows = [];
  if (!snap.gamepads.length) {
    rows.push(`<p class="tuning-micro-note">No controller is reporting as a gamepad yet. Press any button on a controller: a browser only shows a gamepad after its first button press. If none appears, the headset sends pointer and scroll input only; the arrows at the right edge of the window scroll in that case.</p>`);
  }
  snap.gamepads.forEach((pad, i) => {
    rows.push(row(`Gamepad ${i + 1}`, `${escapeHtml(pad.id)} (${escapeHtml(pad.mapping)}${pad.hand ? ", " + escapeHtml(pad.hand) : ""})`));
    rows.push(row("Sticks / axes", pad.axes.map(a => `<code class="${Math.abs(a) > 0.2 ? "on" : ""}">${a.toFixed(2)}</code>`).join(" ") || "none"));
    rows.push(row("Buttons held", pad.pressed.length ? pad.pressed.map(b => `<code class="on">${b}</code>`).join(" ") : "none"));
  });
  const last = snap.last;
  rows.push(row("Last scroll", last.wheel ? `x ${last.wheel.deltaX}, y ${last.wheel.deltaY} (${ago(last.wheel)})` : "none yet"));
  rows.push(row("Last key", last.key ? `${escapeHtml(last.key.key)} (${ago(last.key)})` : "none yet"));
  rows.push(row("Last pointer press", last.pointer ? `${escapeHtml(last.pointer.type)} (${ago(last.pointer)})` : "none yet"));
  out.innerHTML = rows.join("");
}

function stopControllerTest() {
  if (!state.inputTest.timer) return;
  clearInterval(state.inputTest.timer);
  state.inputTest.timer = null;
  const btn = document.getElementById("btn-input-test");
  const badge = document.getElementById("input-test-badge");
  if (btn) btn.textContent = "Start Test";
  if (badge) { badge.textContent = "Off"; badge.style.color = "var(--text-muted)"; }
}

function toggleControllerTest() {
  if (state.inputTest.timer) return stopControllerTest();
  const out = document.getElementById("input-test-output");
  const btn = document.getElementById("btn-input-test");
  const badge = document.getElementById("input-test-badge");
  if (out) out.style.display = "";
  if (btn) btn.textContent = "Stop Test";
  if (badge) { badge.textContent = "Live"; badge.style.color = "var(--accent-emerald)"; }
  renderControllerTest();
  state.inputTest.timer = setInterval(renderControllerTest, 150);
}
window.toggleControllerTest = toggleControllerTest;

document.addEventListener("DOMContentLoaded", () => {
  syncHeaderHeight();
  window.addEventListener("resize", syncHeaderHeight);
  const header = document.querySelector(".app-header");
  if (header && window.ResizeObserver) new ResizeObserver(syncHeaderHeight).observe(header);
});

// --- Install location: asked like Steam does, but only when there is a real choice ---
function driveIcon(dev) {
  return dev.device_type === "microsd" ? "microSD" : dev.device_type === "usb" ? "USB" : "Internal";
}

// Resolves a drive id, undefined when there is nothing to choose (the server's default applies),
// or null when the player cancelled.
async function chooseInstallDrive(title, sizeBytes) {
  let devices = [];
  try {
    devices = (await apiGet("/api/storage/devices")).devices || [];
  } catch (e) {
    return undefined;
  }
  const need = Number(sizeBytes) || 0;
  const usable = devices.filter(d => d.supports_lepton !== false && (!need || d.free_bytes > need * 1.1));
  if (usable.length <= 1) return usable.length ? usable[0].id : undefined;

  const modal = document.getElementById("install-drive-modal");
  if (!modal) return undefined;
  const list = document.getElementById("install-drive-list");
  const makeDefault = document.getElementById("install-drive-default");
  const ok = document.getElementById("install-drive-ok");
  const cancel = document.getElementById("install-drive-cancel");
  document.getElementById("install-drive-title").textContent = `Install ${title}`;
  document.getElementById("install-drive-size").textContent = need
    ? `Needs about ${formatBytes(need * 1.1)} including room to unpack.` : "Choose where to install it.";
  makeDefault.checked = false;

  let chosen = (usable.find(d => d.is_default) || usable[0]).id;
  list.innerHTML = devices.map(dev => {
    const unusable = dev.supports_lepton === false ? `Cannot hold games (${escapeHtml(dev.filesystem || "unsupported format")})`
      : need && dev.free_bytes <= need * 1.1 ? "Not enough free space" : "";
    const used = Math.min(100, Math.max(0, dev.percent_used || 0));
    return `
      <button type="button" class="drive-choice${dev.id === chosen ? " selected" : ""}" role="radio"
              aria-checked="${dev.id === chosen}" data-drive="${escapeHtml(dev.id)}" ${unusable ? "disabled" : ""}>
        <span class="drive-choice-kind">${driveIcon(dev)}</span>
        <span class="drive-choice-main">
          <span class="drive-choice-name">${escapeHtml(dev.name)}${dev.is_default ? ' <span class="drive-choice-default">Default</span>' : ""}</span>
          <span class="drive-choice-bar"><span style="width:${used}%"></span></span>
          <span class="drive-choice-free">${unusable || `${escapeHtml(dev.free_formatted)} free of ${escapeHtml(dev.total_formatted)}`}</span>
        </span>
      </button>`;
  }).join("");

  return new Promise(resolve => {
    const select = (id) => {
      chosen = id;
      list.querySelectorAll(".drive-choice").forEach(b => {
        const on = b.dataset.drive === id;
        b.classList.toggle("selected", on);
        b.setAttribute("aria-checked", on);
      });
    };
    list.onclick = (e) => {
      const btn = e.target.closest(".drive-choice");
      if (btn && !btn.disabled) select(btn.dataset.drive);
    };
    const finish = async (answer) => {
      modal.classList.remove("open");
      list.onclick = ok.onclick = cancel.onclick = modal.onclick = null;
      if (window.gamepadNav) window.gamepadNav.updateFocusables();
      if (answer && makeDefault.checked) {
        try { await apiPost("/api/storage/default", { device_id: answer }); } catch (e) { /* still installs */ }
      }
      resolve(answer);
    };
    ok.onclick = () => finish(chosen);
    cancel.onclick = () => finish(null);
    modal.onclick = (e) => { if (e.target === modal) finish(null); };
    modal.classList.add("open");
    if (window.gamepadNav) window.gamepadNav.updateFocusables();
    ok.focus({ preventScroll: true });
  });
}
window.chooseInstallDrive = chooseInstallDrive;

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Number(bytes) || 0;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

// === Performance: CPU, memory, temperatures ===
state.perf = { history: [], timer: null, chipTimer: null };

function gb(bytes) {
  return (bytes / 1024 ** 3).toFixed(bytes >= 10 * 1024 ** 3 ? 0 : 1);
}

function sparkline(values, max = 100) {
  if (values.length < 2) return "";
  const w = 240, h = 40;
  const points = values.map((v, i) => `${(i / (values.length - 1) * w).toFixed(1)},${(h - Math.min(1, v / max) * (h - 2) - 1).toFixed(1)}`).join(" ");
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${points}"></polyline></svg>`;
}

function meter(label, percent, text, history) {
  const p = Math.max(0, Math.min(100, percent || 0));
  const level = p >= 90 ? "high" : p >= 70 ? "mid" : "";
  return `
    <div class="perf-row">
      <div class="perf-label"><span>${label}</span><strong>${escapeHtml(text)}</strong></div>
      <div class="perf-meter ${level}"><span style="width:${p}%"></span></div>
      ${history ? sparkline(history) : ""}
    </div>`;
}

function renderPerf(snap) {
  const chip = document.getElementById("header-perf");
  const mem = snap.memory;
  const hasData = snap.cpu_percent !== null && snap.cpu_percent !== undefined && mem;
  if (chip) {
    chip.style.display = hasData ? "" : "none";
    if (hasData) chip.textContent = `CPU ${Math.round(snap.cpu_percent)}% · RAM ${gb(mem.used)}/${gb(mem.total)} GB`;
  }
  const body = document.getElementById("perf-body");
  if (!body) return;
  if (!hasData) {
    body.innerHTML = `<p class="tuning-micro-note">This system does not report CPU and memory use.</p>`;
    return;
  }
  state.perf.last = snap;
  renderShellStatus();
  const memPct = mem.used / mem.total * 100;
  state.perf.history.push({ cpu: snap.cpu_percent, mem: memPct });
  state.perf.history = state.perf.history.slice(-60);
  const rows = [
    meter("CPU", snap.cpu_percent, `${Math.round(snap.cpu_percent)}% of ${snap.cores} cores`, state.perf.history.map(h => h.cpu)),
    meter("Memory", memPct, `${gb(mem.used)} of ${gb(mem.total)} GB`, state.perf.history.map(h => h.mem)),
  ];
  if (mem.swap_total) rows.push(meter("Swap", mem.swap_used / mem.swap_total * 100, `${gb(mem.swap_used)} of ${gb(mem.swap_total)} GB`));
  if (snap.gpu && snap.gpu.mhz) {
    rows.push(snap.gpu.busy !== undefined
      ? meter("GPU", snap.gpu.busy, `${snap.gpu.busy}% at ${snap.gpu.mhz} MHz`)
      : meter("GPU clock", snap.gpu.max_mhz ? snap.gpu.mhz / snap.gpu.max_mhz * 100 : 0, `${snap.gpu.mhz} of ${snap.gpu.max_mhz} MHz`));
  }
  const temps = snap.temps || {};
  const names = { cpu: "CPU", gpu: "GPU", memory: "Memory", battery: "Battery" };
  const chips = Object.keys(names).filter(k => temps[k] !== undefined)
    .map(k => `<span class="temp-chip ${temps[k] >= 85 ? "hot" : temps[k] >= 70 ? "warm" : ""}">${names[k]} ${Math.round(temps[k])}°C</span>`).join("");
  const pressure = snap.pressure && snap.pressure.some !== undefined
    ? `<p class="tuning-micro-note">Waiting for memory: ${snap.pressure.some.toFixed(1)}% of the last 10 s${snap.pressure.full >= 5 ? " (the headset is short of memory)" : ""}.</p>` : "";
  body.innerHTML = rows.join("") + (chips ? `<div class="temp-row">${chips}</div>` : "") + pressure;
}

async function loadPerf() {
  try {
    renderPerf(await apiGet("/api/system/perf"));
  } catch (e) { /* next round */ }
}

function startPerfLive() {
  clearInterval(state.perf.timer);
  loadPerf();
  state.perf.timer = setInterval(loadPerf, 2000);
}

function stopPerfLive() {
  clearInterval(state.perf.timer);
  state.perf.timer = null;
}

function openPerformanceCard() {
  goToTab("system");
  setTimeout(() => {
    const card = document.getElementById("perf-card");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
  }, 120);
}
window.openPerformanceCard = openPerformanceCard;

// === Freeze guard ===
state.guard = { seen: null };

function noteGuardEvent(event) {
  if (!event) return;
  if (state.guard.seen === null) {
    state.guard.seen = event.id;
    // Something happened while the dashboard was closed: still worth knowing for a while.
    if (Date.now() / 1000 - event.time > 600) return;
  } else if (event.id <= state.guard.seen) {
    return;
  }
  state.guard.seen = event.id;
  showToast(`${event.title || event.package} ${event.message}`, event.kind === "memory" ? "error" : "warning");
  refreshRunningGames();
}

async function loadGuard() {
  const badge = document.getElementById("guard-badge");
  if (!badge) return;
  try {
    const st = await apiGet("/api/guard");
    const cfg = st.settings;
    document.getElementById("guard-enabled").checked = cfg.enabled;
    document.getElementById("guard-limit").checked = cfg.memory_limit;
    document.getElementById("guard-frozen").checked = cfg.stop_frozen;
    document.getElementById("guard-frozen-seconds").value = String(cfg.frozen_seconds);
    badge.textContent = !cfg.enabled ? "Off" : st.running ? "Watching" : "Not on this system";
    badge.style.color = cfg.enabled && st.running ? "var(--accent-emerald)" : "var(--text-muted)";
    const games = document.getElementById("guard-games");
    games.innerHTML = (st.games || []).map(g => {
      const frames = g.fps ? `${Math.round(g.fps)} fps${g.frame_age !== null && g.frame_age > 15 ? `, last frame ${g.frame_age} s ago` : ""}` : "no frames yet";
      const limit = g.memory_limit === "applied" ? "memory limited" : g.memory_limit ? `limit not set: ${g.memory_limit}` : "";
      return `<div class="doctor-row"><span class="doctor-state ok">RUN</span><span><strong>${escapeHtml(g.title)}</strong> · ${escapeHtml(frames)}${limit ? ` · ${escapeHtml(limit)}` : ""}</span></div>`;
    }).join("");
    const events = document.getElementById("guard-events");
    events.innerHTML = (st.events || []).slice().reverse().slice(0, 4).map(e =>
      `<div class="log-finding ${e.kind === "memory" ? "error" : "warn"}"><strong>${escapeHtml(e.title || e.package)} · ${escapeHtml(timeAgo(e.time))}</strong><span>${escapeHtml(e.message)}</span></div>`).join("");
  } catch (e) {
    badge.textContent = "Unavailable";
  }
}

async function saveGuardSettings() {
  try {
    await apiPost("/api/guard/settings", {
      enabled: document.getElementById("guard-enabled").checked,
      memory_limit: document.getElementById("guard-limit").checked,
      stop_frozen: document.getElementById("guard-frozen").checked,
      frozen_seconds: Number(document.getElementById("guard-frozen-seconds").value),
    });
    showToast("Freeze guard settings saved.", "success");
    loadGuard();
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.saveGuardSettings = saveGuardSettings;

// === Keep awake ===
function renderKeepAwake(st) {
  const badge = document.getElementById("awake-badge");
  const text = document.getElementById("awake-status");
  if (!badge || !text) return;
  document.getElementById("awake-busy").checked = st.while_busy !== false;
  document.getElementById("awake-off").style.display = st.manual ? "" : "none";
  if (!st.available) {
    badge.textContent = "Not available";
    text.textContent = "This system has no sleep inhibitor (systemd-inhibit), so FrameLoad cannot keep it awake.";
    return;
  }
  badge.textContent = st.held ? "Awake" : "Sleep allowed";
  badge.style.color = st.held ? "var(--accent-emerald)" : "var(--text-muted)";
  text.textContent = st.held
    ? `Keeping the headset awake: ${st.reason}${st.manual && st.manual_until ? ` (until ${new Date(st.manual_until * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })})` : ""}.`
    : "The headset may sleep as usual. FrameLoad keeps it awake on its own while it downloads, installs or ports.";
}

async function loadKeepAwake() {
  try { renderKeepAwake(await apiGet("/api/power")); } catch (e) { /* next round */ }
}

async function setKeepAwake(hours) {
  try {
    const st = await apiPost("/api/power/keep-awake", { hours });
    renderKeepAwake({ ...st, while_busy: document.getElementById("awake-busy").checked });
    showToast(hours === 0 ? "The headset may sleep again." : hours < 0 ? "Staying awake until you switch it off." : "Staying awake for an hour.", "success");
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.setKeepAwake = setKeepAwake;

async function setKeepAwakeWhileBusy(enabled) {
  try {
    renderKeepAwake(await apiPost("/api/power/settings", { while_busy: !!enabled }));
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.setKeepAwakeWhileBusy = setKeepAwakeWhileBusy;

document.addEventListener("DOMContentLoaded", () => {
  loadPerf();
  state.perf.chipTimer = setInterval(() => { if (!state.perf.timer) loadPerf(); }, 5000);
  if (state.activeTab === "system") { startPerfLive(); loadGuard(); loadKeepAwake(); }
  setInterval(() => { if (state.activeTab === "system") { loadGuard(); loadKeepAwake(); } }, 6000);
});

// === Steam artwork, drawn by the dashboard ===
// Python's standard library cannot decode or scale images; a browser can. Every game whose Steam
// artwork is still a plain placeholder gets a poster, banner, hero, logo and icon drawn here from
// its own launcher icon, a downloaded cover and its title. The server stores them and copies them
// into each Steam user's grid folder (Steam shows them after a restart at the latest).
state.artwork = { done: new Set(), running: false, version: {} };

function libraryArt(game) {
  const url = game.thumbnail_url || "/static/assets/fallback_cover.svg";
  const v = state.artwork.version[game.package];
  return v ? `${url}${url.includes("?") ? "&" : "?"}v=${v}` : url;
}

function loadArtImage(url) {
  return new Promise(resolve => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img.naturalWidth ? img : null);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

function drawCover(ctx, img, x, y, w, h) {
  const scale = Math.max(w / img.naturalWidth, h / img.naturalHeight);
  const sw = w / scale, sh = h / scale;
  ctx.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, x, y, w, h);
}

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function artBackdrop(ctx, w, h, colors, img, blur) {
  const g = ctx.createLinearGradient(0, 0, w * 0.4, h);
  g.addColorStop(0, colors[0]);
  g.addColorStop(1, colors[1]);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  if (img) {
    ctx.save();
    ctx.filter = `blur(${blur}px) saturate(1.3)`;
    ctx.globalAlpha = 0.8;
    drawCover(ctx, img, -blur * 3, -blur * 3, w + blur * 6, h + blur * 6);
    ctx.restore();
  }
  const glow = ctx.createRadialGradient(w * 0.5, h * 0.35, 0, w * 0.5, h * 0.35, Math.max(w, h) * 0.75);
  glow.addColorStop(0, "rgba(255,255,255,0.10)");
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);
  const shade = ctx.createLinearGradient(0, 0, 0, h);
  shade.addColorStop(0, "rgba(4,8,18,0.10)");
  shade.addColorStop(1, "rgba(4,8,18,0.72)");
  ctx.fillStyle = shade;
  ctx.fillRect(0, 0, w, h);
}

const ART_FONT = 'system-ui, "Segoe UI", "Noto Sans", Roboto, sans-serif';

function wrapLines(ctx, text, maxWidth, maxLines) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width <= maxWidth || !line) {
      line = next;
    } else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    lines.length = maxLines;
    let last = lines[maxLines - 1];
    while (last.length > 1 && ctx.measureText(`${last}…`).width > maxWidth) last = last.slice(0, -1);
    lines[maxLines - 1] = `${last.trim()}…`;
  }
  return lines;
}

// Draws a title in as large a size as fits; returns the height used.
function drawTitle(ctx, text, x, y, maxWidth, size, maxLines, align, maxHeight = Infinity) {
  let lines;
  for (;; size -= 4) {
    ctx.font = `800 ${size}px ${ART_FONT}`;
    lines = wrapLines(ctx, text, maxWidth, maxLines);
    const fits = lines.every(l => ctx.measureText(l).width <= maxWidth) && lines.length * size * 1.12 <= maxHeight;
    if (fits || size <= 24) break;
  }
  ctx.save();
  ctx.fillStyle = "#ffffff";
  ctx.textAlign = align;
  ctx.textBaseline = "top";
  ctx.shadowColor = "rgba(0,0,0,0.55)";
  ctx.shadowBlur = size * 0.35;
  ctx.shadowOffsetY = size * 0.06;
  lines.forEach((l, i) => ctx.fillText(l, x, y + i * size * 1.12));
  ctx.restore();
  return lines.length * size * 1.12;
}

function drawTile(ctx, img, x, y, size, radius) {
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.5)";
  ctx.shadowBlur = size * 0.12;
  ctx.shadowOffsetY = size * 0.04;
  roundRectPath(ctx, x, y, size, size, radius);
  ctx.fillStyle = "rgba(255,255,255,0.06)";
  ctx.fill();
  ctx.restore();
  ctx.save();
  roundRectPath(ctx, x, y, size, size, radius);
  ctx.clip();
  drawCover(ctx, img, x, y, size, size);
  ctx.restore();
}

function artCanvas(w, h) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  return [canvas, canvas.getContext("2d")];
}

async function composeArtwork(game) {
  const info = game.artwork;
  if (!info || !info.pending || !info.pending.length) return false;
  const base = `/api/installed/artwork/${encodeURIComponent(game.package)}`;
  let icon = null, iconSlot = "";
  for (const slot of info.icon ? (info.icon_from === "icon" ? ["icon", "apk_icon"] : ["apk_icon", "icon"]) : []) {
    icon = await loadArtImage(`${base}?slot=${slot}`);
    if (icon) { iconSlot = slot; break; }
  }
  // Only the foreground layer of an adaptive icon: it needs a background behind it.
  const iconLayer = !!info.icon_layer && iconSlot === "apk_icon";
  const cover = info.cover ? await loadArtImage(`${base}?slot=poster`) : null;
  const art = cover || icon;
  const colors = info.colors || ["#123456", "#0a1020"];
  const title = game.title || game.package;
  const slots = {};

  for (const slot of info.pending) {
    if (slot === "poster") {
      const [c, ctx] = artCanvas(600, 900);
      artBackdrop(ctx, 600, 900, colors, art, 34);
      if (icon) drawTile(ctx, icon, 160, 200, 280, 56);
      drawTitle(ctx, title, 300, icon ? 560 : 330, 520, 60, 3, "center", 260);
      slots.poster = c.toDataURL("image/jpeg", 0.9);
    } else if (slot === "banner") {
      const [c, ctx] = artCanvas(920, 430);
      artBackdrop(ctx, 920, 430, colors, art, 26);
      if (art) drawTile(ctx, icon || cover, 64, 80, 270, 48);
      ctx.font = `800 58px ${ART_FONT}`;
      const x = art ? 380 : 460, width = art ? 480 : 800;
      const lines = Math.min(3, wrapLines(ctx, title, width, 3).length);
      drawTitle(ctx, title, x, 215 - lines * 58 * 0.56, width, 58, 3, art ? "left" : "center", 330);
      slots.banner = c.toDataURL("image/jpeg", 0.9);
    } else if (slot === "hero") {
      const [c, ctx] = artCanvas(1920, 620);
      artBackdrop(ctx, 1920, 620, colors, art, 50);
      if (cover) {  // the real cover, sharp on the right, fading into the backdrop
        const [layer, lctx] = artCanvas(820, 620);
        drawCover(lctx, cover, 0, 0, 820, 620);
        lctx.globalCompositeOperation = "destination-in";
        const fade = lctx.createLinearGradient(0, 0, 420, 0);
        fade.addColorStop(0, "rgba(0,0,0,0)");
        fade.addColorStop(1, "rgba(0,0,0,1)");
        lctx.fillStyle = fade;
        lctx.fillRect(0, 0, 820, 620);
        ctx.drawImage(layer, 1100, 0);
      }
      slots.hero = c.toDataURL("image/jpeg", 0.88);
    } else if (slot === "logo") {
      const [measure] = artCanvas(10, 10);
      const mctx = measure.getContext("2d");
      mctx.font = `800 120px ${ART_FONT}`;
      const lines = wrapLines(mctx, title, 1500, 2);
      const width = Math.ceil(Math.max(...lines.map(l => mctx.measureText(l).width))) + 60;
      const [c, ctx] = artCanvas(Math.min(1600, width), Math.ceil(lines.length * 134 + 50));
      drawTitle(ctx, title, c.width / 2, 25, c.width - 60, 120, 2, "center");
      slots.logo = c.toDataURL("image/png");
    } else if (slot === "icon") {
      const [c, ctx] = artCanvas(256, 256);
      if (icon && iconLayer) {
        roundRectPath(ctx, 8, 8, 240, 240, 52);
        ctx.save();
        ctx.clip();
        artBackdrop(ctx, 256, 256, colors, null, 0);
        const scale = Math.min(240 / icon.naturalWidth, 240 / icon.naturalHeight);
        const w = icon.naturalWidth * scale, h = icon.naturalHeight * scale;
        ctx.drawImage(icon, (256 - w) / 2, (256 - h) / 2, w, h);
        ctx.restore();
      } else if (icon) {
        const scale = Math.min(256 / icon.naturalWidth, 256 / icon.naturalHeight);
        const w = icon.naturalWidth * scale, h = icon.naturalHeight * scale;
        ctx.drawImage(icon, (256 - w) / 2, (256 - h) / 2, w, h);
      } else {
        roundRectPath(ctx, 8, 8, 240, 240, 52);
        ctx.save();
        ctx.clip();
        artBackdrop(ctx, 256, 256, colors, cover, 0);
        if (cover) drawCover(ctx, cover, 8, 8, 240, 240);
        ctx.restore();
        if (!cover) {
          const initials = title.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
          drawTitle(ctx, initials || "?", 128, 72, 200, 110, 1, "center");
        }
      }
      slots.icon = c.toDataURL("image/png");
    }
  }
  if (!Object.keys(slots).length) return false;
  const res = await apiPost(base, { slots });
  if (res.success) state.artwork.version[game.package] = Date.now();
  return !!res.success;
}

// One game at a time, quietly in the background, once per game per session.
async function composePendingArtwork() {
  if (state.artwork.running) return;
  state.artwork.running = true;
  let changed = false;
  try {
    for (const game of state.installed || []) {
      const pending = game.artwork && game.artwork.pending && game.artwork.pending.length;
      if (!pending || state.artwork.done.has(game.package)) continue;
      state.artwork.done.add(game.package);
      try {
        if (await composeArtwork(game)) changed = true;
      } catch (e) {
        console.warn("Could not draw artwork for", game.package, e);
      }
      await new Promise(r => setTimeout(r, 250));
    }
  } finally {
    state.artwork.running = false;
  }
  if (changed) renderInstalledGrid();
}

// === Store media: screenshots and a trailer from the app's own F-Droid metadata ===
state.media = { shots: [], index: 0 };

function youtubeId(url) {
  const m = String(url || "").match(/(?:youtube(?:-nocookie)?\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : "";
}

function renderAppMedia(game) {
  const box = document.getElementById("modal-media");
  if (!box) return;
  const shots = (game.screenshots || []).filter(u => /^https:\/\//.test(u));
  const video = youtubeId(game.video);
  state.media.shots = shots;
  if (!shots.length && !video) {
    box.style.display = "none";
    return;
  }
  const videoTile = video ? `
    <button type="button" class="media-tile media-video" onclick="playAppVideo(this, ${jsArg(video)})" aria-label="Play the trailer">
      <img src="https://i.ytimg.com/vi/${video}/hqdefault.jpg" alt="" loading="lazy" draggable="false">
      <span class="media-play" aria-hidden="true"></span>
    </button>` : "";
  box.innerHTML = `
    <div class="media-strip">
      ${videoTile}
      ${shots.map((url, i) => `
        <button type="button" class="media-tile" onclick="openMediaViewer(${i})" aria-label="Screenshot ${i + 1}">
          <img src="${escapeHtml(url)}" alt="" loading="lazy" draggable="false" onerror="this.closest('.media-tile').remove()">
        </button>`).join("")}
    </div>`;
  box.style.display = "";
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

function playAppVideo(tile, id) {
  const frame = document.createElement("iframe");
  frame.className = "media-frame";
  frame.src = `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`;
  frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
  frame.allowFullscreen = true;
  frame.title = "Trailer";
  tile.replaceWith(frame);
}
window.playAppVideo = playAppVideo;

function openMediaViewer(index) {
  const viewer = document.getElementById("media-viewer");
  if (!viewer || !state.media.shots.length) return;
  state.media.index = index;
  stepMediaViewer(0);
  viewer.classList.add("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}
window.openMediaViewer = openMediaViewer;

function stepMediaViewer(delta) {
  const shots = state.media.shots;
  if (!shots.length) return;
  state.media.index = (state.media.index + delta + shots.length) % shots.length;
  document.getElementById("media-viewer-img").src = shots[state.media.index];
  document.getElementById("media-viewer-count").textContent = `${state.media.index + 1} / ${shots.length}`;
}
window.stepMediaViewer = stepMediaViewer;

function closeMediaViewer() {
  const viewer = document.getElementById("media-viewer");
  if (viewer) viewer.classList.remove("open");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}
window.closeMediaViewer = closeMediaViewer;

// ==========================================================================
// Looks (System > Appearance). A look is a stylesheet, static/css/skins/<id>.css, plus, where it
// arranges things differently, a view registered by static/js/skins/<id>.js. The server writes the
// saved look into <html data-skin> so the page paints in it; ?skin=<id> previews one without saving.
// ==========================================================================
const SKINS = [
  { id: "a", name: "Big Picture", note: "Looks like SteamOS: tabs on top, Steam covers, button hints." },
  { id: "b", name: "Spatial", note: "A floating glass window with the navigation beside it." },
  { id: "c", name: "Showcase", note: "Your last game fills the screen, the library sits in one row." },
  { id: "d", name: "Neon", note: "The original FrameLoad look, refined." },
  { id: "e", name: "Command Center", note: "A sortable list beside a detail panel, for big libraries." },
  { id: "f", name: "Daylight", note: "Calm and very legible, in a light and a dark version." },
];
const SKIN_VIEWS = {};
state.activity = { port: null, download: null };

function currentSkin() {
  const id = document.documentElement.getAttribute("data-skin");
  return SKINS.some(k => k.id === id) ? id : "a";
}

function currentMode() {
  return document.documentElement.getAttribute("data-mode") === "dark" ? "dark" : "light";
}

// Called by each static/js/skins/<id>.js. A view may have: library(ctx), empty(ctx),
// status(ctx) (after device or activity changes), mount(ctx) and unmount() (on switching looks).
function registerSkin(id, view) {
  SKIN_VIEWS[id] = view || {};
  if (id === currentSkin()) {
    if (view && view.mount) view.mount(skinContext());
    if (state.installed) renderInstalledGrid();
    renderShellStatus();
  }
}
window.registerSkin = registerSkin;

const ICONS = {
  battery: '<rect x="2.5" y="7" width="17" height="10" rx="2.5"/><path d="M22 10.5v3"/><rect x="5" y="9.5" width="10" height="5" rx="1" fill="currentColor" stroke="none"/>',
  drive: '<rect x="3" y="4.5" width="18" height="6.5" rx="2"/><rect x="3" y="13" width="18" height="6.5" rx="2"/><path d="M7 7.75h.01M7 16.25h.01"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2.5"/><path d="M9.5 2.5v3M14.5 2.5v3M9.5 18.5v3M14.5 18.5v3M2.5 9.5h3M2.5 14.5h3M18.5 9.5h3M18.5 14.5h3"/>',
  download: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M4 19.5h16"/>',
  port: '<path d="M20 11a8 8 0 0 0-14.3-4.6L4 8.5M4 4v4.5h4.5M4 13a8 8 0 0 0 14.3 4.6L20 15.5M20 20v-4.5h-4.5"/>',
  play: '<path d="M8 5.2v13.6L19 12z" fill="currentColor" stroke="none"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" stroke="none"/>',
  settings: '<path d="M4 6.5h9M17 6.5h3M4 12h3M11 12h9M4 17.5h11M19 17.5h1"/><circle cx="15" cy="6.5" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17.5" r="2"/>',
  dots: '<circle cx="5.5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="18.5" cy="12" r="1.6" fill="currentColor"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  chevron: '<path d="m6.5 9.5 5.5 5.5 5.5-5.5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  update: '<path d="M12 20V9M7 13.5l5-5 5 5M5 4.5h14"/>',
  wifi: '<path d="M2.5 9a14 14 0 0 1 19 0M5.8 12.6a9.2 9.2 0 0 1 12.4 0M9 16.1a4.5 4.5 0 0 1 6 0"/><circle cx="12" cy="19.4" r="1.1" fill="currentColor" stroke="none"/>',
};
function icon(name, cls = "") {
  return `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
window.icon = icon;

// A specific artwork slot of an installed game: poster, banner, hero, logo, icon or apk_icon.
function artUrl(game, slot = "poster") {
  const base = `/api/installed/artwork/${encodeURIComponent(game.package)}`;
  const v = state.artwork && state.artwork.version[game.package];
  return slot === "poster" ? libraryArt(game) : `${base}?slot=${slot}${v ? `&v=${v}` : ""}`;
}

function deviceStatus() {
  const sys = state.system || {};
  const perf = (state.perf && state.perf.last) || {};
  const mem = perf.memory;
  return {
    battery: sys.battery ? sys.battery.percent : null,
    plugged: !!(sys.battery && sys.battery.plugged),
    freeGb: sys.storage ? sys.storage.free_gb : null,
    cpu: typeof perf.cpu_percent === "number" ? Math.round(perf.cpu_percent) : null,
    ramUsedGb: mem ? +(mem.used / 1024 ** 3).toFixed(1) : null,
    ramTotalGb: mem ? Math.round(mem.total / 1024 ** 3) : null,
  };
}

// Everything a look's view needs, so looks never reach into app.js's internals.
function skinContext() {
  return {
    state,
    root: document.getElementById("library-view"),
    navExtra: document.getElementById("nav-extra"),
    skin: currentSkin(),
    mode: currentMode(),
    games: state.installed || [],
    recent: recentGames(state.installed || []),
    activity: state.activity,
    device: deviceStatus(),
    esc: escapeHtml,
    arg: jsArg,
    icon,
    art: artUrl,
    played: playedLabel,
    playtime: formatPlaytime,
    ago: timeAgo,
    primaryButton: libraryPrimaryButton,
    updateFor: libraryUpdateFor,
    cardHtml: libraryCardHtml,
    sortSelect: () => {
      const options = [["recent", "Recently played"], ["name", "Name"], ["installed", "Recently installed"], ["size", "Size"]];
      return `<select class="select-styled compact library-sort-select" aria-label="Sort the library" onchange="setLibrarySort(this.value)">${options.map(([v, l]) => `<option value="${v}"${state.librarySort === v ? " selected" : ""}>${l}</option>`).join("")}</select>`;
    },
  };
}

function skinName(id) {
  return (SKINS.find(k => k.id === id) || SKINS[0]).name;
}

function applySkin(skin, mode) {
  const root = document.documentElement;
  const before = root.getAttribute("data-skin");
  root.setAttribute("data-skin", skin);
  root.setAttribute("data-mode", mode);
  const link = document.getElementById("skin-css");
  const href = `/static/css/skins/${skin}.css`;
  if (link && link.getAttribute("href") !== href) link.setAttribute("href", href);
  if (before !== skin) {
    const old = SKIN_VIEWS[before];
    if (old && old.unmount) old.unmount();
    const nav = document.getElementById("nav-extra");
    if (nav) nav.innerHTML = "";
    const view = SKIN_VIEWS[skin];
    if (view && view.mount) view.mount(skinContext());
  }
  if (state.installed) renderInstalledGrid();
  renderShellStatus();
  renderAppearance();
  if (typeof syncHeaderHeight === "function") setTimeout(syncHeaderHeight, 60);
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

async function saveAppearance(skin, mode, message) {
  if (document.documentElement.getAttribute("data-preview") === "1") {
    showToast("Previewing. Remove ?skin= from the address to keep a look.", "info");
    return;
  }
  try {
    await apiPost("/api/ui/appearance", { skin, daylight: mode });
    showToast(message, "success");
  } catch (e) {
    showToast(`Could not save the look: ${e.message}`, "error");
  }
}

function chooseSkin(skin) {
  if (skin === currentSkin()) return;
  applySkin(skin, currentMode());
  saveAppearance(skin, currentMode(), `${skinName(skin)} is now FrameLoad's look.`);
}
window.chooseSkin = chooseSkin;

function chooseDaylight(mode) {
  applySkin(currentSkin(), mode);
  saveAppearance(currentSkin(), mode, mode === "dark" ? "Daylight now uses its dark version." : "Daylight now uses its light version.");
}
window.chooseDaylight = chooseDaylight;

function renderAppearance() {
  const box = document.getElementById("appearance-options");
  if (!box) return;
  const cur = currentSkin();
  box.innerHTML = SKINS.map(k => `
    <button type="button" class="skin-tile${k.id === cur ? " on" : ""}" role="radio" aria-checked="${k.id === cur}" onclick="chooseSkin('${k.id}')">
      <span class="skin-thumb skin-thumb-${k.id}" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
      <span class="skin-text">
        <span class="skin-name">${escapeHtml(k.name)}${k.id === "a" ? '<em>Default</em>' : ""}</span>
        <span class="skin-note">${escapeHtml(k.note)}</span>
      </span>
    </button>`).join("");
  const modes = document.getElementById("daylight-mode");
  if (modes) {
    modes.hidden = cur !== "f";
    modes.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.mode === currentMode()));
  }
}

function noteDownloadActivity() {
  const active = (state.downloads || []).find(t => ["downloading", "decompressing", "installing"].includes(t.status));
  state.activity.download = active ? {
    label: `${active.status === "installing" ? "Installing" : active.status === "decompressing" ? "Unpacking" : "Downloading"} ${(active.game && active.game.name) || ""}`.trim(),
    percent: Math.max(0, Math.min(100, Number(active.progress_percent) || 0)),
    detail: active.status === "downloading" ? active.speed_formatted : "",
  } : null;
  renderShellStatus();
}

// The status dock and the controller-hint bar, filled for every look; the look decides whether and
// where they show. A look with its own status area gets status(ctx).
function renderShellStatus() {
  const dev = deviceStatus();
  const set = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  set("dock-battery", dev.battery == null ? "" : `${icon("battery")}<span>${dev.battery}%${dev.plugged ? " charging" : ""}</span>`);
  set("dock-storage", dev.freeGb == null ? "" : `${icon("drive")}<span>${dev.freeGb} GB free</span>`);
  set("dock-cpu", dev.cpu == null ? "" : `${icon("cpu")}<span>CPU ${dev.cpu}%</span>`);
  const act = state.activity.port || state.activity.download;
  const actHtml = act ? `${icon(state.activity.port ? "port" : "download", "act-icon")}<span class="act-label">${escapeHtml(act.label)}</span><span class="act-bar"><i style="width:${act.queued ? 100 : act.percent}%"></i></span><span class="act-pct">${act.queued ? "Waiting" : act.percent + "%"}</span>` : "";
  ["dock-activity", "hint-activity"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.hidden = !act;
    el.innerHTML = actHtml;
  });
  const view = SKIN_VIEWS[currentSkin()];
  if (view && view.status) view.status(skinContext());
}

function openActivity() {
  if (state.activity.port) openPortingModal();
  else goToTab("downloads");
}
window.openActivity = openActivity;

document.addEventListener("DOMContentLoaded", () => {
  renderAppearance();
  renderShellStatus();
});
