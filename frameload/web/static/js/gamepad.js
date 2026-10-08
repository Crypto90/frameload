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
 *  6. On-screen scroll controls:
 *     Top / up / down buttons for the laser pointer, so scrolling never depends on a stick.
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
    window.addEventListener("pointercancel", (e) => {
      if (this.isDragging) {
        this.onPointerUp(e);
      } else {
        this.isPointerDown = false;
        this.isDragging = false;
      }
    }, { passive: false });
    window.addEventListener("click", this.onClickCapture, { capture: true });
    // Prevent default browser dragstart on images/cards from killing pointer drag
    window.addEventListener("dragstart", (e) => {
      e.preventDefault();
      return false;
    }, { capture: true });
  }

  findScrollTarget(el) {
    if (!el || el === document.body || el === document.documentElement) {
      return window;
    }

    // Check for open modal body first
    const openModals = document.querySelectorAll(".modal-backdrop.open");
    const openModal = openModals.length ? openModals[openModals.length - 1] : null;
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
      setTimeout(() => {
        this.suppressClick = false;
      }, 80);
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
    this.stickHoldTimes = {};
    this.lastAxisTime = 0;
    this.axisThreshold = 0.52;
    this.repeatDelay = 200; // ms
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
        <div class="vr-hud-item"><span class="vr-hud-key">LT / RT</span> Page</div>
        <div class="vr-hud-divider"></div>
        <div class="vr-hud-item"><span class="vr-hud-key">Stick Click</span> Top</div>
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
      "button:not([disabled]):not([data-nav-skip])",
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
    const open = document.querySelectorAll(".modal-backdrop.open");
    return open.length ? open[open.length - 1] : null;
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

    // A focused slider takes left/right itself; up/down still leave it.
    const current = this.focusedElement;
    if (current && current.isConnected && current.type === "range" && (direction === "left" || direction === "right")) {
      if (direction === "left") current.stepDown(); else current.stepUp();
      current.dispatchEvent(new Event("input", { bubbles: true }));
      current.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }

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

    // 2. Check if current focused element is inside a scrollable container
    if (this.focusedElement && this.focusedElement.isConnected) {
      const focusedContainer = this.findScrollableContainerUnderPoint(this.focusedElement);
      if (focusedContainer) return focusedContainer;
    }

    // 3. Fallback to active modal body if modal is open
    const openModal = this.getActiveModal();
    if (openModal) {
      const modalBody = openModal.querySelector(".modal-body, .modal-content, .card-details-grid, .settings-modal-body");
      if (modalBody) {
        return {
          element: modalBody,
          canScrollY: modalBody.scrollHeight > modalBody.clientHeight,
          canScrollX: modalBody.scrollWidth > modalBody.clientWidth
        };
      }
    }

    // 4. Fallback to main window
    const docEl = document.scrollingElement || document.documentElement || document.body;
    return {
      element: window,
      canScrollY: true,
      canScrollX: (docEl && docEl.scrollWidth > window.innerWidth)
    };
  }

  // The innermost scrollable element under the laser (or the focused control) that can still move in
  // the stick's direction. A list at its end hands over to the page, the way a mouse wheel does.
  pickScroller(dx, dy) {
    const vertical = Math.abs(dy) >= Math.abs(dx);
    const start = (this.laserPointedTarget && this.laserPointedTarget.isConnected && this.laserPointedTarget)
      || (this.focusedElement && this.focusedElement.isConnected && this.focusedElement) || null;
    const modal = this.getActiveModal();
    let el = start && (!modal || modal.contains(start)) ? start : (modal ? modal.querySelector(".modal-content") : null);
    while (el && el !== document.body && el !== document.documentElement) {
      const style = window.getComputedStyle(el);
      if (vertical && /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 4) {
        const room = dy > 0 ? el.scrollTop < el.scrollHeight - el.clientHeight - 1 : el.scrollTop > 0;
        if (room) return el;
      }
      if (!vertical && /(auto|scroll)/.test(style.overflowX) && el.scrollWidth > el.clientWidth + 4) {
        const room = dx > 0 ? el.scrollLeft < el.scrollWidth - el.clientWidth - 1 : el.scrollLeft > 0;
        if (room) return el;
      }
      el = el.parentElement;
    }
    return modal ? null : window;  // behind an open dialog the page stays put
  }

  scrollToTop() {
    const modal = this.getActiveModal();
    const target = modal ? modal.querySelector(".modal-content") : window;
    if (target) target.scrollTo({ top: 0, behavior: "smooth" });
    this.showHUD();
  }

  pollLoop() {
    const rawGamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (let i = 0; i < rawGamepads.length; i++) {
      const gp = rawGamepads[i];
      if (!gp) continue;
      this.handleGamepad(gp, i);
    }
    requestAnimationFrame(this.pollLoop);
  }

  applyAnalogScroll(axisX, axisY) {
    const deadzone = 0.12;
    const absX = Math.abs(axisX);
    const absY = Math.abs(axisY);

    if (absX <= deadzone && absY <= deadzone) return;

    const target = this.pickScroller(axisX, axisY);
    if (!target) return;

    // Smooth response curve with fine micro-adjustment and high max speed
    const calcSpeed = (val) => {
      const mag = Math.abs(val);
      if (mag <= deadzone) return 0;
      const normalized = (mag - deadzone) / (1 - deadzone);
      return Math.sign(val) * Math.pow(normalized, 1.35) * 26; // max 26px per frame
    };

    let scrollX = calcSpeed(axisX);
    let scrollY = calcSpeed(axisY);
    // One direction at a time: a slightly diagonal push must not drift sideways.
    if (Math.abs(scrollY) >= Math.abs(scrollX)) scrollX = 0; else scrollY = 0;

    if (target === window) {
      window.scrollBy({ left: scrollX, top: scrollY, behavior: "auto" });
    } else if (target) {
      target.scrollTop += scrollY;
      target.scrollLeft += scrollX;
    }
    this.showHUD();
  }

  handleGamepad(gp, gpIndex) {
    const now = Date.now();
    const gpKey = `${gpIndex}_${gp.id || ""}`;
    if (!this.lastButtonStates[gpKey]) {
      this.lastButtonStates[gpKey] = {};
    }
    const prev = this.lastButtonStates[gpKey];

    const hand = (gp.hand || "").toLowerCase();
    const id = (gp.id || "").toLowerCase();
    const isExplicitRight = (hand === "right" || id.includes("right") || id.includes("(r)") || id.includes("right controller"));
    const isExplicitLeft = (hand === "left" || id.includes("left") || id.includes("(l)") || id.includes("left controller"));
    const isDualStick = gp.axes.length >= 4;
    const isRightVR = isExplicitRight && gp.axes.length <= 3;
    const isLeftVR = isExplicitLeft && gp.axes.length <= 3;

    // 1. Right Thumbstick Analog Smooth Scroll (Dedicated for Right VR Controller or Dual Stick Gamepad)
    if (isRightVR) {
      // On Right VR Motion Controller, the stick is on axes 0 (X) and 1 (Y)
      const stickRX = gp.axes[0] || 0;
      const stickRY = gp.axes[1] || 0;
      this.applyAnalogScroll(stickRX, stickRY);
    } else if (isDualStick) {
      // Standard Gamepad / Steam Deck right stick (axes 2 & 3 or 4 & 5)
      const stickRX = gp.axes[2] ?? gp.axes[4] ?? 0;
      const stickRY = gp.axes[3] ?? gp.axes[5] ?? 0;
      this.applyAnalogScroll(stickRX, stickRY);
    }

    // 2. Left Stick / Spatial Navigation Stick
    const axisLX = gp.axes[0] || 0;
    const axisLY = gp.axes[1] || 0;
    const dpadUp = gp.buttons[12]?.pressed;
    const dpadDown = gp.buttons[13]?.pressed;
    const dpadLeft = gp.buttons[14]?.pressed;
    const dpadRight = gp.buttons[15]?.pressed;

    const stickTilted = Math.abs(axisLX) > 0.15 || Math.abs(axisLY) > 0.15;
    const dpadPressed = dpadUp || dpadDown || dpadLeft || dpadRight;
    if (dpadPressed && !stickTilted && now - this.lastAxisTime > this.repeatDelay) {
      // The D-pad used to be read only while a stick was tilted as well.
      this.navigateSpatial(dpadDown ? "down" : dpadUp ? "up" : dpadRight ? "right" : "left");
      this.lastAxisTime = now;
    }
    if (stickTilted) {
      if (!this.stickHoldTimes[gpKey]) {
        this.stickHoldTimes[gpKey] = now;
      }
      const holdDuration = now - this.stickHoldTimes[gpKey];
      // A controller with a single stick has no second stick to scroll with: holding it scrolls.
      const holdScrolls = !isDualStick && !isRightVR && holdDuration > 280;

      // Discrete spatial navigation jumps
      if (!holdScrolls && now - this.lastAxisTime > this.repeatDelay) {
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

      // If user holds the Left stick for > 280ms or in single-controller mode, also provide smooth scroll
      if (holdScrolls) {
        this.applyAnalogScroll(axisLX * 0.85, axisLY * 0.85);
      }
    } else {
      this.stickHoldTimes[gpKey] = 0;
    }

    // 3. Controller Buttons (Contextual Mapping)
    const aBtn = gp.buttons[0]?.pressed; // A / Trigger / Cross
    const bBtn = gp.buttons[1]?.pressed; // B / Grip / Circle
    const xBtn = gp.buttons[2]?.pressed; // X / Primary Thumb
    const yBtn = gp.buttons[3]?.pressed; // Y / Secondary Thumb
    const lbBtn = gp.buttons[4]?.pressed; // LB: Prev Tab
    const rbBtn = gp.buttons[5]?.pressed; // RB: Next Tab
    const ltBtn = gp.buttons[6]?.pressed; // LT: Fast Page Up
    const rtBtn = gp.buttons[7]?.pressed; // RT: Fast Page Down
    const stickBtn = gp.buttons[10]?.pressed || gp.buttons[11]?.pressed; // stick click: back to top

    if (aBtn && !prev.a) {
      this.triggerSelect();
      this.showHUD();
    }
    if (bBtn && !prev.b) {
      this.triggerBack();
      this.showHUD();
    }
    if (xBtn && !prev.x) {
      this.triggerAction();
      this.showHUD();
    }
    if (yBtn && !prev.y) {
      this.triggerSearch();
      this.showHUD();
    }
    if (lbBtn && !prev.lb) {
      this.switchTab(-1);
      this.showHUD();
    }
    if (rbBtn && !prev.rb) {
      this.switchTab(1);
      this.showHUD();
    }
    if (ltBtn && !prev.lt) {
      this.pageScroll(-1);
    }
    if (rtBtn && !prev.rt) {
      this.pageScroll(1);
    }
    if (stickBtn && !prev.stick) {
      this.scrollToTop();
    }

    this.lastButtonStates[gpKey] = {
      a: aBtn,
      b: bBtn,
      x: xBtn,
      y: yBtn,
      lb: lbBtn,
      rb: rbBtn,
      lt: ltBtn,
      rt: rtBtn,
      stick: stickBtn
    };
  }

  // direction: -1 up, 1 down; moves most of one screen
  pageScroll(direction) {
    const target = this.pickScroller(0, direction);
    if (!target) return;
    const height = target === window ? window.innerHeight : target.clientHeight;
    target.scrollBy({ top: direction * Math.round(height * 0.8), behavior: "smooth" });
    this.showHUD();
  }

  triggerSelect() {
    const el = this.focusedElement;
    if (!el) return;
    if (el.tagName === "SELECT") {
      // A script cannot open a native dropdown, so Select steps through its options.
      const options = Array.from(el.options).filter(o => !o.disabled && !o.hidden);
      if (options.length === 0) return;
      const next = options[(options.indexOf(el.selectedOptions[0]) + 1) % options.length];
      el.value = next.value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    el.click();
  }

  triggerBack() {
    const modal = this.getActiveModal();
    if (modal) {
      const closeBtn = modal.querySelector("[data-back]") || modal.querySelector(".modal-close")
        || modal.querySelector(".modal-close-btn, .btn-secondary, [onclick*='close']");
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

    if (this.focusedElement.tagName === "INPUT" || this.focusedElement.tagName === "TEXTAREA") {
      this.focusedElement.focus();
      if (window.SteamOSK && window.SteamOSK.enabled) {
        window.SteamOSK.trigger("show");
      }
      return;
    }

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
      if (window.SteamOSK && window.SteamOSK.enabled) {
        window.SteamOSK.trigger("show");
      }
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
   3. On-screen scroll controls, keyboard paging and input diagnostics
   ========================================================================== */
class ScrollAssist {
  constructor() {
    this.repeat = null;
    this.rail = document.createElement("div");
    this.rail.className = "scroll-rail";
    this.rail.innerHTML = `
      <button type="button" data-nav-skip data-scroll="top" aria-label="Back to top" title="Back to top">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="4" x2="19" y2="4"></line><polyline points="6 14 12 8 18 14"></polyline><line x1="12" y1="8" x2="12" y2="21"></line></svg>
      </button>
      <button type="button" data-nav-skip data-scroll="up" aria-label="Scroll up" title="Scroll up (hold)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 15 12 9 18 15"></polyline></svg>
      </button>
      <button type="button" data-nav-skip data-scroll="down" aria-label="Scroll down" title="Scroll down (hold)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </button>`;
    document.body.appendChild(this.rail);

    this.rail.addEventListener("pointerdown", (e) => {
      const btn = e.target.closest("[data-scroll]");
      if (!btn) return;
      e.stopPropagation();  // not a drag-to-scroll gesture
      this.press(btn.dataset.scroll);
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach(type =>
      this.rail.addEventListener(type, () => this.release()));
    window.addEventListener("blur", () => this.release());

    // Page keys reach the open dialog too, and work whatever currently has focus.
    window.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const height = this.viewHeight();
      if (e.key === "PageDown") this.scroller().scrollBy({ top: height * 0.8, behavior: "smooth" });
      else if (e.key === "PageUp") this.scroller().scrollBy({ top: -height * 0.8, behavior: "smooth" });
      else if (e.key === "Home") this.scroller().scrollTo({ top: 0, behavior: "smooth" });
      else if (e.key === "End") this.scroller().scrollTo({ top: 1e7, behavior: "smooth" });
      else return;
      e.preventDefault();
    });

    window.addEventListener("scroll", () => this.update(), { passive: true, capture: true });
    window.addEventListener("resize", () => this.update());
    // Content arrives after loads and tab changes; reacting in the same frame keeps the
    // card grid from jumping when the arrows appear.
    const content = document.querySelector(".main-content");
    if (content && window.ResizeObserver) new ResizeObserver(() => this.update()).observe(content);
    setInterval(() => this.update(), 600);
    this.update();
  }

  scroller() {
    const open = document.querySelectorAll(".modal-backdrop.open .modal-content");
    return open.length ? open[open.length - 1] : window;
  }

  viewHeight() {
    const target = this.scroller();
    return target === window ? window.innerHeight : target.clientHeight;
  }

  metrics() {
    const target = this.scroller();
    if (target === window) {
      const doc = document.scrollingElement || document.documentElement;
      return { top: window.scrollY, max: doc.scrollHeight - window.innerHeight };
    }
    return { top: target.scrollTop, max: target.scrollHeight - target.clientHeight };
  }

  press(kind) {
    this.release();
    const target = this.scroller();
    if (kind === "top") {
      target.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const step = kind === "down" ? 1 : -1;
    target.scrollBy({ top: step * 140, behavior: "smooth" });  // a tap moves a little
    let speed = 10;
    this.repeat = setTimeout(() => {                             // holding keeps going, faster and faster
      this.repeat = setInterval(() => {
        speed = Math.min(speed + 0.6, 46);
        target.scrollBy({ top: step * speed, behavior: "auto" });
      }, 16);
    }, 300);
  }

  release() {
    clearTimeout(this.repeat);
    clearInterval(this.repeat);
    this.repeat = null;
  }

  update() {
    const { top, max } = this.metrics();
    this.rail.classList.toggle("visible", max > 40);
    this.rail.classList.toggle("in-dialog", this.scroller() !== window);
    this.rail.querySelector('[data-scroll="top"]').disabled = top < 60;
    this.rail.querySelector('[data-scroll="up"]').disabled = top < 2;
    this.rail.querySelector('[data-scroll="down"]').disabled = top > max - 2;
  }
}

// What actually reaches the page from the controllers: shown by System > Controller Test.
window.FrameLoadInput = {
  last: { wheel: null, key: null, pointer: null },
  init() {
    window.addEventListener("wheel", (e) => {
      this.last.wheel = { deltaX: Math.round(e.deltaX), deltaY: Math.round(e.deltaY), time: Date.now() };
    }, { passive: true, capture: true });
    window.addEventListener("keydown", (e) => {
      this.last.key = { key: e.key, time: Date.now() };
    }, { capture: true });
    window.addEventListener("pointerdown", (e) => {
      this.last.pointer = { type: e.pointerType || "unknown", time: Date.now() };
    }, { capture: true });
  },
  snapshot() {
    const pads = navigator.getGamepads ? Array.from(navigator.getGamepads()).filter(Boolean) : [];
    return {
      gamepads: pads.map(p => ({
        id: p.id, mapping: p.mapping || "none", hand: p.hand || "",
        axes: Array.from(p.axes).map(a => Math.round(a * 100) / 100),
        pressed: p.buttons.map((b, i) => (b.pressed ? i : -1)).filter(i => i >= 0),
      })),
      last: this.last,
    };
  },
};

// Global initialization
document.addEventListener("DOMContentLoaded", () => {
  window.vrLaserDragEngine = new VRLaserDragEngine();
  window.vrControllerEngine = new SpatialGamepadNavigator();
  window.scrollAssist = new ScrollAssist();
  window.FrameLoadInput.init();
  // Backward compatibility alias for any existing references
  window.gamepadNav = window.vrControllerEngine;
});

