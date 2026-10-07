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
    const openModal = this.getActiveModal();
    if (openModal) {
      const modalBody = openModal.querySelector(".modal-body, .modal-content, .card-details-grid");
      if (modalBody) return modalBody;
    }
    return window;
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
      const scrollContainer = this.getActiveScrollContainer();
      const scrollY = Math.abs(axisRY) > deadzone ? axisRY * 18 : 0;
      const scrollX = Math.abs(axisRX) > deadzone ? axisRX * 18 : 0;

      if (scrollContainer === window) {
        window.scrollBy({ left: scrollX, top: scrollY, behavior: "auto" });
      } else {
        scrollContainer.scrollTop += scrollY;
        scrollContainer.scrollLeft += scrollX;
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
    const container = this.getActiveScrollContainer();
    if (container === window) {
      window.scrollBy({ top: offset, behavior: "smooth" });
    } else {
      container.scrollBy({ top: offset, behavior: "smooth" });
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

// Global initialization
document.addEventListener("DOMContentLoaded", () => {
  window.vrLaserDragEngine = new VRLaserDragEngine();
  window.vrControllerEngine = new SpatialGamepadNavigator();
  // Backward compatibility alias for any existing references
  window.gamepadNav = window.vrControllerEngine;
});
