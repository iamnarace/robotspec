"""Regenerate the README screenshots from real robotspec output.

Requires Playwright with Chromium (``pip install playwright && playwright install chromium``).
Run from the repository root:  python scripts/capture_screenshots.py
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
ANSI = re.compile(r"\x1b\[(\d+)m")
COLOURS = {"31": "#ff7b72", "32": "#7ee787", "33": "#e3b341", "2": "#8b949e", "1": None}


def run(*args: str) -> str:
    env = {**os.environ, "FORCE_COLOR": "1"}
    env.pop("NO_COLOR", None)
    env.pop("GITHUB_STEP_SUMMARY", None)
    result = subprocess.run(
        [sys.executable, "-m", "robotspec", *args], cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    return result.stdout


def ansi_to_html(text: str) -> str:
    out, open_spans = [], 0
    for piece in ANSI.split(text):
        if piece in COLOURS or piece == "0":
            if piece == "0":
                out.append("</span>" * open_spans)
                open_spans = 0
            elif piece == "1":
                out.append('<span style="font-weight:700">')
                open_spans += 1
            else:
                out.append(f'<span style="color:{COLOURS[piece]}">')
                open_spans += 1
        else:
            out.append(html.escape(piece))
    return "".join(out) + "</span>" * open_spans


def terminal_page(blocks: list[tuple[str, str]]) -> str:
    body = "".join(
        f'<div class="cmd"><span class="p">$</span> {html.escape(cmd)}</div><pre>{ansi_to_html(out)}</pre>'
        for cmd, out in blocks
    )
    return f"""<!doctype html><meta charset="utf-8"><style>
    body {{ margin:0; background:#0d1117; padding:24px; }}
    .win {{ background:#161b22; border:1px solid #30363d; border-radius:10px; overflow:hidden; }}
    .bar {{ height:34px; background:#21262d; display:flex; gap:8px; align-items:center; padding:0 14px; }}
    .bar i {{ width:12px; height:12px; border-radius:50%; background:#484f58; display:inline-block; }}
    .term {{ padding:16px 20px 20px; font:14px/1.5 "DejaVu Sans Mono", Menlo, monospace; color:#e6edf3; }}
    .cmd {{ color:#e6edf3; margin-top:10px; }} .p {{ color:#7ee787; }}
    pre {{ margin:6px 0 0; font:inherit; white-space:pre; }}
    </style><div class="win"><div class="bar"><i></i><i></i><i></i></div><div class="term">{body}</div></div>"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.html"
        subprocess.run(
            [sys.executable, "-m", "robotspec", "matrix", "examples/robots.txt", "-f", "html", "-o", str(report)],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        failing = run("test", "-c", "examples/robotspec.toml", "--robots", "examples/robots-before.txt")
        passing = run("test", "-c", "examples/robotspec.toml")
        check = run(
            "check", "examples/robots.txt", "-b", "PerplexityBot", "-p", "/blog/launch?session=42", "-p", "/blog/launch"
        )
        term_fail = Path(tmp) / "fail.html"
        term_fail.write_text(
            terminal_page(
                [
                    ("robotspec test --robots examples/robots-before.txt", failing),
                    ("robotspec test   # after the fix", passing.strip().splitlines()[-1] + "\n"),
                ]
            )
        )
        term_check = Path(tmp) / "check.html"
        term_check.write_text(
            terminal_page(
                [
                    (
                        'robotspec check examples/robots.txt -b PerplexityBot -p "/blog/launch?session=42" '
                        "-p /blog/launch",
                        check,
                    )
                ]
            )
        )

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
            page.goto(report.as_uri())
            page.screenshot(path=str(OUT / "report-desktop.png"), full_page=True)

            dark = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2, color_scheme="dark")
            dark.goto(report.as_uri())
            dark.screenshot(path=str(OUT / "report-dark.png"), clip={"x": 0, "y": 0, "width": 1280, "height": 760})

            mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
            mobile.goto(report.as_uri())
            mobile.screenshot(path=str(OUT / "report-mobile.png"))

            for name, file in (("terminal-test", term_fail), ("terminal-check", term_check)):
                term = browser.new_page(viewport={"width": 1000, "height": 400}, device_scale_factor=2)
                term.goto(file.as_uri())
                term.locator(".win").screenshot(path=str(OUT / f"{name}.png"))
            browser.close()
    for f in sorted(OUT.glob("*.png")):
        print(f.relative_to(ROOT))


if __name__ == "__main__":
    main()
