# Linux Disk Info PyInstaller spec — GTK4 + libadwaita, console+GUI.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "linuxdiskinfo" / "style.css"), "linuxdiskinfo"),
    (str(ROOT / "data"), "data"),
]
binaries = []
hiddenimports = [
    "gi",
    "gi.repository.Gtk",
    "gi.repository.Adw",
    "gi.repository.Gdk",
    "gi.repository.Gio",
    "gi.repository.GLib",
    "gi.repository.GObject",
    "gi.repository.Gsk",
    "gi.repository.Graphene",
    "gi.repository.Pango",
    "gi.repository.GdkPixbuf",
    "gi.repository.cairo",
    "cairo",
]

for pkg in ("gi", "cairo"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        datas += collect_data_files(pkg, include_py_files=False)

a = Analysis(
    [str(ROOT / "linuxdiskinfo.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="linuxdiskinfo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(ROOT / "data" / "icons" / "hicolor" / "scalable" / "apps" / "linuxdiskinfo.svg"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="linuxdiskinfo",
)
