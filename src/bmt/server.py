"""Local server for a project: the live 3D preview, plus pages used to check and print.

Surfaces are served as live HTML, so the preview shows exactly the documents
that get printed. The preview page is view-only: whoever edits the project's
files (normally an AI agent) drives the design, and every save shows up in the
open page within a moment.
"""

from __future__ import annotations

import html
import json
import mimetypes
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import __version__
from .core import (
    CSS_PX_PER_IN,
    IGNORED_DIRS,
    Build,
    Project,
    ProjectError,
    asset_signature,
    load_project,
    source_signature,
)

STATIC_DIR = Path(__file__).parent / "static"
POLL_SECONDS = 0.3
PROJECT_BASE = "/project/"


class ProjectServer:
    def __init__(self, root: Path, *, watch: bool = True, host: str = "127.0.0.1", port: int = 0):
        self.root = Path(root).resolve()
        self.project: Project = load_project(self.root)  # fail early if this is not a project
        self.watch = watch
        self.cond = threading.Condition()
        self.version = 0
        self.status = "ready"
        self.build: Build | None = None
        self.manifest: dict = {"name": self.project.name, "kind": self.project.kind.id, "surfaces": {}, "issues": [], "model": None, "error": None}
        self._stop = threading.Event()
        self._signature = source_signature(self.root)
        self.rebuild()

        handler = _make_handler(self)
        self.httpd = None
        ports = [port] if port == 0 else range(port, port + 20)
        for candidate in ports:
            try:
                self.httpd = ThreadingHTTPServer((host, candidate), handler)
                break
            except OSError:
                continue
        if self.httpd is None:
            raise SystemExit(f"bmt: no free port between {port} and {port + 19}")
        self.httpd.daemon_threads = True
        self.url = f"http://{host}:{self.httpd.server_address[1]}/"

    # ---------- state ----------
    def rebuild(self) -> None:
        try:
            project = load_project(self.root)
            build = project.build()
        except ProjectError as e:
            self._publish(status="error", error=str(e))
            return
        except Exception as e:  # keep serving whatever happens
            traceback.print_exc()
            self._publish(status="error", error=f"{type(e).__name__}: {e}")
            return
        assets = asset_signature(self.root)[:8]
        surfaces = {}
        for s in build.surfaces:
            v = f"{s.hash}{assets}"
            surfaces[s.id] = {
                "url": f"/surface/{s.id}.html?v={v}",
                "v": v,
                "label": s.label,
                "width_in": s.width_in,
                "height_in": s.height_in,
                "bleed_in": s.bleed_in,
                "safe_in": s.safe_in,
            }
        manifest = {
            "name": project.name,
            "kind": project.kind.id,
            "product": project.product.to_dict(),
            "model": build.model,
            "surfaces": surfaces,
            "issues": [i.to_dict() for i in build.issues],
            "error": None,
        }
        with self.cond:
            self.project, self.build = project, build
        self._publish(status="ready", manifest=manifest)

    def _publish(self, *, status: str, manifest: dict | None = None, error: str | None = None) -> None:
        with self.cond:
            # On an error keep showing the last good design, with the error on top.
            self.manifest = manifest if manifest is not None else {**self.manifest, "error": error}
            self.status = status
            self.version += 1
            self.cond.notify_all()

    def snapshot(self) -> dict:
        with self.cond:
            return {**self.manifest, "version": self.version, "status": self.status, "bmt": __version__}

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(POLL_SECONDS)
            sig = source_signature(self.root)
            if sig == self._signature:
                continue
            time.sleep(0.1)  # let a burst of writes settle
            self._signature = source_signature(self.root)
            self.rebuild()

    # ---------- lifecycle ----------
    def start(self) -> None:
        """Serve in background threads."""
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        if self.watch:
            threading.Thread(target=self._watch_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        with self.cond:
            self.cond.notify_all()
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> "ProjectServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---------- generated pages ----------
    def surface_html(self, surface_id: str, *, raw: bool) -> str | None:
        with self.cond:
            build = self.build
        surface = next((s for s in build.surfaces if s.id == surface_id), None) if build else None
        if surface is None:
            return None
        if raw:
            return surface.document(PROJECT_BASE)
        config = {
            "id": surface.id,
            "label": surface.label,
            "bleedPx": surface.bleed_in * CSS_PX_PER_IN,
            "safePx": surface.safe_in * CSS_PX_PER_IN,
            "dpi": surface.dpi,
        }
        inject = f'<script>window.__bmt = {json.dumps(config)};</script><script src="/static/check.js"></script>'
        return surface.document(PROJECT_BASE, inject)

    def _frames(self, *, raw: bool) -> str:
        surfaces = self.build.surfaces if self.build else []
        q = "?raw=1" if raw else ""
        return "\n".join(
            f'<iframe src="/surface/{s.id}.html{q}" style="width:{s.width_in}in;height:{s.height_in}in" '
            f'title="{html.escape(s.label)}" scrolling="no"></iframe>'
            for s in surfaces
        )

    def check_page(self) -> str:
        """Every surface in one page; their check results end up in #bmt-result as JSON."""
        n = len(self.build.surfaces) if self.build else 0
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>bmt check</title>
<style>body{{margin:0}} iframe{{display:block;border:0}}</style></head><body>
<pre id="bmt-result"></pre>
<script>
const want = {n}, got = {{}};
addEventListener('message', (e) => {{
  if (!e.data || e.data.bmt !== 'issues') return;
  got[e.data.id] = e.data.issues;
  if (Object.keys(got).length >= want) document.getElementById('bmt-result').textContent = JSON.stringify(got);
}});
</script>
{self._frames(raw=False)}
</body></html>"""

    def print_page(self) -> str:
        """Every surface as one printed page each, in order, at exact size."""
        surfaces = self.build.surfaces if self.build else []
        w, h = (surfaces[0].width_in, surfaces[0].height_in) if surfaces else (8.5, 11)
        name = html.escape(self.manifest.get("name", "bmt"))
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>{name}</title>
<style>
@page {{ size: {w}in {h}in; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
iframe {{ display: block; border: 0; break-after: page; break-inside: avoid; }}
iframe:last-of-type {{ break-after: auto; }}
#note {{ font: 14px/1.5 system-ui, sans-serif; padding: 12px 16px; background: #fff7d6; }}
@media print {{ #note {{ display: none; }} }}
@media screen {{ body {{ background: #333; }} iframe {{ margin: 12px auto; }} }}
</style></head><body>
<div id="note">To save the print file: choose <b>Save as PDF</b> in the print dialog, set
<b>Margins</b> to <b>None</b>, and keep <b>Background graphics</b> on. The paper size is set
for you ({w}in × {h}in per page).</div>
{self._frames(raw=True)}
<script>
if (new URLSearchParams(location.search).has('auto')) {{
  addEventListener('load', () => setTimeout(() => window.print(), 800));
}}
</script>
</body></html>"""


def _make_handler(server: ProjectServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes | str, ctype: str) -> None:
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path) -> None:
            if not path.is_file():
                self._send(404, "not found", "text/plain")
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix in {".js", ".mjs"}:
                ctype = "text/javascript"
            if ctype.startswith("text/") or ctype in {"application/json", "image/svg+xml"}:
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype)

        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            path = unquote(path)
            html_type = "text/html; charset=utf-8"
            if path == "/":
                self._file(STATIC_DIR / "index.html")
            elif path == "/viewer.js":
                self._file(server.project.kind.viewer_js)
            elif path.startswith("/static/"):
                self._file(STATIC_DIR / Path(path).name)
            elif path.startswith("/surface/") and path.endswith(".html"):
                doc = server.surface_html(Path(path).stem, raw="raw=1" in query)
                self._send(200 if doc else 404, doc or "no such surface", html_type)
            elif path.startswith(PROJECT_BASE):
                self._project_file(path[len(PROJECT_BASE):])
            elif path == "/check":
                self._send(200, server.check_page(), html_type)
            elif path == "/print":
                self._send(200, server.print_page(), html_type)
            elif path == "/api/state":
                self._send(200, json.dumps(server.snapshot()), "application/json")
            elif path == "/api/events":
                self._events()
            else:
                self._send(404, "not found", "text/plain")

        def _project_file(self, rel: str) -> None:
            target = (server.root / rel).resolve()
            parts = target.relative_to(server.root).parts if target.is_relative_to(server.root) else None
            if parts is None or any(p in IGNORED_DIRS or p.startswith(".") for p in parts):
                self._send(404, "not found", "text/plain")
                return
            self._file(target)

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            seen = -1
            try:
                while not server._stop.is_set():
                    with server.cond:
                        if server.version == seen:
                            server.cond.wait(timeout=15)
                        version, status = server.version, server.status
                    if version != seen:
                        seen = version
                        self.wfile.write(f"data: {json.dumps({'version': version, 'status': status})}\n\n".encode())
                    else:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            self.close_connection = True

    return Handler


def serve(root: Path, *, host: str = "127.0.0.1", port: int = 4173, open_browser: bool = True) -> None:
    """Run the live preview in the foreground until interrupted."""
    server = ProjectServer(Path(root), watch=True, host=host, port=port)
    server.start()
    print(f"bmt preview of {server.project.name!r} running at {server.url}", flush=True)
    print("Edit the project's files and the page updates by itself. Ctrl-C to stop.", flush=True)
    if open_browser:
        import webbrowser

        webbrowser.open(server.url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
