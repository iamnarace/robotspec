"""Load robots.txt from a file, stdin or URL with RFC 9309 status semantics."""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import __version__
from .parser import PARSE_LIMIT_BYTES, RobotsFile, parse

USER_AGENT = f"robotspec/{__version__} (+https://github.com/iamnarace/robotspec)"
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 15


class SourceError(Exception):
    """The source could not be read for a reason unrelated to RFC 9309 semantics."""


@dataclass(frozen=True)
class Loaded:
    robots: RobotsFile
    origin: str  # what the user asked for, resolved (path or URL)
    status: int | None = None  # HTTP status, for URLs


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def robots_url(url: str) -> str:
    """Point a site URL at its robots.txt (``https://e.com/x`` -> ``https://e.com/robots.txt``)."""
    parts = urlsplit(url)
    if parts.path.endswith("/robots.txt"):
        return url
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def load(source: str) -> Loaded:
    if source == "-":
        data = sys.stdin.buffer.read()
        return Loaded(parse(data), "<stdin>")
    if is_url(source):
        return fetch(robots_url(source))
    path = Path(source)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise SourceError(f"No such file: {source}") from exc
    except IsADirectoryError as exc:
        raise SourceError(f"{source} is a directory; pass the robots.txt file itself") from exc
    except OSError as exc:
        raise SourceError(f"Cannot read {source}: {exc.strerror}") from exc
    return Loaded(parse(data), str(path))


class _LimitedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS


def fetch(url: str, timeout: float = TIMEOUT_SECONDS) -> Loaded:
    """Fetch robots.txt following RFC 9309 §2.3.1.

    * 2xx: parse the body (at most a little over the 500 KiB parsing limit is read).
    * 4xx (unavailable): crawlers may access everything.
    * 5xx or network failure (unreachable): crawlers must assume complete disallow.
    * More than five redirects: treated as unavailable.
    """
    opener = urllib.request.build_opener(_LimitedRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(PARSE_LIMIT_BYTES + 1)
            return Loaded(parse(body), url, response.status)
    except urllib.error.HTTPError as exc:
        status = exc.code
        if 300 <= status < 400:
            return Loaded(
                RobotsFile.allow_all(f"More than {MAX_REDIRECTS} redirects; treated as unavailable."),
                url,
                status,
            )
        if 400 <= status < 500:
            return Loaded(
                RobotsFile.allow_all(f"HTTP {status}: robots.txt is unavailable, so everything is allowed."),
                url,
                status,
            )
        return Loaded(
            RobotsFile.disallow_all(f"HTTP {status}: robots.txt is unreachable, so crawlers assume full disallow."),
            url,
            status,
        )
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        reason = getattr(exc, "reason", exc)
        return Loaded(
            RobotsFile.disallow_all(
                f"Network error ({reason}): robots.txt is unreachable, so crawlers assume full disallow."
            ),
            url,
            None,
        )
