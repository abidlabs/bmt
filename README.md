# bmt

**Build, make, buy.** A tool your AI agent uses to turn something you describe
into a real, orderable physical product.

You tell your agent (Claude Code, for example) what you want. The agent writes the
design, you watch it in a live 3D preview in your browser and ask for changes in
chat, and at the end you get print-ready files to upload to a print-on-demand
vendor.

The first thing bmt can make is a **deck of flashcards**, printed by
[QPMN as 3.5" x 5.75" large cards](https://www.qpmarketnetwork.com/app/products/custom-large-playing-cards-3.5x5.75/).

## Use it with your agent

Tell your agent:

> Install bmt with `uv tool install git+https://github.com/abidlabs/bmt`, run
> `bmt guide`, and help me make a deck of flashcards about ...

Or install the skill in [skills/bmt](skills/bmt/SKILL.md) so the agent knows about bmt by itself.

## Use it yourself

```bash
uv tool install git+https://github.com/abidlabs/bmt
```

```bash
bmt new cards my-deck --name "My Deck"
```

```bash
bmt preview my-deck
```

```bash
bmt export my-deck
```

| Command | What it does |
|---|---|
| `bmt products` | Lists what can be made |
| `bmt new <kind> <dir>` | Starts a project from a working example |
| `bmt preview <dir>` | Serves a live 3D preview that updates whenever the files change |
| `bmt check <dir>` | Preflights the design against the product's print specs |
| `bmt export <dir>` | Writes the print-ready PDF and images |
| `bmt guide` | Prints the instructions an agent needs |

The first render downloads a headless Chromium (about 300 MB, one time). The
preview page loads three.js from a CDN, so it needs an internet connection.

A full sample deck lives in [examples/animal-alphabet](examples/animal-alphabet).

## How it is built

Every printable surface is an HTML page of an exact physical size, rendered by
headless Chromium for both the preview and the print files, so the preview
matches the print.

```
src/bmt/
  core.py        projects, products, printable surfaces, issues
  render.py      Chromium rendering to PNG/PDF and the preflight checks
  export.py      check and export
  preview/       live-reload server and the page shell
  kinds/
    base.py      the interface a kind implements
    cards/       card decks: product specs, starter project, 3D viewer, agent guide
```

A **kind** is a type of thing (card decks today). A **product** is one specific
orderable item of that kind from a vendor. Adding a product is one entry in its
kind's product list; adding a kind is a new folder under `kinds/` with its own
specs, starter project, 3D viewer and guide. See [kinds/base.py](src/bmt/kinds/base.py).

## Development

```bash
uv sync
```

```bash
uv run pytest
```
