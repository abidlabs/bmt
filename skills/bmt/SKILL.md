---
name: bmt
description: Design a physical product with the user and get it made. Use when the user wants to create something printable or orderable such as flashcards, a card deck or game cards, with a live 3D preview while designing and print-ready files at the end.
---

# bmt: build, make, buy

`bmt` is a command line tool for agents. You write the design as HTML/CSS files,
the user watches a live 3D preview and directs changes by chatting with you, and
you export print-ready files for a print-on-demand vendor.

## Setup

If the `bmt` command is missing, install it:

```bash
uv tool install git+https://github.com/abidlabs/bmt
```

(or run it without installing: `uvx --from git+https://github.com/abidlabs/bmt bmt ...`)

## What to do

1. Run `bmt guide` and read it fully. It has the workflow, the print rules and
   the file format for each kind of product. It is the source of truth.
2. `bmt new <kind> <dir> --name "<name>"` to scaffold a project.
3. Run `bmt preview <dir>` in the background and give the user the URL.
4. Edit the project files as the user asks; the preview updates on every save.
5. `bmt check <dir>` to preflight, then `bmt export <dir>` when the user is happy.

Do not ask the user to edit files or run commands themselves; do it for them and
let them steer by looking at the preview.
