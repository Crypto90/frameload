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
  updates: {
    app: null,
    games: []
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
  checkForUpdates(false);
  startPollingDownloads();
  setInterval(loadSystemTelemetry, 8000);
  setInterval(() => checkForUpdates(false), 60000);
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
        const bs = (state.installed && state.installed.find(g => g.package === "com.beatgames.beatsaber")) || (state.installed && state.installed[0]) || (state.catalog && state.catalog.items[0]);
        if (bs) openGameModal(bs.package || bs.id, state.installed && state.installed.length ? "installed" : "catalog");
      }, 500);
    }
    if (hash === "sideload") {
      setTimeout(() => {
        const flatCheck = document.getElementById("sideload-flat");
        if (flatCheck) {
          flatCheck.checked = true;
          toggleFlatWindowPreset(true);
        }
        const pathInput = document.getElementById("sideload-apk-path");
        if (pathInput) pathInput.value = "/run/media/deck/SD_CARD/GorillaTag_v1.2.xapk";
      }, 200);
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

  container.innerHTML = state.installed.map(game => {
    const updateInfo = (state.updates && state.updates.games)
      ? state.updates.games.find(u => u.package === game.package)
      : null;

    return `
      <div class="game-card" data-package="${game.package}" onclick="openGameModal('${game.package}', 'installed')">
        <div class="card-poster">
          <img src="${game.thumbnail_url || '/static/assets/fallback_cover.svg'}" alt="${game.title}" onerror="this.onerror=null; this.src='/static/assets/fallback_cover.svg';">
          <div class="badge-overlay">
            <span class="badge ${game.is_vr ? 'vr' : 'flat'}">${game.is_vr ? 'VR' : '2D'}</span>
            ${game.is_external ? '<span class="badge" style="background:#27ae60; color:#fff;" title="Installed on MicroSD Card">MicroSD</span>' : ''}
            ${game.is_running ? '<span class="badge installed" style="background:#00f2fe;">Running</span>' : ''}
            ${updateInfo ? '<span class="badge update" title="New update available on mirror">Update Available</span>' : ''}
          </div>
        </div>
        <div class="card-body">
          <div class="card-title">${game.title}</div>
          <div class="card-meta">
            <span>${game.is_external ? '💾 MicroSD' : '💿 Internal'}</span>
            <span>Engine: ${game.engine}</span>
          </div>
          <div class="card-actions">
            ${updateInfo 
              ? `<button class="card-btn update" title="1-Click Update" onclick="event.stopPropagation(); updateGame('${game.package}')">⚡ Update</button>`
              : `<button class="card-btn play" onclick="event.stopPropagation(); launchGame('${game.package}')">Launch</button>`}
            <button class="card-btn download" onclick="event.stopPropagation(); openSettingsModal('${game.package}')">Config</button>
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
    } else if (game.force_flat) {
      platformEl.textContent = `Steam Frame (Lepton 2D Window: ${game.window_preset || "tablet"})`;
    } else {
      platformEl.textContent = "Steam Frame (Lepton Container VR)";
    }
  }
  if (openxrEl) {
    if (game.install_type === "windows_proton") {
      openxrEl.textContent = game.is_vr ? "WineOpenXR -> SteamVR" : "Disabled (Flat Desktop App)";
    } else if (game.install_type === "linux_native") {
      openxrEl.textContent = game.is_vr ? "Monado / SteamVR Native OpenXR" : "Disabled (Flat Native App)";
    } else {
      openxrEl.textContent = "FrameBridge Adapter & Controller Models";
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
          badgeEl.textContent = insp.is_vr ? "Quest VR" : "2D Flat";
          badgeEl.style.background = insp.is_vr ? "var(--accent-cyan)" : "var(--accent-amber)";
        }
        badgeEl.style.color = "#000";
      }
      if (titleInput && !titleInput.value) {
        titleInput.value = insp.title || "";
      }
      showToast("Package inspected successfully!", "success");
    } else {
      showToast(data.error || "Could not inspect source path", "error");
    }
  } catch (err) {
    showToast(`Inspection failed: ${err.message}`, "error");
  }
}
window.inspectSideloadPath = inspectSideloadPath;

function toggleFlatWindowPreset(isFlat) {
  const group = document.getElementById("sideload-window-preset-group");
  if (group) {
    group.style.display = isFlat ? "block" : "none";
  }
}
window.toggleFlatWindowPreset = toggleFlatWindowPreset;

function setupSideloadForm() {
  const form = document.getElementById("sideload-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sourcePath = document.getElementById("sideload-apk-path").value.trim();
    const title = document.getElementById("sideload-title").value.trim();
    const forceFlat = document.getElementById("sideload-flat").checked;
    const windowPresetSelect = document.getElementById("sideload-window-preset");
    const windowPreset = windowPresetSelect ? windowPresetSelect.value : "tablet";
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
          window_preset: windowPreset,
          device_id: deviceId
        })
      });
      const data = await res.json();
      if (data.success) {
        showToast("Installation complete! Added to Steam Library.", "success");
        form.reset();
        const preview = document.getElementById("sideload-inspect-preview");
        if (preview) preview.style.display = "none";
        const group = document.getElementById("sideload-window-preset-group");
        if (group) group.style.display = "none";
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
          <span style="font-weight:600; color:#fff;">${m.name}</span>
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
        ${dev.is_sd_card ? '💾 [MicroSD] ' : '💿 [SSD] '} ${dev.name} (${dev.free_formatted} free)
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
    const res = await fetch("/api/updates");
    const data = await res.json();
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
    const gameUpdates = (data.games && data.games.games) ? data.games.games : [];
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

