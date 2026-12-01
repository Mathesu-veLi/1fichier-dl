"""Tests for the command line front end."""

from __future__ import annotations

import pytest

from core.cli import main as cli_main


@pytest.fixture
def local_link(monkeypatch):
    monkeypatch.setattr(cli_main, "is_valid_link", lambda link: True)
    monkeypatch.setattr(cli_main, "_supported_link", lambda link: True)


def test_info_prints_metadata(fichier_server, local_link, capsys):
    exit_code = cli_main.main(["--info", fichier_server.url])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "name: test.bin" in captured.out
    assert f"size: {len(fichier_server.state.payload)} B" in captured.out
    assert "password: no" in captured.out


def test_download_from_cli(fichier_server, local_link, tmp_path, capsys):
    exit_code = cli_main.main(["-o", str(tmp_path), fichier_server.url])
    captured = capsys.readouterr()

    target = tmp_path / "test.bin"
    assert exit_code == 0
    assert target.read_bytes() == fichier_server.state.payload
    assert "Saved" in captured.out


def test_cli_wrong_password(fichier_server, local_link, tmp_path, capsys):
    fichier_server.state.password = "secret"

    exit_code = cli_main.main(
        ["-o", str(tmp_path), "--password", "wrong", fichier_server.url]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "rejected the password" in captured.err
    assert not (tmp_path / "test.bin").exists()


def test_cli_rejects_unknown_links(capsys):
    exit_code = cli_main.main(["https://example.com/file"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "unsupported or malformed link" in captured.err


def test_cli_rejects_lookalike_hosts():
    assert cli_main._supported_link("https://example.com/1fichier.com/?abc") is False


def test_cli_accepts_real_hosts():
    assert cli_main._supported_link("https://1fichier.com/?abc") is True
    assert cli_main._supported_link("1fichier.com/?abc&af=4186346") is True


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(["--version"])

    assert excinfo.value.code == 0
    assert "1fichier-dl" in capsys.readouterr().out


def test_load_proxies_parses_comments_and_schemes(tmp_path):
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "# comment\n"
        "\n"
        "1.2.3.4:8080\n"
        "socks5://5.6.7.8:1080\n"
        "1.2.3.4:8080\n"
    )

    assert cli_main._load_proxies(str(proxy_file)) == [
        "http://1.2.3.4:8080",
        "socks5://5.6.7.8:1080",
    ]


def test_load_proxies_rejects_missing_or_empty_files(tmp_path):
    with pytest.raises(ValueError):
        cli_main._load_proxies(str(tmp_path / "missing.txt"))

    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing here\n\n")
    with pytest.raises(ValueError):
        cli_main._load_proxies(str(empty))


def test_proxy_options_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(
            [
                "--proxy",
                "http://127.0.0.1:8080",
                "--proxy-file",
                str(tmp_path / "proxies.txt"),
                "https://1fichier.com/?abc",
            ]
        )

    assert excinfo.value.code == 2


def test_proxy_rotation_moves_to_next_proxy(monkeypatch, tmp_path, capsys):
    seen = []

    class FakeDownloader:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        def download(self, link, filename=None):
            seen.append(self.proxy)
            if self.proxy == "http://bad:1":
                raise cli_main.engine.RateLimited("rate limited")
            return cli_main.engine.DownloadResult(
                path=str(tmp_path / "ok.bin"), size=42, elapsed=0.1
            )

    monkeypatch.setattr(cli_main.engine, "Downloader", FakeDownloader)
    args = cli_main.build_parser().parse_args(
        ["-o", str(tmp_path), "https://1fichier.com/?abc"]
    )

    result = cli_main._download_one(
        args,
        "https://1fichier.com/?abc",
        None,
        ["http://bad:1", "http://good:2"],
    )

    assert result is True
    assert seen == ["http://bad:1", "http://good:2"]
    assert "Trying proxy 1/2" in capsys.readouterr().err


def test_proxy_rotation_reports_exhausted_list(monkeypatch, tmp_path, capsys):
    class AlwaysLimited:
        def __init__(self, **kwargs):
            pass

        def download(self, link, filename=None):
            raise cli_main.engine.RateLimited("rate limited")

    monkeypatch.setattr(cli_main.engine, "Downloader", AlwaysLimited)
    args = cli_main.build_parser().parse_args(
        ["-o", str(tmp_path), "https://1fichier.com/?abc"]
    )

    result = cli_main._download_one(
        args,
        "https://1fichier.com/?abc",
        None,
        ["http://first:1", "http://second:2"],
    )

    captured = capsys.readouterr()
    assert result is False
    assert "all 2 proxies failed" in captured.err


def test_main_loads_proxy_file(monkeypatch, tmp_path):
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("1.2.3.4:8080\n")
    monkeypatch.setattr(cli_main, "_supported_link", lambda link: True)
    captured = {}

    def fake_download(args, link, name, proxies):
        captured["proxies"] = proxies
        return True

    monkeypatch.setattr(cli_main, "_download_one", fake_download)

    exit_code = cli_main.main(
        ["--proxy-file", str(proxy_file), "-o", str(tmp_path), "https://1fichier.com/?abc"]
    )

    assert exit_code == 0
    assert captured["proxies"] == ["http://1.2.3.4:8080"]
