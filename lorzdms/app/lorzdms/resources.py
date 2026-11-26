"""Schutz des Home-Assistant-Betriebs: Last, Speicher, Zeitfenster."""

from __future__ import annotations

import os
import shutil
from datetime import datetime

from .config import Settings


def load_ok(s: Settings) -> tuple[bool, str]:
    try:
        load1, _, _ = os.getloadavg()
    except OSError:
        return True, ""
    cpus = os.cpu_count() or 1
    if load1 / cpus > s.max_load_per_cpu:
        return False, f"Systemlast hoch ({load1:.1f} bei {cpus} CPUs)"
    return True, ""


def disk_ok(s: Settings) -> tuple[bool, str]:
    try:
        free = shutil.disk_usage(s.data_dir).free // (1024 * 1024)
    except OSError:
        return True, ""
    if free < s.min_free_disk_mb:
        return False, f"Wenig freier Speicher ({free} MB)"
    return True, ""


def memory_available_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def in_window(window: str, now: datetime | None = None) -> bool:
    """``"22:00-06:00"`` → True innerhalb des Fensters. Leer = immer."""
    if not window:
        return True
    now = now or datetime.now()
    try:
        a, b = window.split("-")
        ah, am = map(int, a.split(":"))
        bh, bm = map(int, b.split(":"))
    except ValueError:
        return True
    cur = now.hour * 60 + now.minute
    start, end = ah * 60 + am, bh * 60 + bm
    return start <= cur < end if start <= end else cur >= start or cur < end


def can_process(s: Settings, priority: int) -> tuple[bool, str]:
    ok, why = disk_ok(s)
    if not ok:
        return ok, why
    ok, why = load_ok(s)
    if not ok:
        return ok, why
    mem = memory_available_mb()
    if mem is not None and mem < 300:
        return False, f"Wenig freier Arbeitsspeicher ({mem} MB)"
    if priority >= 500 and not in_window(s.processing_window):
        return False, "Außerhalb des Verarbeitungsfensters für Massenimporte"
    return True, ""
