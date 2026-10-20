# Research notes

Research carried out on 2026-10-20 before choosing and designing robotspec.

## Problem

Site owners increasingly use `robots.txt` to make fine-grained choices: allow search engines, refuse AI model training, allow AI search tools onto some sections, and so on. The format's rules (group selection, no inheritance from `*`, longest-match precedence, wildcards, fallback tokens) make those intentions easy to break with a small edit, and nothing in a typical deployment pipeline notices.

**Intended users:** web developers and site maintainers who keep `robots.txt` in a repository, SEO practitioners, and teams that want a reviewed, tested policy for AI crawlers.

## Existing solutions

| Tool | What it does well | Gap robotspec addresses |
|---|---|---|
| Google Search Console's robots.txt report (replaced the old Tester in 2023) | Shows how Google fetched and parsed your live file | Google's crawlers only; live site only; nothing for CI |
| Online checkers (for example AI-crawler checkers and robots.txt analyzers from many SEO vendors) | Quick checks of a live URL, often with AI-bot lists | Usually one URL and bot at a time, hosted, not versioned with your code, no failing build |
| Python's `urllib.robotparser` | Built in; in Python 3.13 it handles longest match and wildcards | Doesn't report *which* rule decided, and (tested on 3.13.16) doesn't merge duplicate user-agent groups as RFC 9309 requires |
| Google's open-source `robotstxt` C++ parser | The reference behaviour for Googlebot | A library, not a policy/testing tool; one user agent at a time |
| Dark Visitors and similar agent directories | Large, maintained lists of AI agents | Directories and generators rather than an offline test runner |

robotspec does not claim to be the first or only tool of its kind. Its distinct angle is **policy-as-code**: a reviewed `robotspec.toml` file that states intent per crawler category, checked offline in CI, with explanations that point at the deciding line.

## Differentiators

- Assertions over crawler *categories* (`category:ai-training`) so new bots added to the catalogue are covered automatically.
- Documented fallback chains (Applebot → Googlebot) that most simple checkers ignore.
- Explicit flags for user-initiated fetchers whose operators say robots.txt may not apply, so the report doesn't overstate what robots.txt achieves.
- `init` snapshots, Markdown step summaries and stable exit codes for CI.

## Technical decisions

- **Python, standard library only.** `tomllib` (3.11+) parses the policy, so installing robotspec in CI pulls in nothing else.
- **Own matcher.** Needed to expose the deciding rule and to follow RFC 9309 group merging; verified against the RFC's and Google's published examples in `tests/test_matcher.py`.
- **Specificity by pattern length**, matching Google's reference parser; the RFC's wording ("the match that has the most octets") is open to interpretation, so this is documented.
- **TOML policy**, not YAML, to avoid a dependency and YAML's implicit typing surprises.
- **Hand-curated catalogue with sources** instead of scraping a third-party list, so every entry can be checked against the operator's own words.

## Sources

- RFC 9309, Robots Exclusion Protocol: https://datatracker.ietf.org/doc/rfc9309/
- Google, common crawlers and tokens: https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers
- Search Engine Land, Search Console robots.txt report (replacing the Tester): https://searchengineland.com/google-search-console-adds-robots-txt-report-434708
- OpenAI crawlers: https://developers.openai.com/api/docs/bots
- Anthropic crawlers: https://support.claude.com/en/articles/8896518
- Apple, About Applebot: https://support.apple.com/119829
- Perplexity crawlers: https://docs.perplexity.ai/docs/resources/perplexity-crawlers
- Meta web crawlers: https://developers.facebook.com/docs/sharing/webmasters/web-crawlers
- Common Crawl FAQ: https://commoncrawl.org/faq
- Bing, bingbot announcement: https://blogs.bing.com/webmaster/June-2010/Bing-crawler-bingbot-on-the-horizon
- DuckDuckGo, DuckDuckBot: https://duckduckgo.com/duckduckgo-help-pages/results/duckduckbot
- Example AI-crawler checker (comparable tool): https://www.365i.co.uk/tools/ai-bot-checker/
