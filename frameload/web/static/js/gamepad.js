/**
 * FrameLoad Gamepad & Steam Frame VR Controller Navigation Engine
 * Enables seamless control using VR controllers, Steam Deck controls, or Gamepads.
 */

class GamepadNavigator {
  constructor() {
    this.enabled = true;
    this.focusedIndex = 0;
    this.focusableElements = [];
    this.lastButtonStates = {};
    this.axisThreshold = 0.5;
    this.lastAxisTime = 0;
    this.repeatDelay = 220; // ms

    window.addEventListener("gamepadconnected", (e) => {
      console.log(`[FrameLoad] Gamepad connected: ${e.gamepad.id}`);
      this.showToast(`🎮 Controller connected: ${e.gamepad.id.split("(")[0]}`);
      this.updateFocusables();
    });

    window.addEventListener("gamepaddisconnected", () => {
      console.log("[FrameLoad] Gamepad disconnected");
    });

    this.pollLoop = this.pollLoop.bind(this);
    requestAnimationFrame(this.pollLoop);
  }

  updateFocusables() {
    const selector = 'button:not([disabled]), [tabindex]:not([tabindex="-1"]), .game-card, input:not([disabled]), select:not([disabled])';
    const visibleElements = Array.from(document.querySelectorAll(selector)).filter((el) => {
      return el.offsetParent !== null && window.getComputedStyle(el).visibility !== "hidden";
    });

    this.focusableElements = visibleElements;
    if (this.focusedIndex >= this.focusableElements.length) {
      this.focusedIndex = Math.max(0, this.focusableElements.length - 1);
    }
  }

  setFocus(index) {
    if (this.focusableElements.length === 0) return;
    this.focusableElements.forEach((el) => el.classList.remove("gamepad-focused"));

    this.focusedIndex = (index + this.focusableElements.length) % this.focusableElements.length;
    const target = this.focusableElements[this.focusedIndex];
    if (target) {
      target.classList.add("gamepad-focused");
      target.scrollIntoView({ behavior: "smooth", block: "nearest" });
      if (document.activeElement !== target && target.tagName !== "INPUT") {
        target.focus({ preventScroll: true });
      }
    }
  }

  pollLoop() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (let i = 0; i < gamepads.length; i++) {
      const gp = gamepads[i];
      if (!gp) continue;
      this.handleGamepad(gp);
      break; // Primary controller
    }
    requestAnimationFrame(this.pollLoop);
  }

  handleGamepad(gp) {
    const now = Date.now();

    // D-Pad / Axis Navigation
    const axisX = gp.axes[0] || 0;
    const axisY = gp.axes[1] || 0;
    const dpadUp = gp.buttons[12]?.pressed;
    const dpadDown = gp.buttons[13]?.pressed;
    const dpadLeft = gp.buttons[14]?.pressed;
    const dpadRight = gp.buttons[15]?.pressed;

    if (now - this.lastAxisTime > this.repeatDelay) {
      if (axisY > this.axisThreshold || dpadDown) {
        this.navigate(1); // Down
        this.lastAxisTime = now;
      } else if (axisY < -this.axisThreshold || dpadUp) {
        this.navigate(-1); // Up
        this.lastAxisTime = now;
      } else if (axisX > this.axisThreshold || dpadRight) {
        this.navigate(1); // Right
        this.lastAxisTime = now;
      } else if (axisX < -this.axisThreshold || dpadLeft) {
        this.navigate(-1); // Left
        this.lastAxisTime = now;
      }
    }

    // Button Actions
    const aBtn = gp.buttons[0]?.pressed; // A / Cross: Select
    const bBtn = gp.buttons[1]?.pressed; // B / Circle: Back/Close
    const xBtn = gp.buttons[2]?.pressed; // X / Square: Action
    const yBtn = gp.buttons[3]?.pressed; // Y / Triangle: Search
    const lbBtn = gp.buttons[4]?.pressed; // LB: Prev Tab
    const rbBtn = gp.buttons[5]?.pressed; // RB: Next Tab

    if (aBtn && !this.lastButtonStates.a) {
      this.triggerSelect();
    }
    if (bBtn && !this.lastButtonStates.b) {
      this.triggerBack();
    }
    if (xBtn && !this.lastButtonStates.x) {
      this.triggerAction();
    }
    if (yBtn && !this.lastButtonStates.y) {
      this.triggerSearch();
    }
    if (lbBtn && !this.lastButtonStates.lb) {
      this.switchTab(-1);
    }
    if (rbBtn && !this.lastButtonStates.rb) {
      this.switchTab(1);
    }

    this.lastButtonStates = {
      a: aBtn,
      b: bBtn,
      x: xBtn,
      y: yBtn,
      lb: lbBtn,
      rb: rbBtn
    };
  }

  navigate(dir) {
    this.updateFocusables();
    this.setFocus(this.focusedIndex + dir);
  }

  triggerSelect() {
    const el = this.focusableElements[this.focusedIndex];
    if (el) {
      el.click();
    }
  }

  triggerBack() {
    const modal = document.querySelector(".modal-backdrop.open");
    if (modal) {
      modal.classList.remove("open");
    }
  }

  triggerAction() {
    const el = this.focusableElements[this.focusedIndex];
    if (el && el.classList.contains("game-card")) {
      const btn = el.querySelector(".card-btn");
      if (btn) btn.click();
    }
  }

  triggerSearch() {
    const searchInput = document.getElementById("search-input");
    if (searchInput) {
      searchInput.focus();
    }
  }

  switchTab(dir) {
    const tabs = Array.from(document.querySelectorAll(".tab-btn"));
    const currentIdx = tabs.findIndex(t => t.classList.contains("active"));
    const nextIdx = (currentIdx + dir + tabs.length) % tabs.length;
    tabs[nextIdx]?.click();
  }

  showToast(msg) {
    if (window.showToast) {
      window.showToast(msg);
    }
  }
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.gamepadNav = new GamepadNavigator();
});
