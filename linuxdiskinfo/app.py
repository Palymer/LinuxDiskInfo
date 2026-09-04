"""GTK4 + libadwaita application window."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import __app_id__, __version__
from .collector import IoTracker, collect
from .formatters import (
    format_bytes,
    format_hours,
    format_int,
    format_pcie,
    format_pct,
    format_rate,
    format_temp,
    kelvin_to_c,
)
from .i18n import t
from .paths import AUTHOR, GITHUB_URL, WALLETS, icons_dir, style_css
from .widgets import (
    HealthGauge,
    IoChart,
    PartitionMap,
    advice_row,
    attr_row,
    info_row,
    metric_tile,
)


def _load_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_path(str(style_css()))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def _clear(box: Gtk.Box) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


class DriveRow(Gtk.ListBoxRow):
    def __init__(self, drive: dict) -> None:
        super().__init__()
        self.drive_name = drive["name"]
        self.add_css_class("drive-row")
        grid = Gtk.Grid(column_spacing=10, row_spacing=0)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)

        icon_name = {
            "nvme": "drive-harddisk-symbolic",
            "ssd": "drive-harddisk-symbolic",
            "hdd": "drive-harddisk-symbolic",
            "usb": "drive-removable-media-symbolic",
        }.get(drive.get("media"), "drive-harddisk-symbolic")
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(28)
        icon.set_valign(Gtk.Align.CENTER)
        grid.attach(icon, 0, 0, 1, 3)

        model = Gtk.Label(label=drive.get("model") or drive["name"], xalign=0)
        model.add_css_class("heading")
        model.set_ellipsize(Pango.EllipsizeMode.END)
        model.set_hexpand(True)
        grid.attach(model, 1, 0, 1, 1)

        sub = Gtk.Label(
            label=f"{drive['name']}  ·  {format_bytes(drive.get('size'))}",
            xalign=0,
        )
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        grid.attach(sub, 1, 1, 1, 1)

        health = drive.get("health") or {}
        grade = health.get("grade") or "unknown"
        status = Gtk.Label(
            label=f"{health.get('label', '')}  {format_temp(drive.get('temperature_c'))}",
            xalign=0,
        )
        status.add_css_class(f"grade-{grade}")
        status.add_css_class("caption")
        grid.attach(status, 1, 2, 1, 1)
        self.set_child(grid)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=t("app_name"))
        self.set_default_size(1120, 740)
        icon_dir = icons_dir()
        if icon_dir.is_dir():
            display = Gdk.Display.get_default()
            if display:
                Gtk.IconTheme.get_for_display(display).add_search_path(str(icon_dir))
        self.set_icon_name("linuxdiskinfo")
        self._tracker = IoTracker()
        self._snapshot: dict[str, Any] = {"drives": []}
        self._selected: str | None = None
        self._ticks = 0

        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)

        split = Adw.OverlaySplitView(
            sidebar_width_fraction=0.26,
            min_sidebar_width=260,
            max_sidebar_width=360,
        )
        self._toast.set_child(split)
        self._split = split

        split.set_sidebar(self._build_sidebar())
        split.set_content(self._build_content())

        self._reload(full=True)
        GLib.timeout_add(1000, self._on_tick)

    def _build_sidebar(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title=t("app_name"), subtitle=t("drives"))
        header.set_title_widget(title)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(self._menu())
        header.pack_end(menu_btn)
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh.set_tooltip_text(t("refresh"))
        refresh.connect("clicked", lambda *_: self._reload(full=True))
        header.pack_end(refresh)
        toolbar.add_top_bar(header)

        self._list = Gtk.ListBox()
        self._list.add_css_class("navigation-sidebar")
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.connect("row-selected", self._on_row_selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(self._list)
        toolbar.set_content(scroll)
        return toolbar

    def _menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append(t("export_json"), "win.export-json")
        menu.append(t("export_text"), "win.export-text")
        menu.append(t("about"), "win.about")
        menu.append(t("quit"), "win.quit")
        self._install_actions()
        return menu

    def _install_actions(self) -> None:
        def add(name: str, callback: Callable) -> None:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        add("export-json", lambda *_: self._export("json"))
        add("export-text", lambda *_: self._export("text"))
        add("about", lambda *_: self._about())
        add("quit", lambda *_: self.get_application().quit())
        self.get_application().set_accels_for_action("win.quit", ["<Ctrl>q"])
        self.get_application().set_accels_for_action("win.export-json", ["<Ctrl>e"])

        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *_: self._reload(full=True))
        self.add_action(refresh)
        self.get_application().set_accels_for_action("win.refresh", ["F5"])

    def _build_content(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self._stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        show_btn = Gtk.Button.new_from_icon_name("sidebar-show-symbolic")
        show_btn.set_tooltip_text(t("drives"))
        show_btn.connect(
            "clicked",
            lambda *_: self._split.set_show_sidebar(not self._split.get_show_sidebar()),
        )
        self._split.bind_property(
            "collapsed",
            show_btn,
            "visible",
            GObject.BindingFlags.SYNC_CREATE,
        )
        header.pack_start(show_btn)
        toolbar.add_top_bar(header)

        self._banner = Adw.Banner()
        self._banner.set_revealed(False)

        self._overview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self._smart_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._activity_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for box in (self._overview_box, self._smart_box, self._activity_box):
            box.set_margin_start(20)
            box.set_margin_end(20)
            box.set_margin_top(16)
            box.set_margin_bottom(24)

        def page(child: Gtk.Widget) -> Gtk.Widget:
            clamp = Adw.Clamp(maximum_size=860, tightening_threshold=600)
            clamp.set_child(child)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)
            scroll.set_child(clamp)
            return scroll

        self._stack.add_titled_with_icon(
            page(self._overview_box), "overview", t("overview"), "view-list-symbolic"
        )
        self._stack.add_titled_with_icon(
            page(self._smart_box), "smart", t("smart"), "emblem-system-symbolic"
        )

        act_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        act_wrap.set_margin_start(20)
        act_wrap.set_margin_end(20)
        act_wrap.set_margin_top(16)
        act_wrap.set_margin_bottom(24)
        self._io_read = Gtk.Label(xalign=0)
        self._io_write = Gtk.Label(xalign=0)
        self._io_meta = Gtk.Label(xalign=0)
        self._io_meta.add_css_class("dim-label")
        tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._io_tiles = tiles
        self._chart = IoChart()
        hint = Gtk.Label(label=t("activity_hint"), wrap=True, xalign=0)
        hint.add_css_class("dim-label")
        act_wrap.append(tiles)
        act_wrap.append(self._chart)
        act_wrap.append(hint)
        self._activity_box = act_wrap
        self._stack.add_titled_with_icon(
            page(act_wrap), "activity", t("activity"), "utilities-system-monitor-symbolic"
        )

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self._banner)
        outer.append(self._stack)
        toolbar.set_content(outer)
        return toolbar

    def _on_row_selected(self, _list, row: DriveRow | None) -> None:
        if row is None:
            return
        self._selected = row.drive_name
        self._render_drive()

    def _on_tick(self) -> bool:
        self._ticks += 1
        if self._ticks % 12 == 0:
            self._reload(full=True)
        else:
            self._reload(full=False)
        return True

    def _reload(self, full: bool) -> None:
        selected = self._selected
        if full:
            try:
                self._snapshot = collect()
            except Exception as exc:
                self._banner.set_title(str(exc))
                self._banner.set_revealed(True)
                return
            self._banner.set_revealed(False)
            self._rebuild_list(selected)
        self._render_drive(live_only=not full)

    def _rebuild_list(self, selected: str | None) -> None:
        # Preserve selection
        while True:
            row = self._list.get_row_at_index(0)
            if row is None:
                break
            self._list.remove(row)
        pick = None
        for drive in self._snapshot.get("drives") or []:
            row = DriveRow(drive)
            self._list.append(row)
            if selected and drive["name"] == selected:
                pick = row
            if pick is None:
                pick = row
        if pick is not None:
            self._list.select_row(pick)
        elif not (self._snapshot.get("drives") or []):
            self._selected = None
            self._show_empty()

    def _show_empty(self) -> None:
        _clear(self._overview_box)
        page = Adw.StatusPage(
            icon_name="drive-harddisk-symbolic",
            title=t("no_drives"),
            description=t("no_drives_body"),
        )
        self._overview_box.append(page)
        _clear(self._smart_box)
        _clear(self._io_tiles)

    def _drive(self) -> dict | None:
        if not self._selected:
            drives = self._snapshot.get("drives") or []
            return drives[0] if drives else None
        for d in self._snapshot.get("drives") or []:
            if d["name"] == self._selected:
                return d
        drives = self._snapshot.get("drives") or []
        return drives[0] if drives else None

    def _render_drive(self, live_only: bool = False) -> None:
        drive = self._drive()
        if not drive:
            self._show_empty()
            return
        sample = self._tracker.sample(drive["name"])
        self._update_activity(drive, sample)
        if live_only:
            return
        self._render_overview(drive)
        self._render_smart(drive)
        crit = [
            a
            for a in (drive.get("health") or {}).get("advice") or []
            if a.get("severity") == "critical"
        ]
        if crit:
            self._banner.set_title(crit[0]["text"])
            self._banner.add_css_class("error")
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)

    def _render_overview(self, drive: dict) -> None:
        _clear(self._overview_box)
        health = drive.get("health") or {}
        smart = drive.get("smart") or {}
        grade = health.get("grade") or "unknown"

        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        hero.add_css_class("hero")
        hero.add_css_class("card")
        gauge = HealthGauge()
        gauge.set_health(int(health.get("score") or 0), grade)
        hero.append(gauge)

        textcol = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        textcol.set_valign(Gtk.Align.CENTER)
        textcol.set_hexpand(True)
        badge = Gtk.Label(label=health.get("label") or "", xalign=0)
        badge.add_css_class("health-badge")
        badge.add_css_class(f"grade-{grade}")
        textcol.append(badge)
        sub = Gtk.Label(
            label=f"{t('health_index')}  {health.get('score', 0)} / 100",
            xalign=0,
        )
        sub.add_css_class("dim-label")
        textcol.append(sub)
        model = Gtk.Label(label=drive.get("model") or drive["name"], xalign=0)
        model.add_css_class("title-4")
        textcol.append(model)
        hero.append(textcol)

        tempcol = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tempcol.set_valign(Gtk.Align.CENTER)
        temp = Gtk.Label(label=format_temp(drive.get("temperature_c")))
        temp.add_css_class("temp-value")
        temp.add_css_class(f"grade-{grade}")
        cap = Gtk.Label(label=t("temperature"))
        cap.add_css_class("dim-label")
        warn = smart.get("wctemp")
        extra = []
        wc = kelvin_to_c(warn)
        cc = kelvin_to_c(smart.get("cctemp"))
        if wc:
            extra.append(f"{t('warning_temp')} {wc:.0f} °C")
        if cc:
            extra.append(f"{t('crit_temp')} {cc:.0f} °C")
        tempcol.append(temp)
        tempcol.append(cap)
        if extra:
            lim = Gtk.Label(label=" · ".join(extra), wrap=True)
            lim.add_css_class("caption")
            lim.add_css_class("dim-label")
            tempcol.append(lim)
        hero.append(tempcol)
        self._overview_box.append(hero)

        tiles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        poh = smart.get("power_on_hours")
        tiles.append(
            metric_tile(t("power_on"), format_hours(poh), f"{format_int(poh)} {t('hours_word')}" if poh else None)
        )
        tiles.append(metric_tile(t("power_cycles"), format_int(smart.get("power_cycles"))))
        tiles.append(metric_tile(t("written"), format_bytes(smart.get("total_data_written"))))
        wear = smart.get("percent_used")
        life = None
        if isinstance(wear, int):
            life = f"{t('life_left')} {max(0, 100 - wear)} %"
        end = drive.get("endurance")
        if end:
            life = f"{t('tbw')} {format_bytes(end['rated_bytes'])}"
        tiles.append(
            metric_tile(
                t("wear"),
                format_pct(wear) if wear is not None else "—",
                life,
            )
        )
        self._overview_box.append(tiles)

        ident = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ident.add_css_class("card")
        ident.add_css_class("pad-card")
        head = Gtk.Label(label=t("identity"), xalign=0)
        head.add_css_class("heading")
        ident.append(head)
        media = {
            "nvme": t("nvme"),
            "ssd": t("ssd"),
            "hdd": t("hdd"),
            "usb": t("usb"),
        }.get(drive.get("media"), drive.get("media") or "—")
        spare = smart.get("avail_spare")
        rows = [
            (t("device"), drive.get("path") or "—", False),
            (t("model"), drive.get("model") or "—", True),
            (t("serial"), drive.get("serial") or "—", True),
            (t("firmware"), drive.get("firmware") or "—", False),
            (t("capacity"), format_bytes(drive.get("size")), False),
            (t("interface"), media, False),
            (t("pci"), format_pcie(drive.get("pci")), False),
            (t("nvme_rev"), smart.get("nvme_revision") or "—", False),
            (t("wwn"), drive.get("wwn") or "—", True),
            (t("nqn"), (drive.get("nvme_ctrl") or {}).get("subsysnqn") or smart.get("nqn") or "—", False),
            (t("partition_table"), (drive.get("partition_table") or "—").upper(), False),
            (t("scheduler"), (drive.get("sysfs") or {}).get("scheduler") or "—", False),
            (
                t("sector"),
                f"{(drive.get('sysfs') or {}).get('logical_block_size')} / {(drive.get('sysfs') or {}).get('physical_block_size')}",
                False,
            ),
            (t("cache"), (drive.get("sysfs") or {}).get("write_cache") or "—", False),
            (t("read"), format_bytes(smart.get("total_data_read")), False),
            (t("spare"), format_pct(spare) if spare is not None else "—", False),
            (t("unsafe"), format_int(smart.get("unsafe_shutdowns")), False),
            (t("media_errors"), format_int(smart.get("media_errors")), False),
            (t("selftest"), smart.get("selftest") or "—", False),
        ]
        trim = drive.get("trim") or {}
        if trim.get("supported") and trim.get("timer"):
            rows.append((t("trim"), t("trim_ok"), False))
        elif trim.get("supported"):
            rows.append((t("trim"), t("trim_no_timer"), False))
        else:
            rows.append((t("trim"), t("trim_no"), False))

        def copy(text: str) -> None:
            display = Gdk.Display.get_default()
            if display:
                display.get_clipboard().set(text)
                self._toast.add_toast(Adw.Toast(title=t("copied")))

        grid = Gtk.Grid(column_spacing=28, row_spacing=4)
        grid.set_column_homogeneous(True)
        visible = [(k, v, c) for k, v, c in rows if v not in (None, "", "—")]
        for i, (key, val, can_copy) in enumerate(visible):
            grid.attach(
                info_row(key, str(val), on_copy=copy if can_copy else None),
                i % 2,
                i // 2,
                1,
                1,
            )
        ident.append(grid)

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        layout.add_css_class("card")
        layout.add_css_class("pad-card")
        lh = Gtk.Label(label=t("layout"), xalign=0)
        lh.add_css_class("heading")
        layout.append(lh)
        pmap = PartitionMap()
        pmap.set_partitions(drive.get("partitions") or [], drive.get("size") or 1)
        layout.append(pmap)
        for p in drive.get("partitions") or []:
            if p.get("unallocated"):
                line = f"{t('unallocated')}  {format_bytes(p.get('size'))}"
            else:
                mount = p.get("mountpoint") or "—"
                used = ""
                if p.get("used_pct") is not None:
                    used = f"  ·  {p['used_pct']:.0f}%"
                kind = p.get("fstype") or ""
                if p.get("is_efi"):
                    kind = t("efi")
                if p.get("is_swap"):
                    kind = t("swap")
                line = f"{p.get('name')}  {format_bytes(p.get('size'))}  {kind}  {mount}{used}"
            lab = Gtk.Label(label=line, xalign=0)
            lab.add_css_class("caption")
            lab.add_css_class("dim-label")
            lab.set_selectable(True)
            layout.append(lab)
        self._overview_box.append(layout)

        advice = health.get("advice") or []
        adv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        adv.add_css_class("card")
        adv.add_css_class("pad-card")
        ah = Gtk.Label(label=t("advice"), xalign=0)
        ah.add_css_class("heading")
        adv.append(ah)
        if not advice:
            empty = Gtk.Label(label=t("no_advice"), wrap=True, xalign=0)
            empty.add_css_class("dim-label")
            adv.append(empty)
        else:
            for item in advice:
                adv.append(advice_row(item))
        reasons = health.get("reasons") or []
        if reasons:
            bits = ", ".join(f"{r['text']} −{r['points']}" for r in reasons)
            rlab = Gtk.Label(label=f"{t('reasons')}: {bits}", wrap=True, xalign=0)
            rlab.add_css_class("caption")
            rlab.add_css_class("dim-label")
            adv.append(rlab)
        self._overview_box.append(adv)
        self._overview_box.append(ident)

    def _render_smart(self, drive: dict) -> None:
        _clear(self._smart_box)
        attrs = drive.get("smart_attributes") or []
        head = Gtk.Label(label=t("smart_attrs"), xalign=0)
        head.add_css_class("heading")
        self._smart_box.append(head)
        if not attrs:
            empty = Gtk.Label(label=t("no_smart"), wrap=True, xalign=0)
            empty.add_css_class("dim-label")
            self._smart_box.append(empty)
            return
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("card")
        for attr in attrs:
            card.append(attr_row(attr))
        self._smart_box.append(card)

    def _update_activity(self, drive: dict, sample: dict | None) -> None:
        _clear(self._io_tiles)
        if sample:
            self._io_tiles.append(metric_tile(t("read_rate"), format_rate(sample["read_bps"])))
            self._io_tiles.append(metric_tile(t("write_rate"), format_rate(sample["write_bps"])))
            self._io_tiles.append(
                metric_tile(t("iops"), f"{sample['read_iops'] + sample['write_iops']:.0f}")
            )
            lat = max(sample["read_latency_ms"], sample["write_latency_ms"])
            self._io_tiles.append(metric_tile(t("latency"), f"{lat:.1f} ms"))
            self._io_tiles.append(metric_tile(t("inflight"), f"{sample['inflight']:.0f}"))
        else:
            self._io_tiles.append(metric_tile(t("read_rate"), "…"))
            self._io_tiles.append(metric_tile(t("write_rate"), "…"))
        self._chart.set_points(self._tracker.history.get(drive["name"]) or [])

    def _export(self, kind: str) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_initial_name(
            f"linux-disk-info-{self._snapshot.get('hostname', 'host')}.{ 'json' if kind == 'json' else 'txt'}"
        )

        def done(dlg, result, k=kind) -> None:
            try:
                file = dlg.save_finish(result)
            except GLib.Error:
                return
            if file is None:
                return
            path = file.get_path()
            try:
                if k == "json":
                    data = json.dumps(self._snapshot, ensure_ascii=False, indent=2, default=str)
                else:
                    from .cli import render_text

                    data = render_text(self._snapshot, color=False)
                Path(path).write_text(data, encoding="utf-8")
                self._toast.add_toast(Adw.Toast(title=t("exported")))
            except OSError:
                self._toast.add_toast(Adw.Toast(title=t("export_failed")))

        dialog.save(self, None, done)

    def _about(self) -> None:
        dlg = Adw.AboutDialog()
        dlg.set_application_name(t("app_name"))
        dlg.set_version(__version__)
        dlg.set_developer_name(AUTHOR)
        dlg.set_comments(t("about_comments"))
        dlg.set_license_type(Gtk.License.MIT_X11)
        dlg.set_developers([AUTHOR])
        dlg.set_copyright(f"© 2026 {AUTHOR}")
        dlg.set_website(GITHUB_URL)
        dlg.set_issue_url(f"{GITHUB_URL}/issues")
        dlg.add_acknowledgement_section(
            t("donate"),
            [f"{network}  {address}" for network, address, _url in WALLETS],
        )
        for network, _address, url in WALLETS:
            dlg.add_link(network, url)
        dlg.present(self)


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=__app_id__, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app) -> None:
        _load_css()
        win = self.props.active_window
        if win is None:
            win = MainWindow(self)
        win.present()


def run_gui() -> int:
    Adw.init()
    app = Application()
    return app.run([sys.argv[0]])
