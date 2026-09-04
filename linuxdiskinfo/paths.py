"""Resource locations for source installs and frozen binaries."""

from __future__ import annotations

import sys
from pathlib import Path

GITHUB_URL = "https://github.com/Palymer/LinuxDiskInfo"
AUTHOR = "Palymer"

# Donations / thanks — network, address, block explorer
WALLETS = (
    (
        "TRC-20",
        "TVcEqim8yjAzhPXjpu5DfzKrrgS3Fx9upY",
        "https://tronscan.org/#/address/TVcEqim8yjAzhPXjpu5DfzKrrgS3Fx9upY",
    ),
    (
        "BEP-20",
        "0x327f2F24EC9931f1431bA6059bb3173C11B208AA",
        "https://bscscan.com/address/0x327f2F24EC9931f1431bA6059bb3173C11B208AA",
    ),
    (
        "ERC-20",
        "0x327f2F24EC9931f1431bA6059bb3173C11B208AA",
        "https://etherscan.io/address/0x327f2F24EC9931f1431bA6059bb3173C11B208AA",
    ),
)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def bundle_root() -> Path:
    if frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def package_dir() -> Path:
    if frozen():
        nested = bundle_root() / "linuxdiskinfo"
        if nested.is_dir():
            return nested
        return bundle_root()
    return Path(__file__).resolve().parent


def style_css() -> Path:
    return package_dir() / "style.css"


def icons_dir() -> Path:
    return bundle_root() / "data" / "icons"
