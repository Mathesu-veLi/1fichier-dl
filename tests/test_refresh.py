"""Tests for the proxy list refresher."""

from __future__ import annotations

from core.proxies import refresh


def test_parse_proxy_line_normalizes_schemes():
    assert refresh.parse_proxy_line("1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert refresh.parse_proxy_line("http://1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert refresh.parse_proxy_line("socks5://5.6.7.8:1080") == "socks5h://5.6.7.8:1080"
    assert refresh.parse_proxy_line("1.2.3.4:1080", "socks5h") == "socks5h://1.2.3.4:1080"


def test_parse_proxy_line_keeps_credentials():
    assert (
        refresh.parse_proxy_line("http://user:pass@1.2.3.4:8080")
        == "http://user:pass@1.2.3.4:8080"
    )


def test_parse_proxy_line_rejects_private_and_bad_entries():
    assert refresh.parse_proxy_line("# comment") is None
    assert refresh.parse_proxy_line("") is None
    assert refresh.parse_proxy_line("not-a-proxy") is None
    assert refresh.parse_proxy_line("10.0.0.1:8080") is None
    assert refresh.parse_proxy_line("127.0.0.1:8080") is None
    assert refresh.parse_proxy_line("1.2.3.4:99999") is None


def test_read_source_file(tmp_path):
    path = tmp_path / "sources.txt"
    path.write_text("# comment\nhttp://1.2.3.4:8080\n\nhttps://example.com/list\n")

    assert refresh.read_source_file(str(path)) == [
        "http://1.2.3.4:8080",
        "https://example.com/list",
    ]


def test_collect_candidates_fetches_and_deduplicates(monkeypatch):
    monkeypatch.setattr(
        refresh,
        "fetch_source",
        lambda url, timeout=30: "1.2.3.4:8080\n# comment\n5.6.7.8:1080\n1.2.3.4:8080\n",
    )

    assert refresh.collect_candidates(["https://example.com/list"], timeout=1) == [
        "http://1.2.3.4:8080",
        "http://5.6.7.8:1080",
    ]


def test_collect_candidates_accepts_direct_proxies(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("direct proxies must not be fetched")

    monkeypatch.setattr(refresh, "fetch_source", fail_fetch)

    assert refresh.collect_candidates(["socks5://5.6.7.8:1080"]) == [
        "socks5h://5.6.7.8:1080"
    ]


def test_main_writes_working_proxies(monkeypatch, tmp_path):
    output = tmp_path / "proxies.txt"
    monkeypatch.setattr(
        refresh, "collect_candidates", lambda entries, timeout: ["http://1.2.3.4:8080"]
    )
    monkeypatch.setattr(refresh, "validate_proxy", lambda *args, **kwargs: True)

    code = refresh.main(
        [
            "--source",
            "https://example.com/list",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    text = output.read_text()
    assert "http://1.2.3.4:8080" in text
    assert "# Proxies: 1" in text


def test_main_returns_failure_without_proxies(monkeypatch, tmp_path):
    output = tmp_path / "proxies.txt"
    monkeypatch.setattr(
        refresh, "collect_candidates", lambda entries, timeout: ["http://1.2.3.4:8080"]
    )
    monkeypatch.setattr(refresh, "validate_proxy", lambda *args, **kwargs: False)

    code = refresh.main(
        [
            "--source",
            "https://example.com/list",
            "--output",
            str(output),
        ]
    )

    assert code == 1
    assert "# Proxies: 0" in output.read_text()


def test_main_passes_download_check_options(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(
        refresh, "collect_candidates", lambda entries, timeout: ["http://1.2.3.4:8080"]
    )

    def fake_validate(proxy, **kwargs):
        seen.update(kwargs)
        return True

    monkeypatch.setattr(refresh, "validate_proxy", fake_validate)

    refresh.main(
        [
            "--source",
            "https://example.com/list",
            "--test-url",
            "https://1fichier.com/?abc",
            "--check-download",
            "--password",
            "secret",
            "--output",
            str(tmp_path / "proxies.txt"),
        ]
    )

    assert seen["check_download"] is True
    assert seen["password"] == "secret"
    assert seen["test_url"] == "https://1fichier.com/?abc"
