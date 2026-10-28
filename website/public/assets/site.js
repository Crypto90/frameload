// Compatibility list filter and search, copy buttons. The page works without it.
(() => {
  const rows = Array.from(document.querySelectorAll("#games .game"));
  const search = document.getElementById("search");
  const chips = Array.from(document.querySelectorAll(".chip[data-filter]"));
  const empty = document.getElementById("empty");
  let filter = "all";

  function apply() {
    const words = (search ? search.value : "").toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const row of rows) {
      const ok = (filter === "all" || row.dataset.status === filter) &&
        words.every(w => row.dataset.search.includes(w));
      row.hidden = !ok;
      if (ok) shown++;
    }
    if (empty) empty.hidden = shown > 0;
  }

  for (const chip of chips) {
    chip.addEventListener("click", () => {
      filter = chip.dataset.filter;
      chips.forEach(c => c.setAttribute("aria-pressed", c === chip ? "true" : "false"));
      apply();
    });
  }
  if (search) {
    const fromUrl = new URLSearchParams(location.search).get("q");
    if (fromUrl) search.value = fromUrl;
    search.addEventListener("input", apply);
    apply();
  }

  for (const button of document.querySelectorAll("[data-copy]")) {
    button.addEventListener("click", async () => {
      const text = document.querySelector(button.dataset.copy)?.textContent || "";
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Copied";
      } catch {
        button.textContent = "Select and copy";
      }
      setTimeout(() => (button.textContent = "Copy"), 2000);
    });
  }
})();
