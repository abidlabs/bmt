import json

import pytest

from bmt.cli import main
from bmt.core import ProjectError, load_project
from bmt.kinds import all_products, find_product


def new_deck(tmp_path, name="Test Deck"):
    target = tmp_path / "deck"
    assert main(["new", "cards", str(target), "--name", name]) == 0
    return target


def test_products_registered():
    kind, product = find_product("qpmn-large-cards")
    assert kind.id == "cards"
    assert (product.page_w_in, product.page_h_in) == (3.75, 6.0)
    assert product in all_products()


def test_scaffold_builds(tmp_path):
    project = load_project(new_deck(tmp_path))
    build = project.build()
    assert project.name == "Test Deck"
    assert len(build.surfaces) == 16
    assert [s.id for s in build.surfaces[:2]] == ["01-front", "01-back"]
    assert build.model["cards"][0] == {"front": "01-front", "back": "01-back"}
    assert "2 + 3" in build.surfaces[0].html
    assert build.issues == []


def test_card_count_note_and_escaping(tmp_path):
    deck = new_deck(tmp_path)
    (deck / "cards.json").write_text(json.dumps([{"question": "<b>x</b>", "answer": "y", "hint": "z"}]))
    build = load_project(deck).build()
    assert "&lt;b&gt;x&lt;/b&gt;" in build.surfaces[0].html
    assert [i.level for i in build.issues] == ["info"]


def test_missing_field_is_a_clear_error(tmp_path):
    deck = new_deck(tmp_path)
    (deck / "cards.json").write_text(json.dumps([{"question": "q", "answer": "a"}]))
    with pytest.raises(ProjectError, match="hint"):
        load_project(deck).build()


def test_per_card_template_override(tmp_path):
    deck = new_deck(tmp_path)
    (deck / "title.html").write_text("<h1>TITLE CARD</h1>")
    cards = json.loads((deck / "cards.json").read_text())
    cards[0]["template"] = {"front": "title.html"}
    (deck / "cards.json").write_text(json.dumps(cards))
    build = load_project(deck).build()
    assert "TITLE CARD" in build.surfaces[0].html
    assert "TITLE CARD" not in build.surfaces[1].html


def test_not_a_project(tmp_path):
    with pytest.raises(ProjectError):
        load_project(tmp_path)


def test_export_and_checks(tmp_path):
    """End to end with a real browser: sizes are right and the checks catch real problems."""
    from pypdf import PdfReader
    from PIL import Image

    from bmt.export import check, export

    deck = new_deck(tmp_path)
    written, issues = export(load_project(deck))
    assert issues == []
    pdf = PdfReader(str(deck / "export" / "test-deck.pdf"))
    assert len(pdf.pages) == 16
    box = pdf.pages[0].mediabox
    assert (round(float(box.width) / 72, 2), round(float(box.height) / 72, 2)) == (3.75, 6.0)
    assert Image.open(deck / "export" / "faces" / "01-front.png").size == (1125, 1800)
    assert len(PdfReader(str(deck / "export" / "test-deck-fronts.pdf")).pages) == 8

    # Text pushed to the page edge, and a background that stops at the trim line.
    (deck / "front.html").write_text(
        '<div style="position:absolute; inset: var(--bleed); background:#c00"></div>'
        '<div style="position:absolute; top:0.05in; left:0.05in; font-size:20pt">{{ card.question }}</div>'
    )
    messages = [i.message for i in check(load_project(deck)) if i.where == "card 1 front"]
    assert any("safe area" in m for m in messages)
    assert any("Background stops" in m for m in messages)
