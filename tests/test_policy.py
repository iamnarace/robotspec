import tomllib

import pytest

from robotspec import bots
from robotspec.parser import parse
from robotspec.policy import PolicyError, policy_from_dict, resolve_bots, run, snapshot

ROBOTS = parse(
    "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nDisallow: /\n\nSitemap: https://e.com/sitemap.xml\n"
)


def policy(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "robots": "robots.txt",
        "expect": [{"bots": ["GPTBot"], "paths": ["/"], "access": "deny"}],
    }
    base.update(overrides)
    return base


def test_passing_policy() -> None:
    report = run(policy_from_dict(policy()), ROBOTS)
    assert report.passed
    assert len(report.cases) == 1


def test_failing_case_is_reported() -> None:
    data = policy(expect=[{"bots": ["Googlebot"], "paths": ["/admin/x", "/"], "access": "allow"}])
    report = run(policy_from_dict(data), ROBOTS)
    assert not report.passed
    assert [c.verdict.path for c in report.failures] == ["/admin/x"]


def test_categories_expand_to_every_member() -> None:
    resolved = resolve_bots(["category:ai-training"], "t")
    assert {b.name for b in resolved} == {b.name for b in bots.by_category("ai-training")}


def test_duplicates_are_removed_and_custom_tokens_allowed() -> None:
    resolved = resolve_bots(["GPTBot", "gptbot", "category:ai-training", "token:MyCrawler"], "t")
    names = [b.name for b in resolved]
    assert names.count("GPTBot") == 1
    assert "MyCrawler" in names


def test_unknown_bot_suggests_a_close_name() -> None:
    with pytest.raises(PolicyError, match="Did you mean 'GPTBot'"):
        resolve_bots(["GPTbott"], "t")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"expect": []}, "robots"),
        (policy(expect=[]), "at least one"),
        (policy(expect=[{"bots": ["GPTBot"], "paths": ["/"], "access": "maybe"}]), "access"),
        (policy(expect=[{"bots": "GPTBot", "paths": ["/"], "access": "deny"}]), "must be a list"),
        (policy(expect=[{"bots": ["GPTBot"], "paths": [], "access": "deny"}]), "paths"),
        (policy(expect=[{"bots": ["GPTBot"], "paths": ["/"], "access": "deny", "bogus": 1}]), "unknown key"),
        (policy(expect=[{"bots": ["category:nope"], "paths": ["/"], "access": "deny"}]), "unknown category"),
        (policy(require={"colour": True}), "unknown \\[require\\]"),
    ],
)
def test_invalid_policies_are_rejected(data: dict[str, object], message: str) -> None:
    with pytest.raises(PolicyError, match=message):
        policy_from_dict(data)


def test_requirements() -> None:
    no_sitemap = parse("User-agent: *\nDissallow: /x\n")
    report = run(policy_from_dict(policy(require={"sitemap": True, "no_lint_errors": True})), no_sitemap)
    assert not report.passed
    assert any("Sitemap" in f for f in report.requirement_failures)
    assert any("Lint error" in f for f in report.requirement_failures)


def test_snapshot_round_trips_and_passes() -> None:
    chosen = [bots.get("GPTBot"), bots.get("Googlebot"), bots.get("bingbot"), bots.custom("MyBot")]
    assert all(chosen)
    text = snapshot("robots.txt", ROBOTS, [b for b in chosen if b], ["/", "/admin/x"])
    data = tomllib.loads(text)
    # Googlebot, bingbot and MyBot behave the same, so they share expectations.
    assert any(set(e["bots"]) == {"Googlebot", "bingbot", "token:MyBot"} for e in data["expect"])
    assert data["require"]["sitemap"] is True
    assert run(policy_from_dict(data), ROBOTS).passed
