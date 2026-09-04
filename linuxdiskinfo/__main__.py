"""Entry point: GUI by default, CLI when requested or no display."""

from __future__ import annotations

import argparse
import os
import sys


def _has_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def main(argv: list[str] | None = None) -> int:
    from . import __version__
    from .i18n import init, t

    init()
    parser = argparse.ArgumentParser(
        prog="linuxdiskinfo",
        description="CrystalDiskInfo-style drive health monitor for Linux.",
    )
    parser.add_argument("--gui", action="store_true", help="Open the GTK window")
    parser.add_argument("--cli", action="store_true", help="Print a text report")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    parser.add_argument(
        "--watch",
        nargs="?",
        const=1.0,
        type=float,
        metavar="SEC",
        help="Refresh the text report every SEC seconds (default 1)",
    )
    parser.add_argument("--version", action="version", version=f"Linux Disk Info {__version__}")
    parser.add_argument("--lang", choices=("en", "ru"), help="Force UI language")
    args = parser.parse_args(argv)
    if args.lang:
        init(args.lang)

    want_cli = args.cli or args.json or args.watch is not None
    if args.gui and want_cli:
        parser.error("use either --gui or --cli/--json/--watch")

    if want_cli or (not args.gui and not _has_display()):
        from .cli import run_cli

        return run_cli(args)

    from .app import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
