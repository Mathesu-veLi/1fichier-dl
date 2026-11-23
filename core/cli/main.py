"""Command line interface for 1fichier-dl."""

from __future__ import annotations

import argparse
import logging
import os
import sys
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


def _download_one(args: argparse.Namespace, link: str, name: Optional[str]) -> bool:
    downloader = engine.Downloader(output_dir=args.output_dir, timeout=args.timeout)
    try:
        result = downloader.download(link, filename=name)
    except engine.DownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False
    except Exception as exc:  # network errors and unexpected failures
        print(f"error: could not download {link}: {exc}", file=sys.stderr)
        logging.debug("download failed", exc_info=True)
        return False

    print(f"Saved {result.path} ({convert_size(result.size)}) in {result.elapsed:.1f}s")
    return True


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
        name = args.filename
        if not _download_one(args, link, name):
            failures += 1

    return 1 if failures else 0
