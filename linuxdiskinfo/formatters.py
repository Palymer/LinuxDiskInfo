"""Human-readable formatting for sizes, durations and temperatures."""

from __future__ import annotations

UNITS_SI = ("B", "KB", "MB", "GB", "TB", "PB", "EB")
UNITS_IEC = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB")


def format_bytes(n: int | float | None, *, si: bool = True, digits: int = 1) -> str:
    if n is None:
        return "—"
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "—"
    if value < 0:
        return "—"
    step = 1000.0 if si else 1024.0
    units = UNITS_SI if si else UNITS_IEC
    for unit in units:
        if value < step or unit == units[-1]:
            if unit in ("B", "KiB") and abs(value - round(value)) < 1e-9:
                return f"{int(round(value))} {unit}"
            return f"{value:.{digits}f} {unit}"
        value /= step
    return f"{value:.{digits}f} {units[-1]}"


def format_rate(bps: float | None) -> str:
    if bps is None:
        return "—"
    if bps < 0:
        bps = 0.0
    return format_bytes(bps, si=True, digits=1) + "/s"


def format_hours(hours: float | int | None) -> str:
    if hours is None:
        return "—"
    try:
        total = int(hours)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    days, rem = divmod(total, 24)
    years, days = divmod(days, 365)
    parts: list[str] = []
    if years:
        parts.append(f"{years} y")
    if days:
        parts.append(f"{days} d")
    parts.append(f"{rem} h")
    if years and not days:
        return f"{years} y {rem} h"
    if years:
        return f"{years} y {days} d"
    if days:
        return f"{days} d {rem} h"
    return f"{rem} h"


def format_hours_long(hours: float | int | None, hours_word: str = "h") -> str:
    short = format_hours(hours)
    if hours is None:
        return short
    try:
        total = int(hours)
    except (TypeError, ValueError):
        return short
    return f"{short}  ({total:,} {hours_word})".replace(",", " ")


def kelvin_to_c(kelvin: float | int | None) -> float | None:
    if kelvin is None:
        return None
    try:
        k = float(kelvin)
    except (TypeError, ValueError):
        return None
    if k <= 0:
        return None
    # UDisks NVMe temperature is Kelvin; ignore obviously broken sensors
    if k < 120:
        # already Celsius
        return k
    return k - 273.15


def format_temp(celsius: float | None) -> str:
    if celsius is None:
        return "—"
    return f"{celsius:.0f} °C"


def format_pct(value: float | int | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f} %"


def format_int(value: int | float | None) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def pcie_generation(speed: str | None) -> str | None:
    if not speed:
        return None
    text = speed.lower()
    for token, gen in (
        ("64.0", "6.0"),
        ("32.0", "5.0"),
        ("16.0", "4.0"),
        ("8.0", "3.0"),
        ("5.0", "2.0"),
        ("2.5", "1.0"),
    ):
        if token in text:
            return gen
    return None


def format_pcie(link: dict | None) -> str:
    if not link:
        return "—"
    speed = (link.get("speed") or "").replace("PCIe", "").strip()
    width = link.get("width")
    gen = pcie_generation(link.get("speed"))
    width_s = f"x{width}" if width else ""
    gen_s = f"PCIe {gen}" if gen else "PCIe"
    current = f"{gen_s} {width_s}".strip()
    if speed:
        current = f"{current} ({speed})"
    max_speed = link.get("max_speed")
    max_width = link.get("max_width")
    if max_speed and (max_speed != link.get("speed") or str(max_width) != str(width)):
        max_gen = pcie_generation(max_speed) or max_speed
        current += f"  / max {max_gen} x{max_width}"
    return current.strip()


def read_sysfs(path: str, default: str | None = None) -> str | None:
    try:
        return open(path, "r", encoding="utf-8", errors="replace").read().strip()
    except OSError:
        return default
