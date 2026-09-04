"""Composite health index, grades and actionable advice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .formatters import format_pcie, kelvin_to_c, pcie_generation
from .i18n import t

# Conservative advertised TBW (bytes) for a few well-known models.
TBW_BYTES: dict[str, int] = {
    "KINGSTON SNVS500G": 120 * 10**12,
    "KINGSTON SNVS1000G": 240 * 10**12,
    "KINGSTON SNVS2000G": 480 * 10**12,
    "KINGSTON SNV2S500G": 160 * 10**12,
    "KINGSTON SNV2S1000G": 320 * 10**12,
    "KINGSTON SNV2S2000G": 640 * 10**12,
}


@dataclass
class Advice:
    severity: str  # info / warning / critical
    key: str
    params: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return t(self.key, **self.params)


@dataclass
class Health:
    score: int
    grade: str
    reasons: list[tuple[str, int]] = field(default_factory=list)
    advice: list[Advice] = field(default_factory=list)

    @property
    def label(self) -> str:
        return t(f"grade_{self.grade}")


def _clamp(n: int) -> int:
    return max(0, min(100, n))


def _attr_by_id(drive: dict, *ids: int) -> dict | None:
    for attr in drive.get("smart_attributes") or []:
        if attr.get("id") in ids:
            return attr
    return None


def _pretty_int(attr: dict | None) -> int | None:
    if not attr:
        return None
    raw = attr.get("raw")
    if raw is None:
        raw = attr.get("pretty")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def evaluate(drive: dict) -> Health:
    score = 100
    reasons: list[tuple[str, int]] = []
    advice: list[Advice] = []
    smart = drive.get("smart") or {}
    kind = drive.get("kind")  # nvme / ata / unknown

    def deduct(points: int, reason_key: str) -> None:
        nonlocal score
        if points <= 0:
            return
        score -= points
        reasons.append((reason_key, points))

    flags = smart.get("critical_warning") or []
    if flags:
        deduct(45, "reason_critical")
        advice.append(
            Advice("critical", "advice_critical_warning", {"flags": ", ".join(map(str, flags))})
        )

    if smart.get("failing") is True:
        deduct(40, "reason_ata")
        advice.append(Advice("critical", "advice_smart_failing"))

    media = smart.get("media_errors")
    if isinstance(media, int) and media > 0:
        deduct(min(40, 20 + media * 5), "reason_media")
        advice.append(Advice("critical", "advice_media", {"count": media}))

    spare = smart.get("avail_spare")
    thresh = smart.get("spare_thresh")
    if isinstance(spare, int) and isinstance(thresh, int) and thresh > 0:
        if spare <= thresh:
            deduct(35, "reason_spare")
            advice.append(
                Advice("critical", "advice_spare_crit", {"spare": spare, "thresh": thresh})
            )
        elif spare <= thresh * 2:
            deduct(15, "reason_spare")
            advice.append(
                Advice("warning", "advice_spare_low", {"spare": spare, "thresh": thresh})
            )

    wear = smart.get("percent_used")
    if isinstance(wear, int):
        if wear >= 95:
            deduct(30, "reason_wear")
            advice.append(Advice("critical", "advice_wear_high", {"pct": wear}))
        elif wear >= 80:
            deduct(18, "reason_wear")
            advice.append(Advice("warning", "advice_wear_high", {"pct": wear}))
        elif wear >= 50:
            deduct(8, "reason_wear")
            advice.append(Advice("info", "advice_wear_mid", {"pct": wear}))

    temp = drive.get("temperature_c")
    warn_c = kelvin_to_c(smart.get("wctemp"))
    crit_c = kelvin_to_c(smart.get("cctemp"))
    if temp is not None:
        if crit_c is not None and temp >= crit_c:
            deduct(25, "reason_temp")
            advice.append(
                Advice(
                    "critical",
                    "advice_temp_crit",
                    {"temp": round(temp), "limit": round(crit_c)},
                )
            )
        elif warn_c is not None and temp >= warn_c:
            deduct(15, "reason_temp")
            advice.append(
                Advice(
                    "warning",
                    "advice_temp_warn",
                    {"temp": round(temp), "limit": round(warn_c)},
                )
            )
        elif temp >= 70:
            deduct(10, "reason_temp")
            advice.append(Advice("warning", "advice_temp_high", {"temp": round(temp)}))
        elif temp >= 60:
            deduct(4, "reason_temp")
            advice.append(Advice("info", "advice_temp_high", {"temp": round(temp)}))

    cycles = smart.get("power_cycles")
    unsafe = smart.get("unsafe_shutdowns")
    if isinstance(cycles, int) and cycles > 0 and isinstance(unsafe, int) and unsafe > 0:
        ratio = unsafe / cycles
        if ratio >= 0.5 and unsafe >= 20:
            deduct(8, "reason_unsafe")
            advice.append(
                Advice(
                    "warning",
                    "advice_unsafe",
                    {"count": unsafe, "cycles": cycles, "pct": round(ratio * 100)},
                )
            )
        elif ratio >= 0.2 and unsafe >= 10:
            deduct(4, "reason_unsafe")
            advice.append(
                Advice(
                    "info",
                    "advice_unsafe",
                    {"count": unsafe, "cycles": cycles, "pct": round(ratio * 100)},
                )
            )

    realloc = _pretty_int(_attr_by_id(drive, 5, 196))
    pending = _pretty_int(_attr_by_id(drive, 197, 198))
    if realloc and realloc > 0:
        deduct(min(25, 8 + realloc), "reason_reallocated")
        advice.append(Advice("warning", "advice_reallocated", {"count": realloc}))
    if pending and pending > 0:
        deduct(min(25, 10 + pending), "reason_reallocated")
        advice.append(Advice("warning", "advice_pending", {"count": pending}))

    for attr in drive.get("smart_attributes") or []:
        if attr.get("failed"):
            deduct(12, "reason_ata")
            advice.append(
                Advice(
                    "critical",
                    "advice_ata_failing",
                    {
                        "name": attr.get("name") or attr.get("id"),
                        "value": attr.get("value"),
                        "thresh": attr.get("threshold"),
                    },
                )
            )

    # Filesystem fill is not drive failure, but it is the most useful extra vs CrystalDiskInfo.
    for part in drive.get("partitions") or []:
        used_pct = part.get("used_pct")
        mount = part.get("mountpoint") or ""
        if (
            isinstance(used_pct, (int, float))
            and used_pct >= 85
            and mount.startswith("/")
            and part.get("fstype") not in ("swap", "vfat")
        ):
            advice.append(
                Advice(
                    "warning" if used_pct >= 90 else "info",
                    "advice_root_full",
                    {"mount": mount, "pct": round(used_pct)},
                )
            )

    link = drive.get("pci")
    if link and link.get("speed") and link.get("max_speed"):
        cur_gen = pcie_generation(link.get("speed"))
        max_gen = pcie_generation(link.get("max_speed"))
        cur_w = str(link.get("width") or "")
        max_w = str(link.get("max_width") or "")
        if (cur_gen and max_gen and cur_gen != max_gen) or (cur_w and max_w and cur_w != max_w):
            advice.append(
                Advice(
                    "info",
                    "advice_pcie_down",
                    {
                        "current": format_pcie(
                            {"speed": link.get("speed"), "width": link.get("width")}
                        ),
                        "maximum": format_pcie(
                            {
                                "speed": link.get("max_speed"),
                                "width": link.get("max_width"),
                            }
                        ),
                    },
                )
            )

    trim = drive.get("trim") or {}
    if trim.get("supported") and trim.get("timer") is False:
        advice.append(Advice("info", "advice_trim_timer"))

    selftest = smart.get("selftest")
    if selftest and str(selftest).lower() not in ("success", "ok", "passed", "none", ""):
        if "inprogress" not in str(selftest).lower():
            advice.append(Advice("warning", "advice_selftest", {"status": selftest}))

    score = _clamp(score)
    if not smart and kind == "unknown":
        grade = "unknown"
        score = 0
    elif score >= 95:
        grade = "excellent"
    elif score >= 80:
        grade = "good"
    elif score >= 50:
        grade = "caution"
    else:
        grade = "bad"

    # De-duplicate reason keys keeping the largest deduction
    merged: dict[str, int] = {}
    for key, pts in reasons:
        merged[key] = merged.get(key, 0) + pts
    reason_list = sorted(merged.items(), key=lambda x: -x[1])

    # De-duplicate advice by key
    seen = set()
    unique_advice = []
    for item in advice:
        if item.key in seen:
            continue
        seen.add(item.key)
        unique_advice.append(item)

    return Health(score=score, grade=grade, reasons=reason_list, advice=unique_advice)


def attach(drive: dict) -> dict:
    health = evaluate(drive)
    drive["health"] = {
        "score": health.score,
        "grade": health.grade,
        "label": health.label,
        "reasons": [{"key": k, "points": p, "text": t(k)} for k, p in health.reasons],
        "advice": [
            {"severity": a.severity, "key": a.key, "text": a.text(), "params": a.params}
            for a in health.advice
        ],
    }
    model = (drive.get("model") or "").strip()
    written = (drive.get("smart") or {}).get("total_data_written")
    rated = TBW_BYTES.get(model)
    if rated and isinstance(written, int) and written > 0:
        drive["endurance"] = {
            "rated_bytes": rated,
            "used_pct": min(100.0, written * 100.0 / rated),
        }
    return drive
