# Использование

Программу можно открыть как окно (GTK4) или вызвать из терминала.

Репозиторий: <https://github.com/Palymer/LinuxDiskInfo>

## Команды

| Команда | Назначение |
| --- | --- |
| `python3 -m linuxdiskinfo` | Окно, если есть `DISPLAY` или Wayland; иначе CLI |
| `python3 -m linuxdiskinfo --gui` | Всегда окно |
| `python3 -m linuxdiskinfo --cli` | Текстовый отчёт в stdout |
| `python3 -m linuxdiskinfo --json` | Полный снимок в JSON |
| `python3 -m linuxdiskinfo --watch` | Обновлять отчёт каждую секунду |
| `python3 -m linuxdiskinfo --watch 2` | Интервал 2 с |
| `python3 -m linuxdiskinfo --lang ru` | Русский интерфейс |
| `python3 -m linuxdiskinfo --lang en` | Английский интерфейс |
| `python3 -m linuxdiskinfo --version` | Версия |

`--gui` нельзя совмещать с `--cli` / `--json` / `--watch`.

Без `--lang` язык берётся из `LC_ALL` / `LANG`.

## Окно

- Слева — список физических дисков (loop, zram и RAM скрыты).
- **Обзор** — индекс здоровья, температура, износ, карта разделов, рекомендации.
- **SMART** — атрибуты NVMe или ATA со статусом OK / внимание / плохо.
- **Активность** — живые скорости, IOPS, задержка, график примерно за 60 с.
- Меню: экспорт JSON или текстового отчёта, о программе.
- `F5` — обновить, `Ctrl+E` — экспорт JSON, `Ctrl+Q` — выход.

SMART читается через UDisks2, sudo не нужен. Если D-Bus недоступен, ошибка показывается в шапке окна.

## CLI

Цвет включается только на TTY. Для скриптов удобнее `--json`.

```bash
python3 -m linuxdiskinfo --cli --lang en
python3 -m linuxdiskinfo --json > report.json
```

## Что означает индекс

Старт — 100. Баллы снимаются за критические флаги NVMe, ошибки носителя, износ, температуру, мало spare, отказ SMART, переназначенные сектора и высокую долю unsafe shutdowns. Заполнение корневой ФС индекс **не снижает**, но попадает в рекомендации.

| Оценка | Баллы |
| --- | --- |
| Excellent | 95–100 |
| Good | 80–94 |
| Caution | 50–79 |
| Bad | 0–49 |

Как считаются штрафы: [ARCHITECTURE.md](ARCHITECTURE.md).
