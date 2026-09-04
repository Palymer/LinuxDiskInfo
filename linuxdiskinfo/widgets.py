"""GTK4 drawing widgets: health gauge, partition map, I/O sparkline."""

from __future__ import annotations

import math
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .formatters import format_bytes, format_rate
from .i18n import t

GRADE_RGB = {
    "excellent": (0.18, 0.76, 0.49),
    "good": (0.14, 0.45, 0.85),
    "caution": (0.90, 0.65, 0.04),
    "bad": (0.88, 0.11, 0.14),
    "unknown": (0.55, 0.55, 0.55),
}

PART_PALETTE = [
    (0.22, 0.45, 0.85),
    (0.18, 0.64, 0.47),
    (0.55, 0.27, 0.68),
    (0.80, 0.47, 0.18),
    (0.20, 0.60, 0.72),
    (0.70, 0.30, 0.45),
]


def _dark() -> bool:
    try:
        return Adw.StyleManager.get_default().get_dark()
    except Exception:
        return False


class HealthGauge(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self._score = 0
        self._grade = "unknown"
        self.set_content_width(132)
        self.set_content_height(132)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_draw_func(self._draw)

    def set_health(self, score: int, grade: str) -> None:
        self._score = max(0, min(100, int(score)))
        self._grade = grade
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 8
        track = (1, 1, 1, 0.12) if _dark() else (0, 0, 0, 0.08)
        cr.set_line_width(11)
        cr.set_line_cap(1)  # ROUND
        cr.set_source_rgba(*track)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        rgb = GRADE_RGB.get(self._grade, GRADE_RGB["unknown"])
        cr.set_source_rgb(*rgb)
        start = -math.pi / 2
        cr.arc(cx, cy, radius, start, start + 2 * math.pi * (self._score / 100.0))
        cr.stroke()
        cr.set_source_rgba(1, 1, 1, 0.9) if _dark() else cr.set_source_rgba(0.12, 0.12, 0.14, 0.95)
        cr.select_font_face("Cantarell", 0, 1)
        cr.set_font_size(32)
        text = str(self._score)
        xb, _yb, tw, th, _dx, _dy = cr.text_extents(text)
        cr.move_to(cx - tw / 2 - xb, cy + th / 2 - 4)
        cr.show_text(text)
        cr.set_font_size(11)
        cr.set_source_rgba(1, 1, 1, 0.55) if _dark() else cr.set_source_rgba(0, 0, 0, 0.45)
        sub = "/ 100"
        xb, _yb, tw, th, _dx, _dy = cr.text_extents(sub)
        cr.move_to(cx - tw / 2 - xb, cy + 22)
        cr.show_text(sub)


class PartitionMap(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[dict] = []
        self._total = 1
        self.set_content_height(44)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.set_tooltip_text("")

    def set_partitions(self, partitions: list[dict], total: int) -> None:
        self._parts = partitions or []
        self._total = max(int(total or 1), 1)
        self.queue_draw()
        tips = []
        for p in self._parts:
            label = p.get("mountpoint") or p.get("fstype") or p.get("name") or t("unallocated")
            extra = ""
            if p.get("used_pct") is not None:
                extra = f" · {p['used_pct']:.0f}%"
            tips.append(f"{label}: {format_bytes(p.get('size'))}{extra}")
        self.set_tooltip_text("\n".join(tips) if tips else "")

    def _draw(self, _area, cr, width: int, height: int) -> None:
        radius = 8
        # background track
        cr.set_source_rgba(1, 1, 1, 0.08) if _dark() else cr.set_source_rgba(0, 0, 0, 0.06)
        _round_rect(cr, 0, 0, width, height, radius)
        cr.fill()
        if not self._parts:
            return
        x = 0.0
        gap = 2.0
        usable = width
        for i, p in enumerate(self._parts):
            frac = max(p.get("size") or 0, 0) / self._total
            w = max(frac * usable - gap, 4 if frac > 0 else 0)
            if w <= 0:
                continue
            if p.get("unallocated"):
                rgb = (0.45, 0.45, 0.48)
            elif p.get("is_efi"):
                rgb = (0.20, 0.45, 0.86)
            elif p.get("is_swap"):
                rgb = (0.55, 0.28, 0.70)
            else:
                rgb = PART_PALETTE[i % len(PART_PALETTE)]
            cr.set_source_rgb(*rgb)
            _round_rect(cr, x, 0, w, height, 6)
            cr.fill()
            used_pct = p.get("used_pct")
            if used_pct:
                cr.set_source_rgba(0, 0, 0, 0.28)
                _round_rect(cr, x, 0, w * min(used_pct / 100.0, 1.0), height, 6)
                cr.fill()
            if w > 48:
                cr.set_source_rgb(1, 1, 1)
                cr.select_font_face("Cantarell", 0, 0)
                cr.set_font_size(11)
                label = p.get("mountpoint") or p.get("fstype") or t("unallocated")
                if p.get("is_efi"):
                    label = t("efi")
                if p.get("is_swap"):
                    label = t("swap")
                label = label[-18:]
                xb, _yb, tw, th, _dx, _dy = cr.text_extents(label)
                if tw < w - 8:
                    cr.move_to(x + (w - tw) / 2 - xb, height / 2 + th / 2 - 1)
                    cr.show_text(label)
            x += w + gap


class IoChart(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self._points: list[tuple[float, float, float]] = []
        self.set_content_height(140)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def set_points(self, points: list[tuple[float, float, float]]) -> None:
        self._points = list(points)
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        cr.set_source_rgba(1, 1, 1, 0.05) if _dark() else cr.set_source_rgba(0, 0, 0, 0.04)
        _round_rect(cr, 0, 0, width, height, 10)
        cr.fill()
        if len(self._points) < 2:
            cr.set_source_rgba(1, 1, 1, 0.35) if _dark() else cr.set_source_rgba(0, 0, 0, 0.35)
            cr.select_font_face("Cantarell", 0, 0)
            cr.set_font_size(12)
            msg = "…"
            xb, _yb, tw, th, _dx, _dy = cr.text_extents(msg)
            cr.move_to((width - tw) / 2, height / 2)
            cr.show_text(msg)
            return
        values = [max(r, w) for _, r, w in self._points]
        peak = max(values) or 1.0
        # nice peak
        peak = _nice_peak(peak)
        pad_l, pad_r, pad_t, pad_b = 8, 8, 8, 22
        plot_w = width - pad_l - pad_r
        plot_h = height - pad_t - pad_b
        n = len(self._points)

        def series(idx: int, rgb, fill_a: float) -> None:
            cr.new_path()
            for i, pt in enumerate(self._points):
                x = pad_l + plot_w * i / max(n - 1, 1)
                y = pad_t + plot_h * (1 - pt[idx] / peak)
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.set_source_rgb(*rgb)
            cr.set_line_width(1.8)
            cr.stroke_preserve()
            cr.line_to(pad_l + plot_w, pad_t + plot_h)
            cr.line_to(pad_l, pad_t + plot_h)
            cr.close_path()
            cr.set_source_rgba(*rgb, fill_a)
            cr.fill()

        series(1, (0.20, 0.55, 0.95), 0.18)
        series(2, (0.90, 0.48, 0.16), 0.16)

        cr.set_source_rgba(1, 1, 1, 0.45) if _dark() else cr.set_source_rgba(0, 0, 0, 0.45)
        cr.select_font_face("Cantarell", 0, 0)
        cr.set_font_size(10)
        cr.move_to(pad_l, height - 6)
        cr.show_text(f"0 — {format_rate(peak)}")
        cr.set_source_rgb(0.20, 0.55, 0.95)
        cr.move_to(width - 170, height - 6)
        cr.show_text(t("read_rate"))
        cr.set_source_rgb(0.90, 0.48, 0.16)
        cr.move_to(width - 90, height - 6)
        cr.show_text(t("write_rate"))


def _nice_peak(value: float) -> float:
    if value <= 1:
        return 1.0
    exp = 10 ** math.floor(math.log10(value))
    n = value / exp
    for step in (1, 2, 5, 10):
        if n <= step:
            return step * exp
    return 10 * exp


def _round_rect(cr, x, y, w, h, r) -> None:
    r = min(r, w / 2, h / 2)
    cr.new_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def metric_tile(title: str, value: str, subtitle: str | None = None) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("metric-tile")
    box.add_css_class("card")
    cap = Gtk.Label(label=title, xalign=0)
    cap.add_css_class("dim-label")
    cap.add_css_class("metric-cap")
    val = Gtk.Label(label=value, xalign=0)
    val.add_css_class("metric-value")
    val.set_ellipsize(Pango.EllipsizeMode.END)
    box.append(cap)
    box.append(val)
    if subtitle:
        sub = Gtk.Label(label=subtitle, xalign=0)
        sub.add_css_class("dim-label")
        sub.add_css_class("metric-sub")
        box.append(sub)
    box.set_hexpand(True)
    return box


def info_row(key: str, value: str, on_copy: Callable[[str], None] | None = None) -> Gtk.Widget:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    k = Gtk.Label(label=key, xalign=0)
    k.add_css_class("dim-label")
    k.set_width_chars(14)
    v = Gtk.Label(label=value, xalign=0)
    v.set_selectable(True)
    v.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    v.set_hexpand(True)
    v.set_xalign(0)
    row.append(k)
    row.append(v)
    if on_copy and value and value != "—":
        btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        btn.add_css_class("flat")
        btn.set_tooltip_text(t("copied"))
        btn.connect("clicked", lambda *_: on_copy(value))
        row.append(btn)
    return row


def advice_row(item: dict) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    box.add_css_class("advice-row")
    pill = Gtk.Label(label=item.get("severity", "info").upper())
    pill.add_css_class("advice-pill")
    pill.add_css_class("advice-" + (item.get("severity") or "info"))
    msg = Gtk.Label(label=item.get("text") or "", xalign=0, wrap=True)
    msg.set_hexpand(True)
    msg.set_wrap(True)
    box.append(pill)
    box.append(msg)
    return box


def attr_row(attr: dict) -> Gtk.Widget:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    row.add_css_class("attr-row")
    name = Gtk.Label(label=str(attr.get("name") or attr.get("id") or ""), xalign=0)
    name.set_hexpand(True)
    name.set_ellipsize(Pango.EllipsizeMode.END)
    val = Gtk.Label(label=str(attr.get("display") if attr.get("display") is not None else attr.get("value") or ""), xalign=1)
    val.add_css_class("numeric")
    val.set_width_chars(18)
    st = attr.get("status") or "ok"
    badge = Gtk.Label(label=t(f"status_{st}") if st in ("ok", "info", "caution", "bad") else st)
    badge.add_css_class("status-badge")
    badge.add_css_class(f"status-{st}")
    row.append(name)
    row.append(val)
    row.append(badge)
    if attr.get("hint"):
        row.set_tooltip_text(str(attr["hint"]))
    return row
