"""Collect drive identity, SMART, partitions, PCI and I/O from UDisks2 + sysfs."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from gi.repository import Gio, GLib

from . import __version__
from .formatters import kelvin_to_c, read_sysfs
from .health import attach

UDISKS = "org.freedesktop.UDisks2"
IF_DRIVE = "org.freedesktop.UDisks2.Drive"
IF_BLOCK = "org.freedesktop.UDisks2.Block"
IF_PART = "org.freedesktop.UDisks2.Partition"
IF_PTABLE = "org.freedesktop.UDisks2.PartitionTable"
IF_FS = "org.freedesktop.UDisks2.Filesystem"
IF_SWAP = "org.freedesktop.UDisks2.Swapspace"
IF_NVME = "org.freedesktop.UDisks2.NVMe.Controller"
IF_NS = "org.freedesktop.UDisks2.NVMe.Namespace"
IF_ATA = "org.freedesktop.UDisks2.Drive.Ata"

SKIP_PREFIXES = ("loop", "ram", "zram", "fd", "sr", "dm-", "md")

GPT_EFI = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
GPT_SWAP = "0657fd6d-a4ab-43c4-84e5-0933c84b4f4f"

ATA_UNIT = {
    0: "unknown",
    1: "none",
    2: "ms",
    3: "sectors",
    4: "mK",
}


def _ay(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.split("\0", 1)[0]
    if isinstance(value, bytes):
        return value.split(b"\x00", 1)[0].decode("utf-8", "replace")
    try:
        return bytes(value).split(b"\x00", 1)[0].decode("utf-8", "replace")
    except Exception:
        return str(value)


def _ay_list(values: Any) -> list[str]:
    if not values:
        return []
    return [_ay(v) for v in values if _ay(v)]


def _variant_py(value: Any) -> Any:
    if isinstance(value, GLib.Variant):
        return _variant_py(value.unpack())
    if isinstance(value, dict):
        return {k: _variant_py(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_variant_py(v) for v in value]
    return value


class UDisksClient:
    def __init__(self) -> None:
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.objects: dict[str, dict] = {}

    def refresh(self) -> None:
        proxy = Gio.DBusProxy.new_sync(
            self.bus,
            Gio.DBusProxyFlags.NONE,
            None,
            UDISKS,
            "/org/freedesktop/UDisks2",
            "org.freedesktop.DBus.ObjectManager",
            None,
        )
        result = proxy.call_sync(
            "GetManagedObjects", None, Gio.DBusCallFlags.NONE, 8000, None
        )
        self.objects = result.unpack()[0]

    def _proxy(self, path: str, iface: str) -> Gio.DBusProxy:
        return Gio.DBusProxy.new_sync(
            self.bus,
            Gio.DBusProxyFlags.NONE,
            None,
            UDISKS,
            path,
            iface,
            None,
        )

    def call(self, path: str, iface: str, method: str, params: GLib.Variant | None = None) -> Any:
        proxy = self._proxy(path, iface)
        result = proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, 8000, None)
        return result.unpack() if result is not None else None


def _read_hwmon(ctrl_sysfs: Path | None) -> dict[str, Any]:
    info: dict[str, Any] = {"sensors": []}
    if not ctrl_sysfs:
        return info
    hwmon_root = None
    for child in ctrl_sysfs.iterdir() if ctrl_sysfs.exists() else []:
        if child.name.startswith("hwmon"):
            hwmon_root = child
            break
    if hwmon_root is None:
        # nvme0/hwmon0
        matches = list(ctrl_sysfs.glob("hwmon*"))
        hwmon_root = matches[0] if matches else None
    if hwmon_root is None:
        return info
    temps = []
    for inp in sorted(hwmon_root.glob("temp*_input")):
        idx = inp.name[4:].split("_", 1)[0]
        def read_num(name: str) -> float | None:
            raw = read_sysfs(str(hwmon_root / f"temp{idx}_{name}"))
            if raw is None:
                return None
            try:
                return int(raw) / 1000.0
            except ValueError:
                return None

        sensor = {
            "label": read_sysfs(str(hwmon_root / f"temp{idx}_label")) or f"temp{idx}",
            "celsius": read_num("input"),
            "max_c": read_num("max"),
            "crit_c": read_num("crit"),
            "min_c": read_num("min"),
            "alarm": read_sysfs(str(hwmon_root / f"temp{idx}_alarm")) == "1",
            "path": str(inp),
        }
        temps.append(sensor)
        if sensor["celsius"] is not None and info.get("celsius") is None:
            info["celsius"] = sensor["celsius"]
            info["path"] = str(inp)
    info["sensors"] = temps
    return info


def _pci_link(dev_path: Path) -> dict[str, str] | None:
    current = dev_path
    for _ in range(8):
        speed = current / "current_link_speed"
        if speed.exists():
            return {
                "speed": read_sysfs(str(speed), "") or "",
                "width": read_sysfs(str(current / "current_link_width"), "") or "",
                "max_speed": read_sysfs(str(current / "max_link_speed"), "") or "",
                "max_width": read_sysfs(str(current / "max_link_width"), "") or "",
                "vendor": read_sysfs(str(current / "vendor"), "") or "",
                "device": read_sysfs(str(current / "device"), "") or "",
            }
        current = current.parent
    return None


def _sysfs_block(name: str) -> dict[str, Any]:
    root = Path(f"/sys/block/{name}")
    if not root.exists():
        return {}
    queue = root / "queue"
    data: dict[str, Any] = {
        "rotational": read_sysfs(str(queue / "rotational")) == "1",
        "scheduler": (read_sysfs(str(queue / "scheduler")) or "").strip(),
        "logical_block_size": _to_int(read_sysfs(str(queue / "logical_block_size"))),
        "physical_block_size": _to_int(read_sysfs(str(queue / "physical_block_size"))),
        "discard_max_bytes": _to_int(read_sysfs(str(queue / "discard_max_bytes"))),
        "discard_granularity": _to_int(read_sysfs(str(queue / "discard_granularity"))),
        "nr_requests": _to_int(read_sysfs(str(queue / "nr_requests"))),
        "read_ahead_kb": _to_int(read_sysfs(str(queue / "read_ahead_kb"))),
        "write_cache": read_sysfs(str(queue / "write_cache")),
        "size_sectors": _to_int(read_sysfs(str(root / "size"))),
        "queue_depth": _to_int(read_sysfs(str(root / "queue_depth"))),
    }
    device = (root / "device").resolve()
    data["sysfs_device"] = str(device)
    pci_src = device
    if (device / "device").exists():
        pci_src = (device / "device").resolve()
    data["pci"] = _pci_link(pci_src)
    hwmon_base = device if device.name.startswith("nvme") else None
    if hwmon_base is None and device.parent.name.startswith("nvme"):
        hwmon_base = device.parent
    data["hwmon"] = _read_hwmon(hwmon_base)
    ctrl = None
    match = re.match(r"(nvme\d+)", name)
    if match:
        ctrl = Path(f"/sys/class/nvme/{match.group(1)}")
    if ctrl and ctrl.exists():
        data["nvme_ctrl"] = {
            "model": (read_sysfs(str(ctrl / "model")) or "").strip(),
            "serial": (read_sysfs(str(ctrl / "serial")) or "").strip(),
            "firmware": (read_sysfs(str(ctrl / "firmware_rev")) or "").strip(),
            "transport": read_sysfs(str(ctrl / "transport")),
            "state": read_sysfs(str(ctrl / "state")),
            "address": read_sysfs(str(ctrl / "address")),
            "cntlid": read_sysfs(str(ctrl / "cntlid")),
            "queue_count": _to_int(read_sysfs(str(ctrl / "queue_count"))),
            "sqsize": _to_int(read_sysfs(str(ctrl / "sqsize"))),
            "subsysnqn": (read_sysfs(str(ctrl / "subsysnqn")) or "").strip(),
            "numa_node": read_sysfs(str(ctrl / "numa_node")),
        }
        if not data.get("hwmon") or not data["hwmon"].get("sensors"):
            data["hwmon"] = _read_hwmon(ctrl)
        if not data.get("pci") and (ctrl / "device").exists():
            data["pci"] = _pci_link((ctrl / "device").resolve())
    return data


def _to_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _statvfs(mount: str) -> dict[str, int] | None:
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    total = st.f_frsize * st.f_blocks
    avail = st.f_frsize * st.f_bavail
    used = st.f_frsize * (st.f_blocks - st.f_bfree)
    # Match df(1): percent is used / (used + available to user)
    denom = used + avail
    pct = (used / denom * 100.0) if denom else 0.0
    return {
        "total": total,
        "used": used,
        "free": avail,
        "used_pct": pct,
    }


def _swap_usage() -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    try:
        lines = Path("/proc/swaps").read_text().splitlines()[1:]
    except OSError:
        return result
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        # size/used are in KiB
        result[parts[0]] = {
            "total": int(parts[2]) * 1024,
            "used": int(parts[3]) * 1024,
        }
    return result


def _fstrim_timer() -> bool | None:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return None
    try:
        proc = subprocess.run(
            [systemctl, "is-active", "fstrim.timer"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return proc.stdout.strip() == "active"
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_diskstats(name: str) -> dict[str, int] | None:
    try:
        lines = Path("/proc/diskstats").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) < 14:
            continue
        if parts[2] != name:
            continue
        # kernel docs: field 1 is reads completed ... (index 3 in split after major/minor/name)
        return {
            "reads": int(parts[3]),
            "reads_merged": int(parts[4]),
            "read_sectors": int(parts[5]),
            "read_ms": int(parts[6]),
            "writes": int(parts[7]),
            "writes_merged": int(parts[8]),
            "write_sectors": int(parts[9]),
            "write_ms": int(parts[10]),
            "inflight": int(parts[11]),
            "io_ms": int(parts[12]),
            "weighted_io_ms": int(parts[13]),
            "read_bytes": int(parts[5]) * 512,
            "write_bytes": int(parts[9]) * 512,
            "ts": time.time(),
        }
    return None


class IoTracker:
    """Compute rates from successive /proc/diskstats snapshots."""

    def __init__(self) -> None:
        self._prev: dict[str, dict[str, int | float]] = {}
        self.history: dict[str, list[tuple[float, float, float]]] = {}

    def sample(self, name: str) -> dict[str, float] | None:
        cur = parse_diskstats(name)
        if not cur:
            return None
        prev = self._prev.get(name)
        self._prev[name] = cur
        if not prev:
            return None
        dt = float(cur["ts"]) - float(prev["ts"])
        if dt <= 0:
            dt = 1e-6
        read_bps = (cur["read_bytes"] - prev["read_bytes"]) / dt
        write_bps = (cur["write_bytes"] - prev["write_bytes"]) / dt
        read_iops = (cur["reads"] - prev["reads"]) / dt
        write_iops = (cur["writes"] - prev["writes"]) / dt
        read_ios = cur["reads"] - prev["reads"]
        write_ios = cur["writes"] - prev["writes"]
        rlat = ((cur["read_ms"] - prev["read_ms"]) / read_ios) if read_ios > 0 else 0.0
        wlat = ((cur["write_ms"] - prev["write_ms"]) / write_ios) if write_ios > 0 else 0.0
        sample = {
            "read_bps": max(0.0, read_bps),
            "write_bps": max(0.0, write_bps),
            "read_iops": max(0.0, read_iops),
            "write_iops": max(0.0, write_iops),
            "read_latency_ms": max(0.0, rlat),
            "write_latency_ms": max(0.0, wlat),
            "inflight": float(cur["inflight"]),
        }
        hist = self.history.setdefault(name, [])
        hist.append((time.time(), sample["read_bps"], sample["write_bps"]))
        if len(hist) > 60:
            del hist[0 : len(hist) - 60]
        return sample


def _format_ata_pretty(pretty: int, unit: int) -> str:
    if unit == 2:
        if pretty >= 3_600_000:
            return f"{pretty / 3_600_000:.1f} h"
        if pretty >= 60_000:
            return f"{pretty / 60_000:.1f} min"
        return f"{pretty} ms"
    if unit == 3:
        return f"{pretty} sectors"
    if unit == 4:
        c = pretty / 1000.0 - 273.15
        return f"{c:.0f} °C"
    return str(pretty)


def _nvme_smart(client: UDisksClient, path: str, props: dict) -> dict[str, Any]:
    smart: dict[str, Any] = {
        "kind": "nvme",
        "critical_warning": list(props.get("SmartCriticalWarning") or []),
        "power_on_hours": int(props.get("SmartPowerOnHours") or 0),
        "temperature_k": int(props.get("SmartTemperature") or 0) or None,
        "selftest": props.get("SmartSelftestStatus") or "",
        "selftest_remaining": props.get("SmartSelftestPercentRemaining"),
        "updated": int(props.get("SmartUpdated") or 0) or None,
        "nvme_revision": props.get("NVMeRevision") or "",
        "controller_id": props.get("ControllerID"),
        "state": props.get("State") or "",
        "unallocated": int(props.get("UnallocatedCapacity") or 0),
        "nqn": _ay(props.get("SubsystemNQN")),
    }
    try:
        client.call(path, IF_NVME, "SmartUpdate", GLib.Variant("(a{sv})", ({},)))
    except GLib.Error:
        pass
    try:
        raw = client.call(
            path, IF_NVME, "SmartGetAttributes", GLib.Variant("(a{sv})", ({},))
        )
        attrs = _variant_py(raw[0]) if raw else {}
    except GLib.Error:
        attrs = {}
    if isinstance(attrs, dict):
        smart["avail_spare"] = int(attrs.get("avail_spare", 0))
        smart["spare_thresh"] = int(attrs.get("spare_thresh", 0))
        smart["percent_used"] = int(attrs.get("percent_used", 0))
        smart["total_data_read"] = int(attrs.get("total_data_read", 0) or 0)
        smart["total_data_written"] = int(attrs.get("total_data_written", 0) or 0)
        smart["ctrl_busy_time"] = int(attrs.get("ctrl_busy_time", 0) or 0)
        smart["power_cycles"] = int(attrs.get("power_cycles", 0) or 0)
        smart["unsafe_shutdowns"] = int(attrs.get("unsafe_shutdowns", 0) or 0)
        smart["media_errors"] = int(attrs.get("media_errors", 0) or 0)
        smart["num_err_log_entries"] = int(attrs.get("num_err_log_entries", 0) or 0)
        smart["wctemp"] = int(attrs.get("wctemp", 0) or 0) or None
        smart["cctemp"] = int(attrs.get("cctemp", 0) or 0) or None
        smart["warning_temp_time"] = int(attrs.get("warning_temp_time", 0) or 0)
        smart["critical_temp_time"] = int(attrs.get("critical_temp_time", 0) or 0)
        sensors = attrs.get("temp_sensors") or []
        smart["temp_sensors"] = [int(x) for x in sensors if int(x or 0)]
    return smart


def _ata_smart(client: UDisksClient, path: str, props: dict) -> tuple[dict[str, Any], list[dict]]:
    smart: dict[str, Any] = {
        "kind": "ata",
        "supported": bool(props.get("SmartSupported", True)),
        "enabled": bool(props.get("SmartEnabled", True)),
        "failing": bool(props.get("SmartFailing", False)),
        "power_on_hours": int((props.get("SmartPowerOnSeconds") or 0) / 3600),
        "temperature_k": props.get("SmartTemperature") or None,
        "selftest": props.get("SmartSelftestStatus") or "",
        "num_bad_sectors": props.get("SmartNumBadSectors"),
        "attrs_failing": props.get("SmartNumAttributesFailing"),
        "updated": int(props.get("SmartUpdated") or 0) or None,
    }
    attributes: list[dict] = []
    try:
        client.call(path, IF_ATA, "SmartUpdate", GLib.Variant("(a{sv})", ({},)))
    except GLib.Error:
        pass
    try:
        raw = client.call(
            path, IF_ATA, "SmartGetAttributes", GLib.Variant("(a{sv})", ({},))
        )
        rows = _variant_py(raw[0]) if raw else []
    except GLib.Error:
        rows = []
    for row in rows or []:
        # (id, name, flags, value, worst, threshold, pretty, pretty_unit, extra)
        try:
            aid, name, flags, value, worst, threshold, pretty, unit, _extra = (
                list(row) + [None] * 9
            )[:9]
        except Exception:
            continue
        failed = bool(threshold) and value <= threshold
        attributes.append(
            {
                "id": int(aid),
                "name": str(name).replace("_", " "),
                "flags": int(flags),
                "value": int(value),
                "worst": int(worst),
                "threshold": int(threshold),
                "pretty": int(pretty),
                "raw": int(pretty),
                "unit": ATA_UNIT.get(int(unit), str(unit)),
                "display": _format_ata_pretty(int(pretty), int(unit)),
                "failed": failed,
                "prefail": bool(int(flags) & 1),
                "status": "bad" if failed else "ok",
            }
        )
    return smart, attributes


def _nvme_attr_rows(smart: dict) -> list[dict]:
    rows = []

    def add(name: str, value: Any, status: str = "ok", hint: str = "") -> None:
        if value is None or value == "":
            return
        rows.append(
            {
                "id": name,
                "name": name,
                "display": str(value),
                "status": status,
                "hint": hint,
            }
        )

    flags = smart.get("critical_warning") or []
    add("Critical warning", ", ".join(flags) if flags else "none", "bad" if flags else "ok")
    if smart.get("avail_spare") is not None:
        spare, thresh = smart.get("avail_spare"), smart.get("spare_thresh")
        st = "ok"
        if isinstance(spare, int) and isinstance(thresh, int) and thresh:
            if spare <= thresh:
                st = "bad"
            elif spare <= thresh * 2:
                st = "caution"
        add("Available spare", f"{spare} %  (threshold {thresh} %)", st)
    if smart.get("percent_used") is not None:
        wear = smart["percent_used"]
        st = "ok"
        if wear >= 90:
            st = "bad"
        elif wear >= 80:
            st = "caution"
        add("Percentage used", f"{wear} %", st, "NVMe endurance used")
    add("Data units read", smart.get("total_data_read_fmt") or smart.get("total_data_read"))
    add("Data units written", smart.get("total_data_written_fmt") or smart.get("total_data_written"))
    add("Power-on hours", smart.get("power_on_hours"))
    add("Power cycles", smart.get("power_cycles"))
    unsafe = smart.get("unsafe_shutdowns")
    cycles = smart.get("power_cycles") or 0
    st = "ok"
    if isinstance(unsafe, int) and cycles and unsafe / max(cycles, 1) >= 0.5 and unsafe >= 20:
        st = "caution"
    add("Unsafe shutdowns", unsafe, st)
    media = smart.get("media_errors")
    add("Media errors", media, "bad" if media else "ok")
    add("Error log entries", smart.get("num_err_log_entries"), "caution" if smart.get("num_err_log_entries") else "ok")
    busy = smart.get("ctrl_busy_time")
    if isinstance(busy, int) and busy:
        add("Controller busy", f"{busy} min ({busy / 60:.0f} h)")
    wc = kelvin_to_c(smart.get("wctemp"))
    cc = kelvin_to_c(smart.get("cctemp"))
    if wc is not None:
        add("Warning composite temp", f"{wc:.0f} °C")
    if cc is not None:
        add("Critical composite temp", f"{cc:.0f} °C")
    add("Time over warning temp", smart.get("warning_temp_time"))
    add("Time over critical temp", smart.get("critical_temp_time"))
    add("Self-test", smart.get("selftest"))
    return rows


def collect_snapshot() -> dict[str, Any]:
    client = UDisksClient()
    client.refresh()

    blocks_by_drive: dict[str, list[tuple[str, dict]]] = {}
    for path, ifaces in client.objects.items():
        block = ifaces.get(IF_BLOCK)
        if not block:
            continue
        drive_path = block.get("Drive") or "/"
        if drive_path in ("/", ""):
            continue
        blocks_by_drive.setdefault(drive_path, []).append((path, ifaces))

    swap_map = _swap_usage()
    trim_timer = _fstrim_timer()
    drives: list[dict[str, Any]] = []

    for drive_path, ifaces in client.objects.items():
        drive_props = ifaces.get(IF_DRIVE)
        if not drive_props:
            continue
        if drive_props.get("Optical"):
            continue

        members = blocks_by_drive.get(drive_path) or []
        whole = None
        whole_path = None
        partitions_ifaces: list[tuple[str, dict]] = []
        for bpath, bifaces in members:
            if IF_PART in bifaces:
                partitions_ifaces.append((bpath, bifaces))
            elif IF_BLOCK in bifaces:
                whole = bifaces
                whole_path = bpath

        if whole is None and members:
            whole = members[0][1]
            whole_path = members[0][0]
        if whole is None:
            continue

        block = whole[IF_BLOCK]
        device = _ay(block.get("Device"))
        name = Path(device).name
        if not name or name.startswith(SKIP_PREFIXES):
            continue

        sysfs = _sysfs_block(name)
        kind = "unknown"
        smart: dict[str, Any] = {}
        attributes: list[dict] = []

        if IF_NVME in ifaces:
            kind = "nvme"
            smart = _nvme_smart(client, drive_path, ifaces[IF_NVME])
        elif IF_ATA in ifaces:
            kind = "ata"
            smart, attributes = _ata_smart(client, drive_path, ifaces[IF_ATA])

        ns = whole.get(IF_NS) or {}
        ptable = whole.get(IF_PTABLE) or {}

        temperature_c = None
        if sysfs.get("hwmon", {}).get("celsius") is not None:
            temperature_c = sysfs["hwmon"]["celsius"]
        elif smart.get("temperature_k"):
            temperature_c = kelvin_to_c(smart.get("temperature_k"))

        size = int(block.get("Size") or 0)
        if size <= 0 and sysfs.get("size_sectors"):
            size = int(sysfs["size_sectors"]) * 512

        partitions: list[dict[str, Any]] = []
        for _ppath, pifaces in sorted(
            partitions_ifaces,
            key=lambda item: int((item[1].get(IF_PART) or {}).get("Number") or 0),
        ):
            pblock = pifaces[IF_BLOCK]
            ppart = pifaces.get(IF_PART) or {}
            pfs = pifaces.get(IF_FS) or {}
            mounts = _ay_list(pfs.get("MountPoints"))
            mount = mounts[0] if mounts else None
            pdevice = _ay(pblock.get("Device"))
            psize = int(ppart.get("Size") or pblock.get("Size") or 0)
            fstype = pblock.get("IdType") or ""
            usage = None
            used_pct = None
            if mount:
                usage = _statvfs(mount)
                if usage:
                    used_pct = usage["used_pct"]
            if pdevice in swap_map:
                usage = {
                    "total": swap_map[pdevice]["total"],
                    "used": swap_map[pdevice]["used"],
                    "free": swap_map[pdevice]["total"] - swap_map[pdevice]["used"],
                    "used_pct": (
                        swap_map[pdevice]["used"] / swap_map[pdevice]["total"] * 100.0
                        if swap_map[pdevice]["total"]
                        else 0
                    ),
                }
                used_pct = usage["used_pct"]
                mount = mount or "[SWAP]"
            ptype = (ppart.get("Type") or "").lower()
            partitions.append(
                {
                    "name": Path(pdevice).name,
                    "path": pdevice,
                    "number": int(ppart.get("Number") or 0),
                    "size": psize,
                    "offset": int(ppart.get("Offset") or 0),
                    "fstype": fstype,
                    "label": pblock.get("IdLabel") or ppart.get("Name") or "",
                    "uuid": pblock.get("IdUUID") or "",
                    "part_uuid": ppart.get("UUID") or "",
                    "part_type": ppart.get("Type") or "",
                    "mountpoint": mount,
                    "usage": usage,
                    "used_pct": used_pct,
                    "is_efi": ptype == GPT_EFI,
                    "is_swap": ptype == GPT_SWAP or fstype == "swap",
                }
            )

        allocated = sum(p["size"] for p in partitions)
        if size and allocated < size * 0.999:
            partitions.append(
                {
                    "name": "",
                    "path": "",
                    "number": 0,
                    "size": max(0, size - allocated),
                    "offset": allocated,
                    "fstype": "",
                    "label": "",
                    "uuid": "",
                    "part_uuid": "",
                    "part_type": "",
                    "mountpoint": None,
                    "usage": None,
                    "used_pct": None,
                    "is_efi": False,
                    "is_swap": False,
                    "unallocated": True,
                }
            )

        rotational = bool(sysfs.get("rotational"))
        if drive_props.get("RotationRate") not in (None, 0, -1):
            rotational = int(drive_props.get("RotationRate") or 0) > 0
        bus = drive_props.get("ConnectionBus") or ""
        if kind == "nvme":
            media = "nvme"
        elif bus == "usb":
            media = "usb"
        elif rotational:
            media = "hdd"
        else:
            media = "ssd"

        discard = int(sysfs.get("discard_max_bytes") or 0)
        trim = {
            "supported": discard > 0,
            "discard_max_bytes": discard,
            "timer": trim_timer if discard > 0 else None,
        }

        # Human fields used by SMART table for NVMe byte counters
        from .formatters import format_bytes

        if smart.get("total_data_read"):
            smart["total_data_read_fmt"] = format_bytes(smart["total_data_read"])
        if smart.get("total_data_written"):
            smart["total_data_written_fmt"] = format_bytes(smart["total_data_written"])

        if kind == "nvme":
            attributes = _nvme_attr_rows(smart)

        model = (drive_props.get("Model") or sysfs.get("nvme_ctrl", {}).get("model") or "").strip()
        serial = (drive_props.get("Serial") or sysfs.get("nvme_ctrl", {}).get("serial") or "").strip()
        firmware = (
            drive_props.get("Revision") or sysfs.get("nvme_ctrl", {}).get("firmware") or ""
        ).strip()

        drive = {
            "id": drive_props.get("Id") or name,
            "name": name,
            "path": device,
            "model": model,
            "serial": serial,
            "firmware": firmware,
            "vendor": (drive_props.get("Vendor") or "").strip(),
            "wwn": (ns.get("WWN") or drive_props.get("WWN") or "").strip(),
            "size": size,
            "kind": kind,
            "media": media,
            "bus": bus or ("nvme" if kind == "nvme" else ""),
            "removable": bool(drive_props.get("Removable")),
            "partition_table": ptable.get("Type") or "",
            "temperature_c": temperature_c,
            "smart": smart,
            "smart_attributes": attributes,
            "partitions": partitions,
            "sysfs": {
                "scheduler": sysfs.get("scheduler"),
                "logical_block_size": sysfs.get("logical_block_size"),
                "physical_block_size": sysfs.get("physical_block_size"),
                "write_cache": sysfs.get("write_cache"),
                "nr_requests": sysfs.get("nr_requests"),
                "read_ahead_kb": sysfs.get("read_ahead_kb"),
                "queue_depth": sysfs.get("queue_depth"),
            },
            "pci": sysfs.get("pci"),
            "nvme_ctrl": sysfs.get("nvme_ctrl") or {},
            "hwmon": sysfs.get("hwmon") or {},
            "trim": trim,
            "namespace": {
                "nsid": ns.get("NSID"),
                "lba": ns.get("FormattedLBASize"),
                "size": ns.get("NamespaceSize"),
                "capacity": ns.get("NamespaceCapacity"),
                "utilization": ns.get("NamespaceUtilization"),
                "nguid": ns.get("NGUID"),
                "eui64": ns.get("EUI64"),
            },
            "io": parse_diskstats(name),
        }
        attach(drive)
        drives.append(drive)

    drives.sort(key=lambda d: d.get("name") or "")
    return {
        "app": "Linux Disk Info",
        "version": __version__,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hostname": platform.node(),
        "kernel": platform.release(),
        "os": " ".join(platform.linux_distribution())
        if hasattr(platform, "linux_distribution")
        else " ".join(x for x in platform.uname() if x),
        "distro": _distro(),
        "drives": drives,
    }


def _distro() -> str:
    try:
        data = Path("/etc/os-release").read_text()
    except OSError:
        return platform.platform()
    kv = {}
    for line in data.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k] = v.strip().strip('"')
    return kv.get("PRETTY_NAME") or kv.get("NAME") or platform.platform()


def collect() -> dict[str, Any]:
    return collect_snapshot()
