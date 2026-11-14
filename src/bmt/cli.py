"""Command line interface. Designed to be driven by an AI agent; see `bmt guide`."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .browser import BrowserNotFound
from .core import PROJECT_FILE, Issue, ProjectError, load_project
from .kinds import KINDS, all_products, get_kind

GUIDE_MD = Path(__file__).parent / "GUIDE.md"


def _print_issues(issues: list[Issue]) -> None:
    if not issues:
        print("No issues found.")
        return
    for level in ("error", "warning", "info"):
        for i in issues:
            if i.level == level:
                print(str(i))
    counts = {lvl: sum(i.level == lvl for i in issues) for lvl in ("error", "warning", "info")}
    print(f"{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} note(s).")


def cmd_new(args) -> int:
    kind = get_kind(args.kind)
    product_id = args.product or kind.default_product
    kind.product(product_id)  # validate
    target = Path(args.dir)
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"bmt: {target} already exists and is not empty (use --force to write into it).", file=sys.stderr)
        return 1
    shutil.copytree(kind.scaffold_dir, target, dirs_exist_ok=True)
    name = args.name or target.resolve().name.replace("-", " ").replace("_", " ").title()
    (target / PROJECT_FILE).write_text(f'name = {json.dumps(name)}\nproduct = "{product_id}"\n', encoding="utf-8")
    print(f"Created a {kind.id} project for {product_id} in {target}")
    print(f"Next: `bmt preview {target}` to see it, and `bmt guide {kind.id}` for how to design it.")
    return 0


def cmd_preview(args) -> int:
    from .server import serve

    serve(Path(args.dir), host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def cmd_check(args) -> int:
    from .export import check

    issues = check(load_project(args.dir))
    if args.json:
        print(json.dumps([i.to_dict() for i in issues], indent=2))
    else:
        _print_issues(issues)
    return 1 if any(i.level == "error" for i in issues) else 0


def cmd_export(args) -> int:
    from .export import export

    project = load_project(args.dir)
    written, issues = export(project, Path(args.out) if args.out else None, images=not args.no_images)
    _print_issues(issues)
    print("\nWrote:")
    for p in written:
        print(f"  {p}")
    print(f"\nOrder at: {project.product.url}")
    return 1 if any(i.level == "error" for i in issues) else 0


def cmd_products(args) -> int:
    products = [p.to_dict() for p in all_products()]
    if args.json:
        print(json.dumps(products, indent=2))
    else:
        for p in all_products():
            print(f"{p.id}  [{p.kind}]  {p.name} - {p.vendor}\n    {p.url}")
    return 0


def cmd_guide(args) -> int:
    text = GUIDE_MD.read_text(encoding="utf-8")
    kinds = [get_kind(args.kind)] if args.kind else list(KINDS.values())
    for kind in kinds:
        text += "\n\n" + kind.guide_md.read_text(encoding="utf-8")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bmt",
        description="Build, make and buy things you design with your AI agent. Agents: run `bmt guide` first.",
    )
    parser.add_argument("--version", action="version", version=f"bmt {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="start a project from a working example")
    p.add_argument("kind", choices=sorted(KINDS), help="what to make")
    p.add_argument("dir", help="folder to create")
    p.add_argument("--product", help="product id (see `bmt products`); defaults to the kind's main product")
    p.add_argument("--name", help="display name of the project")
    p.add_argument("--force", action="store_true", help="write into an existing non-empty folder")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("preview", help="serve a live 3D preview that updates as files change")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--port", type=int, default=4173)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--no-open", action="store_true", help="do not open a browser window")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("check", help="preflight the design against the product's print specs")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("export", help="write the print-ready files to upload to the vendor")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--out", help="output folder (default: <dir>/export)")
    p.add_argument("--no-images", action="store_true", help="write only the PDFs, not per-surface PNGs")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("products", help="list the products bmt can make")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_products)

    p = sub.add_parser("guide", help="print instructions for AI agents")
    p.add_argument("kind", nargs="?", choices=sorted(KINDS))
    p.set_defaults(func=cmd_guide)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ProjectError, ValueError, BrowserNotFound, RuntimeError) as e:
        print(f"bmt: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
