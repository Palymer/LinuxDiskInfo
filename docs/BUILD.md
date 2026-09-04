# Сборка бинарников

Бинарник собирается в каталог (`onedir`) через [PyInstaller](https://pyinstaller.org/). Внутри — Python и код приложения. **GTK 4 и libadwaita** на целевой машине должны быть установлены отдельно: это системные библиотеки, в архив они не входят.

Репозиторий: [Palymer/LinuxDiskInfo](https://github.com/Palymer/LinuxDiskInfo).

## Что получается

Архив `dist/linuxdiskinfo-<версия>-linux-<arch>.tar.gz`:

- `linuxdiskinfo` — исполняемый файл
- `linuxdiskinfo.sh` — обёртка, которая запускает бинарник из своего каталога
- `README.md`, `LICENSE`
- `share/applications/linuxdiskinfo.desktop`
- `share/icons/hicolor/scalable/apps/linuxdiskinfo.svg`

Сборка идёт на **Ubuntu 24.04**, поэтому запускать архив разумно на Ubuntu 24.04 / Debian 13 и новее (тот же класс glibc и libadwaita).

На машине, где запускаете бинарник:

```bash
sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 libgtk-4-1 libadwaita-1-0
```

## Локально

Зависимости сборки (Debian/Ubuntu):

```bash
sudo apt install python3 python3-venv python3-pip python3-gi python3-gi-cairo \
  gir1.2-gtk-4.0 gir1.2-adw-1 binutils
```

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pyinstaller pyinstaller-hooks-contrib
bash scripts/build-binary.sh
```

`--system-site-packages` нужен, чтобы взять модуль `gi` из дистрибутива. Иначе PyInstaller не найдёт typelib GTK/Adwaita.

Проверка:

```bash
./dist/linuxdiskinfo/linuxdiskinfo --version
./dist/linuxdiskinfo/linuxdiskinfo --cli
```

Спека: [`packaging/linuxdiskinfo.spec`](../packaging/linuxdiskinfo.spec).

## GitHub Actions

Workflow [`.github/workflows/build.yml`](../.github/workflows/build.yml):

| Событие | Действие |
| --- | --- |
| `push` в `main` / `master`, `pull_request`, `workflow_dispatch` | Сборка и артефакт `linuxdiskinfo-linux-x86_64` |
| тег `v*` (например `v1.0.1`) | То же плюс вложение архива в GitHub Release |

Образ: `ubuntu-24.04`.

Скачать артефакт: вкладка Actions у нужного прогона → `linuxdiskinfo-linux-x86_64`.

Новый релиз:

```bash
git tag v1.0.1
git push origin v1.0.1
```

Тег `v1.0.0` уже использован.

## Ограничения

- Это не AppImage: бинарник завязан на glibc и GTK сборочного образа Ubuntu 24.04.
- Windows и macOS не поддерживаются: нужны Linux sysfs и UDisks2.
- В CI проверяются `--cli` и `--version`. GUI там не запускается — нет графической сессии.
