"""Decide whether a crawler may fetch a path, and explain why."""

from __future__ import annotations

from dataclasses import dataclass

from .bots import Bot
from .matcher import pattern_matches, request_path, specificity
from .parser import RobotsFile, Rule


@dataclass(frozen=True)
class Verdict:
    bot: Bot
    path: str  # normalised request path
    allowed: bool
    group: str | None  # the user-agent token whose group was used, "*" or None
    rule: Rule | None  # the deciding rule, if any
    reason: str

    @property
    def label(self) -> str:
        return "allow" if self.allowed else "deny"


def select_group(robots: RobotsFile, bot: Bot) -> tuple[str | None, list[Rule]]:
    """Pick the group a crawler obeys.

    The crawler's tokens are tried in order (most specific first, then any
    documented fallback); if none has a group the ``*`` group is used.
    """
    for token in bot.tokens:
        rules = robots.rules_for(token)
        if rules is not None:
            return token.lower(), rules
    star = robots.rules_for("*")
    if star is not None:
        return "*", star
    return None, []


def evaluate(robots: RobotsFile, bot: Bot, url_or_path: str) -> Verdict:
    path = request_path(url_or_path)

    if path == "/robots.txt" and robots.synthetic is None:
        return Verdict(bot, path, True, None, None, "/robots.txt is always allowed (RFC 9309 §2.2.2).")

    group, rules = select_group(robots, bot)
    if group is None:
        if robots.synthetic == "allow-all":
            reason = "robots.txt is unavailable (4xx), so everything is allowed."
        else:
            reason = "No group matches this crawler and there is no '*' group."
        return Verdict(bot, path, True, None, None, reason)

    best: Rule | None = None
    best_len = -1
    for rule in rules:
        if not pattern_matches(rule.pattern, path):
            continue
        length = specificity(rule.pattern)
        if length > best_len or (length == best_len and rule.allow and best is not None and not best.allow):
            best, best_len = rule, length

    where = "the '*' group" if group == "*" else f"the '{group}' group"
    if best is None:
        return Verdict(bot, path, True, group, None, f"No rule in {where} matches, so it is allowed.")

    if robots.synthetic == "disallow-all":
        reason = "robots.txt is unreachable (5xx or network error), so crawlers must assume full disallow."
    else:
        reason = f"Line {best.line} in {where} is the most specific match."
    return Verdict(bot, path, best.allow, group, best, reason)
