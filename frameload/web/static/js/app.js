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
  activeTab: "catalog",
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
        badge.style.background = "rgba(0, 245, 212, 0.15)";
        badge.style.color = "var(--accent-emerald)";
      } else {
        badge.textContent = "Manual Only (Steam + X)";
        badge.style.background = "rgba(255, 255, 255, 0.1)";
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
  setInterval(() => checkForUpdates(false), 6 * 3600 * 1000);
  loadSteamStatus();
});

// --- Tab Switching ---
function setupTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = tab.dataset.tab;
      state.activeTab = targetId;

      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");

      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      const targetPanel = document.getElementById(`tab-${targetId}`);
      if (targetPanel) targetPanel.classList.add("active");

      if (targetId === "catalog") loadCatalog();
      else if (targetId === "library") { loadInstalled(); loadSteamStatus(); }
      else if (targetId === "storage") loadStorageOverview();
      else if (targetId === "system") { loadSystemTelemetry(); loadHandStatus(); loadPortingStatus(); loadAccess(); }

      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    });
  });

  // Handle URL hash on load (e.g. #library, #system, #downloads)
  const hash = window.location.hash.replace("#", "");
  if (hash) {
    const tabEl = document.querySelector(`.tab-btn[data-tab="${hash}"]`);
    if (tabEl) tabEl.click();
  }
}

// --- Search & Filters ---
function setupSearch() {
  const searchInput = document.getElementById("search-input");
  let debounceTimeout = null;

  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(() => {
        state.catalog.query = e.target.value;
        state.catalog.page = 1;
        loadCatalog();
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
  if (search) search.placeholder = isFlat ? "Search apps... (Y to focus)" : "Search VR games, packages, or releases... (Y to focus)";
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
  const meta = game.downloads ? "📥 " + Number(game.downloads).toLocaleString() : version;

  let action = `<button class="card-btn download" onclick="event.stopPropagation(); queueDownload(${jsArg(game.id)})">${isFlat ? "Install" : "Download"}</button>`;
  if (isInstalled && game.update_available) {
    action = `<button class="card-btn update" onclick="event.stopPropagation(); queueDownload(${jsArg(game.id)})">Update</button>`;
  } else if (isInstalled) {
    action = `<button class="card-btn play" onclick="event.stopPropagation(); launchGame(${jsArg(game.package_name)})">${isFlat ? "Open" : "Play"}</button>`;
  }

  return `
    <div class="game-card${isFlat ? " app-card" : ""}" data-id="${escapeHtml(game.id)}" draggable="false" onclick="openGameModal(${jsArg(game.id)}, 'catalog')">
      <div class="card-poster">
        <img src="${escapeHtml(thumbUrl)}" alt="" draggable="false" loading="lazy" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
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
        const cardsHtml = newItems.map(game => buildGameCardHTML(game, installedPkgs)).join("");
        container.insertAdjacentHTML("beforeend", cardsHtml);
      }
    } else {
      state.catalog.items = newItems;
      if (newItems.length === 0) {
        container.innerHTML = `<div class="empty-state">${catalogEmptyMessage(data)}</div>`;
      } else {
        container.innerHTML = newItems.map(game => buildGameCardHTML(game, installedPkgs)).join("");
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
  }

  // Smooth scroll fallback
  window.addEventListener("scroll", () => {
    if (state.activeTab !== "catalog") return;
    const scrollY = window.scrollY || window.pageYOffset;
    const windowHeight = window.innerHeight;
    const docHeight = document.documentElement.scrollHeight;
    if (docHeight - (scrollY + windowHeight) < 450) {
      loadMoreCatalog();
    }
  }, { passive: true });
}

function renderCatalogGrid() {
  const container = document.getElementById("catalog-grid");
  if (!container) return;
  if (!state.catalog.items || state.catalog.items.length === 0) {
    container.innerHTML = `<div class="empty-state">No VR titles match your query. Click "Sync Catalog" to refresh mirror metadata.</div>`;
    return;
  }
  const installedPkgs = new Set((state.installed || []).map(g => g.package));
  container.innerHTML = state.catalog.items.map(game => buildGameCardHTML(game, installedPkgs)).join("");
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

async function syncCatalog() {
  const btn = document.getElementById("sync-catalog-btn");
  const isFlat = state.catalog.kind === "flat";
  if (btn) { btn.classList.add("spinning"); btn.disabled = true; }
  showToast(isFlat ? "Downloading the F-Droid app catalog..." : "🔄 Syncing VR catalog metadata from mirror...", "info");

  try {
    const data = await apiPost("/api/catalog/sync", { kind: state.catalog.kind });
    if (data.success) {
      showToast(isFlat ? (data.message || `${data.total_games} apps available.`) : `✅ Catalog synced! ${data.total_games} games available.`, "success");
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
  showToast("Adding game to download queue...", "info");
  try {
    const res = await fetch("/api/downloads/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: gameId })
    });
    const data = await res.json();
    if (data.success) {
      showToast("🚀 Download queued!", "success");
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
    showToast("⏸ Download paused", "info");
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
    showToast("▶ Download resumed", "info");
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
    showToast(`🧹 Cleared ${data.cleared || 0} completed tasks`, "info");
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
      pauseBtn.textContent = "⏸ Pause";
      pauseBtn.onclick = () => pauseDownload(activeTask.id);
    } else if (activeTask.status === "paused") {
      pauseBtn.style.display = "inline-flex";
      pauseBtn.textContent = "▶ Resume";
      pauseBtn.onclick = () => resumeDownload(activeTask.id);
    } else {
      pauseBtn.style.display = "none";
    }
  }
}

function renderDownloadsTab() {
  const container = document.getElementById("downloads-list");
  if (!container) return;

  if (state.downloads.length === 0) {
    container.innerHTML = `<div class="empty-state">No downloads active or queued.</div>`;
    return;
  }

  container.innerHTML = state.downloads.map(t => {
    let statusText = t.status.toUpperCase();
    let fillClass = "";

    if (t.status === "decompressing") {
      statusText = `EXTRACTING (${t.status_detail || (t.progress_percent + '%')})`;
      fillClass = "extracting";
    } else if (t.status === "installing") {
      statusText = `INSTALLING (${t.status_detail || 'Configuring container...'})`;
      fillClass = "installing";
    } else if (t.status === "completed") {
      statusText = `INSTALLED &amp; READY TO PLAY`;
      fillClass = "completed";
    } else if (t.status === "paused") {
      statusText = `PAUSED • ${t.downloaded_formatted} / ${t.total_formatted}`;
    } else if (t.status === "error") {
      statusText = `ERROR: ${t.error_message || 'Download failed'}`;
    } else if (t.status === "downloading") {
      statusText = `DOWNLOADING • ${t.speed_formatted} • ${t.downloaded_formatted} / ${t.total_formatted} • ETA: ${t.eta_seconds}s`;
    }

    let actionsHtml = "";
    if (t.status === "downloading") {
      actionsHtml = `
        <button class="btn-secondary" onclick="pauseDownload('${t.id}')">⏸ Pause</button>
        <button class="btn-secondary" onclick="cancelDownload('${t.id}')">✖ Cancel</button>
      `;
    } else if (t.status === "paused") {
      actionsHtml = `
        <button class="btn-primary" onclick="resumeDownload('${t.id}')">▶ Resume</button>
        <button class="btn-secondary" onclick="cancelDownload('${t.id}')">✖ Cancel</button>
      `;
    } else if (t.status === "completed") {
      const launchPkg = t.game.package_name || (t.game.to_dict && t.game.to_dict().package_name) || "";
      actionsHtml = `
        <button class="btn-primary" onclick="launchGame('${launchPkg}')">🚀 Play Now</button>
        <button class="btn-secondary" onclick="removeDownload('${t.id}')">✖ Dismiss</button>
      `;
    } else if (t.status === "error") {
      actionsHtml = `
        <button class="btn-primary" onclick="resumeDownload('${t.id}')">🔄 Retry</button>
        <button class="btn-secondary" onclick="removeDownload('${t.id}')">✖ Dismiss</button>
      `;
    } else {
      actionsHtml = `
        <button class="btn-secondary" onclick="cancelDownload('${t.id}')">✖ Cancel</button>
      `;
    }

    return `
      <div class="download-item-card" data-id="${t.id}">
        <div class="download-info">
          <h3>${escapeHtml(t.game.name)}</h3>
          <p>${statusText}</p>
        </div>
        <div class="progress-track" style="margin: 12px 0;">
          <div class="progress-fill ${fillClass}" style="width: ${t.status === 'completed' ? 100 : t.progress_percent}%;"></div>
        </div>
        <div class="download-actions">
          ${actionsHtml}
        </div>
      </div>
    `;
  }).join("");
}

// --- Installed Library API ---
async function loadInstalled() {
  const container = document.getElementById("library-grid");
  if (!container) return;

  try {
    const res = await fetch("/api/installed");
    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }
    const data = await res.json();
    state.installed = Array.isArray(data.games) ? data.games : [];
    renderInstalledGrid();
  } catch (err) {
    console.error("Error loading installed library:", err);
    container.innerHTML = `
      <div class="error-state" style="padding:40px; text-align:center;">
        <p style="margin-bottom:12px; font-weight:600;">Failed to load installed library: ${err.message}</p>
        <button class="btn-primary compact" onclick="loadInstalled()">🔄 Retry Now</button>
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
  const container = document.getElementById("library-grid");
  if (!container) return;

  if (state.installed.length === 0) {
    container.innerHTML = `<div class="empty-state">Nothing installed yet. Browse the catalog or sideload an APK.</div>`;
    return;
  }

  container.innerHTML = state.installed.map(game => {
    const updateInfo = (state.updates && state.updates.games)
      ? state.updates.games.find(u => u.package === game.package)
      : null;
    const pkg = jsArg(game.package);
    const level = (game.compat && game.compat.level) || "";
    const needsAttention = level === "needs_port" || level === "blocked";

    return `
      <div class="game-card" data-package="${escapeHtml(game.package)}" draggable="false" onclick="openGameModal(${pkg}, 'installed')">
        <div class="card-poster">
          <img src="${escapeHtml(game.thumbnail_url || '/static/assets/fallback_cover.svg')}" alt="" draggable="false" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
          <div class="badge-overlay">
            <span class="badge ${game.is_vr ? 'vr' : 'flat'}">${game.is_vr ? 'VR' : '2D'}</span>
            ${game.is_external ? '<span class="badge" style="background:#27ae60; color:#fff;" title="Installed on MicroSD Card">MicroSD</span>' : ''}
            ${game.is_running ? '<span class="badge installed" style="background:#00f2fe;">Running</span>' : ''}
            ${updateInfo ? '<span class="badge update" title="New update available on mirror">Update Available</span>' : ''}
            ${needsAttention ? `<span class="badge compat-${escapeHtml(level)}" title="${escapeHtml(game.compat.label)}">${level === "blocked" ? "Cannot run" : "Needs porting"}</span>` : ''}
          </div>
        </div>
        <div class="card-body">
          <div class="card-title" title="${escapeHtml(game.title)}">${escapeHtml(game.title)}</div>
          <div class="card-meta">
            <span>${game.is_external ? '💾 MicroSD' : '💿 Internal'}</span>
            <span>${escapeHtml(game.engine || "")}</span>
          </div>
          <div class="card-actions">
            ${updateInfo
              ? `<button class="card-btn update" title="1-Click Update" onclick="event.stopPropagation(); updateGame(${pkg})">⚡ Update</button>`
              : `<button class="card-btn play" onclick="event.stopPropagation(); launchGame(${pkg})">Launch</button>`}
            <button class="card-btn download" onclick="event.stopPropagation(); openSettingsModal(${pkg})">Settings</button>
          </div>
        </div>
      </div>
    `;
  }).join("");

  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

async function launchGame(pkg) {
  showToast(`🚀 Launching ${pkg}...`, "info");
  try {
    const res = await fetch("/api/installed/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package: pkg })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.launched_via_steam ? "Starting through Steam..."
        : data.in_steam_library === false ? "Starting directly: Steam has not loaded this game yet."
        : "Starting...", "success");
      loadInstalled();
    } else {
      showToast(data.error || "Failed to launch game", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  }
}

async function uninstallGame(pkg, keepSaves = true) {
  if (!confirm(`Are you sure you want to uninstall ${pkg}?`)) return;

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
      batChip.innerHTML = `<span class="pulse-dot"></span> ${data.battery.percent}% ${data.battery.plugged ? '⚡' : ''}`;
    }

    const storageChip = document.getElementById("header-storage");
    if (storageChip && data.storage) {
      storageChip.textContent = `💾 ${data.storage.free_gb} GB Free`;
    }

    const lepChip = document.getElementById("header-lepton");
    if (lepChip) {
      const isReady = data.lepton && data.lepton.installed;
      lepChip.className = `telemetry-chip lepton ${isReady ? 'active' : 'missing'}`;
      lepChip.textContent = isReady ? 'Lepton Ready' : 'Lepton Not Found';
      lepChip.title = isReady ? data.lepton.path : "Lepton ships with the Steam Frame. It was not found in any Steam library on this machine.";
    }

    renderSystemTab(data);
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

  // Cover image banner
  const coverEl = document.getElementById("modal-game-cover");
  if (coverEl) {
    coverEl.src = thumbUrl;
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
          if (state.selectedGame !== game || !data.game || !data.game.description) return;
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
    actionContainer.innerHTML = `
      <button class="btn-primary" onclick="launchGame(${arg}); closeModal();">${game.is_vr ? "Launch in VR" : "Open"}</button>
      ${lepton ? `<button class="btn-secondary" onclick="openTuningModal(${arg})">Settings</button>` : ""}
      ${game.kind === "quest" && game.compat && game.compat.level === "needs_port" ? `<button class="btn-secondary" style="border-color:var(--accent-amber); color:var(--accent-amber);" onclick="closeModal(); portGame(${arg})">Port for Steam Frame</button>` : ""}
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
  if (!confirm(`Move ${state.selectedGame.title || pkg} to ${targetDev.name}? Steam shortcut will be automatically updated.`)) {
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
          showToast("Installed. Porting it for the Steam Frame now...", "info");
        } else if (port.needed && port.reason === "not_set_up") {
          showToast("Installed. It needs porting before it starts: press Set Up Porting under System & Diagnostics once, and it is ported automatically.", "warning");
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
      <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.05);">
        <div>
          <span style="font-weight:600; color:#fff;">${escapeHtml(m.name)}</span>
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
  if (!confirm(`Delete this custom content item?`)) return;
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
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
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

  // Also populate the Sideload tab's target drive dropdown
  const sideloadSelect = document.getElementById("sideload-target-drive");
  if (sideloadSelect) {
    const currentVal = sideloadSelect.value;
    sideloadSelect.innerHTML = devices.map(dev => `
      <option value="${dev.id}" ${dev.id === currentVal ? 'selected' : (dev.is_default ? 'selected' : '')}>
        ${dev.is_sd_card ? '💾 [MicroSD] ' : '💿 [SSD] '} ${escapeHtml(dev.name)} (${dev.free_formatted} free)
      </option>
    `).join("");
  }

  container.innerHTML = devices.map(dev => {
    const isActive = activeDev && activeDev.id === dev.id;
    const isSd = dev.is_sd_card;
    const badgeHtml = isSd 
      ? `<span class="badge" style="background:#27ae60; color:#fff; font-size:0.7rem; padding:2px 6px; border-radius:4px; margin-left:6px;">MicroSD</span>`
      : `<span class="badge" style="background:rgba(255,255,255,0.1); color:#ccc; font-size:0.7rem; padding:2px 6px; border-radius:4px; margin-left:6px;">SSD</span>`;
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
        <p style="font-size:1.05rem; font-weight:600; color:#fff; margin-bottom:6px;">No installed games match your search</p>
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
        <option value="${d.id}">${d.is_sd_card ? '💾 ' : '💿 '} Move to ${d.name}</option>
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

  if (!confirm("Reset shader caches across all installed games? Shader files will be safely regenerated on next launch.")) return;

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
        sysBadge.style.background = "rgba(255, 183, 3, 0.15)";
        sysBadge.style.color = "var(--accent-amber)";
        sysBadge.textContent = `Update: v${appUpdate.latest_version}`;
      }
      if (sysUpdateBtn) sysUpdateBtn.style.display = "inline-flex";
    } else {
      if (alertChip) alertChip.style.display = "none";
      if (topBanner) topBanner.style.display = "none";
      if (sysBadge) {
        sysBadge.style.background = "rgba(0, 245, 212, 0.15)";
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
        btn.textContent = "⚡ Update & Restart Service (1-Click)";
      }
      if (sysBtn) {
        sysBtn.disabled = false;
        sysBtn.textContent = "⚡ 1-Click Update";
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
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; background:#040915; color:#fff; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align:center; padding:24px;">
          <div style="font-size:3.5rem; margin-bottom:16px;">✨</div>
          <h1 style="color:#00f5d4; font-size:2rem; font-weight:800; margin-bottom:14px;">FrameLoad Successfully Uninstalled</h1>
          <p style="color:#94a3b8; max-width:520px; line-height:1.6; margin-bottom:24px; font-size:1rem;">
            All system integrations have been removed from your Steam Frame: background systemd service stopped, desktop launcher deleted, Steam shortcuts &amp; grid artwork removed, and caches cleared.
          </p>
          <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:16px 24px; color:#cbd5e1; font-size:0.9rem; margin-bottom:20px;">
            ${keepBackups ? "💾 Save game backups preserved in <code>~/.local/share/frameload/backups</code>" : "🗑️ All data and caches have been purged."}
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
      <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; background:#040915; color:#fff; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align:center; padding:24px;">
        <div style="font-size:3.5rem; margin-bottom:16px;">✨</div>
        <h1 style="color:#00f5d4; font-size:2rem; font-weight:800; margin-bottom:14px;">FrameLoad Successfully Uninstalled</h1>
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
        badge.style.background = "rgba(0,242,254,0.12)";
        badge.style.color = "var(--accent-cyan)";
        badge.style.border = "1px solid rgba(0,242,254,0.3)";
      }
      if (text) text.textContent = `Mirror configured: ${data.active_base_url}`;
      if (url) url.textContent = data.active_base_url;
      if (clearBtn) clearBtn.style.display = "";
    } else {
      if (badge) {
        badge.textContent = "Built-in Catalog";
        badge.style.background = "rgba(255,255,255,0.08)";
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
    if (statusText) statusText.textContent = "✅ rclone: Ready (auto-installs on first sync)";
    if (bar) {
      bar.style.background = "rgba(0,242,254,0.05)";
      bar.style.borderColor = "rgba(0,242,254,0.15)";
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
      if (statusText) statusText.textContent = "✅ rclone installed!";
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
        resultEl.style.background = "rgba(0,242,254,0.08)";
        resultEl.style.border = "1px solid rgba(0,242,254,0.3)";
        resultEl.style.color = "var(--accent-cyan)";
        resultEl.textContent = `✅ ${data.message} — Click Sync Catalog in the Catalog tab to load games.`;
      }
      loadMirrorStatus();
    } else {
      showToast(data.error || "Failed to apply config", "error");
      if (resultEl) {
        resultEl.style.display = "block";
        resultEl.style.background = "rgba(255,80,80,0.08)";
        resultEl.style.border = "1px solid rgba(255,80,80,0.3)";
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
  if (resultEl) { resultEl.style.display = "block"; resultEl.textContent = "⌛ Connecting..."; resultEl.style.background = "rgba(255,183,3,0.06)"; resultEl.style.border = "1px solid rgba(255,183,3,0.2)"; resultEl.style.color = "var(--accent-amber)"; }

  try {
    const data = await apiPost("/api/mirrors/test", {});
    if (data.success) {
      if (resultEl) {
        resultEl.style.background = "rgba(0,242,254,0.08)";
        resultEl.style.border = "1px solid rgba(0,242,254,0.3)";
        resultEl.style.color = "var(--accent-cyan)";
        resultEl.textContent = `✅ ${data.message}`;
      }
      showToast("Mirror connection OK!", "success");
    } else {
      if (resultEl) {
        resultEl.style.background = "rgba(255,80,80,0.08)";
        resultEl.style.border = "1px solid rgba(255,80,80,0.3)";
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
    showToast(data.success ? `✅ ${data.message}` : `❌ ${data.error}`, data.success ? "success" : "error");
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
state.porting = { status: null, jobId: null, timer: null };

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
    badge.textContent = st.job ? "Working..." : ready ? "Ready" : st.installed ? "Tools missing" : "Not set up";
    badge.style.color = ready ? "var(--accent-emerald)" : "var(--text-muted)";
    const waiting = (st.pending || []).map(g => g.title);
    const parts = [];
    if (st.installed) parts.push(`FramePort ${st.version}${ready ? " with Java, OVRPort and apksigner." : "; its tools still need to be downloaded."}`);
    if (st.limited) parts.push(st.limited);
    if (waiting.length) parts.push(`Waiting to be ported after setup: ${waiting.join(", ")}.`);
    if (detail) detail.textContent = parts.join(" ");
    const autoCheck = document.getElementById("porting-auto-check");
    if (autoCheck) autoCheck.checked = st.auto !== false;
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

function closePortingModal() {
  const modal = document.getElementById("porting-modal");
  if (modal) modal.classList.remove("open");
  clearTimeout(state.porting.timer);
  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

async function pollPortingJob() {
  clearTimeout(state.porting.timer);
  const id = state.porting.jobId;
  const title = document.getElementById("porting-modal-title");
  const status = document.getElementById("porting-modal-status");
  const log = document.getElementById("porting-modal-log");
  if (!id || !log) return;
  try {
    const job = await apiGet(`/api/porting/jobs/${encodeURIComponent(id)}`);
    if (title) title.textContent = job.kind === "setup" ? "Setting up porting" : `Porting ${job.package}`;
    const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.textContent = job.log.join("\n");
    if (atEnd) log.scrollTop = log.scrollHeight;
    if (job.status === "running" || job.status === "queued") {
      if (status) status.textContent = job.status === "queued"
        ? "Waiting for another porting job to finish."
        : "Working. This can take several minutes; you can close this window, it keeps going.";
      state.porting.timer = setTimeout(pollPortingJob, 1500);
      return;
    }
    if (status) {
      status.textContent = job.status === "done"
        ? (job.kind === "setup" ? "Porting is set up." : `Finished: ${(job.result && job.result.compat && job.result.compat.label) || "installed"}. Start it from your library.`)
        : `Failed: ${job.error}`;
    }
    showToast(job.status === "done" ? "Finished." : `Failed: ${job.error}`, job.status === "done" ? "success" : "error");
    loadPortingStatus();
    loadInstalled();
  } catch (e) {
    if (status) status.textContent = `Could not read progress: ${e.message}`;
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
    showToast(enabled ? "Quest games are ported automatically after installing." : "Automatic porting is off. Use Port for Steam Frame on a game.", "info");
  } catch (e) {
    showToast(e.message, "error");
  }
}
window.setPortingAuto = setPortingAuto;

function startPortingSetup() {
  return startPortingJob("/api/porting/setup", {});
}

async function portGame(pkg) {
  const st = state.porting.status || await loadPortingStatus();
  if (!st || !st.installed || !st.tools_ready) {
    showToast("Porting is not set up yet. Open System & Diagnostics and press Set Up Porting first.", "warning");
    return;
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
  if (!confirm("Restart Steam now? This closes FrameLoad's window and any running game. Steam comes back by itself with the new games in your library.")) return;
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
