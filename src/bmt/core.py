"""Shared building blocks: projects, products, printable surfaces and issues.

Everything here is independent of what is being made. A *kind* (see
``bmt.kinds``) turns a project folder into a list of flat printable
``Surface`` objects plus a ``model`` describing the 3D object for the preview.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .kinds.base import Kind

CSS_PX_PER_IN = 96
PROJECT_FILE = "bmt.toml"
# Stands in for the URL of the project folder until a surface is served or printed.
BASE_TOKEN = "__BMT_PROJECT_BASE__/"
# Folders inside a project that bmt writes to and must not treat as sources.
IGNORED_DIRS = {".bmt", "export", ".git", "__pycache__", "node_modules"}


class ProjectError(Exception):
    """A problem with the project's files that its author needs to fix."""


@dataclass(frozen=True)
class Product:
    """Something a vendor can manufacture. Kinds subclass this with their specs."""

    id: str
    kind: str
    name: str
    vendor: str
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Surface:
    """One flat printable area, described as a standalone HTML document."""

    id: str  # file-name friendly and unique in the project, e.g. "01-front"
    label: str  # human readable, e.g. "card 1 front"
    html: str
    width_in: float  # full page size, including bleed
    height_in: float
    bleed_in: float = 0.0
    safe_in: float = 0.0
    dpi: int = 300

    @property
    def width_px(self) -> int:
        return round(self.width_in * CSS_PX_PER_IN)

    @property
    def hash(self) -> str:
        return hashlib.sha1(self.html.encode()).hexdigest()[:12]

    def document(self, base_url: str, inject: str = "") -> str:
        """The final HTML, with relative URLs resolving against ``base_url``.

        ``inject`` is extra markup placed at the end of the body (bmt's check script).
        """
        html = self.html.replace(BASE_TOKEN, base_url)
        return html.replace("</body>", inject + "</body>") if inject else html

    @property
    def height_px(self) -> int:
        return round(self.height_in * CSS_PX_PER_IN)


@dataclass
class Issue:
    level: str  # "error" | "warning" | "info"
    message: str
    where: str = ""  # surface label, or "" for project-wide

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        prefix = f"{self.where}: " if self.where else ""
        return f"[{self.level}] {prefix}{self.message}"


@dataclass
class Build:
    """What a kind produces from a project folder."""

    surfaces: list[Surface]
    model: dict[str, Any]  # kind-specific description of the 3D object for the viewer
    issues: list[Issue] = field(default_factory=list)


@dataclass
class Project:
    path: Path
    name: str
    config: dict[str, Any]
    product: Product
    kind: "Kind"

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-") or "project"

    def build(self) -> Build:
        return self.kind.build(self)


def load_project(path: str | Path) -> Project:
    from .kinds import find_product

    root = Path(path).resolve()
    config_path = root / PROJECT_FILE
    if not config_path.is_file():
        raise ProjectError(f"No {PROJECT_FILE} in {root}. Start a project with `bmt new <kind> <dir>`.")
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ProjectError(f"{PROJECT_FILE} is not valid TOML: {e}") from None
    try:
        kind, product = find_product(config.get("product", ""))
    except ValueError as e:
        raise ProjectError(f"{PROJECT_FILE}: {e}") from None
    return Project(path=root, name=config.get("name", root.name), config=config, product=product, kind=kind)


def source_files(root: Path) -> list[Path]:
    """Every file that belongs to the project's design (not bmt's own output)."""
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if p.is_file() and not p.name.startswith("."):
            out.append(p)
    return out


def _signature(root: Path, skip_suffixes: set[str]) -> str:
    h = hashlib.sha1()
    for p in source_files(root):
        if p.suffix in skip_suffixes:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.relative_to(root)}:{st.st_mtime_ns}:{st.st_size};".encode())
    return h.hexdigest()


def source_signature(root: Path) -> str:
    """Changes whenever any project source file changes."""
    return _signature(root, set())


def asset_signature(root: Path) -> str:
    """Changes when files that surfaces load by URL (css, images, fonts) change."""
    return _signature(root, {".html", ".json", ".toml", ".md"})


_PAGE_WRAPPER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<base href="{base}">
<style>
@page {{ size: {w}in {h}in; margin: 0; }}
:root {{
  --page-w: {w}in; --page-h: {h}in;
  --bleed: {bleed}in; --safe: {safe}in; --inset: {inset}in;
}}
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0;
  width: var(--page-w); height: var(--page-h);
  overflow: hidden;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}}
body {{ position: relative; }}
/* Fills the whole page including bleed: use for backgrounds. */
.bleed {{ position: absolute; inset: 0; }}
/* The area guaranteed to survive trimming: put text and key art in here. */
.safe {{ position: absolute; inset: var(--inset); }}
</style>
{head}
</head>
<body class="{body_class}">
{body}
</body>
</html>
"""


def page_html(
    *,
    root: Path,
    body: str,
    width_in: float,
    height_in: float,
    bleed_in: float,
    safe_in: float,
    body_class: str = "",
) -> str:
    """Wrap a body fragment in a page of an exact physical size.

    Relative URLs resolve against the project folder (see ``Surface.document``),
    and ``style.css`` in the project folder is linked when present.
    """
    head = '<link rel="stylesheet" href="style.css">' if (root / "style.css").is_file() else ""
    return _PAGE_WRAPPER.format(
        base=BASE_TOKEN,
        w=width_in,
        h=height_in,
        bleed=bleed_in,
        safe=safe_in,
        inset=bleed_in + safe_in,
        head=head,
        body_class=body_class,
        body=body,
    )
