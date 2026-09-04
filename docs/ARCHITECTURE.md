# Архитектура

Linux Disk Info — пакет Python 3 без pip-зависимостей в runtime: системные **PyGObject**, **GTK 4** и **libadwaita**. Репозиторий: [Palymer/LinuxDiskInfo](https://github.com/Palymer/LinuxDiskInfo).

## Модули

| Модуль | Роль |
| --- | --- |
| `linuxdiskinfo/collector.py` | Снимок дисков: UDisks2 D-Bus, sysfs, `/proc/diskstats`, `statvfs`, `fstrim.timer` |
| `linuxdiskinfo/health.py` | Индекс 0–100, грейд, рекомендации |
| `linuxdiskinfo/app.py` | Окно GTK4 / Adwaita |
| `linuxdiskinfo/widgets.py` | Кольцо здоровья, карта разделов, график I/O |
| `linuxdiskinfo/cli.py` | Текст и JSON |
| `linuxdiskinfo/i18n.py` | Строки `en` / `ru` |
| `linuxdiskinfo/formatters.py` | Размеры, часы, PCIe, температура |
| `linuxdiskinfo/paths.py` | Ресурсы в исходниках и в сборке PyInstaller |

Точка входа: `python3 -m linuxdiskinfo` → [`linuxdiskinfo/__main__.py`](../linuxdiskinfo/__main__.py).

## Поток данных

```
UDisks2 (Drive, Block, NVMe.Controller / Drive.Ata)
        + sysfs (/sys/block, hwmon, PCI link)
        + /proc/diskstats + statvfs
                ↓
        collect()  →  dict  →  health.attach()
                ↓
        GUI / CLI / JSON / файл экспорта
```

Физический диск — объект `org.freedesktop.UDisks2.Drive` плюс block-устройство без partition. Optical, `loop`, `ram`, `zram`, `fd`, `sr`, `dm-`, `md` пропускаются.

NVMe SMART: `SmartUpdate` + `SmartGetAttributes` (spare, percent used, байты чтения/записи, циклы, unsafe shutdowns, media errors, пороги температуры в кельвинах).

ATA SMART: нормализованные атрибуты, pretty-value; отказ, если value ≤ threshold (при ненулевом пороге).

Температура: hwmon (`temp*_input` в милли°C), иначе кельвины из UDisks.

## Индекс здоровья

Старт — 100. Штрафы суммируются, затем ограничение 0–100:

- флаги NVMe critical warning: −45
- overall SMART failing: −40
- media errors: до −40
- spare ≤ порога: −35; spare ≤ 2× порога: −15
- износ ≥ 95 / 80 / 50 %: −30 / −18 / −8
- температура ≥ crit / warn / 70 °C / 60 °C: −25 / −15 / −10 / −4
- unsafe shutdowns ≥ 50 % циклов: −8; ≥ 20 %: −4
- failing ATA-атрибут: −12 каждый
- reallocated / pending sectors: до −25

Заполнение `/` ≥ 85 % попадает в рекомендации, балл не меняет. PCIe ниже максимума — информационный совет. Нет SMART — грейд `unknown`.

## GUI

`Adw.Application` (`org.linuxdiskinfo.LinuxDiskInfo`). Сайдбар — список дисков, контент — `Adw.ViewStack` (обзор / SMART / активность).

- I/O: `IoTracker` по дельтам `/proc/diskstats`, таймер 1 с.
- Полный `collect()` каждые 12 с.
- CSS: `linuxdiskinfo/style.css`.

## Бинарная сборка

PyInstaller `onedir` и venv с `--system-site-packages`, чтобы заморозить дистрибутивный `gi`. Подробности: [BUILD.md](BUILD.md).
