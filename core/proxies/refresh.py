"""Download, validate and write a fresh proxy list.

The bundled ``https_proxy_list.txt`` and ``socks5_proxy_list.txt`` files are
lists of *source* URLs used by the GUI. This module turns those sources into a
flat list of proxies that the CLI can consume with ``--proxy-file``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import logging
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_TEST_URL = "https://1fichier.com/"
DEFAULT_OUTPUT = "proxies-fresh.txt"

# Kept in sync with the source files at the repository root. The sources are
# embedded so the command also works after a pipx install outside the checkout.
DEFAULT_SOURCES = (
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
)

_PROXY_RE = re.compile(
    r"(?:(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://)?"
    r"(?:(?P<userinfo>[^@\s/]+)@)?"
    r"(?P<host>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})"
)
_DIRECT_LINK_RE = re.compile(
    r'href=["\'](https?://[a-z]-\d+\.1fichier\.com/[^"\']+)["\']',
    re.IGNORECASE,
)


def _normalize_scheme(scheme: Optional[str], default: str) -> str:
    scheme = (scheme or default).lower()
    if scheme in ("socks5", "socks5h"):
        return "socks5h"
    if scheme in ("http", "https"):
        return "http"
    return default


def parse_proxy_line(line: str, default_scheme: str = "http") -> Optional[str]:
    """Turn one proxy list line into a requests-compatible proxy URL.

    Returns ``None`` for comments, malformed entries and hosts that are not
    public IPv4 addresses.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    match = _PROXY_RE.search(line)
    if not match:
        return None

    host = match.group("host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if (
        address.is_private
        or address.is_loopback
        or address.is_reserved
        or address.is_multicast
        or address.is_link_local
        or address.is_unspecified
    ):
        return None

    port = int(match.group("port"))
    if not 0 < port < 65536:
        return None

    scheme = _normalize_scheme(match.group("scheme"), default_scheme)
    userinfo = match.group("userinfo")
    credentials = f"{userinfo}@" if userinfo else ""
    return f"{scheme}://{credentials}{host}:{port}"


def read_source_file(path: str) -> list[str]:
    """Read source URLs (or direct proxies) from a local file."""
    expanded = Path(path).expanduser()
    try:
        lines = expanded.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read source file {path}: {exc}") from exc

    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def fetch_source(url: str, timeout: float = 30) -> str:
    """Fetch a raw proxy list over HTTP(S)."""
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def collect_candidates(entries: Iterable[str], timeout: float = 30) -> list[str]:
    """Resolve source entries into a deduplicated list of proxy URLs."""
    candidates: list[str] = []

    for entry in entries:
        entry = entry.strip()
        if not entry or entry.startswith("#"):
            continue

        direct = parse_proxy_line(entry)
        if direct:
            candidates.append(direct)
            continue

        if entry.startswith(("http://", "https://")):
            try:
                body = fetch_source(entry, timeout=timeout)
            except requests.RequestException as exc:
                logging.warning("could not fetch %s: %s", entry, exc)
                continue
            for line in body.splitlines():
                proxy = parse_proxy_line(line)
                if proxy:
                    candidates.append(proxy)
            continue

        logging.warning("ignoring source entry %r", entry)

    return list(dict.fromkeys(candidates))


def validate_proxy(
    proxy: str,
    test_url: str = DEFAULT_TEST_URL,
    timeout: float = 8,
    check_download: bool = False,
    password: Optional[str] = None,
) -> bool:
    """Return True when the proxy can reach the test URL.

    With ``check_download`` the function also requests a direct link and reads
    the first byte of the file. That is the only way to prove the proxy can
    download, but it consumes the proxy's free-download window.
    """
    proxies = {"http": proxy, "https": proxy}
    connect_timeout = min(5.0, timeout)
    try:
        response = requests.get(
            test_url,
            headers={"User-Agent": USER_AGENT},
            proxies=proxies,
            timeout=(connect_timeout, timeout),
            verify=True,
        )
        if response.status_code != 200:
            return False

        body = response.text.lower()
        is_file_url = bool(urlparse(test_url).query)
        if is_file_url:
            if "tier-name" not in body and 'id="pass"' not in body:
                return False
        elif "1fichier" not in body:
            return False

        if not check_download:
            return True

        payload = {"dl_no_ssl": "on", "dlinline": "on"}
        if password:
            payload["pass"] = password
        post = requests.post(
            test_url,
            headers={"User-Agent": USER_AGENT},
            proxies=proxies,
            data=payload,
            timeout=(connect_timeout, timeout * 2),
            verify=True,
        )
        lowered = post.text.lower()
        if "must wait" in lowered or "incorrect password" in lowered:
            return False

        match = _DIRECT_LINK_RE.search(post.text)
        if not match:
            return False

        probe = requests.get(
            match.group(1),
            headers={
                "User-Agent": USER_AGENT,
                "Referer": test_url,
                "Range": "bytes=0-0",
            },
            proxies=proxies,
            stream=True,
            timeout=(connect_timeout, timeout),
            verify=True,
        )
        chunk = next(probe.iter_content(1), b"")
        ok = (
            probe.status_code in (200, 206)
            and "Content-Disposition" in probe.headers
            and bool(chunk)
        )
        probe.close()
        return ok
    except requests.RequestException:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="1fichier-dl-refresh-proxies",
        description="Fetch, validate and write a fresh proxy list.",
    )
    parser.add_argument(
        "--source-file",
        action="append",
        metavar="FILE",
        help="file with source URLs or proxies (repeatable; replaces defaults)",
    )
    parser.add_argument(
        "--source",
        action="append",
        metavar="URL",
        help="extra source URL or proxy (repeatable)",
    )
    parser.add_argument(
        "--test-url",
        default=DEFAULT_TEST_URL,
        help="URL used to validate each proxy (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8,
        help="per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=100,
        help="parallel validations (default: %(default)s)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="test only the first N candidates",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=0,
        help="stop after finding N working proxies",
    )
    parser.add_argument(
        "--check-download",
        action="store_true",
        help="also require a direct link and one downloaded byte (uses the free window)",
    )
    parser.add_argument(
        "--password",
        help="password for protected files when using --check-download",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="shuffle candidates before testing",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="output list (default: %(default)s)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show debug information",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.limit < 0 or args.max < 0:
        parser.error("--limit and --max cannot be negative")

    entries: list[str] = []
    if args.source_file:
        for path in args.source_file:
            try:
                entries.extend(read_source_file(path))
            except ValueError as exc:
                parser.error(str(exc))
    if args.source:
        entries.extend(args.source)
    if not entries:
        entries = list(DEFAULT_SOURCES)

    print(f"Collecting proxies from {len(entries)} source entries...", file=sys.stderr)
    candidates = collect_candidates(entries, timeout=max(args.timeout, 10))
    if args.shuffle:
        random.shuffle(candidates)
    if args.limit:
        candidates = candidates[: args.limit]

    print(f"Testing {len(candidates)} proxies...", file=sys.stderr)
    if args.check_download:
        print(
            "Download checking consumes each proxy's free-download window.",
            file=sys.stderr,
        )

    alive: list[str] = []
    interrupted = False
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=args.workers)
    try:
        checks = executor.map(
            lambda proxy: validate_proxy(
                proxy,
                test_url=args.test_url,
                timeout=args.timeout,
                check_download=args.check_download,
                password=args.password,
            ),
            candidates,
        )
        for index, (proxy, ok) in enumerate(zip(candidates, checks), start=1):
            if ok:
                alive.append(proxy)
                print(f"OK {len(alive)}: {proxy}", file=sys.stderr)
                if args.max and len(alive) >= args.max:
                    print(f"Reached --max ({args.max})", file=sys.stderr)
                    break
            if index % 50 == 0:
                print(
                    f"progress {index}/{len(candidates)} (alive {len(alive)})",
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        interrupted = True
        print("\ninterrupted; writing the proxies found so far", file=sys.stderr)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    output = Path(args.output).expanduser()
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        f"# Generated by 1fichier-dl-refresh-proxies on {timestamp}",
        f"# Test URL: {args.test_url}",
        f"# Proxies: {len(alive)}",
    ]
    lines.extend(alive)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(alive)} proxies to {output}", file=sys.stderr)
    if interrupted:
        return 130
    return 0 if alive else 1


if __name__ == "__main__":
    raise SystemExit(main())
