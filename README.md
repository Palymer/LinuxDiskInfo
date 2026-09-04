# Linux Disk Info

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Build](https://github.com/Palymer/LinuxDiskInfo/actions/workflows/build.yml/badge.svg)](https://github.com/Palymer/LinuxDiskInfo/actions/workflows/build.yml)
[![GitHub](https://img.shields.io/badge/GitHub-Palymer%2FLinuxDiskInfo-181717?logo=github)](https://github.com/Palymer/LinuxDiskInfo)

Я написал аналог [CrystalDiskInfo](https://crystalmark.info/) для Linux: здоровье диска, SMART, температура, износ NAND, карта разделов и живой I/O.

Репозиторий: [github.com/Palymer/LinuxDiskInfo](https://github.com/Palymer/LinuxDiskInfo)

В отличие от CrystalDiskInfo программа считает не только «Good / Caution / Bad», а **индекс здоровья 0–100** с объяснением штрафов, даёт рекомендации (место на SSD, небезопасные выключения, TRIM), показывает PCIe-линк и активность без отдельного бенчмарка.

SMART читается через **UDisks2**, без root.

## Документация

- [Использование](docs/USAGE.md) — GUI, CLI, JSON, экспорт
- [Сборка бинарников](docs/BUILD.md) — локально и GitHub Actions
- [Архитектура](docs/ARCHITECTURE.md) — коллектор, оценка здоровья, интерфейс

## Возможности

- NVMe и SATA (ATA SMART) через D-Bus UDisks2
- Температура из hwmon, пороги warning/critical
- Износ, spare, TBW, сколько записано и прочитано, циклы питания
- Карта GPT-разделов с заполнением файловых систем
- Живой график чтения/записи из `/proc/diskstats`
- Рекомендации: место на SSD, TRIM (`fstrim.timer`), unsafe shutdowns, просадка PCIe
- GUI на GTK4 + libadwaita и CLI / JSON
- Интерфейс на русском и английском (`LANG` или `--lang ru|en`)

## Требования

- Linux (Debian 13 / Ubuntu 24.04 или новее: GTK 4 и libadwaita ≥ 1.5)
- Python 3.11+
- `udisks2` (обычно уже стоит)

```bash
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 udisks2
```

## Запуск из исходников

```bash
git clone https://github.com/Palymer/LinuxDiskInfo.git
cd LinuxDiskInfo
python3 -m linuxdiskinfo          # окно, если есть графическая сессия
python3 -m linuxdiskinfo --cli    # текстовый отчёт
python3 -m linuxdiskinfo --json   # JSON
python3 -m linuxdiskinfo --watch  # обновление CLI раз в секунду
python3 -m linuxdiskinfo --lang en --cli
```

Установка:

```bash
pipx install .
# или
pip install --user .
linuxdiskinfo
```

Файл `.desktop`: [`data/linuxdiskinfo.desktop`](data/linuxdiskinfo.desktop).

## Готовый бинарник

Сборка Linux x86_64 идёт в GitHub Actions: [Build binaries](https://github.com/Palymer/LinuxDiskInfo/actions/workflows/build.yml). Артефакт — `linuxdiskinfo-*-linux-x86_64.tar.gz`. Тег `v*` публикует тот же архив в GitHub Release.

Как собрать у себя: [docs/BUILD.md](docs/BUILD.md).

```bash
tar -xzf linuxdiskinfo-*-linux-x86_64.tar.gz
./linuxdiskinfo-*/linuxdiskinfo --cli
./linuxdiskinfo-*/linuxdiskinfo --gui
```

На целевой машине всё равно нужны GTK 4 и libadwaita (`gir1.2-gtk-4.0 gir1.2-adw-1`): в архиве упакован Python и код, системные GTK-библиотеки — нет.

## Почему не GNOME Disks

GNOME Disks умеет SMART, но заточен под разметку. Linux Disk Info заточен под **состояние носителя**: индекс, износ, советы и активность — в одном окне, как CrystalDiskInfo, с учётом Linux (NVMe, TRIM, точки монтирования).

## Поддержать

Если программа вам помогла — можете поблагодарить меня переводом на любой из кошельков:

| Сеть | Адрес |
| --- | --- |
| **TRC-20** (Tron) | `TVcEqim8yjAzhPXjpu5DfzKrrgS3Fx9upY` |
| **BEP-20** (BNB Smart Chain) | `0x327f2F24EC9931f1431bA6059bb3173C11B208AA` |
| **ERC-20** (Ethereum) | `0x327f2F24EC9931f1431bA6059bb3173C11B208AA` |

Те же адреса есть в окне **О программе**.

## Лицензия

[MIT](LICENSE) © Palymer
