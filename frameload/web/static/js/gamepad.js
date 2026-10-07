/**
 * FrameLoad VR Controller & Laser Pointer Navigation Engine
 * Engineered specifically for Valve Steam Frame (Galileo / Roy) & Standalone VR Headsets.
 * 
 * Features:
 *  1. Laser Pointer Momentum Drag-to-Scroll:
 *     Enables smooth trigger-drag & flick inertial scrolling across the entire virtual UI,
 *     game catalog grid, modals, logs, and horizontal category chips.
 *  2. 2D Spatial Gamepad & VR Controller Navigation:
 *     True geometric directional traversal (Up/Down/Left/Right) for 2D game grids.
 *  3. Right Stick Analog Scrolling:
 *     Smooth continuous scrolling of the active view or open modal using the right thumbstick.
 *  4. Modal Focus Trap:
 *     Automatically confines controller focus inside open dialogs.
 *  5. Discreet VR Controller HUD:
 *     Contextual on-screen button legend that shows during controller activity.
 */

/* ==========================================================================
   1. VR Laser Pointer Drag-to-Scroll Engine
   ========================================================================== */
class VRLaserDragEngine {
  constructor() {
    this.isPointerDown = false;
    this.isDragging = false;
    this.startX = 0;
    this.startY = 0;
    this.lastX = 0;
    this.lastY = 0;
    this.lastTime = 0;
    this.vx = 0;
    this.vy = 0;
    this.scrollTarget = null;
    this.momentumRaf = null;
    this.suppressClick = false;
    this.dragThreshold = 6; // px

    this.onPointerDown = this.onPointerDown.bind(this);
    this.onPointerMove = this.onPointerMove.bind(this);
    this.onPointerUp = this.onPointerUp.bind(this);
    this.onClickCapture = this.onClickCapture.bind(this);

    this.init();
  }

  init() {
    window.addEventListener("pointerdown", this.onPointerDown, { passive: true });
    window.addEventListener("pointermove", this.onPointerMove, { passive: false });
    window.addEventListener("pointerup", this.onPointerUp, { passive: false });
    window.addEventListener("pointercancel", this.onPointerUp, { passive: false });
    window.addEventListener("click", this.onClickCapture, { capture: true });
  }

  findScrollTarget(el) {
    if (!el || el === document.body || el === document.documentElement) {
      return window;
    }

    // Check for open modal body first
    const openModal = document.querySelector(".modal-backdrop.open");
    if (openModal && openModal.contains(el)) {
      const modalBody = openModal.querySelector(".modal-body, .modal-content, .card-details-grid");
      if (modalBody && modalBody.scrollHeight > modalBody.clientHeight) {
        return modalBody;
      }
    }

    // Traverse upwards to find scrollable ancestor
    let curr = el;
    while (curr && curr !== document.body && curr !== document.documentElement) {
      const style = window.getComputedStyle(curr);
      const overflowY = style.overflowY;
      const overflowX = style.overflowX;
      const isScrollY = (overflowY === "auto" || overflowY === "scroll") && curr.scrollHeight > curr.clientHeight;
      const isScrollX = (overflowX === "auto" || overflowX === "scroll") && curr.scrollWidth > curr.clientWidth;

      if (isScrollY || isScrollX) {
        return curr;
      }
      curr = curr.parentElement;
    }

    return window;
  }

  createLaserRipple(x, y) {
    const ripple = document.createElement("div");
    ripple.className = "vr-laser-ripple";
    ripple.style.left = `${x}px`;
    ripple.style.top = `${y}px`;
    document.body.appendChild(ripple);

    requestAnimationFrame(() => {
      ripple.classList.add("expand");
    });

    setTimeout(() => {
      if (ripple.parentElement) ripple.remove();
    }, 380);
  }

  onPointerDown(e) {
    // Ignore secondary mouse buttons, sliders, or input typing
    if (e.button && e.button !== 0) return;
    if (e.target && (e.target.tagName === "INPUT" && (e.target.type === "range" || e.target.type === "text" || e.target.type === "search"))) {
      return;
    }

    if (this.momentumRaf) {
      cancelAnimationFrame(this.momentumRaf);
      this.momentumRaf = null;
    }

    this.isPointerDown = true;
    this.isDragging = false;
    this.suppressClick = false;
    this.startX = e.clientX;
    this.startY = e.clientY;
    this.lastX = e.clientX;
    this.lastY = e.clientY;
    this.lastTime = performance.now();
    this.vx = 0;
    this.vy = 0;
    this.scrollTarget = this.findScrollTarget(e.target);

    // Subtle laser point ripple on VR touch
    if (e.pointerType === "touch" || e.pointerType === "pen" || !e.pointerType) {
      this.createLaserRipple(e.clientX, e.clientY);
    }
  }

  onPointerMove(e) {
    if (!this.isPointerDown) return;

    const dx = e.clientX - this.lastX;
    const dy = e.clientY - this.lastY;
    const totalDist = Math.hypot(e.clientX - this.startX, e.clientY - this.startY);

    if (!this.isDragging && totalDist >= this.dragThreshold) {
      this.isDragging = true;
      this.suppressClick = true;
      document.body.classList.add("vr-grabbing");
    }

    if (this.isDragging && this.scrollTarget) {
      const now = performance.now();
      const dt = Math.max(1, now - this.lastTime);

      // Low-pass filtered instantaneous velocity (pixels/ms)
      this.vx = 0.7 * (dx / dt) + 0.3 * this.vx;
      this.vy = 0.7 * (dy / dt) + 0.3 * this.vy;

      this.lastX = e.clientX;
      this.lastY = e.clientY;
      this.lastTime = now;

      // Apply drag scroll
      if (this.scrollTarget === window) {
        window.scrollBy({ left: -dx, top: -dy, behavior: "auto" });
      } else {
        this.scrollTarget.scrollLeft -= dx;
        this.scrollTarget.scrollTop -= dy;
      }

      if (e.cancelable) {
        e.preventDefault();
      }
    }
  }

  onPointerUp() {
    if (!this.isPointerDown) return;
    this.isPointerDown = false;

    if (this.isDragging) {
      document.body.classList.remove("vr-grabbing");

      // Apply inertial momentum flick coasting
      const speed = Math.hypot(this.vx, this.vy);
      if (speed > 0.08 && this.scrollTarget) {
        this.startMomentum();
      } else {
        this.isDragging = false;
      }
    }
  }

  startMomentum() {
    let currVx = this.vx;
    let currVy = this.vy;
    let lastMomentumTime = performance.now();
    const friction = 0.92;

    const step = (time) => {
      const dt = Math.min(32, time - lastMomentumTime);
      lastMomentumTime = time;

      const deltaX = currVx * dt;
      const deltaY = currVy * dt;

      if (this.scrollTarget === window) {
        window.scrollBy({ left: -deltaX, top: -deltaY, behavior: "auto" });
      } else if (this.scrollTarget) {
        this.scrollTarget.scrollLeft -= deltaX;
        this.scrollTarget.scrollTop -= deltaY;
      }

      currVx *= Math.pow(friction, dt / 16);
      currVy *= Math.pow(friction, dt / 16);

      if (Math.hypot(currVx, currVy) > 0.015) {
        this.momentumRaf = requestAnimationFrame(step);
      } else {
        this.momentumRaf = null;
        this.isDragging = false;
      }
    };

    this.momentumRaf = requestAnimationFrame(step);
  }

  onClickCapture(e) {
    if (this.suppressClick) {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      this.suppressClick = false;
    }
  }
}

/* ==========================================================================
   2. 2D Spatial Gamepad & VR Controller Navigation Engine
   ========================================================================== */
class SpatialGamepadNavigator {
  constructor() {
    this.enabled = true;
    this.focusedElement = null;
    this.lastButtonStates = {};
    this.lastAxisTime = 0;
    this.axisThreshold = 0.55;
    this.repeatDelay = 210; // ms
    this.hudTimer = null;

    // Laser pointer aiming & context tracking
    this.laserPointedTarget = null;
    this.laserPointedScrollContainer = null;
    this.laserPointedFocusable = null;

    this.initHUD();
    this.bindEvents();
    this.pollLoop = this.pollLoop.bind(this);
    requestAnimationFrame(this.pollLoop);
  }

  initHUD() {
    let hud = document.getElementById("vr-controller-hud");
    if (!hud) {
      hud = document.createElement("div");
      hud.id = "vr-controller-hud";
      hud.className = "vr-controller-hud";
      hud.innerHTML = `
        <div class="vr-hud-item"><span class="vr-hud-key">A</span> Select</div>
        <div class="vr-hud-divider"></div>
        <div class="vr-hud-item"><span class="vr-hud-key">B</span> Back</div>
        <div class="vr-hud-divider"></div>
        <div class="vr-hud-item"><span class="vr-hud-key">X</span> Action</div>
        <div class="vr-hud-divider"></div>
        <div class="vr-hud-item"><span class="vr-hud-key">Y</span> Search</div>
        <div class="vr-hud-divider"></div>
        <div class="vr-hud-item"><span class="vr-hud-key">LB / RB</span> Tabs</div>
        <div class="vr-hud-divider"></div>
        <div class="vr-hud-item"><span class="vr-hud-key">R-Stick</span> Scroll</div>
        <div class="vr-hud-divider"></div>
        <div class="vr-hud-item" id="vr-hud-hands-item"><span class="vr-hud-key">🖐️ Pinch</span> Select / Drag</div>
      `;
      document.body.appendChild(hud);
    }
    this.hudElement = hud;
  }

  showHUD() {
    if (!this.hudElement) return;
    this.hudElement.classList.add("visible");
    clearTimeout(this.hudTimer);
    this.hudTimer = setTimeout(() => {
      this.hudElement.classList.remove("visible");
    }, 5500);
  }

  bindEvents() {
    window.addEventListener("gamepadconnected", (e) => {
      console.log(`[FrameLoad VR] Gamepad/Controller connected: ${e.gamepad.id}`);
      this.showToast(`🎮 Controller connected: ${e.gamepad.id.split("(")[0]}`);
      this.showHUD();
      this.refreshFocus();
    });

    window.addEventListener("gamepaddisconnected", () => {
      console.log("[FrameLoad VR] Controller disconnected");
    });

    // Track laser pointer ray coordinates & aimed scroll/focus targets
    const updateLaserAim = (e) => {
      let el = null;
      if (e.target && e.target.nodeType === 1 && e.target !== document.body && e.target !== document.documentElement) {
        el = e.target;
      } else if (typeof document.elementFromPoint === "function" && e.clientX && e.clientY) {
        el = document.elementFromPoint(e.clientX, e.clientY);
      }
      if (!el) return;

      this.laserPointedTarget = el;
      this.laserPointedScrollContainer = this.findScrollableContainerUnderPoint(el);
      const focusable = this.findFocusableUnderPoint(el);
      if (focusable) {
        this.laserPointedFocusable = focusable;
      }
    };
    window.addEventListener("pointermove", updateLaserAim, { passive: true });
    window.addEventListener("pointerdown", updateLaserAim, { passive: true });

    // Keyboard spatial navigation fallback (Arrow keys, Enter, Esc)
    window.addEventListener("keydown", (e) => {
      if (document.activeElement && (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA")) {
        if (e.key === "Escape") {
          document.activeElement.blur();
          e.preventDefault();
        }
        return;
      }

      switch (e.key) {
        case "ArrowUp":
          this.navigateSpatial("up");
          e.preventDefault();
          break;
        case "ArrowDown":
          this.navigateSpatial("down");
          e.preventDefault();
          break;
        case "ArrowLeft":
          this.navigateSpatial("left");
          e.preventDefault();
          break;
        case "ArrowRight":
          this.navigateSpatial("right");
          e.preventDefault();
          break;
        case "Enter":
        case " ":
          if (this.focusedElement) {
            this.focusedElement.click();
            e.preventDefault();
          }
          break;
        case "Escape":
          this.triggerBack();
          e.preventDefault();
          break;
      }
    });
  }

  findScrollableContainerUnderPoint(el) {
    if (!el || el === document.body || el === document.documentElement) return null;
    let curr = el;
    while (curr && curr !== document.body && curr !== document.documentElement) {
      const style = window.getComputedStyle(curr);
      const overflowY = style.overflowY;
      const overflowX = style.overflowX;
      const canScrollY = (overflowY === "auto" || overflowY === "scroll") && (curr.scrollHeight > curr.clientHeight + 4);
      const canScrollX = (overflowX === "auto" || overflowX === "scroll") && (curr.scrollWidth > curr.clientWidth + 4);
      if (canScrollY || canScrollX) {
        return { element: curr, canScrollY, canScrollX };
      }
      curr = curr.parentElement;
    }
    return null;
  }

  findFocusableUnderPoint(el) {
    if (!el) return null;
    const selector = [
      "button:not([disabled])",
      '[tabindex]:not([tabindex="-1"])',
      ".game-card",
      "input:not([disabled])",
      "select:not([disabled])",
      ".category-chip",
      ".tab-btn",
      ".telemetry-chip.kofi-chip"
    ].join(", ");
    return el.closest(selector);
  }

  getActiveModal() {
    return document.querySelector(".modal-backdrop.open");
  }

  getFocusableCandidates() {
    const activeModal = this.getActiveModal();
    const root = activeModal || document;

    const selector = [
      "button:not([disabled])",
      '[tabindex]:not([tabindex="-1"])',
      ".game-card",
      "input:not([disabled])",
      "select:not([disabled])",
      ".category-chip",
      ".tab-btn",
      ".telemetry-chip.kofi-chip"
    ].join(", ");

    const elements = Array.from(root.querySelectorAll(selector));

    return elements.filter((el) => {
      if (el.offsetParent === null) return false;
      const style = window.getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") return false;
      return true;
    });
  }

  updateFocusables() {
    this.refreshFocus();
  }

  refreshFocus() {
    const candidates = this.getFocusableCandidates();
    if (candidates.length === 0) return;

    if (this.focusedElement && !candidates.includes(this.focusedElement)) {
      this.setFocus(candidates[0]);
    }
  }

  setFocus(el) {
    if (!el) return;

    if (this.focusedElement) {
      this.focusedElement.classList.remove("gamepad-focused");
    }

    this.focusedElement = el;
    this.focusedElement.classList.add("gamepad-focused");

    // Scroll into view with comfortable margins
    this.focusedElement.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "nearest"
    });

    if (document.activeElement !== this.focusedElement && this.focusedElement.tagName !== "INPUT") {
      this.focusedElement.focus({ preventScroll: true });
    }
  }

  navigateSpatial(direction) {
    const candidates = this.getFocusableCandidates();
    if (candidates.length === 0) return;

    this.showHUD();

    // Laser-Aim Context Anchor: If user has pointed the laser ray at a focusable element,
    // establish it as the spatial navigation origin immediately!
    if (this.laserPointedFocusable && candidates.includes(this.laserPointedFocusable)) {
      if (this.focusedElement !== this.laserPointedFocusable) {
        this.setFocus(this.laserPointedFocusable);
        this.laserPointedFocusable = null;
        return;
      }
    }

    if (!this.focusedElement || !candidates.includes(this.focusedElement)) {
      this.setFocus(candidates[0]);
      return;
    }

    const currentRect = this.focusedElement.getBoundingClientRect();
    const currentCenter = {
      x: currentRect.left + currentRect.width / 2,
      y: currentRect.top + currentRect.height / 2
    };

    let bestCandidate = null;
    let minScore = Infinity;

    for (const candidate of candidates) {
      if (candidate === this.focusedElement) continue;

      const r = candidate.getBoundingClientRect();
      const c = {
        x: r.left + r.width / 2,
        y: r.top + r.height / 2
      };

      const dx = c.x - currentCenter.x;
      const dy = c.y - currentCenter.y;

      let validDirection = false;
      let primaryDist = 0;
      let secondaryDist = 0;

      if (direction === "down" && dy > 6) {
        validDirection = true;
        primaryDist = dy;
        secondaryDist = Math.abs(dx);
      } else if (direction === "up" && dy < -6) {
        validDirection = true;
        primaryDist = -dy;
        secondaryDist = Math.abs(dx);
      } else if (direction === "right" && dx > 6) {
        validDirection = true;
        primaryDist = dx;
        secondaryDist = Math.abs(dy);
      } else if (direction === "left" && dx < -6) {
        validDirection = true;
        primaryDist = -dx;
        secondaryDist = Math.abs(dy);
      }

      if (validDirection) {
        // Primary axis distance + heavy perpendicular alignment penalty
        const score = primaryDist + secondaryDist * 2.6;
        if (score < minScore) {
          minScore = score;
          bestCandidate = candidate;
        }
      }
    }

    if (bestCandidate) {
      this.setFocus(bestCandidate);
    } else {
      // Fallback edge boundaries: jump between rows and header
      if (direction === "up") {
        const chips = document.querySelector(".category-chip.active, .category-chip");
        if (chips && chips !== this.focusedElement) this.setFocus(chips);
      } else if (direction === "down" && this.focusedElement.classList.contains("tab-btn")) {
        const search = document.getElementById("search-input");
        if (search) this.setFocus(search);
      }
    }
  }

  getActiveScrollContainer() {
    // 1. Check if laser pointer is currently aiming at a scrollable sub-container (chips carousel, notes, logs, queue)
    if (this.laserPointedScrollContainer && this.laserPointedScrollContainer.element && this.laserPointedScrollContainer.element.isConnected) {
      const el = this.laserPointedScrollContainer.element;
      if (el.offsetParent !== null && window.getComputedStyle(el).display !== "none") {
        return this.laserPointedScrollContainer;
      }
    }

    // 2. Fallback to active modal body if modal is open
    const openModal = this.getActiveModal();
    if (openModal) {
      const modalBody = openModal.querySelector(".modal-body, .modal-content, .card-details-grid");
      if (modalBody) return { element: modalBody, canScrollY: true, canScrollX: false };
    }

    // 3. Fallback to main window
    return { element: window, canScrollY: true, canScrollX: false };
  }

  pollLoop() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (let i = 0; i < gamepads.length; i++) {
      const gp = gamepads[i];
      if (!gp) continue;
      this.handleGamepad(gp);
      break; // Primary VR controller
    }
    requestAnimationFrame(this.pollLoop);
  }

  handleGamepad(gp) {
    const now = Date.now();

    // 1. Left Stick & D-Pad (2D Spatial Navigation)
    const axisLX = gp.axes[0] || 0;
    const axisLY = gp.axes[1] || 0;
    const dpadUp = gp.buttons[12]?.pressed;
    const dpadDown = gp.buttons[13]?.pressed;
    const dpadLeft = gp.buttons[14]?.pressed;
    const dpadRight = gp.buttons[15]?.pressed;

    if (now - this.lastAxisTime > this.repeatDelay) {
      if (axisLY > this.axisThreshold || dpadDown) {
        this.navigateSpatial("down");
        this.lastAxisTime = now;
      } else if (axisLY < -this.axisThreshold || dpadUp) {
        this.navigateSpatial("up");
        this.lastAxisTime = now;
      } else if (axisLX > this.axisThreshold || dpadRight) {
        this.navigateSpatial("right");
        this.lastAxisTime = now;
      } else if (axisLX < -this.axisThreshold || dpadLeft) {
        this.navigateSpatial("left");
        this.lastAxisTime = now;
      }
    }

    // 2. Right Stick (Analog View Smooth Scroll)
    const axisRX = gp.axes[2] ?? gp.axes[4] ?? 0;
    const axisRY = gp.axes[3] ?? gp.axes[5] ?? 0;
    const deadzone = 0.16;

    if (Math.abs(axisRY) > deadzone || Math.abs(axisRX) > deadzone) {
      const scrollInfo = this.getActiveScrollContainer();
      const target = scrollInfo.element;
      const canScrollX = scrollInfo.canScrollX;
      const canScrollY = scrollInfo.canScrollY;

      let scrollX = 0;
      let scrollY = 0;

      if (canScrollX && !canScrollY) {
        // Horizontally-oriented sub-container (e.g. Category chips bar):
        // Allow either vertical or horizontal tilt of the stick to scroll horizontally!
        const effective = Math.abs(axisRX) > deadzone ? axisRX : (Math.abs(axisRY) > deadzone ? axisRY : 0);
        scrollX = effective * 18;
      } else {
        scrollX = Math.abs(axisRX) > deadzone ? axisRX * 18 : 0;
        scrollY = Math.abs(axisRY) > deadzone ? axisRY * 18 : 0;
      }

      if (target === window) {
        window.scrollBy({ left: scrollX, top: scrollY, behavior: "auto" });
      } else {
        target.scrollTop += scrollY;
        target.scrollLeft += scrollX;
      }
      this.showHUD();
    }

    // 3. Buttons
    const aBtn = gp.buttons[0]?.pressed; // A / Trigger / Cross: Select
    const bBtn = gp.buttons[1]?.pressed; // B / Grip / Circle: Back/Close
    const xBtn = gp.buttons[2]?.pressed; // X / Primary Thumb: Action
    const yBtn = gp.buttons[3]?.pressed; // Y / Secondary Thumb: Search
    const lbBtn = gp.buttons[4]?.pressed; // LB: Prev Tab
    const rbBtn = gp.buttons[5]?.pressed; // RB: Next Tab
    const ltBtn = gp.buttons[6]?.pressed; // LT: Fast Page Up
    const rtBtn = gp.buttons[7]?.pressed; // RT: Fast Page Down

    if (aBtn && !this.lastButtonStates.a) {
      this.triggerSelect();
      this.showHUD();
    }
    if (bBtn && !this.lastButtonStates.b) {
      this.triggerBack();
      this.showHUD();
    }
    if (xBtn && !this.lastButtonStates.x) {
      this.triggerAction();
      this.showHUD();
    }
    if (yBtn && !this.lastButtonStates.y) {
      this.triggerSearch();
      this.showHUD();
    }
    if (lbBtn && !this.lastButtonStates.lb) {
      this.switchTab(-1);
      this.showHUD();
    }
    if (rbBtn && !this.lastButtonStates.rb) {
      this.switchTab(1);
      this.showHUD();
    }
    if (ltBtn && !this.lastButtonStates.lt) {
      this.pageScroll(-300);
    }
    if (rtBtn && !this.lastButtonStates.rt) {
      this.pageScroll(300);
    }

    this.lastButtonStates = {
      a: aBtn,
      b: bBtn,
      x: xBtn,
      y: yBtn,
      lb: lbBtn,
      rb: rbBtn,
      lt: ltBtn,
      rt: rtBtn
    };
  }

  pageScroll(offset) {
    const scrollInfo = this.getActiveScrollContainer();
    const target = scrollInfo.element;
    if (target === window) {
      window.scrollBy({ top: offset, behavior: "smooth" });
    } else {
      target.scrollBy({ top: offset, behavior: "smooth" });
    }
    this.showHUD();
  }

  triggerSelect() {
    if (this.focusedElement) {
      this.focusedElement.click();
    }
  }

  triggerBack() {
    const modal = this.getActiveModal();
    if (modal) {
      const closeBtn = modal.querySelector(".modal-close-btn, .btn-secondary, [onclick*='close']");
      if (closeBtn) {
        closeBtn.click();
      } else {
        modal.classList.remove("open");
      }
      this.refreshFocus();
      return true;
    }

    if (document.activeElement && document.activeElement.tagName === "INPUT") {
      document.activeElement.blur();
      this.refreshFocus();
      return true;
    }

    return false;
  }

  triggerAction() {
    if (!this.focusedElement) return;

    if (this.focusedElement.classList.contains("game-card")) {
      const btn = this.focusedElement.querySelector(".card-btn");
      if (btn) {
        btn.click();
        return;
      }
    }

    this.focusedElement.click();
  }

  triggerSearch() {
    const searchInput = document.getElementById("search-input");
    if (searchInput) {
      this.setFocus(searchInput);
      searchInput.focus();
    }
  }

  switchTab(direction) {
    const tabs = Array.from(document.querySelectorAll(".tab-btn"));
    if (tabs.length === 0) return;

    const currentIdx = tabs.findIndex((t) => t.classList.contains("active"));
    const nextIdx = (currentIdx + direction + tabs.length) % tabs.length;
    tabs[nextIdx]?.click();
    setTimeout(() => this.refreshFocus(), 150);
  }

  showToast(msg) {
    if (window.showToast) {
      window.showToast(msg);
    }
  }
}

/* ==========================================================================
   3. WebXR Hand Tracking & Gesture Navigation Engine
   ========================================================================== */
class VRHandTrackingEngine {
  constructor() {
    this.supported = false;
    this.activeSession = null;
    this.refSpace = null;
    this.isTracking = false;
    this.pinchThresholdMm = 24.0;
    this.pinchReleaseMm = 35.0;

    this.hands = {
      left: {
        active: false,
        pinching: false,
        x: -100,
        y: -100,
        tipDistMm: 50.0,
        pinchStrength: 0,
        startTime: 0,
        startX: 0,
        startY: 0,
        isDragging: false,
        scrollTarget: null,
        targetEl: null,
      },
      right: {
        active: false,
        pinching: false,
        x: -100,
        y: -100,
        tipDistMm: 50.0,
        pinchStrength: 0,
        startTime: 0,
        startX: 0,
        startY: 0,
        isDragging: false,
        scrollTarget: null,
        targetEl: null,
      },
    };

    this.reticles = {};
    this.initReticles();
    this.initWebXR();
  }

  initReticles() {
    ["left", "right"].forEach((handKey) => {
      let reticle = document.getElementById(`vr-hand-reticle-${handKey}`);
      if (!reticle) {
        reticle = document.createElement("div");
        reticle.id = `vr-hand-reticle-${handKey}`;
        reticle.className = `vr-hand-reticle vr-hand-${handKey}`;
        reticle.innerHTML = `
          <div class="vr-hand-pinch-glow"></div>
          <div class="vr-hand-ring vr-hand-thumb-ring"></div>
          <div class="vr-hand-ring vr-hand-index-ring"></div>
          <div class="vr-hand-center-dot"></div>
          <div class="vr-hand-label">${handKey === "left" ? "L" : "R"}</div>
        `;
        document.body.appendChild(reticle);
      }
      this.reticles[handKey] = reticle;
    });
  }

  initWebXR() {
    if (!navigator.xr) {
      console.log("[FrameLoad VR] WebXR not available in this environment. Hand tracking running in emulation/bridge mode.");
      return;
    }

    navigator.xr.isSessionSupported("immersive-vr").then((supported) => {
      this.supported = supported;
      if (supported) {
        console.log("[FrameLoad VR] WebXR Immersive VR supported with Hand Tracking extensions.");
        this.updateHUDHandsStatus(true, "WebXR Ready");
      }
    }).catch(() => {});
  }

  attachSession(session, refSpace) {
    this.activeSession = session;
    this.refSpace = refSpace;
    this.isTracking = true;
    this.updateHUDHandsStatus(true, "Hands Active");

    session.addEventListener("end", () => {
      this.activeSession = null;
      this.isTracking = false;
      this.hideReticles();
      this.updateHUDHandsStatus(false, "Disconnected");
    });
  }

  updateFromXRFrame(frame, refSpace) {
    if (!frame || !this.activeSession) return;
    const session = this.activeSession;
    const space = refSpace || this.refSpace;
    if (!space) return;

    for (const source of session.inputSources) {
      if (!source.hand) continue;

      const handKey = source.handedness === "left" ? "left" : "right";
      const handState = this.hands[handKey];
      const reticle = this.reticles[handKey];

      const thumbTipJoint = source.hand.get("thumb-tip");
      const indexTipJoint = source.hand.get("index-finger-tip");

      if (!thumbTipJoint || !indexTipJoint) continue;

      const thumbPose = frame.getJointPose(thumbTipJoint, space);
      const indexPose = frame.getJointPose(indexTipJoint, space);

      if (!thumbPose || !indexPose) {
        handState.active = false;
        if (reticle) reticle.classList.remove("active");
        continue;
      }

      handState.active = true;
      if (reticle) reticle.classList.add("active");

      // 3D Distance in millimeters
      const dx = thumbPose.transform.position.x - indexPose.transform.position.x;
      const dy = thumbPose.transform.position.y - indexPose.transform.position.y;
      const dz = thumbPose.transform.position.z - indexPose.transform.position.z;
      const distMm = Math.hypot(dx, dy, dz) * 1000.0;
      handState.tipDistMm = distMm;

      // Project pointer aim pose to 2D screen coordinate
      let screenX = (indexPose.transform.position.x + 0.5) * window.innerWidth;
      let screenY = (-indexPose.transform.position.y + 0.5) * window.innerHeight;

      if (source.targetRaySpace) {
        const rayPose = frame.getPose(source.targetRaySpace, space);
        if (rayPose) {
          screenX = (rayPose.transform.position.x * 2.0 + 0.5) * window.innerWidth;
          screenY = (-rayPose.transform.position.y * 2.0 + 0.5) * window.innerHeight;
        }
      }

      screenX = Math.max(10, Math.min(window.innerWidth - 10, screenX));
      screenY = Math.max(10, Math.min(window.innerHeight - 10, screenY));

      this.processHandPosition(handKey, screenX, screenY, distMm, source);
    }
  }

  processHandPosition(handKey, x, y, distMm, source = null) {
    const hand = this.hands[handKey];
    const reticle = this.reticles[handKey];
    if (!reticle) return;

    hand.x = x;
    hand.y = y;

    reticle.style.left = `${x}px`;
    reticle.style.top = `${y}px`;

    // Dynamic visual ring convergence as fingers get closer
    const thumbRing = reticle.querySelector(".vr-hand-thumb-ring");
    const indexRing = reticle.querySelector(".vr-hand-index-ring");
    const convergence = Math.max(0, Math.min(1, (distMm - this.pinchThresholdMm) / 32.0));

    if (thumbRing && indexRing) {
      thumbRing.style.transform = `translate(${-4 * convergence}px, ${-4 * convergence}px)`;
      indexRing.style.transform = `translate(${4 * convergence}px, ${4 * convergence}px)`;
    }

    // Pinch detection state machine
    if (!hand.pinching && distMm <= this.pinchThresholdMm) {
      this.onPinchDown(handKey, x, y, source);
    } else if (hand.pinching && distMm >= this.pinchReleaseMm) {
      this.onPinchUp(handKey, x, y);
    } else if (hand.pinching) {
      this.onPinchMove(handKey, x, y);
    }
  }

  onPinchDown(handKey, x, y, source = null) {
    const hand = this.hands[handKey];
    const reticle = this.reticles[handKey];

    hand.pinching = true;
    hand.startTime = performance.now();
    hand.startX = x;
    hand.startY = y;
    hand.isDragging = false;
    hand.targetEl = document.elementFromPoint(x, y);

    if (reticle) {
      reticle.classList.add("pinching");
    }

    // Find scroll target
    hand.scrollTarget = window.vrLaserDragEngine?.findScrollTarget(hand.targetEl) || window;

    // Trigger haptic feedback pulse on pinch
    if (source && source.gamepad && source.gamepad.hapticActuators && source.gamepad.hapticActuators[0]) {
      try {
        source.gamepad.hapticActuators[0].pulse(0.35, 25);
      } catch (_) {}
    }
  }

  onPinchMove(handKey, x, y) {
    const hand = this.hands[handKey];
    const dx = x - hand.startX;
    const dy = y - hand.startY;
    const dist = Math.hypot(dx, dy);

    if (!hand.isDragging && dist >= 8) {
      hand.isDragging = true;
      document.body.classList.add("vr-grabbing");
    }

    if (hand.isDragging && hand.scrollTarget) {
      const scrollDx = x - hand.x;
      const scrollDy = y - hand.y;

      if (hand.scrollTarget === window) {
        window.scrollBy({ left: -scrollDx, top: -scrollDy, behavior: "auto" });
      } else {
        hand.scrollTarget.scrollLeft -= scrollDx;
        hand.scrollTarget.scrollTop -= scrollDy;
      }
    }
  }

  onPinchUp(handKey, x, y) {
    const hand = this.hands[handKey];
    const reticle = this.reticles[handKey];

    hand.pinching = false;
    if (reticle) {
      reticle.classList.remove("pinching");
    }

    if (hand.isDragging) {
      hand.isDragging = false;
      document.body.classList.remove("vr-grabbing");
    } else {
      // Tap / Click action
      const duration = performance.now() - hand.startTime;
      if (duration < 450) {
        const el = document.elementFromPoint(x, y);
        if (el) {
          window.vrLaserDragEngine?.createLaserRipple(x, y);
          el.click();
        }
      }
    }
  }

  updateHUDHandsStatus(active, label = "") {
    const hudItem = document.getElementById("vr-hud-hands-item");
    if (hudItem) {
      if (active) {
        hudItem.innerHTML = `<span class="vr-hud-key" style="border-color:#00ff88; color:#00ff88;">🖐️ ${label || "Tracking"}</span> Pinch / Drag`;
      } else {
        hudItem.innerHTML = `<span class="vr-hud-key">🖐️ Pinch</span> Select / Drag`;
      }
    }
  }

  hideReticles() {
    ["left", "right"].forEach((handKey) => {
      const reticle = this.reticles[handKey];
      if (reticle) reticle.classList.remove("active", "pinching");
    });
  }
}

// Global initialization
document.addEventListener("DOMContentLoaded", () => {
  window.vrLaserDragEngine = new VRLaserDragEngine();
  window.vrControllerEngine = new SpatialGamepadNavigator();
  window.vrHandEngine = new VRHandTrackingEngine();
  // Backward compatibility alias for any existing references
  window.gamepadNav = window.vrControllerEngine;
});

