"""The interface every kind of makeable thing implements.

To add a new kind (say, posters or boxes), create ``bmt/kinds/<id>/`` with:

* a ``Kind`` subclass that lists its products and implements ``build`` and ``export``
* ``scaffold/``  starter project files copied by ``bmt new <id> <dir>``
* ``viewer.js``  an ES module exporting ``createViewer(ctx)`` for the 3D preview
* ``GUIDE.md``   instructions for agents, printed by ``bmt guide <id>``

then register it in ``bmt/kinds/__init__.py``. Adding a new product of an
existing kind is just one more entry in that kind's ``products`` list.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Build, Product, Project


class Kind(ABC):
    id: str
    title: str
    products: list["Product"]
    default_product: str

    @property
    def dir(self) -> Path:
        import inspect

        return Path(inspect.getfile(type(self))).parent

    @property
    def scaffold_dir(self) -> Path:
        return self.dir / "scaffold"

    @property
    def viewer_js(self) -> Path:
        return self.dir / "viewer.js"

    @property
    def guide_md(self) -> Path:
        return self.dir / "GUIDE.md"

    def product(self, product_id: str) -> "Product":
        for p in self.products:
            if p.id == product_id:
                return p
        raise ValueError(f"Kind {self.id!r} has no product {product_id!r}")

    @abstractmethod
    def build(self, project: "Project") -> "Build":
        """Turn the project folder into printable surfaces and a 3D model description.

        Raise ``ProjectError`` for problems the author must fix.
        """

    @abstractmethod
    def export(
        self, project: "Project", build: "Build", pdf: Path, images: dict[str, Path], out_dir: Path
    ) -> list[Path]:
        """Assemble the vendor's files. Returns the files written.

        ``pdf`` has one page per surface, in ``build.surfaces`` order. ``images``
        maps surface ids to print-resolution PNGs (empty if images were skipped).
        """
