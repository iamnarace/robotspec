"""Path normalisation and pattern matching as described in RFC 9309.

RFC 9309 section 2.2.2 says rules are matched against the URI path
(including the query) from the first octet, case-sensitively, after
percent-encoding normalisation.  ``*`` matches any sequence of
characters and a trailing ``$`` anchors the pattern to the end.

Specificity: the RFC says "the most specific match found MUST be used.
The most specific match is the match that has the most octets."  Like
Google's reference implementation, robotspec measures this by the
length of the matching *pattern* (after normalisation), so
``Allow: /a/b`` beats ``Disallow: /a`` for ``/a/b/c``.  When an allow
and a disallow rule are equally specific, allow wins.
"""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_HEX = "0123456789ABCDEFabcdef"


def normalize(value: str, *, keep_wildcards: bool = False) -> str:
    """Normalise percent-encoding so equivalent paths compare equal.

    * ``%XX`` for an unreserved ASCII character is decoded (``%7E`` -> ``~``).
    * Other ``%XX`` sequences are kept, with upper-case hex digits.
    * Non-ASCII characters are UTF-8 encoded and percent-escaped.
    * When ``keep_wildcards`` is false (used for request paths), ``*`` and
      ``$`` are percent-encoded so that they can never act as operators.
    """
    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == "%" and _is_hex_pair(value, i + 1):
            byte = int(value[i + 1 : i + 3], 16)
            decoded = chr(byte)
            if byte < 0x80 and decoded in _UNRESERVED:
                out.append(decoded)
            else:
                out.append("%" + value[i + 1 : i + 3].upper())
            i += 3
            continue
        if ord(ch) >= 0x80:
            out.extend(f"%{b:02X}" for b in ch.encode("utf-8"))
        elif not keep_wildcards and ch in "*$":
            out.append(f"%{ord(ch):02X}")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _is_hex_pair(value: str, start: int) -> bool:
    return start + 1 < len(value) and value[start] in _HEX and value[start + 1] in _HEX


def request_path(url_or_path: str) -> str:
    """Return the normalised path+query that rules are matched against.

    Accepts either a full URL (``https://example.com/a?b=1``) or a bare
    path (``/a?b=1``).  An empty path becomes ``/``.
    """
    if "://" in url_or_path:
        parts = urlsplit(url_or_path)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
    else:
        path = url_or_path or "/"
        # Drop any fragment; crawlers never send it.
        path = path.split("#", 1)[0]
        if not path.startswith("/"):
            path = "/" + path
    return normalize(path)


@lru_cache(maxsize=4096)
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(piece) for piece in body.split("*"))
    if anchored:
        regex += r"\Z"
    return re.compile(regex, re.DOTALL)


def pattern_matches(pattern: str, path: str) -> bool:
    """Return True if a normalised rule ``pattern`` matches ``path``.

    Both arguments must already be normalised (see :func:`normalize` and
    :func:`request_path`).  An empty pattern never matches.
    """
    if not pattern:
        return False
    if "*" not in pattern and not pattern.endswith("$"):
        return path.startswith(pattern)
    return _compile(pattern).match(path) is not None


def specificity(pattern: str) -> int:
    """Length in octets of a normalised pattern, used to rank matches."""
    return len(pattern.encode("utf-8"))
