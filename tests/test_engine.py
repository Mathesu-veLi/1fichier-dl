"""Tests for the headless download engine."""

from __future__ import annotations

import os

import pytest

from core.download import engine


class RecordingReporter(engine.DownloadReporter):
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.progress: list[tuple[int, int]] = []
        self.completed: list[engine.DownloadResult] = []

    def on_status(self, message: str) -> None:
        self.statuses.append(message)

    def on_progress(self, downloaded: int, total: int, speed: float) -> None:
        self.progress.append((downloaded, total))

    def on_complete(self, result: engine.DownloadResult) -> None:
        self.completed.append(result)


def test_normalize_link_adds_scheme():
    assert engine.normalize_link("1fichier.com/?abc") == "https://1fichier.com/?abc"
    assert engine.normalize_link("  https://1fichier.com/?abc  ") == "https://1fichier.com/?abc"


def test_normalize_link_rejects_empty():
    with pytest.raises(engine.LinkUnavailable):
        engine.normalize_link("  ")


def test_parse_size():
    assert engine.parse_size("250.06 KB") == int(250.06 * 1024)
    assert engine.parse_size("1 GB") == 1024**3
    assert engine.parse_size("not a size") is None


def test_affiliate_code():
    assert engine.affiliate_code("https://1fichier.com/?abc&af=4186346") == "4186346"
    assert engine.affiliate_code("https://1fichier.com/?abc") is None


def test_make_session_stores_affiliate_cookie():
    session = engine.make_session("https://1fichier.com/?abc&af=4186346")
    assert session.cookies.get("AF") == "4186346"


def test_filename_from_disposition():
    assert (
        engine._filename_from_disposition('attachment; filename="movie.mkv"')
        == "movie.mkv"
    )
    assert (
        engine._filename_from_disposition("attachment; filename*=UTF-8''caf%C3%A9.txt")
        == "café.txt"
    )
    assert engine._filename_from_disposition(None) is None


def test_get_file_info(fichier_server):
    info = engine.get_file_info(fichier_server.url)
    assert info.name == "test.bin"
    assert info.size == len(fichier_server.state.payload)
    assert info.private is False


def test_download_success(fichier_server, tmp_path):
    reporter = RecordingReporter()
    result = engine.Downloader(output_dir=str(tmp_path), reporter=reporter).download(
        fichier_server.url
    )

    assert open(result.path, "rb").read() == fichier_server.state.payload
    assert result.size == len(fichier_server.state.payload)
    assert result.skipped is False
    assert not os.path.exists(result.path + ".unfinished")
    assert reporter.progress
    assert reporter.completed == [result]
    assert any("Downloading" in status for status in reporter.statuses)


def test_private_file_requires_password(fichier_server):
    fichier_server.state.password = "secret"

    info = engine.get_file_info(fichier_server.url)
    assert info.private is True

    with pytest.raises(engine.PasswordRequired):
        engine.Downloader(output_dir=".").download(fichier_server.url)

    with pytest.raises(engine.IncorrectPassword):
        engine.Downloader(
            output_dir=".", password="wrong"
        ).download(fichier_server.url)


def test_private_file_downloads_with_password(fichier_server, tmp_path):
    fichier_server.state.password = "secret"

    result = engine.Downloader(
        output_dir=str(tmp_path), password="secret"
    ).download(fichier_server.url)

    assert open(result.path, "rb").read() == fichier_server.state.payload


def test_rate_limit_reports_wait_time(fichier_server, tmp_path):
    fichier_server.state.wait_minutes = 92

    with pytest.raises(engine.RateLimited) as excinfo:
        engine.Downloader(output_dir=str(tmp_path)).download(fichier_server.url)

    assert "92 minutes" in str(excinfo.value)
    assert isinstance(excinfo.value, engine.DownloadError)


def test_resume_partial_download(fichier_server, tmp_path):
    payload = fichier_server.state.payload
    part = tmp_path / "test.bin.unfinished"
    part.write_bytes(payload[:1000])

    result = engine.Downloader(output_dir=str(tmp_path)).download(fichier_server.url)

    assert open(result.path, "rb").read() == payload
    assert fichier_server.state.range_requests == ["bytes=1000-"]


def test_skips_complete_file(fichier_server, tmp_path):
    downloader = engine.Downloader(output_dir=str(tmp_path))
    first = downloader.download(fichier_server.url)

    second = engine.Downloader(output_dir=str(tmp_path)).download(fichier_server.url)

    assert second.skipped is True
    assert second.path == first.path
    assert second.size == len(fichier_server.state.payload)


def test_overwrite_replaces_file(fichier_server, tmp_path):
    downloader = engine.Downloader(output_dir=str(tmp_path))
    first = downloader.download(fichier_server.url)
    with open(first.path, "wb") as handle:
        handle.write(b"truncated")

    result = engine.Downloader(
        output_dir=str(tmp_path), overwrite=True
    ).download(fichier_server.url)

    assert result.skipped is False
    assert open(result.path, "rb").read() == fichier_server.state.payload
