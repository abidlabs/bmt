"""Card decks: flashcards, game cards, playing cards.

A deck project is a folder with:

* ``bmt.toml``    product id and deck name
* ``cards.json``  a list with one object of data per card
* ``front.html`` / ``back.html``  Jinja templates for the two faces
* ``style.css`` and any assets the templates reference
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jinja2

from ...core import Build, Issue, Product, Project, ProjectError, Surface, page_html
from ..base import Kind

SIDES = ("front", "back")


@dataclass(frozen=True)
class CardProduct(Product):
    trim_w_in: float = 0.0
    trim_h_in: float = 0.0
    bleed_in: float = 0.125
    safe_in: float = 0.125
    dpi: int = 300
    # Deck sizes the vendor offers as presets; other counts need their "custom" option.
    min_cards: int = 1
    max_cards: int = 1000
    # Only used by the 3D preview; approximate.
    corner_radius_in: float = 0.125
    thickness_in: float = 0.012

    @property
    def page_w_in(self) -> float:
        return self.trim_w_in + 2 * self.bleed_in

    @property
    def page_h_in(self) -> float:
        return self.trim_h_in + 2 * self.bleed_in


QPMN_LARGE_CARDS = CardProduct(
    id="qpmn-large-cards",
    kind="cards",
    name='Large Playing Cards (3.5" x 5.75")',
    vendor="QPMN",
    url="https://www.qpmarketnetwork.com/app/products/custom-large-playing-cards-3.5x5.75/",
    trim_w_in=3.5,
    trim_h_in=5.75,
    bleed_in=0.125,
    safe_in=0.125,
    dpi=300,
    min_cards=8,
    max_cards=92,
    corner_radius_in=0.15,
    thickness_in=0.012,
)


class CardsKind(Kind):
    id = "cards"
    title = "Card decks (flashcards, game cards)"
    products = [QPMN_LARGE_CARDS]
    default_product = QPMN_LARGE_CARDS.id

    def build(self, project: Project) -> Build:
        product: CardProduct = project.product  # type: ignore[assignment]
        root = project.path
        config = project.config

        cards_path = root / config.get("cards", "cards.json")
        if not cards_path.is_file():
            raise ProjectError(f"Missing {cards_path.name}: it should hold a JSON list with one object per card.")
        try:
            cards = json.loads(cards_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ProjectError(f"{cards_path.name} is not valid JSON: {e}") from None
        if not isinstance(cards, list) or not all(isinstance(c, dict) for c in cards):
            raise ProjectError(f"{cards_path.name} must be a JSON list of objects, one per card.")
        if not cards:
            raise ProjectError(f"{cards_path.name} has no cards.")

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(root)),
            autoescape=True,
            undefined=jinja2.StrictUndefined,
        )
        deck_info = {"name": project.name, "total": len(cards)}
        surfaces: list[Surface] = []
        model_cards = []

        for i, card in enumerate(cards, start=1):
            overrides = card.get("template") if isinstance(card.get("template"), dict) else {}
            ids = {}
            for side in SIDES:
                template_name = overrides.get(side) or config.get(side, f"{side}.html")
                try:
                    body = env.get_template(template_name).render(
                        card=card, index=i, total=len(cards), deck=deck_info, side=side
                    )
                except jinja2.TemplateNotFound:
                    raise ProjectError(f"Card {i} {side}: template {template_name!r} not found.") from None
                except jinja2.TemplateSyntaxError as e:
                    raise ProjectError(f"{Path(e.filename or template_name).name} line {e.lineno}: {e.message}") from None
                except jinja2.UndefinedError as e:
                    raise ProjectError(
                        f"Card {i} {side} ({template_name}): {e.message}. "
                        f"Add that field to card {i} in {cards_path.name} or guard it in the template."
                    ) from None
                surface = Surface(
                    id=f"{i:02d}-{side}",
                    label=f"card {i} {side}",
                    html=page_html(
                        root=root,
                        body=body,
                        width_in=product.page_w_in,
                        height_in=product.page_h_in,
                        bleed_in=product.bleed_in,
                        safe_in=product.safe_in,
                        body_class=f"face {side}",
                    ),
                    width_in=product.page_w_in,
                    height_in=product.page_h_in,
                    bleed_in=product.bleed_in,
                    safe_in=product.safe_in,
                    dpi=product.dpi,
                )
                surfaces.append(surface)
                ids[side] = surface.id
            model_cards.append(ids)

        issues: list[Issue] = []
        n = len(cards)
        if not product.min_cards <= n <= product.max_cards:
            issues.append(
                Issue(
                    "info",
                    f"{n} cards is outside {product.vendor}'s preset deck sizes "
                    f"({product.min_cards}-{product.max_cards}); choose the custom count when ordering.",
                )
            )

        model = {
            "cards": model_cards,
            "trim_w_in": product.trim_w_in,
            "trim_h_in": product.trim_h_in,
            "bleed_in": product.bleed_in,
            "safe_in": product.safe_in,
            "corner_radius_in": product.corner_radius_in,
            "thickness_in": product.thickness_in,
        }
        return Build(surfaces=surfaces, model=model, issues=issues)

    def export(self, project, build, pdf: Path, images: dict[str, Path], out_dir: Path) -> list[Path]:
        """One PDF with every face in order (1 front, 1 back, 2 front, ...), plus fronts/backs PDFs and PNGs."""
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(str(pdf))
        page_of = {s.id: i for i, s in enumerate(build.surfaces)}
        written: list[Path] = []

        def write(surface_ids: list[str], name: str) -> None:
            writer = PdfWriter()
            for sid in surface_ids:
                writer.add_page(reader.pages[page_of[sid]])
            target = out_dir / name
            with open(target, "wb") as f:
                writer.write(f)
            written.append(target)

        cards = build.model["cards"]
        write([c[s] for c in cards for s in SIDES], f"{project.slug}.pdf")
        write([c["front"] for c in cards], f"{project.slug}-fronts.pdf")
        write([c["back"] for c in cards], f"{project.slug}-backs.pdf")

        if images:
            faces_dir = out_dir / "faces"
            faces_dir.mkdir(exist_ok=True)
            for old in faces_dir.glob("*.png"):
                old.unlink()
            for s in build.surfaces:
                (faces_dir / f"{s.id}.png").write_bytes(images[s.id].read_bytes())
            written.append(faces_dir)
        return written
