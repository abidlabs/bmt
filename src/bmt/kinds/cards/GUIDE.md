# Kind: cards (flashcards, game cards)

## Products

| id | size (trim) | page incl. bleed | bleed | safe margin | cards |
|---|---|---|---|---|---|
| `qpmn-large-cards` | 3.5in x 5.75in | 3.74in x 5.99in | 0.12in | 0.12in inside trim | presets 8-92, or custom |

`qpmn-large-cards` is QPMN's Large Playing Cards, good for flashcards:
https://www.qpmarketnetwork.com/app/products/custom-large-playing-cards-3.5x5.75/

## Project files

```
bmt.toml      name = "Animal Alphabet"   product = "qpmn-large-cards"
cards.json    a JSON list; one object per card, with any fields you like
front.html    Jinja template for the front of every card
back.html     Jinja template for the back of every card
style.css     shared styles
assets/       images and fonts (optional)
```

The number of cards is the number of objects in `cards.json`. To add, remove or
reorder cards, edit that list.

## Templates

`front.html` and `back.html` are **body fragments** (no `<html>` or `<body>`);
bmt wraps each in a page of the right size whose body has the classes
`face front` or `face back`. They are Jinja templates with these variables:

- `card`   this card's object from `cards.json` (`{{ card.question }}`)
- `index`  1-based card number, `total` the number of cards
- `deck.name`, `side` (`"front"` or `"back"`)

Values are HTML-escaped; use `{{ card.html|safe }}` to insert markup. A field
that is missing from a card is an error, so guard optional fields:
`{% if card.hint is defined %}...{% endif %}`.

A typical face:

```html
<div class="bleed bg" style="--c: {{ card.color }}"></div>
<div class="safe layout">
  <h1>{{ card.question }}</h1>
</div>
```

- For one shared back, simply do not use `card` in `back.html`.
- For a one-off layout, give a card its own template:
  `{"template": {"front": "title-card.html"}, ...}`.
- Different front/back styling: scope CSS with `.front` and `.back`.

## Design tips for cards

- The card is small and held in the hand: one idea per face, large type
  (flashcard prompts 40pt or more, body text 14pt or more), strong contrast.
- Long text varies per card. Check the longest entry fits; `bmt check` warns
  when text leaves the safe area.
- The corners are rounded when cut; keep corner decoration inside the safe area.
- The back of a card is seen flipped left-to-right relative to the front, as with any
  real card, so do not rely on front and back artwork lining up.

## The preview

The user sees the deck as a 3D stack; clicking it spreads all cards into a grid
where each card slowly spins to show both sides. Clicking a card inspects it up
close. Cards are shown as they will be cut: the bleed is cropped and the corners
rounded. **Print guides** overlays the vendor's template on every card: the red
zone outside the trim line is cut off, and the dashed line is the safe area.

## Export

`bmt export <dir>` writes into `<dir>/export/`:

- `<name>.pdf`         every face in order: card 1 front, card 1 back, card 2 front, ...
- `<name>-fronts.pdf`  fronts only, one card per page
- `<name>-backs.pdf`   backs only, one card per page
- `faces/NN-front.png`, `faces/NN-back.png`  300 dpi images, one per face
  (these take the longest; `--no-images` skips them)

Each PDF page and PNG is the full page including bleed, which is what the
vendor's template expects. QPMN's design tool takes uploads of PDF, PNG or JPG
and assigns one file per card face; if it does not split a multi-page PDF, the
user should upload the PNGs in `faces/` instead (its bulk upload fills cards in
file-name order). Tell the user to set the deck's card count to match and to
choose "different designs" for fronts (and for backs, unless the back is shared).
