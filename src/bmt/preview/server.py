"""Local live preview: watches a project folder, re-renders it, and serves a 3D page.

The page is view-only. Whoever edits the project's files (normally an AI agent)
drives the design; every save shows up in the open page within a moment.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..core import Project, ProjectError, asset_signature, load_project, source_signature
from ..render import Renderer

STATIC_DIR = Path(__file__).parent / "static"
POLL_SECONDS = 0.4


class PreviewState:
    def __init__(self, root: Path, kind_id: str):
        self.root = root
        self.kind_id = kind_id
        self.cond = threading.Condition()
        self.version = 0
        self.status = "rendering"
        self.manifest: dict = {"name": root.name, "kind": kind_id, "error": None, "issues": [], "model": None, "surfaces": {}}
        self.stop = threading.Event()

    def publish(self, *, status: str, manifest: dict | None = None, error: str | None = None) -> None:
        with self.cond:
            if manifest is not None:
                self.manifest = manifest
            if status != "rendering":
                self.manifest = {**self.manifest, "error": error}
            self.status = status
            self.version += 1
            self.cond.notify_all()

    def snapshot(self) -> dict:
        with self.cond:
            return {**self.manifest, "version": self.version, "status": self.status, "bmt": __version__}


def _render_project(project: Project, renderer: Renderer) -> dict:
    build = project.build()
    # Keep GPU memory reasonable for big projects.
    scale = 2.0 if len(build.surfaces) <= 64 else 1.25
    salt = asset_signature(project.path)
    surfaces = {}
    issues = [i.to_dict() for i in build.issues]
    keep = set()
    for s in build.surfaces:
        r = renderer.render(s, scale=scale, salt=salt)
        keep.add(r.png)
        surfaces[s.id] = f"/render/{r.png.name}"
        issues += [i.to_dict() for i in r.issues]
    renderer.prune(keep)
    return {
        "name": project.name,
        "kind": project.kind.id,
        "product": project.product.to_dict(),
        "model": build.model,
        "surfaces": surfaces,
        "issues": issues,
        "error": None,
    }


def _watch(state: PreviewState) -> None:
    last = None
    with Renderer(state.root / ".bmt" / "preview") as renderer:
        while not state.stop.is_set():
            sig = source_signature(state.root)
            if sig == last:
                time.sleep(POLL_SECONDS)
                continue
            # Let a burst of writes settle so we don't render half-saved files.
            time.sleep(0.15)
            sig = source_signature(state.root)
            last = sig
            state.publish(status="rendering")
            try:
                manifest = _render_project(load_project(state.root), renderer)
                state.publish(status="ready", manifest=manifest)
            except ProjectError as e:
                state.publish(status="error", error=str(e))
            except Exception as e:  # keep the preview alive whatever happens
                traceback.print_exc()
                state.publish(status="error", error=f"{type(e).__name__}: {e}")


def _make_handler(state: PreviewState, viewer_js: Path):
    render_dir = state.root / ".bmt" / "preview"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path, cache: str = "no-store") -> None:
            if not path.is_file():
                self._send(404, b"not found", "text/plain")
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix == ".js":
                ctype = "text/javascript"
            self._send(200, path.read_bytes(), ctype, cache)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._file(STATIC_DIR / "index.html")
            elif path == "/viewer.js":
                self._file(viewer_js)
            elif path.startswith("/static/"):
                self._file(STATIC_DIR / Path(path).name)
            elif path.startswith("/render/"):
                # Named by content hash, so safe to cache forever.
                self._file(render_dir / Path(path).name, cache="public, max-age=31536000, immutable")
            elif path == "/api/state":
                self._send(200, json.dumps(state.snapshot()).encode(), "application/json")
            elif path == "/api/events":
                self._events()
            else:
                self._send(404, b"not found", "text/plain")

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            seen = -1
            try:
                while not state.stop.is_set():
                    with state.cond:
                        if state.version == seen:
                            state.cond.wait(timeout=15)
                        version, status = state.version, state.status
                    if version != seen:
                        seen = version
                        payload = json.dumps({"version": version, "status": status})
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    else:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            self.close_connection = True

    return Handler


def serve(root: Path, *, host: str = "127.0.0.1", port: int = 4173, open_browser: bool = True) -> None:
    root = Path(root).resolve()
    project = load_project(root)  # fail early if this is not a bmt project
    state = PreviewState(root, project.kind.id)
    handler = _make_handler(state, project.kind.viewer_js)

    server = None
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer((host, candidate), handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit(f"bmt: no free port between {port} and {port + 19}")
    server.daemon_threads = True

    watcher = threading.Thread(target=_watch, args=(state,), daemon=True)
    watcher.start()

    url = f"http://{host}:{server.server_address[1]}/"
    print(f"bmt preview of {project.name!r} running at {url}", flush=True)
    print("Edit the project's files and the page updates by itself. Ctrl-C to stop.", flush=True)
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.stop.set()
        server.server_close()
