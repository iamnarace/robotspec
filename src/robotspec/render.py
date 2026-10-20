"""Output formats: terminal text, Markdown, JSON and a standalone HTML report."""

from __future__ import annotations

import html
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from . import __version__
from .bots import CATEGORIES, Bot
from .evaluate import Verdict
from .parser import Finding, RobotsFile
from .policy import Report


# --------------------------------------------------------------------------- colour
class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)


def use_color(stream: Any = None, force: bool | None = None) -> bool:
    if force is not None:
        return force
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


# --------------------------------------------------------------------------- verdicts
def verdict_text(v: Verdict, style: Style) -> str:
    word = style.green("ALLOW") if v.allowed else style.red("DENY ")
    rule = f"  {style.dim(str(v.rule))}" if v.rule else ""
    lines = [f"{word}  {style.bold(v.bot.name)}  {v.path}{rule}", f"       {style.dim(v.reason)}"]
    if not v.bot.respects_robots:
        lines.append("       " + style.yellow(f"note: {v.bot.note}"))
    return "\n".join(lines)


def verdicts_json(verdicts: Sequence[Verdict]) -> str:
    return json.dumps([_verdict_dict(v) for v in verdicts], indent=2)


def _verdict_dict(v: Verdict) -> dict[str, Any]:
    return {
        "bot": v.bot.name,
        "path": v.path,
        "access": v.label,
        "group": v.group,
        "rule": str(v.rule) if v.rule else None,
        "line": v.rule.line if v.rule and v.rule.line else None,
        "reason": v.reason,
        "respects_robots": v.bot.respects_robots,
    }


# --------------------------------------------------------------------------- matrix
Matrix = list[tuple[Bot, list[Verdict]]]


def matrix_text(matrix: Matrix, paths: Sequence[str], style: Style) -> str:
    name_width = max([len(b.name) for b, _ in matrix] + [7]) + 2
    col_width = max([len(p) for p in paths] + [5]) + 2
    header = "Crawler".ljust(name_width) + "".join(p.ljust(col_width) for p in paths)
    out = [style.bold(header), style.dim("─" * len(header))]
    category = None
    for bot, verdicts in matrix:
        if bot.category != category:
            category = bot.category
            out.append(style.dim(f"{CATEGORIES.get(category, category)}"))
        name = bot.name + ("*" if not bot.respects_robots else "")
        row = name.ljust(name_width)
        for v in verdicts:
            cell = ("allow" if v.allowed else "deny").ljust(col_width)
            row += style.green(cell) if v.allowed else style.red(cell)
        out.append(row.rstrip())
    if any(not b.respects_robots for b, _ in matrix):
        out.append("")
        out.append(style.yellow("* operator says this fetcher may not follow robots.txt for user-initiated requests"))
    return "\n".join(out)


def matrix_markdown(matrix: Matrix, paths: Sequence[str]) -> str:
    head = "| Crawler | " + " | ".join(f"`{p}`" for p in paths) + " |"
    sep = "|---|" + "---|" * len(paths)
    rows = [head, sep]
    for bot, verdicts in matrix:
        flag = " ⚠️" if not bot.respects_robots else ""
        cells = " | ".join("✅ allow" if v.allowed else "⛔ deny" for v in verdicts)
        rows.append(f"| {bot.name}{flag} | {cells} |")
    if any(not b.respects_robots for b, _ in matrix):
        rows.append("")
        rows.append("⚠️ The operator says this fetcher may not follow robots.txt for user-initiated requests.")
    return "\n".join(rows)


def matrix_json(matrix: Matrix) -> str:
    return json.dumps(
        [
            {
                "bot": bot.name,
                "category": bot.category,
                "operator": bot.operator,
                "respects_robots": bot.respects_robots,
                "results": [_verdict_dict(v) for v in verdicts],
            }
            for bot, verdicts in matrix
        ],
        indent=2,
    )


# --------------------------------------------------------------------------- findings
def findings_text(findings: Sequence[Finding], style: Style) -> str:
    if not findings:
        return style.green("No problems found.")
    colour = {"error": style.red, "warning": style.yellow, "info": style.dim}
    out = []
    for f in sorted(findings, key=lambda f: f.line or 0):
        where = f"line {f.line}" if f.line else "file"
        out.append(
            f"{colour[f.severity](f.severity.upper().ljust(7))} {where.ljust(9)} {f.message}  {style.dim(f'[{f.code}]')}"
        )
    return "\n".join(out)


def findings_json(findings: Sequence[Finding]) -> str:
    return json.dumps(
        [{"severity": f.severity, "line": f.line, "code": f.code, "message": f.message} for f in findings],
        indent=2,
    )


# --------------------------------------------------------------------------- test reports
def report_text(report: Report, style: Style) -> str:
    out = []
    by_expectation: dict[int, list[Any]] = {}
    for case in report.cases:
        by_expectation.setdefault(id(case.expectation), []).append(case)
    for expectation in report.policy.expectations:
        cases = by_expectation.get(id(expectation), [])
        failed = [c for c in cases if not c.passed]
        mark = style.green("✓") if not failed else style.red("✗")
        out.append(f"{mark} {expectation.name}  {style.dim(f'({len(cases) - len(failed)}/{len(cases)})')}")
        for case in failed:
            v = case.verdict
            want = "allow" if expectation.allow else "deny"
            rule = f" by {v.rule} (line {v.rule.line})" if v.rule and v.rule.line else ""
            out.append(f"    {style.red('expected ' + want)}, got {v.label}: {style.bold(v.bot.name)} {v.path}{rule}")
            out.append(f"    {style.dim(v.reason)}")
    for failure in report.requirement_failures:
        out.append(f"{style.red('✗')} {failure}")
    total, failed_count = len(report.cases), len(report.failures)
    summary = f"{total - failed_count} passed, {failed_count} failed"
    if report.requirement_failures:
        summary += f", {len(report.requirement_failures)} requirement(s) not met"
    out.append("")
    out.append(style.green(summary) if report.passed else style.red(summary))
    return "\n".join(out)


def report_markdown(report: Report) -> str:
    status = "✅ robots.txt policy passed" if report.passed else "❌ robots.txt policy failed"
    out = [f"### {status}", "", f"Policy: `{report.policy.path}` · robots.txt: `{report.policy.robots}`", ""]
    out += ["| Expectation | Result |", "|---|---|"]
    for expectation in report.policy.expectations:
        cases = [c for c in report.cases if c.expectation is expectation]
        failed = [c for c in cases if not c.passed]
        out.append(f"| {expectation.name} | {'✅' if not failed else '❌'} {len(cases) - len(failed)}/{len(cases)} |")
    if report.failures or report.requirement_failures:
        out += ["", "**Failures**", ""]
        for case in report.failures:
            v = case.verdict
            want = "allow" if case.expectation.allow else "deny"
            rule = f" — `{v.rule}` (line {v.rule.line})" if v.rule and v.rule.line else ""
            out.append(f"- **{v.bot.name}** `{v.path}`: expected {want}, got {v.label}{rule}")
        for failure in report.requirement_failures:
            out.append(f"- {failure}")
    return "\n".join(out) + "\n"


def report_json(report: Report) -> str:
    return json.dumps(
        {
            "passed": report.passed,
            "policy": report.policy.path,
            "robots": report.policy.robots,
            "cases": [
                {
                    "expectation": c.expectation.name,
                    "expected": "allow" if c.expectation.allow else "deny",
                    "passed": c.passed,
                    **_verdict_dict(c.verdict),
                }
                for c in report.cases
            ],
            "requirement_failures": report.requirement_failures,
        },
        indent=2,
    )


# --------------------------------------------------------------------------- HTML
def matrix_html(matrix: Matrix, paths: Sequence[str], robots: RobotsFile, origin: str) -> str:
    e = html.escape
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    total = sum(len(v) for _, v in matrix)
    denied = sum(1 for _, vs in matrix for v in vs if not v.allowed)
    errors = sum(1 for f in robots.findings if f.severity == "error")
    warnings = sum(1 for f in robots.findings if f.severity == "warning")

    head_cells = "".join(f'<th scope="col"><code>{e(p)}</code></th>' for p in paths)
    body_rows = []
    category = None
    for bot, verdicts in matrix:
        if bot.category != category:
            category = bot.category
            body_rows.append(
                f'<tr class="cat"><th colspan="{len(paths) + 1}" scope="rowgroup">'
                f"{e(CATEGORIES.get(category, category))}</th></tr>"
            )
        flag = (
            f' <span class="flag" title="{e(bot.note)}">may ignore robots.txt</span>' if not bot.respects_robots else ""
        )
        cells = []
        for v in verdicts:
            if v.rule and v.rule.line:
                detail = f"{v.rule} (L{v.rule.line})"
            elif v.group is None:
                detail = "no group applies"
            else:
                detail = "no matching rule"
            group = f"[{v.group}] " if v.group else ""
            css, mark, word = ("ok", "✓", "Allowed") if v.allowed else ("no", "✕", "Blocked")
            cells.append(
                f'<td class="{css}" title="{e(v.reason)}"><span class="mark" aria-hidden="true">{mark}</span>'
                f'<span class="word">{word}</span><span class="why">{e(group + detail)}</span></td>'
            )
        operator = f'<span class="op">{e(bot.operator)}</span>'
        name = f'<a href="{e(bot.source)}">{e(bot.name)}</a>' if bot.source else e(bot.name)
        body_rows.append(f'<tr><th scope="row">{name}{flag}{operator}</th>{"".join(cells)}</tr>')

    finding_items = (
        "".join(
            f'<li class="{f.severity}"><span class="sev">{f.severity}</span>'
            f'<span class="ln">{"line " + str(f.line) if f.line else "file"}</span>{e(f.message)}</li>'
            for f in sorted(robots.findings, key=lambda f: f.line or 0)
        )
        or '<li class="none">No problems found.</li>'
    )
    sitemaps = "".join(f"<li><code>{e(s)}</code></li>" for s in robots.sitemaps) or "<li>None declared</li>"

    return _HTML_TEMPLATE.format(
        title=e(f"robots.txt report · {origin}"),
        origin=e(origin),
        generated=e(generated),
        version=e(__version__),
        bots=len(matrix),
        paths=len(paths),
        denied=denied,
        total=total,
        errors=errors,
        warnings=warnings,
        head_cells=head_cells,
        rows="\n".join(body_rows),
        findings=finding_items,
        sitemaps=sitemaps,
    )


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --paper: #f5f2ea; --card: #fffdf8; --ink: #1d1b16; --muted: #6b665b; --rule: #ddd6c6;
  --ok: #1d6b45; --ok-bg: #e3f1e8; --no: #a3261c; --no-bg: #f8e3df; --warn: #8a5a00; --warn-bg: #fbefd4;
  --accent: #2f4a8a;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper: #15140f; --card: #1e1c17; --ink: #ece7db; --muted: #a39d8f; --rule: #37332a;
    --ok: #7fd3a4; --ok-bg: #18301f; --no: #f2988c; --no-bg: #3a1c18; --warn: #f0c46a; --warn-bg: #362a12;
    --accent: #9db4f2;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 32px 16px 64px; }}
code, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.92em; }}
header .kicker {{ text-transform: uppercase; letter-spacing: .12em; font-size: 12px; color: var(--muted); }}
h1 {{ font-size: clamp(24px, 4vw, 34px); line-height: 1.15; margin: 6px 0 4px; letter-spacing: -0.01em; }}
h1 code {{ font-size: 0.8em; color: var(--accent); word-break: break-all; }}
.meta {{ color: var(--muted); font-size: 13px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 24px 0; }}
.stat {{ background: var(--card); border: 1px solid var(--rule); border-radius: 10px; padding: 12px 14px; }}
.stat b {{ display: block; font-size: 24px; font-variant-numeric: tabular-nums; }}
.stat span {{ color: var(--muted); font-size: 13px; }}
.panel {{ background: var(--card); border: 1px solid var(--rule); border-radius: 12px; overflow: hidden; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: separate; border-spacing: 0; width: 100%; min-width: 560px; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--rule); text-align: left; vertical-align: top; }}
thead th {{ position: sticky; top: 0; background: var(--card); font-weight: 600; font-size: 13px; white-space: nowrap; }}
tbody th[scope=row] {{ position: sticky; left: 0; background: var(--card); font-weight: 600; min-width: 170px; z-index: 1; }}
@media (max-width: 600px) {{ tbody th[scope=row] {{ min-width: 118px; max-width: 132px; word-break: break-word; }} th, td {{ padding: 8px 9px; }} td {{ min-width: 104px; }} }}
tbody th a {{ color: inherit; text-decoration-color: var(--rule); text-underline-offset: 3px; }}
.op {{ display: block; font-weight: 400; color: var(--muted); font-size: 12px; }}
.flag {{ display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 999px; font-size: 11px; font-weight: 600;
  background: var(--warn-bg); color: var(--warn); vertical-align: 1px; }}
tr.cat th {{ background: var(--paper); color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em;
  font-weight: 600; padding: 8px 12px; }}
td.ok {{ background: var(--ok-bg); color: var(--ok); }}
td.no {{ background: var(--no-bg); color: var(--no); }}
.mark {{ font-weight: 700; margin-right: 6px; }}
.word {{ font-weight: 600; }}
.why {{ display: block; font-size: 12px; opacity: .85; font-family: ui-monospace, Menlo, monospace; word-break: break-word; }}
section {{ margin-top: 28px; }}
h2 {{ font-size: 18px; margin: 0 0 10px; }}
.grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }}
@media (max-width: 760px) {{ .grid {{ grid-template-columns: 1fr; }} }}
ul.findings, ul.plain {{ list-style: none; margin: 0; padding: 0; }}
ul.findings li {{ padding: 10px 14px; border-bottom: 1px solid var(--rule); display: grid; grid-template-columns: 74px 64px 1fr; gap: 8px; }}
ul.findings li:last-child {{ border-bottom: 0; }}
ul.findings li.none {{ display: block; }}
@media (max-width: 520px) {{ ul.findings li {{ grid-template-columns: 1fr; gap: 2px; }} }}
.sev {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }}
li.error .sev {{ color: var(--no); }} li.warning .sev {{ color: var(--warn); }} li.info .sev {{ color: var(--muted); }}
.ln {{ color: var(--muted); font-size: 13px; font-family: ui-monospace, Menlo, monospace; }}
ul.plain li {{ padding: 10px 14px; border-bottom: 1px solid var(--rule); word-break: break-all; }}
footer {{ margin-top: 32px; color: var(--muted); font-size: 13px; }}
footer a {{ color: var(--accent); }}
</style>
</head>
<body>
<main>
<header>
  <div class="kicker">robotspec · crawler access report</div>
  <h1>Who can crawl <code>{origin}</code></h1>
  <div class="meta">Generated {generated} · robotspec {version} · evaluated with RFC 9309 matching</div>
</header>
<div class="stats" role="list">
  <div class="stat" role="listitem"><b>{bots}</b><span>crawlers checked</span></div>
  <div class="stat" role="listitem"><b>{paths}</b><span>paths tested</span></div>
  <div class="stat" role="listitem"><b>{denied}/{total}</b><span>combinations blocked</span></div>
  <div class="stat" role="listitem"><b>{errors} · {warnings}</b><span>lint errors · warnings</span></div>
</div>
<div class="panel"><div class="scroll">
<table>
<caption class="sr-only" style="position:absolute;left:-9999px">Access by crawler and path</caption>
<thead><tr><th scope="col">Crawler</th>{head_cells}</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div></div>
<div class="grid">
<section><h2>Lint findings</h2><div class="panel"><ul class="findings">{findings}</ul></div></section>
<section><h2>Sitemaps</h2><div class="panel"><ul class="plain">{sitemaps}</ul></div></section>
</div>
<p class="meta" style="margin-top:10px">Hover a cell for the full explanation. <code>[token]</code> is the user-agent group the crawler obeys.</p>
<footer>robots.txt is a request, not access control: it does not stop crawlers that choose to ignore it.
Crawler details link to each operator's documentation. Made with <a href="https://github.com/iamnarace/robotspec">robotspec</a>.</footer>
</main>
</body>
</html>
"""
