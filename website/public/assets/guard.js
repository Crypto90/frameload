// The site is dark already. Dark Reader switches itself off for it (meta darkreader-lock); this removes
// what a version that ignores the lock injects anyway: its <style class="darkreader ..."> sheets and the
// data-darkreader-* attributes it puts on elements (its filter mode inverts the whole page through them).
(() => {
  const SHEETS = "style.darkreader, style[class*='darkreader'], link.darkreader, meta[name='darkreader']";

  function clean(root) {
    if (root.nodeType !== 1) return;
    if (root.matches(SHEETS)) {
      root.remove();
      return;
    }
    for (const node of root.querySelectorAll(SHEETS)) node.remove();
    for (const el of [root, ...root.querySelectorAll("[data-darkreader-inline-bgcolor], [data-darkreader-inline-color], [data-darkreader-inline-border], [data-darkreader-inline-fill], [data-darkreader-inline-stroke]")]) {
      for (const attr of Array.from(el.attributes)) {
        if (attr.name.startsWith("data-darkreader-")) el.removeAttribute(attr.name);
      }
    }
  }

  const html = document.documentElement;
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === "attributes") {
        if (record.attributeName && record.attributeName.startsWith("data-darkreader")) {
          record.target.removeAttribute(record.attributeName);
        }
      } else {
        record.addedNodes.forEach(clean);
      }
    }
  }).observe(html, { childList: true, subtree: true, attributes: true, attributeFilter: [
    "data-darkreader-mode", "data-darkreader-scheme", "data-darkreader-proxy-injected",
    "data-darkreader-inline-bgcolor", "data-darkreader-inline-color", "data-darkreader-inline-border",
    "data-darkreader-inline-fill", "data-darkreader-inline-stroke",
  ] });
  clean(html);
})();
