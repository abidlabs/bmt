"""Render surfaces to PNG and PDF with headless Chromium, and preflight them.

The same engine produces the preview textures and the print files, so what the
user sees in the 3D preview is what gets printed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .core import CSS_PX_PER_IN, Issue, Surface


# Bump when rendering or the checks change, so cached results are not reused.
CACHE_VERSION = 2


@dataclass
class Rendered:
    png: Path
    pdf: Path | None
    issues: list[Issue] = field(default_factory=list)


# Runs inside the page. Flags text and images that leave the safe area, and
# images without enough pixels for print. Elements (or ancestors) marked with
# the `data-bleed-ok` attribute are exempt: use it for deliberate edge-to-edge art.
_CHECK_JS = r"""
(cfg) => {
  const issues = [];
  const W = window.innerWidth, H = window.innerHeight;
  const m = cfg.insetPx, tol = 0.75;
  const outside = (r) => r.left < m - tol || r.top < m - tol || r.right > W - m + tol || r.bottom > H - m + tol;
  const visible = (el) => {
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.02;
  };
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
    const tm = ctx.measureText(cs.textTransform === 'uppercase' ? text.toUpperCase() : text);
    const rects = [...range.getClientRects()]
      .filter((r) => r.width > 0.5 && r.height > 0.5)
      .map((r) => {
        const baseline = r.top + (r.height - (tm.fontBoundingBoxAscent + tm.fontBoundingBoxDescent)) / 2 + tm.fontBoundingBoxAscent;
        return { left: r.left, right: r.right, top: baseline - tm.actualBoundingBoxAscent, bottom: baseline + tm.actualBoundingBoxDescent };
      });
    if (rects.some(outside)) {
      seen.add(el);
      const snippet = text.length > 40 ? text.slice(0, 40) + '…' : text;
      issues.push({ level: 'warning', message: `Text "${snippet}" extends outside the safe area and may be trimmed.` });
    }
  }
  for (const img of document.querySelectorAll('img')) {
    if (!visible(img)) continue;
    const r = img.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const name = (img.getAttribute('src') || '').split('/').pop();
    const vector = /\.svg($|\?)/i.test(img.currentSrc || '') || (img.currentSrc || '').startsWith('data:image/svg');
    if (!img.complete || img.naturalWidth === 0) {
      issues.push({ level: 'error', message: `Image "${name}" failed to load.` });
      continue;
    }
    if (!vector) {
      const dpi = Math.min(img.naturalWidth / (r.width / 96), img.naturalHeight / (r.height / 96));
      if (dpi < cfg.dpi * 0.98) {
        issues.push({ level: 'warning', message: `Image "${name}" prints at about ${Math.round(dpi)} dpi; ${cfg.dpi} dpi or more is recommended.` });
      }
    }
    if (!img.closest('[data-bleed-ok]') && outside(r)) {
      issues.push({ level: 'warning', message: `Image "${name}" extends outside the safe area; add data-bleed-ok if that is intended.` });
    }
  }
  if (document.documentElement.scrollHeight > H + 1 || document.documentElement.scrollWidth > W + 1) {
    issues.push({ level: 'warning', message: 'Content overflows the page and is being clipped.' });
  }
  return issues;
}
"""


def _bleed_issues(png: Path, surface: Surface, scale: float) -> list[Issue]:
    """Warn when artwork reaches the trim line but stops short of the page edge."""
    if surface.bleed_in <= 0:
        return []
    from PIL import Image, ImageStat

    with Image.open(png) as im:
        im = im.convert("RGB")
        w, h = im.size
        bleed = surface.bleed_in * CSS_PX_PER_IN * scale
        inner = int(bleed + 3 * scale)
        strip = max(2, int(2 * scale))
        if inner + strip >= min(w, h) // 2:
            return []
        edges = {
            "top": ((inner, 0, w - inner, strip), (inner, inner, w - inner, inner + strip)),
            "bottom": ((inner, h - strip, w - inner, h), (inner, h - inner - strip, w - inner, h - inner)),
            "left": ((0, inner, strip, h - inner), (inner, inner, inner + strip, h - inner)),
            "right": ((w - strip, inner, w, h - inner), (w - inner - strip, inner, w - inner, h - inner)),
        }
        bad = []
        for name, (outer_box, inner_box) in edges.items():
            outer_mean = ImageStat.Stat(im.crop(outer_box)).mean
            inner_mean = ImageStat.Stat(im.crop(inner_box)).mean
            if min(outer_mean) > 250 and min(inner_mean) < 235:
                bad.append(name)
    if bad:
        return [
            Issue(
                "warning",
                f"Background stops before the {', '.join(bad)} page edge; extend it through the bleed "
                "(use the .bleed class) or trimming may leave a white sliver.",
            )
        ]
    return []


class Renderer:
    """Renders surfaces with one long-lived headless browser. Use from a single thread."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self._browser = None
        self._contexts: dict[tuple, object] = {}

    def __enter__(self) -> "Renderer":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch()
        except Exception as e:  # browser binary not downloaded yet
            if "Executable doesn't exist" not in str(e) and "playwright install" not in str(e):
                raise
            print("bmt: downloading Chromium for rendering (one time, about 150 MB)...", file=sys.stderr)
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            self._browser = self._pw.chromium.launch()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _context(self, surface: Surface, scale: float):
        key = (surface.width_px, surface.height_px, scale)
        if key not in self._contexts:
            self._contexts[key] = self._browser.new_context(
                viewport={"width": surface.width_px, "height": surface.height_px},
                device_scale_factor=scale,
            )
        return self._contexts[key]

    def render(self, surface: Surface, *, scale: float, pdf: bool = False, salt: str = "") -> Rendered:
        """Render one surface. Results are cached by content, so unchanged surfaces are free."""
        key = hashlib.sha1(f"{CACHE_VERSION}|{surface.html}|{scale}|{pdf}|{salt}".encode()).hexdigest()[:20]
        png = self.work_dir / f"{key}.png"
        pdf_path = self.work_dir / f"{key}.pdf" if pdf else None
        meta = self.work_dir / f"{key}.json"
        if png.exists() and meta.exists() and (not pdf or pdf_path.exists()):
            issues = [Issue(**i) for i in json.loads(meta.read_text())]
            return Rendered(png=png, pdf=pdf_path, issues=issues)

        src = self.work_dir / f"{key}.html"
        src.write_text(surface.html, encoding="utf-8")
        page = self._context(surface, scale).new_page()
        issues: list[Issue] = []
        try:
            try:
                page.goto(src.as_uri(), wait_until="load", timeout=30_000)
                page.evaluate("document.fonts.ready.then(() => true)")
            except Exception as e:
                issues.append(Issue("warning", f"Page did not finish loading ({type(e).__name__}); a font or image may be missing.", surface.label))
            page.emulate_media(media="screen")
            found = page.evaluate(
                _CHECK_JS,
                {"insetPx": (surface.bleed_in + surface.safe_in) * CSS_PX_PER_IN, "dpi": surface.dpi},
            )
            issues += [Issue(i["level"], i["message"], surface.label) for i in found]
            page.screenshot(path=str(png), type="png")
            if pdf:
                page.pdf(
                    path=str(pdf_path),
                    width=f"{surface.width_in}in",
                    height=f"{surface.height_in}in",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
        finally:
            page.close()
            src.unlink(missing_ok=True)
        for issue in _bleed_issues(png, surface, scale):
            issue.where = surface.label
            issues.append(issue)
        meta.write_text(json.dumps([i.to_dict() for i in issues]))
        return Rendered(png=png, pdf=pdf_path, issues=issues)

    def prune(self, keep: set[Path]) -> None:
        """Delete cached files that no current surface uses."""
        keep_stems = {p.stem for p in keep}
        for p in self.work_dir.iterdir():
            if p.is_file() and p.stem not in keep_stems:
                p.unlink(missing_ok=True)
