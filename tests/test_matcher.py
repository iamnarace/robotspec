import pytest

from robotspec.matcher import normalize, pattern_matches, request_path, specificity


def m(pattern: str, path: str) -> bool:
    return pattern_matches(normalize(pattern, keep_wildcards=True), request_path(path))


# Examples from RFC 9309 §2.2.3 and Google's robots.txt documentation.
@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("/fish", "/fish", True),
        ("/fish", "/fish.html", True),
        ("/fish", "/fish/salmon.html", True),
        ("/fish", "/fishheads", True),
        ("/fish", "/fish.php?id=anything", True),
        ("/fish", "/Fish.asp", False),  # case-sensitive
        ("/fish", "/catfish", False),
        ("/fish*", "/fishheads/yummy.html", True),
        ("/fish/", "/fish", False),
        ("/fish/", "/fish/?id=anything", True),
        ("/*.php", "/index.php", True),
        ("/*.php", "/filename.php?parameters", True),
        ("/*.php", "/folder/any.php.file.html", True),
        ("/*.php", "/windows.PHP", False),
        ("/*.php$", "/filename.php", True),
        ("/*.php$", "/filename.php?parameters", False),
        ("/*.php$", "/filename.php5", False),
        ("/fish*.php", "/fishheads/catfish.php?parameters", True),
        ("/fish*.php", "/Fish.PHP", False),
        ("/", "/anything", True),
        ("/$", "/", True),
        ("/$", "/page", False),
        ("*", "/x", True),
    ],
)
def test_google_and_rfc_examples(pattern: str, path: str, expected: bool) -> None:
    assert m(pattern, path) is expected


def test_empty_pattern_never_matches() -> None:
    assert not pattern_matches("", "/")


def test_percent_encoding_of_unreserved_chars_is_decoded() -> None:
    # RFC 9309: "%62%61%7A" matches "baz".
    assert m("/foo/%62%61%7A", "/foo/baz")
    assert m("/foo/baz", "/foo/%62%61%7A")


def test_reserved_percent_encoding_is_kept_and_uppercased() -> None:
    assert normalize("/a%2fb") == "/a%2Fb"
    assert m("/a%2Fb", "/a%2fb")
    assert not m("/a/b", "/a%2Fb")


def test_non_ascii_is_utf8_percent_encoded() -> None:
    assert normalize("/café") == "/caf%C3%A9"
    assert m("/café", "/caf%C3%A9")
    assert m("/caf%c3%a9", "/café")


def test_literal_star_and_dollar_in_request_paths_are_not_operators() -> None:
    assert request_path("/price$") == "/price%24"
    assert request_path("/a*b") == "/a%2Ab"
    # A pattern needs %2A to match a literal '*' in the URL.
    assert m("/a%2Ab", "/a*b")


def test_request_path_from_url_includes_query_drops_fragment() -> None:
    assert request_path("https://example.com/a/b?x=1#frag") == "/a/b?x=1"
    assert request_path("https://example.com") == "/"
    assert request_path("page") == "/page"
    assert request_path("/p#top") == "/p"


def test_regex_metacharacters_are_literal() -> None:
    assert m("/a.b", "/a.b")
    assert not m("/a.b", "/axb")
    assert m("/(x)+", "/(x)+y")


def test_specificity_counts_pattern_octets() -> None:
    assert specificity("/a") < specificity("/a/b")
    assert specificity("/caf%C3%A9") == len("/caf%C3%A9")
