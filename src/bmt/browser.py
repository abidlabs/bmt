"""Drive a Chrome-family browser that is already installed, headlessly.

bmt ships no browser. Printing to PDF, taking print-resolution images and
running checks from the command line borrow whatever Chrome, Edge, Chromium or
Brave the machine has. Set ``BMT_BROWSER`` to the executable to choose one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
]
_LINUX = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable", "brave-browser",
]
_WINDOWS = [
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"Chromium\Application\chrome.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
]


class BrowserNotFound(Exception):
    pass


def find_browser() -> str:
    override = os.environ.get("BMT_BROWSER")
    if override:
        found = shutil.which(override) or (override if Path(override).is_file() else None)
        if not found:
            raise BrowserNotFound(f"BMT_BROWSER is set to {override!r}, which does not exist.")
        return found
    candidates: list[str] = []
    if sys.platform == "darwin":
        candidates = _MAC + [str(Path.home() / p.lstrip("/")) for p in _MAC]
    elif sys.platform.startswith("win"):
        roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        candidates = [str(Path(r) / p) for r in roots if r for p in _WINDOWS]
    for c in candidates:
        if Path(c).is_file():
            return c
    for name in _LINUX + ["chrome"]:
        found = shutil.which(name)
        if found:
            return found
    raise BrowserNotFound(
        "No Chrome, Edge, Chromium or Brave found. Install one, or set BMT_BROWSER to a "
        "Chrome-family executable. Without one you can still open `bmt preview` and use "
        "its Save PDF button."
    )


def run_headless(url: str, *args: str, timeout: float = 180, budget_ms: int = 15000) -> str:
    """Load ``url`` in a throwaway headless browser with extra flags; returns its stdout.

    The virtual time budget lets fonts, images and scripts finish before the
    browser prints, captures or dumps the page.
    """
    browser = find_browser()
    with tempfile.TemporaryDirectory(prefix="bmt-browser-") as profile:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--hide-scrollbars",
            f"--user-data-dir={profile}",
            f"--virtual-time-budget={budget_ms}",
            *args,
            url,
        ]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")  # Chrome refuses to sandbox as root (containers, CI)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"{Path(browser).name} exited with code {proc.returncode}: {' | '.join(tail)}")
    return proc.stdout


def print_to_pdf(url: str, out: Path) -> None:
    run_headless(url, "--no-pdf-header-footer", f"--print-to-pdf={out}")
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError("The browser did not produce a PDF.")


def screenshot(url: str, out: Path, *, width_px: int, height_px: int, scale: float) -> None:
    run_headless(
        url,
        f"--window-size={width_px},{height_px}",
        f"--force-device-scale-factor={scale}",
        f"--screenshot={out}",
    )
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError("The browser did not produce an image.")


def dump_dom(url: str) -> str:
    return run_headless(url, "--dump-dom")
