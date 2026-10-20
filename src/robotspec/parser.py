"""Parse robots.txt files into groups of rules (RFC 9309, section 2).

The parser is deliberately forgiving: like real crawlers it tries every
line and keeps whatever it can understand.  Anything surprising is
recorded as a :class:`Finding` so ``robotspec lint`` can report it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .matcher import normalize

#: RFC 9309 requires crawlers to parse at least 500 KiB.
PARSE_LIMIT_BYTES = 500 * 1024

Severity = Literal["error", "warning", "info"]

_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*(?:[ \t]+[A-Za-z][A-Za-z0-9_-]*)?)\s*:\s*(.*?)\s*$")
_TOKEN_RE = re.compile(r"[A-Za-z_-]+")

_KNOWN_NON_GROUP = {"sitemap"}
_KNOWN_IGNORED = {
    "crawl-delay": "Crawl-delay is not part of RFC 9309; Google and Apple ignore it.",
    "host": "Host is a legacy Yandex extension and is ignored by most crawlers.",
    "noindex": "Noindex in robots.txt is not supported (Google stopped honouring it in 2019).",
    "clean-param": "Clean-param is a Yandex-only extension.",
    "request-rate": "Request-rate is a non-standard extension that most crawlers ignore.",
    "visit-time": "Visit-time is a non-standard extension that most crawlers ignore.",
    "content-signal": "Content-Signal is a newer, non-RFC extension; support varies by crawler.",
}
_TYPOS = {
    "useragent": "user-agent",
    "user agent": "user-agent",
    "user_agent": "user-agent",
    "dissallow": "disallow",
    "disalow": "disallow",
    "dissalow": "disallow",
    "allowed": "allow",
    "disallowed": "disallow",
    "site-map": "sitemap",
}


@dataclass(frozen=True)
class Finding:
    """Something worth telling the author about a robots.txt file."""

    severity: Severity
    line: int | None
    code: str
    message: str


@dataclass(frozen=True)
class Rule:
    """A single Allow or Disallow line."""

    allow: bool
    raw: str  # value as written in the file
    pattern: str  # normalised pattern used for matching
    line: int

    @property
    def directive(self) -> str:
        return "Allow" if self.allow else "Disallow"

    def __str__(self) -> str:
        return f"{self.directive}: {self.raw}"


@dataclass
class Group:
    """Rules addressed to one or more user-agent product tokens."""

    agents: list[str]  # lower-cased tokens; "*" for the catch-all
    rules: list[Rule] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)  # line where each agent first appears


@dataclass
class RobotsFile:
    """The parsed form of a robots.txt file."""

    groups: list[Group]
    sitemaps: list[str]
    findings: list[Finding]
    size_bytes: int
    #: Synthetic files created for unavailable/unreachable robots.txt.
    synthetic: Literal["allow-all", "disallow-all"] | None = None

    def rules_for(self, token: str) -> list[Rule] | None:
        """Merged rules for ``token`` (case-insensitive), or None if no group names it.

        RFC 9309: "If there are multiple groups indicated by the same
        product token, the rules from the groups MUST be combined into
        one group."
        """
        wanted = token.lower()
        merged: list[Rule] | None = None
        for group in self.groups:
            if wanted in group.agents:
                if merged is None:
                    merged = []
                merged.extend(group.rules)
        return merged

    @property
    def agents(self) -> list[str]:
        seen: dict[str, None] = {}
        for group in self.groups:
            for agent in group.agents:
                seen.setdefault(agent, None)
        return list(seen)

    @classmethod
    def allow_all(cls, reason: str) -> RobotsFile:
        return cls([], [], [Finding("info", None, "unavailable", reason)], 0, "allow-all")

    @classmethod
    def disallow_all(cls, reason: str) -> RobotsFile:
        rule = Rule(False, "/", "/", 0)
        group = Group(["*"], [rule])
        return cls([group], [], [Finding("warning", None, "unreachable", reason)], 0, "disallow-all")


def parse(text: str | bytes) -> RobotsFile:
    """Parse robots.txt content.

    ``bytes`` input is decoded as UTF-8 (invalid sequences are replaced),
    which is what RFC 9309 requires of the file encoding.
    """
    findings: list[Finding] = []
    if isinstance(text, bytes):
        raw = text
        size = len(raw)
        if size > PARSE_LIMIT_BYTES:
            findings.append(
                Finding(
                    "warning",
                    None,
                    "too-large",
                    f"File is {size:,} bytes; crawlers may stop parsing after 500 KiB "
                    f"({PARSE_LIMIT_BYTES:,} bytes). Rules beyond that point may be ignored.",
                )
            )
        text = raw.decode("utf-8", errors="replace")
        if "�" in text:
            findings.append(Finding("warning", None, "encoding", "File is not valid UTF-8; some bytes were replaced."))
    else:
        size = len(text.encode("utf-8"))
        if size > PARSE_LIMIT_BYTES:
            findings.append(
                Finding(
                    "warning",
                    None,
                    "too-large",
                    f"File is {size:,} bytes; crawlers may stop parsing after 500 KiB.",
                )
            )

    if text.startswith("﻿"):
        text = text[1:]

    groups: list[Group] = []
    sitemaps: list[str] = []
    current: Group | None = None
    collecting_agents = False  # True while consecutive user-agent lines build one group

    for number, original in enumerate(re.split(r"\r\n|\r|\n", text), start=1):
        line = original.split("#", 1)[0]
        if not line.strip():
            continue
        match = _LINE_RE.match(line)
        if not match:
            findings.append(
                Finding(
                    "error",
                    number,
                    "unparseable",
                    f"Cannot parse line {original.strip()!r}; expected 'Directive: value'.",
                )
            )
            continue

        key = re.sub(r"\s+", " ", match.group(1).lower())
        value = match.group(2)

        if key in _TYPOS:
            findings.append(
                Finding(
                    "error",
                    number,
                    "typo",
                    f"Unknown directive {match.group(1)!r}; did you mean "
                    f"'{_TYPOS[key].title()}'? Crawlers that follow RFC 9309 ignore this line.",
                )
            )
            continue

        if key == "user-agent":
            token = _agent_token(value, number, findings)
            if token is None:
                continue
            if current is None or not collecting_agents:
                current = Group([token], [], [number])
                groups.append(current)
                collecting_agents = True
            else:
                if token not in current.agents:
                    current.agents.append(token)
                    current.lines.append(number)
            continue

        if key in ("allow", "disallow"):
            collecting_agents = False
            if current is None:
                findings.append(
                    Finding(
                        "error",
                        number,
                        "rule-before-agent",
                        f"'{match.group(1)}: {value}' appears before any User-agent line and is ignored.",
                    )
                )
                continue
            if value == "":
                if key == "disallow":
                    findings.append(
                        Finding(
                            "info",
                            number,
                            "empty-disallow",
                            "Empty Disallow means 'nothing is disallowed' for this group.",
                        )
                    )
                continue
            _check_pattern(value, number, findings)
            current.rules.append(Rule(key == "allow", value, normalize(value, keep_wildcards=True), number))
            continue

        if key in _KNOWN_NON_GROUP:
            if not re.match(r"^https?://", value, re.I):
                findings.append(
                    Finding(
                        "warning",
                        number,
                        "sitemap-url",
                        f"Sitemap should be an absolute URL, got {value!r}.",
                    )
                )
            sitemaps.append(value)
            continue

        if key in _KNOWN_IGNORED:
            findings.append(Finding("warning", number, "ignored-directive", _KNOWN_IGNORED[key]))
            continue

        findings.append(
            Finding(
                "warning",
                number,
                "unknown-directive",
                f"Unknown directive {match.group(1)!r}; crawlers will ignore it.",
            )
        )

    _check_groups(groups, findings)
    return RobotsFile(groups, sitemaps, findings, size)


def _agent_token(value: str, number: int, findings: list[Finding]) -> str | None:
    stripped = value.strip()
    if stripped == "*":
        return "*"
    token_match = _TOKEN_RE.match(stripped)
    if not token_match:
        findings.append(
            Finding(
                "error",
                number,
                "bad-agent",
                f"User-agent value {value!r} contains no product token; the line is ignored.",
            )
        )
        return None
    token = token_match.group(0)
    if token != stripped:
        findings.append(
            Finding(
                "warning",
                number,
                "agent-token",
                f"User-agent {stripped!r} is read as the product token {token!r}. "
                "Use only the token (letters, '-' and '_').",
            )
        )
    return token.lower()


def _check_pattern(value: str, number: int, findings: list[Finding]) -> None:
    if not (value.startswith("/") or value.startswith("*")):
        findings.append(
            Finding(
                "warning",
                number,
                "relative-path",
                f"Path {value!r} should start with '/' or '*'; most crawlers will treat it as never matching.",
            )
        )
    if "$" in value[:-1]:
        findings.append(
            Finding(
                "warning",
                number,
                "dollar",
                f"'$' only anchors at the end of a pattern; in {value!r} it is matched literally "
                "by some crawlers and ignored by others.",
            )
        )
    if " " in value:
        findings.append(
            Finding(
                "warning",
                number,
                "space",
                f"Path {value!r} contains a space; percent-encode it as %20.",
            )
        )


def _check_groups(groups: list[Group], findings: list[Finding]) -> None:
    first_seen: dict[str, int] = {}
    for group in groups:
        for agent, line in zip(group.agents, group.lines, strict=False):
            if agent in first_seen:
                findings.append(
                    Finding(
                        "info",
                        line,
                        "merged-group",
                        f"User-agent {agent!r} also appears on line {first_seen[agent]}; "
                        "RFC 9309 merges both groups' rules.",
                    )
                )
            else:
                first_seen[agent] = line
        if not group.rules:
            findings.append(
                Finding(
                    "info",
                    group.lines[0] if group.lines else None,
                    "empty-group",
                    f"Group for {', '.join(group.agents)} has no Allow/Disallow rules, so "
                    "everything is allowed for it.",
                )
            )
