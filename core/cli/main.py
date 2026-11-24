"""Command line interface for 1fichier-dl."""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import time
from typing import Optional, Sequence

from core import __version__
from core.download import engine
from core.download.helpers import convert_size, is_valid_link

DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="1fichier-dl",
        description="Download files from 1fichier share links without a GUI.",
    )
    parser.add_argument(
        "links",
        metavar="URL",
        nargs="+",
        help="1fichier share link(s) to download",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="directory where files are saved (default: ~/Downloads)",
    )
    parser.add_argument(
        "--filename",
        help="save a single download under this name",
    )
    parser.add_argument(
        "-p",
        "--password",
        help="password for protected files (prompted if omitted)",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="only print file name and size, do not download",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=engine.DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show debugging information",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _supported_link(link: str) -> bool:
    return is_valid_link(link) and "ouo." not in link.lower()


class ConsoleReporter(engine.DownloadReporter):
    """Print status lines and, on a terminal, a live progress bar."""

    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stderr
        self.interactive = self.stream.isatty()
        self._last_update = 0.0
        self._line_active = False

    def _finish_line(self) -> None:
        if self._line_active:
            self.stream.write("\n")
            self.stream.flush()
            self._line_active = False

    def on_status(self, message: str) -> None:
        self._finish_line()
        print(message, file=self.stream)

    def on_progress(self, downloaded: int, total: int, speed: float) -> None:
        if not self.interactive:
            return
        now = time.monotonic()
        if now - self._last_update < 0.2 and (not total or downloaded < total):
            return
        self._last_update = now
        percentage = f"{100 * downloaded / total:5.1f}%" if total else "  ?  "
        line = f"\r{percentage} {convert_size(downloaded)}"
        if total:
            line += f"/{convert_size(total)}"
        line += f"  {convert_size(int(speed))}/s"
        self.stream.write(line)
        self.stream.flush()
        self._line_active = True

    def on_complete(self, result: engine.DownloadResult) -> None:
        self._finish_line()


def _print_info(link: str, timeout: int) -> bool:
    try:
        info = engine.get_file_info(link, timeout=timeout)
    except engine.DownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False

    print(link)
    print(f"  name: {info.name or '(unknown)'}")
    print(f"  size: {info.size_text}")
    print(f"  password: {'yes' if info.private else 'no'}")
    return True


def _download_one(args: argparse.Namespace, link: str, name: Optional[str]) -> bool:
    reporter = ConsoleReporter()
    password = args.password
    can_prompt = sys.stdin.isatty()

    for attempt in range(3):
        downloader = engine.Downloader(
            output_dir=args.output_dir,
            timeout=args.timeout,
            reporter=reporter,
            password=password,
        )
        try:
            result = downloader.download(link, filename=name)
        except engine.PasswordRequired as exc:
            if password is not None or not can_prompt:
                print(f"error: {exc}", file=sys.stderr)
                return False
            password = getpass.getpass("Password: ")
            if not password:
                print("error: a password is required for this file", file=sys.stderr)
                return False
            continue
        except engine.IncorrectPassword as exc:
            if args.password is not None or not can_prompt or attempt == 2:
                print(f"error: {exc}", file=sys.stderr)
                return False
            print("Incorrect password, try again.", file=sys.stderr)
            password = getpass.getpass("Password: ")
            continue
        except engine.DownloadError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return False
        except Exception as exc:  # network errors and unexpected failures
            print(f"error: could not download {link}: {exc}", file=sys.stderr)
            logging.debug("download failed", exc_info=True)
            return False

        print(f"Saved {result.path} ({convert_size(result.size)}) in {result.elapsed:.1f}s")
        return True

    return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if args.filename and len(args.links) > 1:
        parser.error("--filename can only be used with a single link")

    failures = 0
    for link in args.links:
        if not _supported_link(link):
            print(f"error: unsupported or malformed link: {link}", file=sys.stderr)
            failures += 1
            continue
        if args.info:
            if not _print_info(link, args.timeout):
                failures += 1
            continue
        if not _download_one(args, link, args.filename):
            failures += 1

    return 1 if failures else 0
