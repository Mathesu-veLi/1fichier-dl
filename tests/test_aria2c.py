"""Integration tests for the optional aria2c backend."""

from __future__ import annotations

import shutil

import pytest

from core.download import engine

pytestmark = pytest.mark.skipif(
    shutil.which("aria2c") is None, reason="aria2c is not installed"
)


def test_aria2c_download(fichier_server, tmp_path):
    result = engine.Downloader(
        output_dir=str(tmp_path), aria2c=True, aria2c_connections=2
    ).download(fichier_server.url)

    assert result.skipped is False
    assert result.path == str(tmp_path / "test.bin")
    assert open(result.path, "rb").read() == fichier_server.state.payload
    assert not (tmp_path / "test.bin.aria2").exists()


def test_aria2c_skips_existing_complete_file(fichier_server, tmp_path):
    engine.Downloader(output_dir=str(tmp_path), aria2c=True).download(
        fichier_server.url
    )

    result = engine.Downloader(output_dir=str(tmp_path), aria2c=True).download(
        fichier_server.url
    )

    assert result.skipped is True
    assert result.size == len(fichier_server.state.payload)


def test_aria2c_resumes_unfinished_file(fichier_server, tmp_path):
    payload = fichier_server.state.payload
    (tmp_path / "test.bin.unfinished").write_bytes(payload[:1000])

    result = engine.Downloader(output_dir=str(tmp_path), aria2c=True).download(
        fichier_server.url
    )

    assert open(result.path, "rb").read() == payload


def test_aria2c_missing_binary():
    with pytest.raises(engine.Aria2Unavailable):
        engine.Downloader(
            aria2c=True, aria2c_path="/definitely/not/aria2c"
        ).download("https://1fichier.com/?abc")


def test_aria2c_rejects_socks_proxy():
    with pytest.raises(engine.DownloadError, match="SOCKS"):
        engine.Downloader(
            aria2c=True, proxy="socks5h://127.0.0.1:1080"
        ).download("https://1fichier.com/?abc")


def test_cli_aria2c(fichier_server, monkeypatch, tmp_path):
    import core.cli.main as cli_main

    monkeypatch.setattr(cli_main, "_supported_link", lambda link: True)

    exit_code = cli_main.main(
        ["--aria2c", "--aria2c-connections", "2", "-o", str(tmp_path), fichier_server.url]
    )

    assert exit_code == 0
    assert (tmp_path / "test.bin").read_bytes() == fichier_server.state.payload
