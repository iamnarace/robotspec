import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from robotspec.cli import main
from robotspec.source import fetch, load, robots_url

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# --------------------------------------------------------------------------- local HTTP server
class Handler(http.server.BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, tuple[int, bytes, dict[str, str]]]] = {}

    def do_GET(self) -> None:
        status, body, headers = self.routes.get(self.path, (404, b"not found", {}))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_robots_url() -> None:
    assert robots_url("https://e.com") == "https://e.com/robots.txt"
    assert robots_url("https://e.com/blog/post?x=1") == "https://e.com/robots.txt"
    assert robots_url("https://e.com/robots.txt") == "https://e.com/robots.txt"


def test_fetch_success(server: str) -> None:
    Handler.routes = {"/robots.txt": (200, b"User-agent: *\nDisallow: /x\n", {})}
    loaded = fetch(server + "/robots.txt")
    assert loaded.status == 200
    assert loaded.robots.synthetic is None
    assert loaded.robots.rules_for("*")


def test_fetch_4xx_is_allow_all(server: str) -> None:
    Handler.routes = {}
    loaded = fetch(server + "/robots.txt")
    assert loaded.robots.synthetic == "allow-all"


def test_fetch_5xx_is_disallow_all(server: str) -> None:
    Handler.routes = {"/robots.txt": (503, b"down", {})}
    loaded = fetch(server + "/robots.txt")
    assert loaded.robots.synthetic == "disallow-all"


def test_fetch_follows_up_to_five_redirects(server: str) -> None:
    routes = {f"/r{i}": (301, b"", {"Location": f"/r{i + 1}"}) for i in range(5)}
    routes["/r5"] = (200, b"User-agent: *\nDisallow: /deep\n", {})
    Handler.routes = routes
    assert fetch(server + "/r0").robots.synthetic is None


def test_fetch_too_many_redirects_is_unavailable(server: str) -> None:
    Handler.routes = {f"/r{i}": (302, b"", {"Location": f"/r{i + 1}"}) for i in range(8)}
    assert fetch(server + "/r0").robots.synthetic == "allow-all"


def test_network_error_is_disallow_all() -> None:
    # Port 9 on localhost (discard) is almost never listening.
    loaded = fetch("http://127.0.0.1:9/robots.txt", timeout=2)
    assert loaded.robots.synthetic == "disallow-all"


def test_load_missing_file_is_a_clear_error(tmp_path: Path) -> None:
    from robotspec.source import SourceError

    with pytest.raises(SourceError, match="No such file"):
        load(str(tmp_path / "missing.txt"))


# --------------------------------------------------------------------------- CLI
def run_cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(["--color", "never", *argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_example_policy_passes(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    code, out, _ = run_cli(capsys, "test", "-c", str(EXAMPLES / "robotspec.toml"))
    assert code == 0, out
    assert "0 failed" in out


def test_cli_catches_the_bug_in_the_before_file(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    code, out, _ = run_cli(
        capsys, "test", "-c", str(EXAMPLES / "robotspec.toml"), "--robots", str(EXAMPLES / "robots-before.txt")
    )
    assert code == 1
    assert "expected deny, got allow: OAI-SearchBot /cart" in out


def test_cli_writes_github_step_summary(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    run_cli(capsys, "test", "-c", str(EXAMPLES / "robotspec.toml"))
    assert "robots.txt policy passed" in summary.read_text()


def test_cli_json_report(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    code, out, _ = run_cli(capsys, "test", "-c", str(EXAMPLES / "robotspec.toml"), "-f", "json")
    data = json.loads(out)
    assert code == 0 and data["passed"] is True
    assert all(case["passed"] for case in data["cases"])


def test_cli_check(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, "check", str(EXAMPLES / "robots.txt"), "-b", "GPTBot", "-p", "/blog/")
    assert code == 0
    assert out.startswith("DENY")
    assert "Disallow: /" in out


def test_cli_matrix_formats(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, out, _ = run_cli(capsys, "matrix", str(EXAMPLES / "robots.txt"), "-c", "ai-user", "-f", "markdown")
    assert code == 0 and "| ChatGPT-User ⚠️ |" in out
    code, out, _ = run_cli(capsys, "matrix", str(EXAMPLES / "robots.txt"), "-b", "GPTBot", "-p", "/", "-f", "json")
    assert json.loads(out)[0]["results"][0]["access"] == "deny"
    target = tmp_path / "report.html"
    code, _, _ = run_cli(capsys, "matrix", str(EXAMPLES / "robots.txt"), "-f", "html", "-o", str(target))
    page = target.read_text()
    assert code == 0 and "<table>" in page and "GPTBot" in page and "Blocked" in page


def test_cli_lint_exit_codes(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    bad = tmp_path / "robots.txt"
    bad.write_text("User-agent: *\nDisalow: /x\n")
    assert run_cli(capsys, "lint", str(bad))[0] == 1
    warn = tmp_path / "warn.txt"
    warn.write_text("User-agent: *\nCrawl-delay: 5\nDisallow: /x\n")
    assert run_cli(capsys, "lint", str(warn))[0] == 0
    assert run_cli(capsys, "lint", "--strict", str(warn))[0] == 1


def test_cli_init_then_test(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    robots = tmp_path / "robots.txt"
    robots.write_text((EXAMPLES / "robots.txt").read_text())
    policy_file = tmp_path / "robotspec.toml"
    code, out, _ = run_cli(capsys, "init", str(robots), "-o", str(policy_file))
    assert code == 0, out
    assert run_cli(capsys, "init", str(robots), "-o", str(policy_file))[0] == 2  # refuses to overwrite
    assert run_cli(capsys, "test", "-c", str(policy_file))[0] == 0
    # Opening the site to GPTBot must now fail the locked-in policy.
    robots.write_text(robots.read_text().replace("User-agent: GPTBot\n", ""))
    assert run_cli(capsys, "test", "-c", str(policy_file))[0] == 1


def test_cli_usage_errors(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, _, err = run_cli(capsys, "check", str(tmp_path / "nope.txt"), "-b", "GPTBot", "-p", "/")
    assert code == 2 and "No such file" in err
    code, _, err = run_cli(capsys, "check", str(EXAMPLES / "robots.txt"), "-b", "NotABot", "-p", "/")
    assert code == 2 and "unknown bot" in err
    code, _, err = run_cli(capsys, "test", "-c", str(tmp_path / "missing.toml"))
    assert code == 2 and "robotspec init" in err


def test_cli_bots_lists_catalogue(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, "bots", "-c", "search")
    assert code == 0 and "Applebot" in out and "falls back to: Googlebot" in out
