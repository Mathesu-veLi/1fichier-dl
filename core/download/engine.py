"""UI-agnostic download engine for 1fichier share links.

The GUI code in :mod:`core.download.download` is tightly coupled to PyQt5.
This module implements the same download flow without importing any GUI
toolkit, so it can also run on headless machines (for example a CachyOS
server or a terminal-only desktop).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlparse

import lxml.html
import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CHUNK_SIZE = 64 * 1024
DEFAULT_TIMEOUT = 30

_DIRECT_LINK_RE = re.compile(
    r'href=["\'](https?://[a-z]-\d+\.1fichier\.com/[^"\']+)["\']',
    re.IGNORECASE,
)
_SIZE_RE = re.compile(r"([\d.,]+)\s*(B|KB|MB|GB|TB)", re.IGNORECASE)
_UNITS = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4}
_AFFILIATE_RE = re.compile(r"[?&]af=(\d+)", re.IGNORECASE)
_WAIT_RE = re.compile(r"var\s+ct\s*=\s*(\d+)\s*\*\s*60", re.IGNORECASE)


class DownloadError(RuntimeError):
    """Base class for errors that can be shown directly to the user."""


class PasswordRequired(DownloadError):
    """The share link is protected by a password that was not supplied."""


class IncorrectPassword(DownloadError):
    """The supplied password was rejected by 1fichier."""


class LinkUnavailable(DownloadError):
    """The link is dead, malformed or does not point to a downloadable file."""


class DestinationExists(DownloadError):
    """A complete file with the target name already exists."""


class Aria2Unavailable(DownloadError):
    """The aria2c executable is not available on this system."""


class RateLimited(DownloadError):
    """1fichier asked this IP to wait before the next download."""


@dataclass
class FileInfo:
    """Metadata shown by 1fichier before a download starts."""

    name: Optional[str] = None
    size: Optional[int] = None
    size_text: str = "-"
    private: bool = False


@dataclass
class DownloadResult:
    """Outcome of a completed download."""

    path: str
    size: int
    elapsed: float
    skipped: bool = False


class DownloadReporter:
    """Optional hooks used to show progress without depending on a UI."""

    def on_status(self, message: str) -> None:
        """Called when the downloader enters a new phase."""

    def on_progress(self, downloaded: int, total: int, speed: float) -> None:
        """Called after each chunk; ``speed`` is measured in bytes/second."""

    def on_complete(self, result: DownloadResult) -> None:
        """Called once the file has been moved to its final name."""


def normalize_link(link: str) -> str:
    """Return a clean http(s) URL for a link copied from a browser."""
    link = link.strip()
    if not link:
        raise LinkUnavailable("empty download link")
    if not link.startswith(("http://", "https://")):
        link = f"https://{link}"
    return link


def affiliate_code(link: str) -> Optional[str]:
    """Return the ``af`` affiliate id embedded in a share link, if any."""
    match = _AFFILIATE_RE.search(link or "")
    return match.group(1) if match else None


def make_session(link: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT) -> requests.Session:
    """Create an HTTP session with the headers 1fichier expects.

    1fichier uses the ``AF`` cookie to remember the affiliate id from links
    such as ``https://1fichier.com/?FILE_ID&af=123``. Without that cookie the
    server answers with its landing page instead of the file page.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.8",
            "Connection": "keep-alive",
        }
    )

    code = affiliate_code(link or "")
    if code:
        session.cookies.set("AF", code, domain="1fichier.com", path="/")

    return session


def parse_size(text: str) -> Optional[int]:
    """Convert a 1fichier size string such as ``1.25 GB`` to bytes."""
    match = _SIZE_RE.search(text or "")
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return int(value * (1024 ** _UNITS[match.group(2).upper()]))


def _first_text(document: lxml.html.HtmlElement, xpaths: list[str]) -> Optional[str]:
    for xpath in xpaths:
        nodes = document.xpath(xpath)
        for node in nodes:
            text = node.text_content().strip()
            if text:
                return text
    return None


def _raise_for_error_page(text: str) -> None:
    """Translate known 1fichier error pages into friendly exceptions."""
    lowered = text.lower()
    if "incorrect password" in lowered:
        raise IncorrectPassword("1fichier rejected the password for this file")
    if "must wait" in lowered or "please wait" in lowered:
        match = _WAIT_RE.search(text)
        wait = f"about {int(match.group(1))} minutes" if match else "a while"
        raise RateLimited(
            f"1fichier is rate-limiting this connection; wait {wait}, "
            "use another IP or pass --proxy"
        )
    if "file not found" in lowered or "file has been removed" in lowered:
        raise LinkUnavailable("the file is no longer available on 1fichier")
    if "welcome !" in lowered or "window.location.reload()" in lowered:
        raise DownloadError(
            "1fichier returned its landing page instead of the file page; "
            "open the share link once in a browser and copy it again"
        )


def get_file_info(
    url: str,
    session: Optional[requests.Session] = None,
    timeout: int = DEFAULT_TIMEOUT,
    proxies: Optional[dict[str, str]] = None,
) -> FileInfo:
    """Fetch the file name and size shown on the 1fichier page."""
    url = normalize_link(url)
    session = session or make_session(url, timeout)

    response = session.get(url, timeout=timeout, proxies=proxies)
    if response.status_code == 404:
        raise LinkUnavailable("the file is no longer available on 1fichier")

    document = lxml.html.fromstring(response.content)
    if document.xpath('//*[@id="pass"]'):
        return FileInfo(private=True)

    name = _first_text(
        document,
        [
            '//span[@class="tier-name"]',
            '//table[@class="premium"]//td[@class="normal"]//span[1]',
        ],
    )
    size_text = _first_text(
        document,
        [
            '//span[@class="tier-feat"]',
            '//table[@class="premium"]//td[@class="normal"]//span[2]',
        ],
    )

    if not name:
        _raise_for_error_page(response.text)
        raise LinkUnavailable("could not read file information from the 1fichier page")

    return FileInfo(
        name=name,
        size=parse_size(size_text or ""),
        size_text=(size_text or "-").strip(),
    )


def _filename_from_disposition(header: Optional[str]) -> Optional[str]:
    """Extract a file name from a ``Content-Disposition`` header."""
    if not header:
        return None

    extended = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", header, re.IGNORECASE)
    if extended:
        return unquote(extended.group(1).strip().strip('"'))

    regular = re.search(r'filename\s*=\s*"?([^";]+)"?', header, re.IGNORECASE)
    if regular:
        return regular.group(1).strip()

    return None


def _extract_direct_link(document: lxml.html.HtmlElement, text: str) -> Optional[str]:
    """Find the temporary direct download URL in a 1fichier response."""
    nodes = document.xpath("/html/body/div[4]/div[2]/a/@href")
    if nodes:
        return nodes[0]

    match = _DIRECT_LINK_RE.search(text)
    return match.group(1) if match else None


class Downloader:
    """Download one or more files from 1fichier without any GUI toolkit."""

    def __init__(
        self,
        output_dir: str = ".",
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
        reporter: Optional[DownloadReporter] = None,
        password: Optional[str] = None,
        proxy: Optional[str] = None,
        overwrite: bool = False,
        aria2c: bool = False,
        aria2c_path: str = "aria2c",
        aria2c_connections: int = 8,
    ) -> None:
        self.output_dir = os.path.abspath(os.path.expanduser(output_dir))
        self.timeout = timeout
        self.session = session
        self.reporter = reporter or DownloadReporter()
        self.password = password
        self.proxy = proxy
        self.overwrite = overwrite
        self.aria2c = aria2c
        self.aria2c_path = aria2c_path
        self.aria2c_connections = max(1, int(aria2c_connections))

    @property
    def proxies(self) -> Optional[dict[str, str]]:
        """Proxy mapping understood by requests, or ``None`` for a direct connection."""
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def _get_session(self, url: str) -> requests.Session:
        if self.session is None:
            self.session = make_session(url, self.timeout)
        return self.session

    def _request_direct_link(self, url: str) -> str:
        session = self._get_session(url)
        payload = {"dl_no_ssl": "on", "dlinline": "on"}
        if self.password:
            payload["pass"] = self.password

        response = session.post(
            url, data=payload, timeout=self.timeout, proxies=self.proxies
        )
        document = lxml.html.fromstring(response.content)

        if document.xpath('//*[@id="pass"]'):
            _raise_for_error_page(response.text)
            raise PasswordRequired(
                "this file is password protected; supply the password with --password"
            )

        direct_link = _extract_direct_link(document, response.text)
        if direct_link:
            return direct_link

        _raise_for_error_page(response.text)
        raise DownloadError("1fichier did not return a direct download link")

    def _prepare(self, url: str) -> tuple[str, FileInfo, str, float]:
        """Resolve file information and a temporary direct download link."""
        url = normalize_link(url)
        started = time.time()

        self.reporter.on_status("Fetching file information")
        info = get_file_info(
            url,
            session=self._get_session(url),
            timeout=self.timeout,
            proxies=self.proxies,
        )
        if info.private and not self.password:
            raise PasswordRequired(
                "this file is password protected; supply the password with --password"
            )

        self.reporter.on_status("Requesting a direct download link")
        direct_link = self._request_direct_link(url)
        return url, info, direct_link, started

    def _probe_filename(self, direct_link: str, referer: str) -> Optional[str]:
        """Read Content-Disposition from the direct link when the page has no name."""
        session = self._get_session(referer)
        response = None
        try:
            response = session.get(
                direct_link,
                stream=True,
                timeout=self.timeout,
                headers={"Referer": referer},
                proxies=self.proxies,
            )
            if response.status_code >= 400:
                return None
            return _filename_from_disposition(
                response.headers.get("Content-Disposition")
            )
        except requests.RequestException:
            return None
        finally:
            if response is not None:
                response.close()

    def _download_with_aria2c(
        self, url: str, filename: Optional[str] = None
    ) -> DownloadResult:
        """Resolve the 1fichier link and hand the transfer to aria2c."""
        if not shutil.which(self.aria2c_path):
            raise Aria2Unavailable(
                "aria2c was not found; install aria2 or use the built-in downloader"
            )

        proxy = self.proxy
        if proxy:
            scheme = urlparse(proxy).scheme.lower()
            if scheme in ("socks5", "socks5h"):
                raise DownloadError(
                    "aria2c does not support SOCKS proxies; "
                    "use the built-in downloader or an HTTP proxy tunnel"
                )
            if not scheme:
                proxy = f"http://{proxy}"

        url, info, direct_link, started = self._prepare(url)
        session = self._get_session(url)

        os.makedirs(self.output_dir, exist_ok=True)
        name = os.path.basename(filename or info.name or "") or None
        if not name:
            name = os.path.basename(
                self._probe_filename(direct_link, url) or ""
            ) or "download.bin"
        target = os.path.join(self.output_dir, name)
        control = f"{target}.aria2"
        part = f"{target}.unfinished"

        if self.overwrite:
            for path in (target, control, part):
                if os.path.exists(path):
                    os.remove(path)

        if os.path.exists(target) and not self.overwrite:
            current_size = os.path.getsize(target)
            if info.size and current_size == info.size:
                self.reporter.on_status(f"Already downloaded: {name}")
                result = DownloadResult(
                    path=target,
                    size=current_size,
                    elapsed=time.time() - started,
                    skipped=True,
                )
                self.reporter.on_complete(result)
                return result

            resumable = os.path.exists(control) or (
                info.size is not None and current_size < info.size
            )
            if not resumable:
                raise DestinationExists(
                    f"{target} already exists; pass --overwrite to replace it"
                )

        if not os.path.exists(target) and os.path.exists(part):
            os.replace(part, target)
            self.reporter.on_status(
                f"Resuming {name} at {os.path.getsize(target)} bytes"
            )

        cmd = [
            self.aria2c_path,
            f"--dir={self.output_dir}",
            f"--out={name}",
            "--continue=true",
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            "--file-allocation=none",
            f"--max-connection-per-server={self.aria2c_connections}",
            f"--split={self.aria2c_connections}",
            "--min-split-size=1M",
            "--max-tries=5",
            "--retry-wait=2",
            f"--connect-timeout={self.timeout}",
            f"--timeout={self.timeout}",
            "--summary-interval=5",
            "--console-log-level=notice",
            f"--user-agent={USER_AGENT}",
            f"--referer={url}",
        ]
        if proxy:
            cmd.append(f"--all-proxy={proxy}")

        cookies = session.cookies.get_dict()
        if cookies:
            cmd.append(
                "--header=Cookie: "
                + "; ".join(f"{key}={value}" for key, value in cookies.items())
            )

        cmd.append(direct_link)

        self.reporter.on_status(f"Starting aria2c for {name}")
        completed = subprocess.run(cmd, check=False)
        if completed.returncode != 0:
            raise DownloadError(
                f"aria2c exited with code {completed.returncode}; "
                "partial files can be resumed"
            )

        if not os.path.exists(target):
            raise DownloadError("aria2c finished but the output file is missing")

        size = os.path.getsize(target)
        logging.debug("downloaded %s (%s bytes) with aria2c", target, size)
        result = DownloadResult(path=target, size=size, elapsed=time.time() - started)
        self.reporter.on_complete(result)
        return result

    def download(self, url: str, filename: Optional[str] = None) -> DownloadResult:
        """Download ``url`` into :attr:`output_dir` and return the result."""
        if self.aria2c:
            return self._download_with_aria2c(url, filename)

        url, info, direct_link, started = self._prepare(url)
        session = self._get_session(url)

        os.makedirs(self.output_dir, exist_ok=True)
        name = os.path.basename(
            filename
            or info.name
            or "download.bin"
        ) or "download.bin"
        target = os.path.join(self.output_dir, name)
        part = f"{target}.unfinished"

        if os.path.exists(target) and not self.overwrite:
            if info.size and os.path.getsize(target) == info.size:
                self.reporter.on_status(f"Already downloaded: {name}")
                result = DownloadResult(
                    path=target,
                    size=os.path.getsize(target),
                    elapsed=time.time() - started,
                    skipped=True,
                )
                self.reporter.on_complete(result)
                return result
            raise DestinationExists(
                f"{target} already exists; pass --overwrite to replace it"
            )

        offset = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {"Referer": url}
        if offset:
            headers["Range"] = f"bytes={offset}-"
            self.reporter.on_status(f"Resuming {name} at {offset} bytes")

        response = session.get(
            direct_link,
            stream=True,
            timeout=self.timeout,
            headers=headers,
            proxies=self.proxies,
        )
        response.raise_for_status()

        try:
            remote_name = _filename_from_disposition(
                response.headers.get("Content-Disposition")
            )
            if filename is None and remote_name and not info.name:
                name = os.path.basename(remote_name) or name
                target = os.path.join(self.output_dir, name)
                part = f"{target}.unfinished"

            if offset and response.status_code != 206:
                logging.debug("server ignored the Range request; restarting from zero")
                offset = 0

            total = offset + int(response.headers.get("Content-Length") or 0)
            if not total:
                total = info.size or 0
            downloaded = offset
            mode = "ab" if offset else "wb"
            self.reporter.on_status(f"Downloading {name}")

            with open(part, mode) as handle:
                for chunk in response.iter_content(CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.time() - started, 1e-9)
                    self.reporter.on_progress(downloaded, total, downloaded / elapsed)

            if total and downloaded != total:
                raise DownloadError(
                    f"incomplete download: received {downloaded} of {total} bytes"
                )

            os.replace(part, target)
        finally:
            response.close()

        logging.debug("downloaded %s (%s bytes)", target, downloaded)
        result = DownloadResult(path=target, size=downloaded, elapsed=time.time() - started)
        self.reporter.on_complete(result)
        return result
