"""Policy files: expectations about a robots.txt, checked like tests.

Example ``robotspec.toml``::

    robots = "public/robots.txt"

    [[expect]]
    name = "AI training crawlers stay out"
    bots = ["category:ai-training"]
    paths = ["/", "/blog/"]
    access = "deny"

    [[expect]]
    bots = ["Googlebot", "bingbot"]
    paths = ["/", "/blog/hello-world"]
    access = "allow"

    [require]
    sitemap = true
    no_lint_errors = true
"""

from __future__ import annotations

import difflib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import bots as catalogue
from .bots import Bot
from .evaluate import Verdict, evaluate
from .parser import RobotsFile


class PolicyError(Exception):
    """The policy file is invalid."""


@dataclass(frozen=True)
class Expectation:
    name: str
    bots: tuple[Bot, ...]
    paths: tuple[str, ...]
    allow: bool


@dataclass(frozen=True)
class Policy:
    robots: str
    expectations: tuple[Expectation, ...]
    require_sitemap: bool = False
    require_no_lint_errors: bool = False
    path: str = ""


@dataclass(frozen=True)
class CaseResult:
    expectation: Expectation
    verdict: Verdict

    @property
    def passed(self) -> bool:
        return self.verdict.allowed == self.expectation.allow


@dataclass
class Report:
    policy: Policy
    cases: list[CaseResult] = field(default_factory=list)
    requirement_failures: list[str] = field(default_factory=list)

    @property
    def failures(self) -> list[CaseResult]:
        return [case for case in self.cases if not case.passed]

    @property
    def passed(self) -> bool:
        return not self.failures and not self.requirement_failures


def resolve_bots(specs: list[str], where: str) -> tuple[Bot, ...]:
    """Turn ``["GPTBot", "category:ai-training", "token:MyBot"]`` into bots."""
    resolved: dict[str, Bot] = {}
    for spec in specs:
        if not isinstance(spec, str) or not spec.strip():
            raise PolicyError(f"{where}: bot entries must be non-empty strings")
        spec = spec.strip()
        if spec.startswith("category:"):
            category = spec.split(":", 1)[1]
            if category not in catalogue.CATEGORIES:
                options = ", ".join(catalogue.CATEGORIES)
                raise PolicyError(f"{where}: unknown category {category!r} (choose from {options})")
            for bot in catalogue.by_category(category):
                resolved.setdefault(bot.name, bot)
        elif spec.startswith("token:"):
            token = spec.split(":", 1)[1].strip()
            if not token:
                raise PolicyError(f"{where}: 'token:' needs a user-agent token after it")
            bot = catalogue.custom(token)
            resolved.setdefault(bot.name, bot)
        else:
            known = catalogue.get(spec)
            if known is None:
                names = [b.name for b in catalogue.BOTS]
                close = difflib.get_close_matches(spec, names, n=1, cutoff=0.6)
                hint = f" Did you mean {close[0]!r}?" if close else ""
                raise PolicyError(
                    f"{where}: unknown bot {spec!r}.{hint} Use 'token:{spec}' for a crawler "
                    "that is not in the catalogue."
                )
            resolved.setdefault(known.name, known)
    if not resolved:
        raise PolicyError(f"{where}: 'bots' must list at least one bot")
    return tuple(resolved.values())


def load_policy(path: str | Path) -> Policy:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"Policy file not found: {path} (create one with 'robotspec init')") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"{path}: invalid TOML: {exc}") from exc
    return policy_from_dict(data, str(path))


def policy_from_dict(data: dict[str, Any], origin: str = "<policy>") -> Policy:
    robots = data.get("robots")
    if not isinstance(robots, str) or not robots:
        raise PolicyError(f"{origin}: set 'robots' to a file path or URL")

    raw_expectations = data.get("expect", [])
    if not isinstance(raw_expectations, list) or not raw_expectations:
        raise PolicyError(f"{origin}: add at least one [[expect]] table")

    expectations: list[Expectation] = []
    for index, item in enumerate(raw_expectations, start=1):
        where = f"{origin}: [[expect]] #{index}"
        if not isinstance(item, dict):
            raise PolicyError(f"{where} must be a table")
        unknown = set(item) - {"name", "bots", "paths", "access"}
        if unknown:
            raise PolicyError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
        access = item.get("access")
        if access not in ("allow", "deny"):
            raise PolicyError(f'{where}: \'access\' must be "allow" or "deny"')
        bots_spec = item.get("bots")
        if not isinstance(bots_spec, list):
            raise PolicyError(f"{where}: 'bots' must be a list")
        paths = item.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
            raise PolicyError(f"{where}: 'paths' must be a non-empty list of strings")
        bots = resolve_bots(bots_spec, where)
        default_name = f"{', '.join(b.name for b in bots[:3])}{'…' if len(bots) > 3 else ''} → {access}"
        name = item.get("name", default_name)
        if not isinstance(name, str):
            raise PolicyError(f"{where}: 'name' must be a string")
        expectations.append(Expectation(name, bots, tuple(paths), access == "allow"))

    require = data.get("require", {})
    if not isinstance(require, dict):
        raise PolicyError(f"{origin}: [require] must be a table")
    unknown_req = set(require) - {"sitemap", "no_lint_errors"}
    if unknown_req:
        raise PolicyError(f"{origin}: unknown [require] key(s) {', '.join(sorted(unknown_req))}")

    return Policy(
        robots=robots,
        expectations=tuple(expectations),
        require_sitemap=bool(require.get("sitemap", False)),
        require_no_lint_errors=bool(require.get("no_lint_errors", False)),
        path=origin,
    )


def run(policy: Policy, robots: RobotsFile) -> Report:
    report = Report(policy)
    for expectation in policy.expectations:
        for bot in expectation.bots:
            for path in expectation.paths:
                report.cases.append(CaseResult(expectation, evaluate(robots, bot, path)))
    if policy.require_sitemap and not robots.sitemaps:
        report.requirement_failures.append("No Sitemap line found, but [require] sitemap = true.")
    if policy.require_no_lint_errors:
        errors = [f for f in robots.findings if f.severity == "error"]
        for finding in errors:
            where = f"line {finding.line}: " if finding.line else ""
            report.requirement_failures.append(f"Lint error, {where}{finding.message}")
    return report


def snapshot(robots_source: str, robots: RobotsFile, bots: list[Bot], paths: list[str]) -> str:
    """Write a policy TOML that locks in the current behaviour."""
    lines = [
        "# Generated by `robotspec init`. It records how your robots.txt behaves today,",
        "# so `robotspec test` fails if a future edit changes that. Edit freely.",
        f"robots = {_toml_str(robots_source)}",
        "",
    ]
    # Group crawlers that behave identically so the policy stays short.
    groups: dict[tuple[tuple[str, ...], tuple[str, ...]], list[Bot]] = {}
    for bot in bots:
        allowed = tuple(p for p in paths if evaluate(robots, bot, p).allowed)
        denied = tuple(p for p in paths if p not in allowed)
        groups.setdefault((allowed, denied), []).append(bot)
    for (allowed, denied), members in groups.items():
        specs = [b.name if catalogue.get(b.name) else f"token:{b.name}" for b in members]
        bot_list = "[" + ", ".join(_toml_str(s) for s in specs) + "]"
        for access, chosen in (("deny", denied), ("allow", allowed)):
            if not chosen:
                continue
            lines += [
                "[[expect]]",
                f"bots = {bot_list}",
                "paths = [" + ", ".join(_toml_str(p) for p in chosen) + "]",
                f'access = "{access}"',
                "",
            ]
    lines += ["[require]", f"sitemap = {'true' if robots.sitemaps else 'false'}", "no_lint_errors = true", ""]
    return "\n".join(lines)


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
