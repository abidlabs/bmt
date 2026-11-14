// Print preflight, injected into every surface when it is served for preview
// or checking (never into the print output). Reports to the embedding page.
//
// Flags text and images that leave the safe area, images without enough pixels
// for print, and backgrounds that stop short of the page edge. Elements (or
// ancestors) with the `data-bleed-ok` attribute are exempt from the safe-area
// check: use it for deliberate edge-to-edge art.
(() => {
  const cfg = window.__bmt;
  if (!cfg || window.parent === window) return;

  function run() {
    const issues = [];
    const add = (level, message) => issues.push({ level, message, where: cfg.label });
    const W = window.innerWidth, H = window.innerHeight;
    // The preview zooms the page to lock its layout, so measure in page units.
    const z = W / cfg.pageWPx;
    const bleed = cfg.bleedPx * z;
    const m = (cfg.bleedPx + cfg.safePx) * z, tol = 0.75;
    const outside = (r) => r.left < m - tol || r.top < m - tol || r.right > W - m + tol || r.bottom > H - m + tol;
    const visible = (el) => {
      const cs = getComputedStyle(el);
      return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.02;
    };

    // --- text inside the safe area ---
    const seen = new Set();
    const ctx = document.createElement('canvas').getContext('2d');
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = node.textContent.trim();
      const el = node.parentElement;
      if (!text || !el || seen.has(el) || el.closest('[data-bleed-ok], script, style') || !visible(el)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      // Layout boxes are taller than the ink (big display type especially), so
      // measure the glyphs and test the rows the ink actually occupies.
      const cs = getComputedStyle(el);
      ctx.font = cs.font;
      const raw = ctx.measureText(cs.textTransform === 'uppercase' ? text.toUpperCase() : text);
      const tm = {};
      for (const k of ['fontBoundingBoxAscent', 'fontBoundingBoxDescent', 'actualBoundingBoxAscent', 'actualBoundingBoxDescent']) tm[k] = raw[k] * z;
      const rects = [...range.getClientRects()]
        .filter((r) => r.width > 0.5 && r.height > 0.5)
        .map((r) => {
          const baseline = r.top + (r.height - (tm.fontBoundingBoxAscent + tm.fontBoundingBoxDescent)) / 2 + tm.fontBoundingBoxAscent;
          return { left: r.left, right: r.right, top: baseline - tm.actualBoundingBoxAscent, bottom: baseline + tm.actualBoundingBoxDescent };
        });
      if (rects.some(outside)) {
        seen.add(el);
        const snippet = text.length > 40 ? text.slice(0, 40) + '…' : text;
        add('warning', `Text "${snippet}" extends outside the safe area and may be trimmed.`);
      }
    }

    // --- images: loaded, sharp enough, inside the safe area ---
    for (const img of document.querySelectorAll('img')) {
      if (!visible(img)) continue;
      const r = img.getBoundingClientRect();
      const name = (img.getAttribute('src') || '').split('/').pop();
      if (!img.complete || img.naturalWidth === 0) { add('error', `Image "${name}" failed to load.`); continue; }
      if (r.width < 1 || r.height < 1) continue;
      const src = img.currentSrc || '';
      const vector = /\.svg($|\?)/i.test(src) || src.startsWith('data:image/svg');
      if (!vector) {
        const dpi = Math.min(img.naturalWidth / (r.width / z / 96), img.naturalHeight / (r.height / z / 96));
        if (dpi < cfg.dpi * 0.98) add('warning', `Image "${name}" prints at about ${Math.round(dpi)} dpi; ${cfg.dpi} dpi or more is recommended.`);
      }
      if (!img.closest('[data-bleed-ok]') && outside(r)) {
        add('warning', `Image "${name}" extends outside the safe area; add data-bleed-ok if that is intended.`);
      }
    }

    // --- backgrounds reach the page edge (through the bleed) ---
    if (cfg.bleedPx > 0) {
      const paints = (el) => {
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.05) return false;
        if (/^(IMG|CANVAS|VIDEO|svg)$/.test(el.tagName)) return true;
        if (cs.backgroundImage !== 'none') return true;
        const c = cs.backgroundColor;
        if (c === 'transparent') return false;
        const rgba = c.match(/^rgba?\(([^)]+)\)$/);
        const parts = rgba ? rgba[1].split(/[\s,\/]+/).filter(Boolean) : [];
        return parts.length < 4 || parseFloat(parts[3]) > 0.05;
      };
      const paintedAt = (x, y) => document.elementsFromPoint(x, y).some(paints);
      const inner = bleed + 3 * z, fr = [0.25, 0.5, 0.75];
      const edges = {
        top: fr.map((f) => [[W * f, z], [W * f, inner]]),
        bottom: fr.map((f) => [[W * f, H - 1.5 * z], [W * f, H - inner]]),
        left: fr.map((f) => [[z, H * f], [inner, H * f]]),
        right: fr.map((f) => [[W - 1.5 * z, H * f], [W - inner, H * f]]),
      };
      const bad = Object.entries(edges)
        .filter(([, samples]) => samples.some(([o, i]) => paintedAt(i[0], i[1]) && !paintedAt(o[0], o[1])))
        .map(([name]) => name);
      if (bad.length) {
        add('warning', `Background stops before the ${bad.join(', ')} page edge; extend it through the bleed (use the .bleed class) or trimming may leave a white sliver.`);
      }
    }

    if (document.documentElement.scrollHeight > H + 1 || document.documentElement.scrollWidth > W + 1) {
      add('warning', 'Content overflows the page and is being clipped.');
    }
    window.parent.postMessage({ bmt: 'issues', id: cfg.id, issues }, '*');
  }

  const loaded = new Promise((resolve) => (document.readyState === 'complete' ? resolve() : addEventListener('load', resolve)));
  loaded.then(() => document.fonts.ready).then(() => setTimeout(run, 50));
})();
