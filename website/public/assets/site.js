// Compatibility list filter, search and sorting, copy buttons. The page works without it.
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

  // Sorting: the column headers (wide screens) and the Sort by menu (narrow ones) set the same order, kept in
  // ?sort=key-dir so a sorted list can be shared. Each column starts in its natural direction; ties go by name.
  const table = document.getElementById("games");
  const sorters = Array.from(document.querySelectorAll(".sort[data-sort]"));
  const menu = document.getElementById("sort-menu");
  const original = rows.slice();
  const FIRST = { title: "asc", status: "asc", note: "asc", reports: "desc" };
  const text = (row, key) => row.dataset[key] || "";
  const compare = {
    title: (a, b) => text(a, "title").localeCompare(text(b, "title")),
    status: (a, b) => Number(a.dataset.rank) - Number(b.dataset.rank),
    note: (a, b) => text(a, "note").localeCompare(text(b, "note")),
    reports: (a, b) => (Number(a.dataset.reports) - Number(b.dataset.reports)) ||
      (Number(a.dataset.tested) - Number(b.dataset.tested)),
  };
  let sort = "";

  function sortBy(value, remember = true) {
    const [key, dir] = (value || "").split("-");
    sort = compare[key] && (dir === "asc" || dir === "desc") ? `${key}-${dir}` : "";
    const ordered = sort ? original.slice().sort((a, b) =>
      (dir === "asc" ? 1 : -1) * compare[key](a, b) || compare.title(a, b)) : original;
    const end = document.getElementById("empty");
    for (const row of ordered) table.insertBefore(row, end);
    for (const button of sorters) {
      const on = sort && button.dataset.sort === key;
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.dataset.dir = on ? dir : "";
      button.title = on ? (dir === "asc" ? "Sorted ascending: click to reverse" : "Sorted descending: click to reverse")
        : "Sort by this column";
    }
    if (menu) menu.value = Array.from(menu.options).some(o => o.value === sort) ? sort : "";
    if (remember) {
      const url = new URL(location.href);
      if (sort) url.searchParams.set("sort", sort); else url.searchParams.delete("sort");
      history.replaceState(null, "", url);
    }
  }

  for (const button of sorters) {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      const current = sort.startsWith(key + "-") ? sort.split("-")[1] : "";
      const dir = current ? (current === "asc" ? "desc" : "asc") : FIRST[key];
      sortBy(`${key}-${dir}`);
    });
  }
  if (menu) menu.addEventListener("change", () => sortBy(menu.value));
  if (table) sortBy(new URLSearchParams(location.search).get("sort"), false);

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
