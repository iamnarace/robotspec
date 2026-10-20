"""Command-line interface.

Exit codes: 0 success, 1 a test/lint failure, 2 bad input or usage.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, render
from . import bots as catalogue
from .bots import Bot
from .evaluate import evaluate
from .parser import RobotsFile
from .policy import PolicyError, load_policy, resolve_bots, run, snapshot
from .source import SourceError, is_url, load

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def _style(args: argparse.Namespace) -> render.Style:
    force = {"always": True, "never": False}.get(args.color)
    return render.Style(render.use_color(sys.stdout, force))


def _pick_bots(specs: Sequence[str] | None, categories: Sequence[str] | None) -> list[Bot]:
    chosen = list(specs or []) + [f"category:{c}" for c in categories or []]
    if not chosen:
        return list(catalogue.BOTS)
    return list(resolve_bots(chosen, "--bot/--category"))


def default_paths(robots: RobotsFile, limit: int = 8) -> list[str]:
    """'/' plus the literal paths mentioned in the file, so the matrix shows real decisions."""
    paths = ["/"]
    for group in robots.groups:
        for rule in group.rules:
            literal = rule.raw.split("*", 1)[0].rstrip("$")
            if literal.startswith("/") and literal not in paths:
                paths.append(literal)
            if len(paths) >= limit:
                return paths
    return paths


def _write(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        print(f"Wrote {output}", file=sys.stderr)
    else:
        print(text)


# --------------------------------------------------------------------------- commands
def cmd_check(args: argparse.Namespace) -> int:
    loaded = load(args.source)
    bots = _pick_bots(args.bot, None)
    verdicts = [evaluate(loaded.robots, bot, path) for bot in bots for path in args.path]
    if args.format == "json":
        print(render.verdicts_json(verdicts))
    else:
        style = _style(args)
        print("\n".join(render.verdict_text(v, style) for v in verdicts))
    return EXIT_OK


def cmd_matrix(args: argparse.Namespace) -> int:
    loaded = load(args.source)
    bots = _pick_bots(args.bot, args.category)
    paths = args.path or default_paths(loaded.robots)
    matrix = [(bot, [evaluate(loaded.robots, bot, p) for p in paths]) for bot in bots]
    shown = [v.path for v in matrix[0][1]] if matrix else paths
    if args.format == "json":
        text = render.matrix_json(matrix)
    elif args.format == "markdown":
        text = render.matrix_markdown(matrix, shown)
    elif args.format == "html":
        text = render.matrix_html(matrix, shown, loaded.robots, loaded.origin)
    else:
        text = render.matrix_text(matrix, shown, _style(args) if not args.output else render.Style(False))
    _write(text, args.output)
    return EXIT_OK


def cmd_lint(args: argparse.Namespace) -> int:
    loaded = load(args.source)
    findings = loaded.robots.findings
    if args.format == "json":
        print(render.findings_json(findings))
    else:
        print(render.findings_text(findings, _style(args)))
    failing = {"error"} | ({"warning"} if args.strict else set())
    return EXIT_FAIL if any(f.severity in failing for f in findings) else EXIT_OK


def cmd_test(args: argparse.Namespace) -> int:
    policy_path = Path(args.config)
    policy = load_policy(policy_path)
    source = policy.robots
    if not is_url(source) and source != "-" and not Path(source).is_absolute():
        source = str(policy_path.parent / source)
    if args.robots:
        source = args.robots
    loaded = load(source)
    report = run(policy, loaded.robots)

    if args.format == "json":
        print(render.report_json(report))
    elif args.format == "markdown":
        print(render.report_markdown(report))
    else:
        print(render.report_text(report, _style(args)))

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file and not args.no_summary:
        try:
            with open(summary_file, "a", encoding="utf-8") as fh:
                fh.write(render.report_markdown(report))
        except OSError as exc:
            print(f"warning: could not write GitHub step summary: {exc}", file=sys.stderr)
    return EXIT_OK if report.passed else EXIT_FAIL


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.exists() and not args.force:
        print(f"error: {target} already exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_USAGE
    loaded = load(args.source)
    bots = _pick_bots(args.bot, args.category)
    paths = args.path or default_paths(loaded.robots)
    target.write_text(snapshot(args.source, loaded.robots, bots, paths), encoding="utf-8")
    print(f"Wrote {target} with {len(bots)} crawlers × {len(paths)} paths. Run `robotspec test` to check it.")
    return EXIT_OK


def cmd_bots(args: argparse.Namespace) -> int:
    style = _style(args)
    selected = [b for b in catalogue.BOTS if not args.category or b.category in args.category]
    width = max(len(b.name) for b in selected) + 2
    category = None
    for bot in selected:
        if bot.category != category:
            category = bot.category
            print(style.bold(f"\n{category}") + style.dim(f" — {catalogue.CATEGORIES[category]}"))
        fallback = f"  falls back to: {', '.join(bot.tokens[1:])}" if len(bot.tokens) > 1 else ""
        flag = style.yellow("  may ignore robots.txt") if not bot.respects_robots else ""
        print(f"  {bot.name.ljust(width)}{style.dim(bot.operator)}{fallback}{flag}")
        print(f"  {' ' * width}{style.dim(bot.source)}")
    return EXIT_OK


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robotspec",
        description="Test your robots.txt like code: RFC 9309 matching, a crawler access matrix, and CI checks.",
    )
    parser.add_argument("--version", action="version", version=f"robotspec {__version__}")
    parser.add_argument(
        "--color", choices=["auto", "always", "never"], default="auto", help="colour output (default: auto)"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    categories = list(catalogue.CATEGORIES)
    source_help = "robots.txt file, site URL, or '-' for stdin"

    p = sub.add_parser("check", help="explain whether crawlers may fetch specific paths")
    p.add_argument("source", help=source_help)
    p.add_argument(
        "-b", "--bot", action="append", required=True, help="bot name, category:NAME or token:TOKEN (repeatable)"
    )
    p.add_argument("-p", "--path", action="append", required=True, help="path or URL to test (repeatable)")
    p.add_argument("-f", "--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("matrix", help="show which crawlers can reach which paths")
    p.add_argument("source", help=source_help)
    p.add_argument("-b", "--bot", action="append", help="limit to these bots (repeatable)")
    p.add_argument("-c", "--category", action="append", choices=categories, help="limit to a category (repeatable)")
    p.add_argument("-p", "--path", action="append", help="paths to test (default: '/' plus paths in the file)")
    p.add_argument("-f", "--format", choices=["text", "markdown", "json", "html"], default="text")
    p.add_argument("-o", "--output", help="write to a file instead of stdout")
    p.set_defaults(func=cmd_matrix)

    p = sub.add_parser("lint", help="report problems in a robots.txt file")
    p.add_argument("source", help=source_help)
    p.add_argument("--strict", action="store_true", help="also fail on warnings")
    p.add_argument("-f", "--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("test", help="check robots.txt against a policy file (for CI)")
    p.add_argument("-c", "--config", default="robotspec.toml", help="policy file (default: robotspec.toml)")
    p.add_argument("--robots", help="override the robots.txt source named in the policy")
    p.add_argument("-f", "--format", choices=["text", "markdown", "json"], default="text")
    p.add_argument("--no-summary", action="store_true", help="don't write to $GITHUB_STEP_SUMMARY")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("init", help="create a policy that locks in current behaviour")
    p.add_argument("source", help=source_help)
    p.add_argument("-o", "--output", default="robotspec.toml")
    p.add_argument("-b", "--bot", action="append")
    p.add_argument("-c", "--category", action="append", choices=categories)
    p.add_argument("-p", "--path", action="append")
    p.add_argument("--force", action="store_true", help="overwrite an existing policy file")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("bots", help="list the crawlers robotspec knows about")
    p.add_argument("-c", "--category", action="append", choices=categories)
    p.set_defaults(func=cmd_bots)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (SourceError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK
    except KeyboardInterrupt:
        return 130
