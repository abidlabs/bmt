"""Preflight a project and write the print-ready files, using an installed browser."""

from __future__ import annotations

import html
import json
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import browser
from .core import CSS_PX_PER_IN, Issue, Project, ProjectError
from .server import ProjectServer


def _served(project: Project) -> ProjectServer:
    server = ProjectServer(project.path, watch=False)
    if server.build is None:
        raise ProjectError(server.manifest.get("error") or "The project could not be built.")
    return server


def _check(server: ProjectServer) -> list[Issue]:
    issues = [Issue(**i) for i in server.manifest["issues"]]
    dom = browser.dump_dom(server.url + "check")
    match = re.search(r'<pre id="bmt-result">(.*?)</pre>', dom, re.S)
    if not match or not match.group(1).strip():
        return issues + [Issue("warning", "The print checks did not finish; a font or image may be failing to load.")]
    found = json.loads(html.unescape(match.group(1)))
    for surface in server.build.surfaces:  # report in surface order
        issues += [Issue(**i) for i in found.get(surface.id, [])]
    return issues


def check(project: Project) -> list[Issue]:
    with _served(project) as server:
        return _check(server)


def export(project: Project, out_dir: Path | None = None, *, images: bool = True) -> tuple[list[Path], list[Issue]]:
    out_dir = Path(out_dir) if out_dir else project.path / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    with _served(project) as server, tempfile.TemporaryDirectory(prefix="bmt-export-") as tmp:
        build = server.build
        issues = _check(server)

        pdf = Path(tmp) / "all.pdf"
        browser.print_to_pdf(server.url + "print", pdf)
        from pypdf import PdfReader

        pages = len(PdfReader(str(pdf)).pages)
        if pages != len(build.surfaces):
            raise RuntimeError(
                f"The browser printed {pages} pages for {len(build.surfaces)} surfaces; "
                "some content is probably overflowing its page."
            )

        pngs: dict[str, Path] = {}
        if images:
            print(f"Rendering {len(build.surfaces)} print-resolution images (skip with --no-images)...", file=sys.stderr)
            def shoot(surface):
                target = Path(tmp) / f"{surface.id}.png"
                # Magnified with a transform at 1x, so the image has exactly the PDF's layout.
                scale = surface.dpi / CSS_PX_PER_IN
                browser.screenshot(
                    f"{server.url}surface/{surface.id}.html?scale={scale}",
                    target,
                    width_px=round(surface.width_in * surface.dpi),
                    height_px=round(surface.height_in * surface.dpi),
                    scale=1,
                )
                return surface.id, target

            with ThreadPoolExecutor(max_workers=8) as pool:
                pngs = dict(pool.map(shoot, build.surfaces))

        written = project.kind.export(project, build, pdf, pngs, out_dir)
    return written, issues
