"""Tests for the continuous-collector runner: per-child isolation, heartbeat
recording, and healthchecks.io ping selection. No test here hits a real feed
or the real internet - child scripts are small stubs, and healthchecks pings
are captured by a local HTTP server.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from src.collect_v2 import jsonl_store, paths, runner

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


@pytest.fixture(autouse=True)
def _isolated_v2_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    monkeypatch.delenv("HEALTHCHECKS_PING_URL", raising=False)
    yield


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


# --- run_child -----------------------------------------------------------------------------


def test_run_child_success_parses_counts(tmp_path: Path):
    script = _write_stub(tmp_path, "ok.py", STUB_SUCCESS.format(seen=10, new=3))
    result = runner.run_child(script, "host-a", fetch_timeout=5.0, child_timeout=5.0)
    assert result == {"ok": True, "duration_seconds": result["duration_seconds"], "new_payloads": 3, "entries_seen": 10, "error": None}


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
