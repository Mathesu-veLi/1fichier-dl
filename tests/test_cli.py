"""Tests for the command line front end."""

from __future__ import annotations

import pytest

from core.cli import main as cli_main


@pytest.fixture
def local_link(monkeypatch):
    monkeypatch.setattr(cli_main, "is_valid_link", lambda link: True)


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


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(["--version"])

    assert excinfo.value.code == 0
    assert "1fichier-dl" in capsys.readouterr().out
