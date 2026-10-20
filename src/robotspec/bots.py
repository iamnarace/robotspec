"""A small, sourced catalogue of well-known crawlers.

Every entry links to the operator's own documentation.  ``tokens`` is
the order in which the crawler looks for a matching group; for example
Applebot obeys a ``Googlebot`` group when no ``Applebot`` group exists,
and Googlebot-Image falls back to ``Googlebot``.

``respects_robots`` is ``False`` for user-initiated fetchers whose
operators say robots.txt may not apply.  robotspec still evaluates them
so you can see what the file *asks* for, and flags them in reports.

Catalogue last reviewed: 2026-10-20.  Corrections are welcome; please
include a link to the operator's documentation.
"""

from __future__ import annotations

from dataclasses import dataclass

CATEGORIES: dict[str, str] = {
    "search": "Search engine crawlers",
    "ai-training": "Crawlers or control tokens for AI model training",
    "ai-search": "Crawlers that index pages for AI search and answers",
    "ai-user": "Fetchers acting on a user's request inside an AI assistant",
    "social": "Link-preview fetchers for social apps",
}


@dataclass(frozen=True)
class Bot:
    name: str
    tokens: tuple[str, ...]
    category: str
    operator: str
    source: str
    respects_robots: bool = True
    note: str = ""


_GOOGLE = "https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers"

BOTS: tuple[Bot, ...] = (
    # --- search -----------------------------------------------------------
    Bot("Googlebot", ("Googlebot",), "search", "Google", _GOOGLE),
    Bot(
        "Googlebot-Image",
        ("Googlebot-Image", "Googlebot"),
        "search",
        "Google",
        _GOOGLE,
        note="Falls back to the Googlebot group.",
    ),
    Bot(
        "Googlebot-News",
        ("Googlebot-News", "Googlebot"),
        "search",
        "Google",
        _GOOGLE,
        note="Falls back to the Googlebot group.",
    ),
    Bot(
        "bingbot",
        ("bingbot",),
        "search",
        "Microsoft",
        "https://blogs.bing.com/webmaster/June-2010/Bing-crawler-bingbot-on-the-horizon",
    ),
    Bot(
        "Applebot",
        ("Applebot", "Googlebot"),
        "search",
        "Apple",
        "https://support.apple.com/119829",
        note="Follows Googlebot rules when no Applebot group exists.",
    ),
    Bot(
        "DuckDuckBot",
        ("DuckDuckBot",),
        "search",
        "DuckDuckGo",
        "https://duckduckgo.com/duckduckgo-help-pages/results/duckduckbot",
    ),
    # --- AI training ------------------------------------------------------
    Bot("GPTBot", ("GPTBot",), "ai-training", "OpenAI", "https://developers.openai.com/api/docs/bots"),
    Bot(
        "ClaudeBot",
        ("ClaudeBot",),
        "ai-training",
        "Anthropic",
        "https://support.claude.com/en/articles/8896518",
    ),
    Bot(
        "Google-Extended",
        ("Google-Extended",),
        "ai-training",
        "Google",
        _GOOGLE,
        note="A control token, not a separate crawler; does not affect Search.",
    ),
    Bot(
        "Applebot-Extended",
        ("Applebot-Extended",),
        "ai-training",
        "Apple",
        "https://support.apple.com/119829",
        note="A control token; does not crawl and does not affect Apple search.",
    ),
    Bot("CCBot", ("CCBot",), "ai-training", "Common Crawl", "https://commoncrawl.org/faq"),
    Bot(
        "meta-externalagent",
        ("meta-externalagent",),
        "ai-training",
        "Meta",
        "https://developers.facebook.com/docs/sharing/webmasters/web-crawlers",
    ),
    # --- AI search --------------------------------------------------------
    Bot(
        "OAI-SearchBot",
        ("OAI-SearchBot",),
        "ai-search",
        "OpenAI",
        "https://developers.openai.com/api/docs/bots",
    ),
    Bot(
        "Claude-SearchBot",
        ("Claude-SearchBot",),
        "ai-search",
        "Anthropic",
        "https://support.claude.com/en/articles/8896518",
    ),
    Bot(
        "PerplexityBot",
        ("PerplexityBot",),
        "ai-search",
        "Perplexity",
        "https://docs.perplexity.ai/docs/resources/perplexity-crawlers",
    ),
    Bot(
        "meta-webindexer",
        ("meta-webindexer",),
        "ai-search",
        "Meta",
        "https://developers.facebook.com/docs/sharing/webmasters/web-crawlers",
    ),
    # --- AI user-initiated fetchers -----------------------------------------
    Bot(
        "ChatGPT-User",
        ("ChatGPT-User",),
        "ai-user",
        "OpenAI",
        "https://developers.openai.com/api/docs/bots",
        respects_robots=False,
        note="OpenAI says robots.txt rules may not apply to user-initiated fetches.",
    ),
    Bot(
        "Claude-User",
        ("Claude-User",),
        "ai-user",
        "Anthropic",
        "https://support.claude.com/en/articles/8896518",
    ),
    Bot(
        "Perplexity-User",
        ("Perplexity-User",),
        "ai-user",
        "Perplexity",
        "https://docs.perplexity.ai/docs/resources/perplexity-crawlers",
        respects_robots=False,
        note="Perplexity says it generally ignores robots.txt for user-requested fetches.",
    ),
    Bot(
        "meta-externalfetcher",
        ("meta-externalfetcher",),
        "ai-user",
        "Meta",
        "https://developers.facebook.com/docs/sharing/webmasters/web-crawlers",
        respects_robots=False,
        note="Meta says it may bypass robots.txt because a user requested the fetch.",
    ),
    # --- social -----------------------------------------------------------
    Bot(
        "facebookexternalhit",
        ("facebookexternalhit",),
        "social",
        "Meta",
        "https://developers.facebook.com/docs/sharing/webmasters/web-crawlers",
        note="Meta says it might bypass robots.txt for security or integrity checks.",
    ),
)

_BY_NAME = {bot.name.lower(): bot for bot in BOTS}


def get(name: str) -> Bot | None:
    return _BY_NAME.get(name.lower())


def by_category(category: str) -> list[Bot]:
    return [bot for bot in BOTS if bot.category == category]


def custom(token: str) -> Bot:
    """A bot that is not in the catalogue, identified only by its token."""
    return Bot(token, (token,), "custom", "unknown", "")
