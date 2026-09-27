"""Tests for the continuous-collector runner: per-child isolation, heartbeat
recording, and healthchecks.io ping selection. No test here hits a real feed
or the real internet - child scripts are small stubs, and healthchecks pings
are captured by a local HTTP server.
"""

from __future__ import annotations

import http.server
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.collect_v2 import feed_diagnostics, feed_state, jsonl_store, paths, runner

STUB_SUCCESS = """
print("[rss] fetching stub: http://example")
print("Entries seen this run : {seen}")
print("New payloads archived : {new}")
"""

STUB_FAILURE = """
import sys
print("boom", file=sys.stderr)
sys.exit(3)
"""

STUB_HANGS = """
import time
time.sleep(30)
"""

# Reproduces the exact real-world bug (see docs/HANDOFF_2026-09-27.md mục 3c):
# a feed that fetches fine (HTTP 200) but whose CDN gzip-compresses the body
# unconditionally - feedparser can't parse the raw gzip bytes as XML, bozo=1,
# zero entries - and the OLD runner had no way to see this at all.
STUB_GZIP_BUG = """
import json
print("[rss] fetching vietnamplus: https://www.vietnamplus.vn/rss/trangchu.rss")
print("[rss] parse failed for vietnamplus: <unknown>:2:0: not well-formed (invalid token)")
result = {{
    "feed_id": "vietnamplus", "feed_url": "https://www.vietnamplus.vn/rss/trangchu.rss",
    "http_status": 200, "content_encoding": "gzip", "n_entries": 0, "n_new": 0,
    "error": "<unknown>:2:0: not well-formed (invalid token)",
}}
print("PER_FEED_JSON:" + json.dumps([result]))
print("Entries seen this run : {seen}")
print("New payloads archived : {new}")
"""

# A feed that fetched fine (real entries, no error) but had nothing NEW this
# run - the "stale, not broken" case that must never fail the main check.
STUB_QUIET_BUT_HEALTHY = """
import json
print("[rss] fetching vnexpress: https://vnexpress.net/rss/tin-moi-nhat.rss")
result = {{
    "feed_id": "vnexpress", "feed_url": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "http_status": 200, "content_encoding": "identity", "n_entries": 47, "n_new": 0,
    "error": None,
}}
print("PER_FEED_JSON:" + json.dumps([result]))
print("Entries seen this run : {seen}")
print("New payloads archived : {new}")
"""


@pytest.fixture(autouse=True)
def _isolated_v2_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    monkeypatch.delenv("HEALTHCHECKS_PING_URL", raising=False)
    monkeypatch.delenv("HEALTHCHECKS_STALE_PING_URL", raising=False)
    yield


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


# --- run_child -----------------------------------------------------------------------------


def test_run_child_success_parses_counts(tmp_path: Path):
    script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=10, new=3))
    result = runner.run_child(script, "host-a", fetch_timeout=5.0, child_timeout=5.0)
    assert result == {
        "ok": True, "duration_seconds": result["duration_seconds"], "new_payloads": 3, "entries_seen": 10,
        "error": None, "per_feed": [],
    }


def test_run_child_nonzero_exit_captured_not_raised(tmp_path: Path):
    script = _write_stub(tmp_path, "fail.py", STUB_FAILURE)
    result = runner.run_child(script, "host-a", fetch_timeout=5.0, child_timeout=5.0)
    assert result["ok"] is False
    assert "exit code 3" in result["error"]
    assert "boom" in result["error"]


def test_run_child_timeout_captured_not_raised(tmp_path: Path):
    script = _write_stub(tmp_path, "hang.py", STUB_HANGS)
    result = runner.run_child(script, "host-a", fetch_timeout=5.0, child_timeout=0.5)
    assert result["ok"] is False
    assert "timed out after 0.5s" in result["error"]


def test_run_child_missing_script_captured_not_raised(tmp_path: Path):
    result = runner.run_child(tmp_path / "does_not_exist.py", "host-a", fetch_timeout=5.0, child_timeout=5.0)
    assert result["ok"] is False
    assert result["error"]


def test_run_child_captures_per_feed_json(tmp_path: Path):
    script = _write_stub(tmp_path, "gzipbug.py", STUB_GZIP_BUG.format(seen=0, new=0))
    result = runner.run_child(script, "host-a", fetch_timeout=5.0, child_timeout=5.0)
    assert result["ok"] is True  # the child itself exits 0 - this is a silent content problem, not a crash
    assert result["per_feed"] == [
        {
            "feed_id": "vietnamplus", "feed_url": "https://www.vietnamplus.vn/rss/trangchu.rss",
            "http_status": 200, "content_encoding": "gzip", "n_entries": 0, "n_new": 0,
            "error": "<unknown>:2:0: not well-formed (invalid token)",
        }
    ]


# --- classify_feed_issues: this run's own per-feed results --------------------------------


def test_classify_feed_issues_flags_explicit_error():
    per_feed = [feed_diagnostics.make_result("x", "url-x", http_status=200, content_encoding="gzip", n_entries=0, n_new=0, error="bozo: bad xml")]
    issues = runner.classify_feed_issues(per_feed, "domestic", "host-a", state={})
    assert len(issues) == 1
    assert "x" in issues[0] and "bozo: bad xml" in issues[0]


def test_classify_feed_issues_flags_established_feed_with_zero_entries_no_error():
    feed_state.record_first_seen_batch("domestic", "host-a", {"url-x": "x"}, "2026-09-01T00:00:00Z")
    state = feed_state.load_state()
    per_feed = [feed_diagnostics.make_result("x", "url-x", http_status=200, content_encoding="identity", n_entries=0, n_new=0, error=None)]
    issues = runner.classify_feed_issues(per_feed, "domestic", "host-a", state)
    assert len(issues) == 1 and "x" in issues[0]


def test_classify_feed_issues_does_not_flag_brand_new_feed_with_zero_entries():
    per_feed = [feed_diagnostics.make_result("x", "url-x", http_status=200, content_encoding="identity", n_entries=0, n_new=0, error=None)]
    issues = runner.classify_feed_issues(per_feed, "domestic", "host-a", state={})  # no feed_started_at recorded anywhere
    assert issues == []


def test_classify_feed_issues_does_not_flag_healthy_feed():
    per_feed = [feed_diagnostics.make_result("x", "url-x", http_status=200, content_encoding="identity", n_entries=5, n_new=2, error=None)]
    issues = runner.classify_feed_issues(per_feed, "domestic", "host-a", state={})
    assert issues == []


# --- stale_feed_issues: reads only the heartbeat, never the raw archive -------------------


def _heartbeat_record(run_at: datetime, feed_id: str, n_new: int) -> dict:
    return {
        "run_id": "r", "run_at": run_at.isoformat(), "collector_host": "host-a",
        "children": {"domestic": {"per_feed": [feed_diagnostics.make_result(feed_id, "url-x", http_status=200, content_encoding="identity", n_entries=1, n_new=n_new, error=None)]}},
    }


def test_stale_feed_issues_flags_feed_with_no_new_payload_past_threshold(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    heartbeat_path = paths.heartbeat_path("host-a", now.strftime("%Y-%m"))
    jsonl_store.append_line(heartbeat_path, _heartbeat_record(now - timedelta(hours=8), "x", n_new=1))
    jsonl_store.append_line(heartbeat_path, _heartbeat_record(now - timedelta(hours=1), "x", n_new=0))

    issues = runner.stale_feed_issues({"x": 0}, "host-a", now)
    assert len(issues) == 1 and "x" in issues[0] and "8.0h" in issues[0]


def test_stale_feed_issues_does_not_flag_feed_fresh_within_threshold(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    heartbeat_path = paths.heartbeat_path("host-a", now.strftime("%Y-%m"))
    jsonl_store.append_line(heartbeat_path, _heartbeat_record(now - timedelta(hours=2), "x", n_new=3))

    assert runner.stale_feed_issues({"x": 0}, "host-a", now) == []


def test_stale_feed_issues_does_not_flag_feed_with_no_heartbeat_history(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    assert runner.stale_feed_issues({"brand-new-feed": 0}, "host-a", now) == []


def test_stale_feed_issues_never_consults_history_when_fresh_this_run(tmp_path: Path, monkeypatch):
    """Regression test for a real bug found live: on the very first run
    after redeploying the monitoring feature, feeds that got new payloads
    THIS run were still flagged stale, because the current run's own record
    isn't written to the heartbeat file until after this check - so a scan
    of prior (feature-less) heartbeat history found no evidence of
    freshness for any feed at all. n_new > 0 right now must short-circuit
    the history scan entirely, regardless of what heartbeat history says."""
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    heartbeat_path = paths.heartbeat_path("host-a", now.strftime("%Y-%m"))
    # Old heartbeat history with no per_feed at all (pre-monitoring-feature schema).
    jsonl_store.append_line(heartbeat_path, {"run_id": "r0", "run_at": (now - timedelta(hours=1)).isoformat(), "children": {"domestic": {}}})

    assert runner.stale_feed_issues({"baotintuc": 50, "tienphong": 6}, "host-a", now) == []


def test_stale_feed_issues_respects_per_feed_override(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    monkeypatch.setitem(runner.FEED_STALE_HOURS_OVERRIDE, "sparse-feed", 12.0)
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    heartbeat_path = paths.heartbeat_path("host-a", now.strftime("%Y-%m"))
    jsonl_store.append_line(heartbeat_path, _heartbeat_record(now - timedelta(hours=8), "sparse-feed", n_new=1))
    jsonl_store.append_line(heartbeat_path, _heartbeat_record(now - timedelta(hours=1), "sparse-feed", n_new=0))

    # 8h since last new - would fail the default 6h threshold, but not the 12h override
    assert runner.stale_feed_issues({"sparse-feed": 0}, "host-a", now) == []


def test_stale_feed_issues_spans_a_month_boundary(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    now = datetime(2026, 10, 1, 2, 0, 0, tzinfo=timezone.utc)  # 2h into the new month
    last_fresh = now - timedelta(hours=10)  # falls in September's heartbeat file
    jsonl_store.append_line(paths.heartbeat_path("host-a", last_fresh.strftime("%Y-%m")), _heartbeat_record(last_fresh, "x", n_new=1))

    issues = runner.stale_feed_issues({"x": 0}, "host-a", now)
    assert len(issues) == 1 and "10.0h" in issues[0]


def test_stale_feed_issues_does_not_flag_when_history_is_too_short_to_confirm(tmp_path: Path, monkeypatch):
    """Regression test for a real bug found live right after deploying: a
    feed with only ~20 minutes of heartbeat history (fresh redeploy, timer
    just started) and no n_new > 0 in either of its 2 recorded runs was
    reported as "no new payload in 24.0h" - a false claim, since the
    collector had only actually been observed for ~20 minutes, nowhere near
    the 6h default threshold. Watching for less time than the threshold
    must never be flagged as stale."""
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    now = datetime(2026, 9, 27, 14, 22, 54, tzinfo=timezone.utc)
    heartbeat_path = paths.heartbeat_path("host-a", now.strftime("%Y-%m"))
    jsonl_store.append_line(heartbeat_path, _heartbeat_record(now - timedelta(minutes=20), "x", n_new=0))

    assert runner.stale_feed_issues({"x": 0}, "host-a", now) == []


# --- run_once: heartbeat + overall_ok ----------------------------------------------------


def test_run_once_records_heartbeat_and_marks_success(tmp_path: Path, monkeypatch):
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=5, new=1))
    monkeypatch.setattr(runner, "COLLECT_VN", ok_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", ok_script)

    record = runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    assert record["overall_ok"] is True
    assert record["children"]["domestic"]["ok"] is True
    assert record["children"]["international"]["ok"] is True

    heartbeats = list(jsonl_store.iter_jsonl(paths.heartbeat_path("host-a")))
    assert len(heartbeats) == 1
    assert heartbeats[0]["run_id"] == record["run_id"]


def test_run_once_one_child_failing_marks_overall_not_ok(tmp_path: Path, monkeypatch):
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=5, new=1))
    fail_script = _write_stub(tmp_path, "fail.py", STUB_FAILURE)
    monkeypatch.setattr(runner, "COLLECT_VN", ok_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", fail_script)

    record = runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    assert record["overall_ok"] is False
    assert record["children"]["domestic"]["ok"] is True
    assert record["children"]["international"]["ok"] is False
    # the successful child's result must still be recorded, not discarded
    assert record["children"]["domestic"]["new_payloads"] == 1


def test_run_once_gzip_bug_reproduction_marks_ping_not_ok_and_names_the_feed(tmp_path: Path, monkeypatch):
    """End to end reproduction of the real incident (docs/HANDOFF_2026-09-27.md
    mục 3c): a feed's child process exits 0 (``overall_ok`` stays True - it
    isn't a crash) but its own per-feed result shows a bozo parse error with
    zero entries. The runner must now catch this and refuse to ping success."""
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=5, new=1))
    gzip_bug_script = _write_stub(tmp_path, "gzipbug.py", STUB_GZIP_BUG.format(seen=0, new=0))
    monkeypatch.setattr(runner, "COLLECT_VN", gzip_bug_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", ok_script)

    record = runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    assert record["overall_ok"] is True  # both children exited 0 - not a process crash
    assert record["ping_ok"] is False  # but the content problem must still be caught
    assert any("vietnamplus" in issue for issue in record["feed_issues"])


def test_run_once_stale_alone_never_fails_the_main_check(tmp_path: Path, monkeypatch):
    """The instructed split: a real error (fetch/parse fail, child crash)
    must fail the main check; staleness alone must NOT - it's expected
    during normal quiet hours (see docs/HANDOFF_2026-09-27.md mục 9) and
    only goes into stale_feed_issues / the optional second check."""
    quiet_script = _write_stub(tmp_path, "quiet.py", STUB_QUIET_BUT_HEALTHY.format(seen=47, new=0))
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=5, new=1))
    monkeypatch.setattr(runner, "COLLECT_VN", quiet_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", ok_script)
    old = datetime.now(timezone.utc) - timedelta(hours=15)
    jsonl_store.append_line(paths.heartbeat_path("host-a"), _heartbeat_record(old, "vnexpress", n_new=0))

    record = runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    assert record["feed_issues"] == []  # no real error
    assert any("vnexpress" in issue for issue in record["stale_feed_issues"])  # but flagged as stale
    assert record["ping_ok"] is True  # staleness alone must not fail the main check


def test_run_once_stale_pings_second_check_only_when_configured(tmp_path: Path, monkeypatch, capturing_server):
    port = capturing_server.server_address[1]
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{port}/ping/main")
    monkeypatch.setenv("HEALTHCHECKS_STALE_PING_URL", f"http://127.0.0.1:{port}/ping/stale")
    quiet_script = _write_stub(tmp_path, "quiet.py", STUB_QUIET_BUT_HEALTHY.format(seen=47, new=0))
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=5, new=1))
    monkeypatch.setattr(runner, "COLLECT_VN", quiet_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", ok_script)
    old = datetime.now(timezone.utc) - timedelta(hours=15)
    jsonl_store.append_line(paths.heartbeat_path("host-a"), _heartbeat_record(old, "vnexpress", n_new=0))

    runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    requests_by_path = {path: (method, body) for method, path, body in capturing_server.requests}
    assert requests_by_path["/ping/main"][0] == "GET"  # main check: staleness doesn't fail it
    assert requests_by_path["/ping/stale/fail"][0] == "POST"  # stale check: this IS what it's for
    assert b"vnexpress" in requests_by_path["/ping/stale/fail"][1]


def test_run_once_stale_second_check_skipped_entirely_when_unconfigured(tmp_path: Path, monkeypatch, capturing_server):
    port = capturing_server.server_address[1]
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{port}/ping/main")
    # HEALTHCHECKS_STALE_PING_URL deliberately left unset
    quiet_script = _write_stub(tmp_path, "quiet.py", STUB_QUIET_BUT_HEALTHY.format(seen=47, new=0))
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=5, new=1))
    monkeypatch.setattr(runner, "COLLECT_VN", quiet_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", ok_script)
    old = datetime.now(timezone.utc) - timedelta(hours=15)
    jsonl_store.append_line(paths.heartbeat_path("host-a"), _heartbeat_record(old, "vnexpress", n_new=0))

    runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    assert len(capturing_server.requests) == 1  # only the main check's GET - no second ping attempted
    assert capturing_server.requests[0][1] == "/ping/main"


def test_run_once_pings_fail_when_only_a_feed_issue_is_present(tmp_path: Path, monkeypatch, capturing_server):
    port = capturing_server.server_address[1]
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{port}/ping/abc")
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=5, new=1))
    gzip_bug_script = _write_stub(tmp_path, "gzipbug.py", STUB_GZIP_BUG.format(seen=0, new=0))
    monkeypatch.setattr(runner, "COLLECT_VN", gzip_bug_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", ok_script)

    runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    assert len(capturing_server.requests) == 1
    method, path, body = capturing_server.requests[0]
    assert (method, path) == ("POST", "/ping/abc/fail")
    assert b"vietnamplus" in body


def test_run_once_appends_to_heartbeat_across_multiple_runs(tmp_path: Path, monkeypatch):
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=1, new=1))
    monkeypatch.setattr(runner, "COLLECT_VN", ok_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", ok_script)

    runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)
    runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    heartbeats = list(jsonl_store.iter_jsonl(paths.heartbeat_path("host-a")))
    assert len(heartbeats) == 2
    assert heartbeats[0]["run_id"] != heartbeats[1]["run_id"]


# --- healthchecks.io ping: real HTTP, captured locally -----------------------------------


class _CapturingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(("GET", self.path, b""))
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.requests.append(("POST", self.path, body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # quiet test output


@pytest.fixture()
def capturing_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=2)


def test_ping_success_is_a_plain_get(capturing_server, monkeypatch):
    port = capturing_server.server_address[1]
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{port}/ping/abc")
    runner.ping_healthchecks(True, "ok")
    assert capturing_server.requests == [("GET", "/ping/abc", b"")]


def test_ping_failure_posts_to_fail_endpoint_with_summary(capturing_server, monkeypatch):
    port = capturing_server.server_address[1]
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{port}/ping/abc")
    runner.ping_healthchecks(False, "international: exit code 1")
    method, path, body = capturing_server.requests[0]
    assert (method, path) == ("POST", "/ping/abc/fail")
    assert b"international" in body


def test_ping_skipped_without_env_var_does_not_raise(capsys):
    runner.ping_healthchecks(True, "ok")  # HEALTHCHECKS_PING_URL unset by the autouse fixture
    assert "skipping ping" in capsys.readouterr().out


def test_run_once_pings_fail_endpoint_on_child_failure(tmp_path: Path, monkeypatch, capturing_server):
    port = capturing_server.server_address[1]
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", f"http://127.0.0.1:{port}/ping/abc")
    ok_script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=1, new=1))
    fail_script = _write_stub(tmp_path, "fail.py", STUB_FAILURE)
    monkeypatch.setattr(runner, "COLLECT_VN", ok_script)
    monkeypatch.setattr(runner, "COLLECT_INTL", fail_script)

    runner.run_once("host-a", fetch_timeout=5.0, child_timeout=5.0)

    assert len(capturing_server.requests) == 1
    method, path, body = capturing_server.requests[0]
    assert (method, path) == ("POST", "/ping/abc/fail")
    assert b"international" in body
