"""Terminal interface — overview, JSON dump and live I/O watch."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from .collector import IoTracker, collect
from .formatters import (
    format_bytes,
    format_hours,
    format_int,
    format_pcie,
    format_pct,
    format_rate,
    format_temp,
)
from .i18n import t

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

GRADE_COLOR = {
    "excellent": GREEN,
    "good": BLUE,
    "caution": YELLOW,
    "bad": RED,
    "unknown": DIM,
}

SEV_COLOR = {
    "critical": RED,
    "warning": YELLOW,
    "info": CYAN,
}


def _c(enabled: bool, color: str, text: str) -> str:
    if not enabled:
        return text
    return f"{color}{text}{RESET}"


def _grade_bar(score: int, width: int = 22) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def render_text(snapshot: dict[str, Any], *, color: bool = True) -> str:
    lines: list[str] = []
    host = snapshot.get("hostname") or ""
    distro = snapshot.get("distro") or ""
    lines.append(_c(color, BOLD, t("app_name")) + f"  {snapshot.get('version')}")
    lines.append(_c(color, DIM, f"{host} · {distro} · {snapshot.get('kernel')}"))
    lines.append(_c(color, DIM, snapshot.get("generated_at") or ""))
    lines.append("")

    drives = snapshot.get("drives") or []
    if not drives:
        lines.append(t("no_drives"))
        return "\n".join(lines)

    for drive in drives:
        health = drive.get("health") or {}
        grade = health.get("grade") or "unknown"
        gc = GRADE_COLOR.get(grade, DIM)
        smart = drive.get("smart") or {}
        title = f"{drive.get('model') or drive.get('name')}  ·  {drive.get('name')}"
        lines.append(_c(color, BOLD, "┌─ " + title))
        label = health.get("label") or t(f"grade_{grade}")
        score = health.get("score", 0)
        lines.append(
            "│  "
            + _c(color, gc + BOLD, f"{label:12}")
            + f"  {score:>3}  "
            + _c(color, gc, _grade_bar(score))
            + "    "
            + t("temperature")
            + " "
            + _c(color, BOLD, format_temp(drive.get("temperature_c")))
        )
        media = {
            "nvme": t("nvme"),
            "ssd": t("ssd"),
            "hdd": t("hdd"),
            "usb": t("usb"),
        }.get(drive.get("media"), drive.get("media") or "")
        ident = [
            (t("model"), drive.get("model")),
            (t("serial"), drive.get("serial")),
            (t("firmware"), drive.get("firmware")),
            (t("capacity"), format_bytes(drive.get("size"))),
            (t("interface"), media),
            (t("pci"), format_pcie(drive.get("pci"))),
        ]
        if smart.get("nvme_revision"):
            ident.append((t("nvme_rev"), smart.get("nvme_revision")))
        ident.extend(
            [
                (t("power_on"), format_hours(smart.get("power_on_hours"))),
                (t("power_cycles"), format_int(smart.get("power_cycles"))),
                (t("written"), format_bytes(smart.get("total_data_written"))),
                (t("read"), format_bytes(smart.get("total_data_read"))),
                (
                    t("wear"),
                    format_pct(smart.get("percent_used"))
                    if smart.get("percent_used") is not None
                    else None,
                ),
                (
                    t("spare"),
                    format_pct(smart.get("avail_spare"))
                    if smart.get("avail_spare") is not None
                    else None,
                ),
                (t("unsafe"), format_int(smart.get("unsafe_shutdowns"))),
                (t("media_errors"), format_int(smart.get("media_errors"))),
            ]
        )
        trim = drive.get("trim") or {}
        if trim.get("supported") and trim.get("timer"):
            ident.append((t("trim"), t("trim_ok")))
        elif trim.get("supported"):
            ident.append((t("trim"), t("trim_no_timer")))
        width_l = max(len(k) for k, v in ident if v not in (None, "", "—"))
        for key, val in ident:
            if val in (None, "", "—"):
                continue
            lines.append(f"│  {key:<{width_l}}  {val}")

        parts = [p for p in drive.get("partitions") or [] if not p.get("unallocated")]
        if parts:
            lines.append("│")
            lines.append("│  " + _c(color, BOLD, t("layout")))
            for p in parts:
                used = ""
                if p.get("used_pct") is not None:
                    used = f"  {p['used_pct']:.0f}%"
                mount = p.get("mountpoint") or "—"
                label = p.get("fstype") or "?"
                if p.get("is_efi"):
                    label = t("efi")
                if p.get("is_swap"):
                    label = t("swap")
                lines.append(
                    f"│    {p.get('name'):<14} {format_bytes(p.get('size')):<10} "
                    f"{label:<10} {mount}{used}"
                )

        advice = health.get("advice") or []
        if advice:
            lines.append("│")
            lines.append("│  " + _c(color, BOLD, t("advice")))
            for item in advice:
                sc = SEV_COLOR.get(item.get("severity"), CYAN)
                mark = {"critical": "×", "warning": "!", "info": "i"}.get(
                    item.get("severity"), "i"
                )
                lines.append("│    " + _c(color, sc, f"[{mark}] {item.get('text')}"))
        lines.append(_c(color, DIM, "└" + "─" * 60))
        lines.append("")
    return "\n".join(lines)


def render_json(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)


def run_cli(args: Any) -> int:
    color = sys.stdout.isatty() and not args.json
    snapshot = collect()
    if args.json and not args.watch:
        sys.stdout.write(render_json(snapshot) + "\n")
        return 0
    if args.watch is not None:
        interval = float(args.watch) if args.watch else 1.0
        tracker = IoTracker()
        print(t("watch_hint"), file=sys.stderr)
        try:
            while True:
                snapshot = collect()
                drives = snapshot.get("drives") or []
                if not drives:
                    print(t("no_drives"))
                    return 1
                # multi-drive: print a compact table each tick
                sys.stdout.write("\033[2J\033[H" if color else "")
                print(render_text(snapshot, color=color))
                print(_c(color, BOLD, t("activity")))
                samples = []
                for d in drives:
                    samples.append((d, tracker.sample(d["name"])))
                time.sleep(0.15)
                # second sample so first watch frame has rates
                print(
                    f"{'DEV':<12} {'R':>12} {'W':>12} {'IOPS':>8}  {t('temperature')}"
                )
                for d, _ in samples:
                    s = tracker.sample(d["name"])
                    if not s:
                        continue
                    print(
                        f"{d['name']:<12} {format_rate(s['read_bps']):>12} "
                        f"{format_rate(s['write_bps']):>12} "
                        f"{s['read_iops']+s['write_iops']:8.0f}  "
                        f"{format_temp(d.get('temperature_c'))}"
                    )
                time.sleep(max(0.2, interval))
        except KeyboardInterrupt:
            print()
            return 0
    sys.stdout.write(render_text(snapshot, color=color) + "\n")
    return 0
