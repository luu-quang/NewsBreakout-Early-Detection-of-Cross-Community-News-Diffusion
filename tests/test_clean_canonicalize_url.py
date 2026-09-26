"""Direct unit tests for canonicalize_url() in the REAL, unmodified
clean_vn.py / clean_intl.py. Closes a pre-existing gap noted in
docs/HANDOFF_2026-09-26.md section 7: "Không có test nào cho collect/clean/merge."
These two scripts are not touched by the v2 continuous-collector work; this
file only adds coverage for logic that already existed.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CLEAN_VN = _load_module(
    "clean_vn_canon_check",
    REPO_ROOT / "team_work/phases/phase1_collection_cleaning/vietnamese_team/code/clean_vn.py",
)
CLEAN_INTL = _load_module(
    "clean_intl_canon_check",
    REPO_ROOT / "team_work/phases/phase1_collection_cleaning/international_team/code/clean_intl.py",
)


class TestCleanVnCanonicalizeUrl:
    def test_strips_tracking_params(self):
        url = "https://vnexpress.net/a.html?utm_source=rss&utm_medium=feed&fbclid=xyz&gclid=abc&gidzl=1&oc=2"
        assert CLEAN_VN.canonicalize_url(url) == "https://vnexpress.net/a.html"

    def test_keeps_non_tracking_query_params(self):
        assert CLEAN_VN.canonicalize_url("https://vnexpress.net/a.html?id=123") == "https://vnexpress.net/a.html?id=123"

    def test_strips_www_prefix(self):
        assert CLEAN_VN.canonicalize_url("https://www.vnexpress.net/a.html") == "https://vnexpress.net/a.html"

    def test_strips_m_prefix(self):
        assert CLEAN_VN.canonicalize_url("https://m.vnexpress.net/a.html") == "https://vnexpress.net/a.html"

    def test_strips_trailing_slash(self):
        assert CLEAN_VN.canonicalize_url("https://vnexpress.net/a.html/") == "https://vnexpress.net/a.html"

    def test_strips_fragment(self):
        assert CLEAN_VN.canonicalize_url("https://vnexpress.net/a.html#section") == "https://vnexpress.net/a.html"

    def test_lowercases_scheme_and_host(self):
        assert CLEAN_VN.canonicalize_url("HTTPS://VnExpress.NET/a.html") == "https://vnexpress.net/a.html"

    def test_no_hostname_returns_empty_string(self):
        assert CLEAN_VN.canonicalize_url("not a url") == ""
        assert CLEAN_VN.canonicalize_url("/relative/path") == ""

    def test_empty_input_returns_empty_string(self):
        assert CLEAN_VN.canonicalize_url("") == ""


class TestCleanIntlCanonicalizeUrl:
    def test_strips_tracking_params(self):
        url = "https://www.scmp.com/a.html?utm_source=rss_feed&fbclid=xyz&gclid=abc&oc=2"
        assert CLEAN_INTL.canonicalize_url(url) == "https://scmp.com/a.html"

    def test_keeps_non_tracking_query_params(self):
        assert CLEAN_INTL.canonicalize_url("https://scmp.com/a.html?id=123") == "https://scmp.com/a.html?id=123"

    def test_strips_www_and_m_prefix(self):
        assert CLEAN_INTL.canonicalize_url("https://www.scmp.com/a.html") == "https://scmp.com/a.html"
        assert CLEAN_INTL.canonicalize_url("https://m.scmp.com/a.html") == "https://scmp.com/a.html"

    def test_strips_trailing_slash(self):
        assert CLEAN_INTL.canonicalize_url("https://scmp.com/a.html/") == "https://scmp.com/a.html"

    def test_strips_fragment(self):
        assert CLEAN_INTL.canonicalize_url("https://scmp.com/a.html#section") == "https://scmp.com/a.html"

    def test_no_hostname_returns_empty_string(self):
        assert CLEAN_INTL.canonicalize_url("not a url") == ""

    def test_empty_input_returns_empty_string(self):
        assert CLEAN_INTL.canonicalize_url("") == ""


def test_both_canonicalizers_agree_on_a_shared_example():
    """Both clean_vn.py and clean_intl.py implement their own canonicalize_url()
    independently (see docs/HANDOFF_2026-09-26.md section 7); this pins that
    they at least agree on the common, uncontroversial cases."""
    url = "https://WWW.Example.com/Path/?utm_source=x#frag"
    assert CLEAN_VN.canonicalize_url(url) == CLEAN_INTL.canonicalize_url(url) == "https://example.com/Path"
