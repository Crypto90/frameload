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
    sortBy: "date",
    sortOrder: "desc"
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
  activeTab: "catalog",
  selectedGame: null
};

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupSearch();
  setupModals();
  setupSideloadForm();
  setupStorage();

  // Initial loads
  loadCatalog();
  loadInstalled();
  loadStorageOverview();
  loadSystemTelemetry();
  startPollingDownloads();
  setInterval(loadSystemTelemetry, 8000);
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
      else if (targetId === "library") loadInstalled();
      else if (targetId === "storage") loadStorageOverview();
      else if (targetId === "system") loadSystemTelemetry();

      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    });
  });

  // Handle URL hash on load (e.g. #library, #system, #downloads)
  const hash = window.location.hash.replace("#", "");
  if (hash) {
    const tabEl = document.querySelector(`.tab-btn[data-tab="${hash}"]`);
    if (tabEl) tabEl.click();
    if (hash === "modal") {
      setTimeout(() => {
        const first = state.installed[0] || state.catalog.items[0];
        if (first) openGameModal(first.package || first.id, state.installed.length ? "installed" : "catalog");
      }, 400);
    }
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
      if (val === "date_desc") { state.catalog.sortBy = "date"; state.catalog.sortOrder = "desc"; }
      else if (val === "name_asc") { state.catalog.sortBy = "name"; state.catalog.sortOrder = "asc"; }
      else if (val === "size_desc") { state.catalog.sortBy = "size"; state.catalog.sortOrder = "desc"; }
      else if (val === "size_asc") { state.catalog.sortBy = "size"; state.catalog.sortOrder = "asc"; }
      state.catalog.page = 1;
      loadCatalog();
    });
  }

  const syncBtn = document.getElementById("sync-catalog-btn");
  if (syncBtn) {
    syncBtn.addEventListener("click", syncCatalog);
  }
}

// --- Catalog API ---
async function loadCatalog(page = state.catalog.page) {
  const container = document.getElementById("catalog-grid");
  if (!container) return;

  container.innerHTML = `<div class="loading-state">Scanning VR mirror catalog...</div>`;

  try {
    const params = new URLSearchParams({
      page: page,
      per_page: 36,
      q: state.catalog.query,
      sort_by: state.catalog.sortBy,
      sort_order: state.catalog.sortOrder
    });

    const res = await fetch(`/api/catalog?${params}`);
    const data = await res.json();

    state.catalog.items = data.items || [];
    state.catalog.page = data.page || 1;
    state.catalog.totalPages = data.total_pages || 1;
    state.catalog.totalCount = data.total_count || 0;

    renderCatalogGrid();
    renderPagination();
  } catch (err) {
    container.innerHTML = `<div class="error-state">Failed to load catalog. Ensure the mirror is reachable.</div>`;
    console.error(err);
  }
}

function renderCatalogGrid() {
  const container = document.getElementById("catalog-grid");
  if (!container) return;

  if (state.catalog.items.length === 0) {
    container.innerHTML = `<div class="empty-state">No VR titles match your query. Click "Sync Catalog" to refresh mirror metadata.</div>`;
    return;
  }

  const installedPkgs = new Set(state.installed.map(g => g.package));

  container.innerHTML = state.catalog.items.map(game => {
    const isInstalled = installedPkgs.has(game.package_name);
    const thumbUrl = game.thumbnail_url || `/api/thumbnail/${game.package_name}`;

    return `
      <div class="game-card" data-id="${game.id}" onclick="openGameModal('${game.id}', 'catalog')">
        <div class="card-poster">
          <img src="${thumbUrl}" alt="${game.name}" loading="lazy" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
          <div class="badge-overlay">
            <span class="badge ${game.kind === 'flat' ? 'flat' : 'vr'}">${game.kind === 'flat' ? '2D' : 'VR'}</span>
            ${isInstalled ? '<span class="badge installed">Installed</span>' : ''}
          </div>
        </div>
        <div class="card-body">
          <div class="card-title" title="${game.name}">${game.name}</div>
          <div class="card-meta">
            <span>${game.size_formatted}</span>
            <span>${game.version_code ? 'v' + game.version_code : ''}</span>
          </div>
          <div class="card-actions">
            ${isInstalled 
              ? `<button class="card-btn play" onclick="event.stopPropagation(); launchGame('${game.package_name}')">Play</button>`
              : `<button class="card-btn download" onclick="event.stopPropagation(); queueDownload('${game.id}')">Download</button>`
            }
          </div>
        </div>
      </div>
    `;
  }).join("");

  if (window.gamepadNav) window.gamepadNav.updateFocusables();
}

function renderPagination() {
  const container = document.getElementById("catalog-pagination");
  if (!container) return;

  const { page, totalPages } = state.catalog;
  if (totalPages <= 1) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = `
    <button class="btn-secondary" ${page <= 1 ? 'disabled' : ''} onclick="loadCatalog(${page - 1})">Previous</button>
    <span class="page-indicator">Page ${page} of ${totalPages}</span>
    <button class="btn-secondary" ${page >= totalPages ? 'disabled' : ''} onclick="loadCatalog(${page + 1})">Next</button>
  `;
}

async function syncCatalog() {
  const btn = document.getElementById("sync-catalog-btn");
  if (btn) btn.classList.add("spinning");
  showToast("🔄 Syncing VR catalog metadata from mirror...", "info");

  try {
    const res = await fetch("/api/catalog/sync", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(`✅ Catalog synced! ${data.total_games} games available.`, "success");
      loadCatalog(1);
    } else {
      showToast("⚠️ Could not download metadata. Check network connection.", "error");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    if (btn) btn.classList.remove("spinning");
  }
}

// --- Download Queue ---
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

function startPollingDownloads() {
  setInterval(pollDownloadsOnce, 1200);
}

async function pollDownloadsOnce() {
  try {
    const res = await fetch("/api/downloads");
    const data = await res.json();
    state.downloads = data.tasks || [];
    renderDownloadsDrawer();
    renderDownloadsTab();
  } catch (err) {
    // Silent polling error
  }
}

function renderDownloadsDrawer() {
  const drawer = document.getElementById("downloads-drawer");
  if (!drawer) return;

  const activeTask = state.downloads.find(t => t.status === "downloading" || t.status === "decompressing" || t.status === "installing");

  if (!activeTask) {
    drawer.classList.remove("visible");
    return;
  }

  drawer.classList.add("visible");
  document.getElementById("drawer-title").textContent = activeTask.game.name;
  document.getElementById("drawer-status").textContent = `${activeTask.status.toUpperCase()} • ${activeTask.speed_formatted} • ${activeTask.downloaded_formatted} / ${activeTask.total_formatted}`;
  document.getElementById("drawer-progress").style.width = `${activeTask.progress_percent}%`;
}

function renderDownloadsTab() {
  const container = document.getElementById("downloads-list");
  if (!container) return;

  if (state.downloads.length === 0) {
    container.innerHTML = `<div class="empty-state">No downloads active or queued.</div>`;
    return;
  }

  container.innerHTML = state.downloads.map(t => `
    <div class="download-item-card">
      <div class="download-info">
        <h3>${t.game.name}</h3>
        <p>${t.status.toUpperCase()} • ${t.speed_formatted} • ETA: ${t.eta_seconds}s</p>
      </div>
      <div class="progress-track" style="margin: 12px 0;">
        <div class="progress-fill" style="width: ${t.progress_percent}%;"></div>
      </div>
      <div class="download-actions">
        <button class="btn-secondary" onclick="cancelDownload('${t.id}')">Cancel</button>
      </div>
    </div>
  `).join("");
}

// --- Installed Library API ---
async function loadInstalled() {
  const container = document.getElementById("library-grid");
  if (!container) return;

  try {
    const res = await fetch("/api/installed");
    const data = await res.json();
    state.installed = data.games || [];
    renderInstalledGrid();
  } catch (err) {
    container.innerHTML = `<div class="error-state">Failed to load installed library.</div>`;
  }
}

function renderInstalledGrid() {
  const container = document.getElementById("library-grid");
  if (!container) return;

  if (state.installed.length === 0) {
    container.innerHTML = `<div class="empty-state">No games installed on Steam Frame yet. Explore the Catalog to download games!</div>`;
    return;
  }

  container.innerHTML = state.installed.map(game => `
    <div class="game-card" data-package="${game.package}" onclick="openGameModal('${game.package}', 'installed')">
      <div class="card-poster">
        <img src="${game.thumbnail_url || '/static/assets/fallback_cover.svg'}" alt="${game.title}" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
        <div class="badge-overlay">
          <span class="badge ${game.is_vr ? 'vr' : 'flat'}">${game.is_vr ? 'VR' : '2D'}</span>
          ${game.is_running ? '<span class="badge installed" style="background:#00f2fe;">Running</span>' : ''}
        </div>
      </div>
      <div class="card-body">
        <div class="card-title">${game.title}</div>
        <div class="card-meta">
          <span>Engine: ${game.engine}</span>
          <span>AppID: ${game.appid}</span>
        </div>
        <div class="card-actions">
          <button class="card-btn play" onclick="event.stopPropagation(); launchGame('${game.package}')">Launch</button>
          <button class="card-btn download" onclick="event.stopPropagation(); openSettingsModal('${game.package}')">Config</button>
        </div>
      </div>
    </div>
  `).join("");

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
      showToast("Game started in SteamVR!", "success");
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
      lepChip.textContent = isReady ? 'Lepton Ready' : 'Lepton Missing';
    }

    renderSystemTab(data);
  } catch (err) {
    console.error("Telemetry error", err);
  }
}

function renderSystemTab(sys) {
  const panel = document.getElementById("tab-system");
  if (!panel || !sys) return;

  const leptonHtml = sys.lepton.installed 
    ? `<span style="color:var(--accent-emerald);">Installed (${sys.lepton.path})</span>`
    : `<button class="btn-primary" onclick="installLepton()">Install Lepton via Steam</button>`;

  const protonHtml = sys.proton.has_proton
    ? `<span style="color:var(--accent-emerald);">${sys.proton.installed_tools.join(', ')}</span>`
    : `<span style="color:var(--accent-amber);">No Proton ARM64 tool detected</span>`;

  document.getElementById("sys-os").textContent = `${sys.os_name} ${sys.os_version} (${sys.arch})`;
  document.getElementById("sys-lepton").innerHTML = leptonHtml;
  document.getElementById("sys-proton").innerHTML = protonHtml;
  document.getElementById("sys-storage").textContent = `${sys.storage.free_gb} GB free / ${sys.storage.total_gb} GB (${sys.storage.percent_used}% used)`;
}

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

  document.getElementById("modal-game-title").textContent = game.name || game.title;
  document.getElementById("modal-game-pkg").textContent = game.package_name || game.package;
  document.getElementById("modal-game-size").textContent = game.size_formatted || `${Math.round((game.apk_size || 0)/(1024*1024))} MB`;

  const actionContainer = document.getElementById("modal-actions");
  if (mode === "catalog") {
    actionContainer.innerHTML = `
      <button class="btn-primary" onclick="queueDownload('${game.id}'); closeModal();">Download to Steam Frame</button>
    `;
  } else {
    actionContainer.innerHTML = `
      <button class="btn-primary" onclick="launchGame('${game.package}'); closeModal();">Launch in VR</button>
      <button class="btn-secondary" onclick="backupSaves('${game.package}')">Backup Saves</button>
      <button class="btn-secondary" style="color:var(--accent-danger);" onclick="uninstallGame('${game.package}')">Uninstall</button>
    `;
  }

  modal.classList.add("open");
}

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

// --- Sideload Form ---
function setupSideloadForm() {
  const form = document.getElementById("sideload-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const apkPath = document.getElementById("sideload-apk-path").value;
    const title = document.getElementById("sideload-title").value;
    const forceFlat = document.getElementById("sideload-flat").checked;

    showToast("Installing APK onto Steam Frame...", "info");
    try {
      const res = await fetch("/api/local/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apk_path: apkPath, title: title, force_flat: forceFlat })
      });
      const data = await res.json();
      if (data.success) {
        showToast("Installation complete! App added to Steam Library.", "success");
        form.reset();
        loadInstalled();
      } else {
        showToast(data.error || "Installation failed", "error");
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, "error");
    }
  });
}

// --- Toast Notifications ---
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "toast";
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

  container.innerHTML = devices.map(dev => {
    const isActive = activeDev && activeDev.id === dev.id;
    return `
      <div class="storage-drive-card ${isActive ? 'active' : ''}" onclick="selectStorageDrive('${dev.id}')">
        <div class="drive-icon-box">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect>
            <rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect>
            <line x1="6" y1="6" x2="6.01" y2="6"></line>
            <line x1="6" y1="18" x2="6.01" y2="18"></line>
          </svg>
        </div>
        <div class="drive-meta">
          <div class="drive-name">
            ${dev.name} ${dev.is_default ? '<span class="drive-star" title="Default Install Drive">★</span>' : ''}
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
      ? `<img src="${thumbUrl}" class="storage-game-thumb" alt="${game.title}" onerror="this.src='/static/icons/default-game.svg'">`
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
            <div class="storage-game-title">${game.title}</div>
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
}

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
        <span class="batch-preview-row-title">${g.title}</span>
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
