# bmt guide for AI agents

bmt turns a design you write as files into a real, orderable physical product.
You (the agent) write the design; the user watches a live 3D preview in their
browser and tells you what to change; when they are happy you export
print-ready files for them to upload to the vendor.

## The loop

1. `bmt products` lists what can be made. Pick one with the user.
2. `bmt new <kind> <dir> --name "..."` creates a project folder with a working example.
3. Start `bmt preview <dir>` **in the background** and tell the user the URL it prints.
   Leave it running for the whole session. It watches the folder: every time you
   save a file, the user's page re-renders by itself within about a second.
4. Ask the user what they want, then edit the project files. Small, frequent
   edits work best because the user sees each one land.
5. Run `bmt check <dir>` after substantial changes and fix what it reports.
   The preview page shows the same warnings to the user.
6. When the user is happy, run `bmt export <dir>` and tell them where the files
   are and where to upload them (the command prints the vendor's URL).

You never need to open the preview yourself; it is for the user. If the project
has a mistake (bad JSON, a template error), the preview page shows the error and
keeps the last good render, so just fix the file.

## Rules that apply to every product

- A project is a folder with a `bmt.toml` (`name`, `product`) plus design files.
- Every printable surface is an HTML page of an exact physical size. Use physical
  CSS units (`in`, `mm`, `pt`), never viewport units or `px` for layout.
- **Bleed**: the page is larger than the finished piece. Backgrounds must cover
  the whole page (`class="bleed"`), because the edge is cut off.
- **Safe area**: text and anything important must stay inside `class="safe"`.
  Things outside it may be trimmed. Mark deliberate edge-to-edge art with the
  `data-bleed-ok` attribute to silence the warning.
- CSS variables available on every page: `--page-w`, `--page-h`, `--bleed`,
  `--safe`, `--inset` (bleed + safe).
- `style.css` in the project folder is linked into every page automatically.
  Other files (images, fonts) are referenced relative to the project folder,
  e.g. `<img src="assets/cat.png">`.
- Images need about 300 pixels per printed inch. Prefer SVG and CSS for shapes.
- Web fonts work (`@import` in `style.css`), but need a network connection at
  render time. For emoji, use the `Noto Color Emoji` web font rather than the
  system emoji font, so the result is the same on every machine and prints sharply.
- Do not write into `.bmt/` or `export/`; bmt owns those.
- Only use artwork the user has the rights to print. Vendors reject copied art.
