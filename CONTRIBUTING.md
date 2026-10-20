# Contributing to robotspec

Thanks for helping. Small, focused pull requests are easiest to review.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Before opening a pull request

```bash
ruff check . && ruff format --check .
mypy
pytest
```

CI runs the same checks on Python 3.11, 3.12 and 3.13.

## Guidelines

- **Matching behaviour** changes need a test in `tests/test_matcher.py` or `tests/test_parser_and_evaluate.py` and a reference: the relevant RFC 9309 section, or a crawler operator's documentation.
- **Catalogue changes** (`src/robotspec/bots.py`) must link to the operator's own documentation. Please don't cite third-party bot directories as the only source. Update the "last reviewed" date in the module docstring and the README.
- Keep the runtime dependency-free (standard library only).
- Update `CHANGELOG.md` under "Unreleased".

## Reporting bugs

Include the robots.txt content (or a minimal excerpt), the command you ran, what you expected and what robotspec printed. If you're comparing with a specific crawler's behaviour, link to where that behaviour is documented.
