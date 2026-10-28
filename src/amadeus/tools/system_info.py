from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .registry import Tool


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _cpu_model() -> str:
    for line in _read_text("/proc/cpuinfo").splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or "неизвестно"


def _memory() -> tuple[str, str]:
    total = available = ""
    for line in _read_text("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            total = line.split(":", 1)[1].strip()
        elif line.startswith("MemAvailable:"):
            available = line.split(":", 1)[1].strip()
    return total, available


def _uptime() -> str:
    raw = _read_text("/proc/uptime").split()
    if not raw:
        return "неизвестно"
    try:
        seconds = int(float(raw[0]))
    except (ValueError, IndexError):
        return "неизвестно"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    parts.append(f"{minutes} мин")
    return " ".join(parts)


def _gpu_lines() -> list[str]:
    executable = shutil.which("lspci")
    if executable is None:
        return []
    try:
        process = subprocess.run(
            [executable],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = [
        line.strip()
        for line in process.stdout.splitlines()
        if any(token in line for token in ("VGA", "3D controller", "Display"))
    ]
    return lines[:4]


def collect_system_info(arguments: dict[str, object] | None = None) -> str:
    total, available = _memory()
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    try:
        usage = shutil.disk_usage(Path.home())
        disk = (
            f"{usage.used / 1024**3:.1f} ГБ занято из "
            f"{usage.total / 1024**3:.1f} ГБ в {Path.home()}"
        )
    except OSError:
        disk = "недоступно"
    lines = [
        f"ОС: {platform.platform()}",
        f"Ядро: {platform.release()} ({platform.machine()})",
        f"CPU: {_cpu_model()}",
        f"Потоков CPU: {os.cpu_count() or 'неизвестно'}",
        f"Память: всего {total}; доступно {available}",
        f"Uptime: {_uptime()}",
        f"Load average: {load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}",
        f"Диск: {disk}",
    ]
    gpu = _gpu_lines()
    if gpu:
        lines.append("GPU:")
        lines.extend(f"  {line}" for line in gpu)
    return "\n".join(lines)


def system_info_tool() -> Tool:
    return Tool(
        name="system_info",
        description="Показать сведения о системе: ОС, CPU, память, диск, GPU.",
        risk="low",
        handler=collect_system_info,
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )
