"""Preflight a project and write the print-ready files."""

from __future__ import annotations

from pathlib import Path

from .core import CSS_PX_PER_IN, Build, Issue, Project, asset_signature
from .render import Rendered, Renderer


def render_all(project: Project, build: Build, renderer: Renderer, *, print_quality: bool) -> dict[str, Rendered]:
    salt = asset_signature(project.path)
    out = {}
    for s in build.surfaces:
        scale = s.dpi / CSS_PX_PER_IN if print_quality else 1.0
        out[s.id] = renderer.render(s, scale=scale, pdf=print_quality, salt=salt)
    return out


def collect_issues(build: Build, rendered: dict[str, Rendered]) -> list[Issue]:
    issues = list(build.issues)
    for s in build.surfaces:
        issues += rendered[s.id].issues
    return issues


def check(project: Project) -> list[Issue]:
    build = project.build()
    with Renderer(project.path / ".bmt" / "check") as renderer:
        rendered = render_all(project, build, renderer, print_quality=False)
    return collect_issues(build, rendered)


def export(project: Project, out_dir: Path | None = None) -> tuple[list[Path], list[Issue]]:
    build = project.build()
    out_dir = Path(out_dir) if out_dir else project.path / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    with Renderer(project.path / ".bmt" / "print") as renderer:
        rendered = render_all(project, build, renderer, print_quality=True)
        written = project.kind.export(project, build, rendered, out_dir)
        keep = {r.png for r in rendered.values()}
        renderer.prune(keep)
    return written, collect_issues(build, rendered)
