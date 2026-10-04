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
  activeTab: "catalog",
  selectedGame: null
};

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupSearch();
  setupModals();
  setupSideloadForm();

  // Initial loads
  loadCatalog();
  loadInstalled();
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
      else if (targetId === "system") loadSystemTelemetry();

      if (window.gamepadNav) window.gamepadNav.updateFocusables();
    });
  });
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
