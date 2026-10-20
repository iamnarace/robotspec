# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-20

### Added

- RFC 9309 parser and matcher: group merging, longest-match precedence with allow winning ties, `*` and `$` wildcards, percent-encoding normalisation, implicit allow for `/robots.txt`.
- Fetching with RFC 9309 status handling (4xx allow all, 5xx/network disallow all, five-redirect limit).
- Catalogue of 21 crawlers in five categories with operator documentation links and fallback tokens.
- Commands: `check`, `matrix` (text, Markdown, JSON, HTML), `lint`, `test`, `init`, `bots`.
- `robotspec.toml` policy files with categories, custom tokens and `[require]` checks; GitHub step summary output.
