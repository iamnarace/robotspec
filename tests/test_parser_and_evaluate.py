from robotspec import bots
from robotspec.bots import Bot
from robotspec.evaluate import evaluate, select_group
from robotspec.parser import PARSE_LIMIT_BYTES, RobotsFile, parse


def bot(token: str, *fallback: str) -> Bot:
    return Bot(token, (token, *fallback), "custom", "test", "")


def codes(robots: RobotsFile) -> set[str]:
    return {f.code for f in robots.findings}


# --------------------------------------------------------------------------- parsing
def test_consecutive_user_agents_share_one_group() -> None:
    robots = parse("User-agent: a\nUser-agent: b\nDisallow: /x\n")
    assert len(robots.groups) == 1
    assert robots.groups[0].agents == ["a", "b"]


def test_user_agent_after_rules_starts_a_new_group() -> None:
    robots = parse("User-agent: a\nDisallow: /x\nUser-agent: b\nDisallow: /y\n")
    assert [g.agents for g in robots.groups] == [["a"], ["b"]]


def test_groups_for_the_same_agent_are_merged() -> None:
    robots = parse("User-agent: bot\nDisallow: /a\n\nUser-agent: other\nDisallow: /\n\nUser-agent: BOT\nDisallow: /b\n")
    rules = robots.rules_for("Bot")
    assert rules is not None
    assert [r.raw for r in rules] == ["/a", "/b"]
    assert "merged-group" in codes(robots)
    assert not evaluate(robots, bot("bot"), "/b").allowed


def test_directives_are_case_insensitive_and_comments_ignored() -> None:
    robots = parse("USER-AGENT: *  # everyone\ndisallow: /private # secret\n")
    assert not evaluate(robots, bot("x"), "/private/file").allowed


def test_rules_before_any_user_agent_are_ignored() -> None:
    robots = parse("Disallow: /\nUser-agent: *\nDisallow: /x\n")
    assert evaluate(robots, bot("x"), "/").allowed
    assert "rule-before-agent" in codes(robots)


def test_empty_disallow_allows_everything() -> None:
    robots = parse("User-agent: *\nDisallow:\n")
    assert evaluate(robots, bot("x"), "/anything").allowed
    assert "empty-disallow" in codes(robots)


def test_crlf_cr_and_bom_are_handled() -> None:
    robots = parse("﻿User-agent: *\r\nDisallow: /a\rDisallow: /b\n")
    assert not evaluate(robots, bot("x"), "/a").allowed
    assert not evaluate(robots, bot("x"), "/b").allowed


def test_agent_value_with_version_uses_product_token() -> None:
    robots = parse("User-agent: Googlebot/2.1\nDisallow: /\n")
    assert robots.groups[0].agents == ["googlebot"]
    assert "agent-token" in codes(robots)


def test_typos_unknown_and_ignored_directives_are_reported() -> None:
    robots = parse("User-agent: *\nDissallow: /x\nCrawl-delay: 10\nNoindex: /y\nFoo: bar\nnot a directive\n")
    found = codes(robots)
    assert {"typo", "ignored-directive", "unknown-directive", "unparseable"} <= found
    # The misspelt rule does not take effect.
    assert evaluate(robots, bot("x"), "/x").allowed


def test_sitemaps_are_collected_and_relative_ones_warned() -> None:
    robots = parse("Sitemap: https://e.com/s.xml\nSitemap: /s2.xml\nUser-agent: *\nDisallow:\n")
    assert robots.sitemaps == ["https://e.com/s.xml", "/s2.xml"]
    assert "sitemap-url" in codes(robots)


def test_pattern_warnings() -> None:
    robots = parse("User-agent: *\nDisallow: private\nDisallow: /a$b\nDisallow: /a b\n")
    assert {"relative-path", "dollar", "space"} <= codes(robots)


def test_large_files_are_flagged() -> None:
    body = ("User-agent: *\n" + "Disallow: /x\n" * (PARSE_LIMIT_BYTES // 12 + 10)).encode()
    assert "too-large" in codes(parse(body))


def test_invalid_utf8_is_flagged_not_fatal() -> None:
    robots = parse(b"User-agent: *\nDisallow: /\xff\n")
    assert "encoding" in codes(robots)
    assert len(robots.groups) == 1


# --------------------------------------------------------------------------- evaluation
def test_longest_match_wins_regardless_of_order() -> None:
    robots = parse("User-agent: *\nAllow: /a/b\nDisallow: /a\n")
    assert evaluate(robots, bot("x"), "/a/b/c").allowed
    assert not evaluate(robots, bot("x"), "/a/c").allowed


def test_allow_wins_a_tie() -> None:
    robots = parse("User-agent: *\nDisallow: /p\nAllow: /p\n")
    assert evaluate(robots, bot("x"), "/p").allowed
    robots = parse("User-agent: *\nAllow: /p\nDisallow: /p\n")
    assert evaluate(robots, bot("x"), "/p").allowed


def test_wildcard_rule_can_outrank_shorter_allow() -> None:
    robots = parse("User-agent: *\nAllow: /blog/\nDisallow: /*?session=\n")
    verdict = evaluate(robots, bot("x"), "/blog/post?session=1")
    assert not verdict.allowed
    assert verdict.rule is not None and verdict.rule.line == 3


def test_specific_group_does_not_inherit_star_rules() -> None:
    robots = parse("User-agent: *\nDisallow: /cart\n\nUser-agent: special\nDisallow: /members\n")
    assert evaluate(robots, bot("special"), "/cart").allowed
    assert not evaluate(robots, bot("other"), "/cart").allowed


def test_fallback_tokens_are_tried_in_order() -> None:
    robots = parse("User-agent: Googlebot\nDisallow: /g\n\nUser-agent: *\nDisallow: /\n")
    applebot = bots.get("Applebot")
    assert applebot is not None
    group, _ = select_group(robots, applebot)
    assert group == "googlebot"
    assert evaluate(robots, applebot, "/ok").allowed
    assert not evaluate(robots, applebot, "/g").allowed


def test_own_group_beats_fallback() -> None:
    robots = parse("User-agent: Googlebot\nDisallow: /\n\nUser-agent: Googlebot-Image\nAllow: /\n")
    image = bots.get("Googlebot-Image")
    assert image is not None
    assert evaluate(robots, image, "/photo.jpg").allowed


def test_no_matching_group_and_no_star_allows_everything() -> None:
    robots = parse("User-agent: somebot\nDisallow: /\n")
    verdict = evaluate(robots, bot("x"), "/")
    assert verdict.allowed and verdict.group is None


def test_robots_txt_itself_is_always_allowed() -> None:
    robots = parse("User-agent: *\nDisallow: /\n")
    assert evaluate(robots, bot("x"), "/robots.txt").allowed
    assert not evaluate(robots, bot("x"), "/robots.txt.bak").allowed


def test_synthetic_files() -> None:
    assert evaluate(RobotsFile.allow_all("404"), bot("x"), "/a").allowed
    deny = RobotsFile.disallow_all("503")
    verdict = evaluate(deny, bot("x"), "/robots.txt")
    assert not verdict.allowed
    assert "unreachable" in verdict.reason


def test_verdict_explains_the_deciding_rule() -> None:
    robots = parse("User-agent: GPTBot\nDisallow: /\n")
    gptbot = bots.get("gptbot")
    assert gptbot is not None
    verdict = evaluate(robots, gptbot, "https://example.com/blog/")
    assert verdict.group == "gptbot"
    assert verdict.rule is not None and str(verdict.rule) == "Disallow: /"
    assert "Line 2" in verdict.reason


def test_catalogue_entries_are_well_formed() -> None:
    names = [b.name.lower() for b in bots.BOTS]
    assert len(names) == len(set(names))
    for entry in bots.BOTS:
        assert entry.category in bots.CATEGORIES
        assert entry.source.startswith("https://")
        assert entry.tokens and entry.tokens[0] == entry.name
        if not entry.respects_robots:
            assert entry.note
