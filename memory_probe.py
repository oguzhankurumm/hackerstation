"""
Memory probe — stdlib-only RAM/CPU pressure detection.

Zero hard dependencies (psutil used opportunistically if installed).
Works on macOS (Apple Silicon via vm_stat + sysctl) and Linux (/proc/meminfo).
On a constrained 8GB box every dependency loaded is RAM stolen from inference,
so we deliberately avoid importing heavy libraries.
"""

import os
import platform
import subprocess
import time
from dataclasses import dataclass

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


@dataclass
class MemorySnapshot:
    total_bytes: int
    available_bytes: int
    used_bytes: int
    percent_used: float
    source: str

    @property
    def available_gb(self) -> float:
        return self.available_bytes / (1024 ** 3)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024 ** 3)


def _probe_psutil() -> MemorySnapshot | None:
    if not _HAS_PSUTIL:
        return None
    vm = psutil.virtual_memory()
    return MemorySnapshot(
        total_bytes=vm.total,
        available_bytes=vm.available,
        used_bytes=vm.used,
        percent_used=vm.percent,
        source="psutil",
    )


def _probe_macos() -> MemorySnapshot | None:
    """vm_stat reports pages; multiply by page size from sysctl."""
    if platform.system() != "Darwin":
        return None
    try:
        page_size = int(subprocess.check_output(
            ["sysctl", "-n", "hw.pagesize"], timeout=2
        ).decode().strip())
        total = int(subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], timeout=2
        ).decode().strip())
        vm_out = subprocess.check_output(["vm_stat"], timeout=2).decode()

        pages = {}
        for line in vm_out.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            val = val.strip().rstrip(".")
            if val.isdigit():
                pages[key.strip()] = int(val) * page_size

        # "Available" on macOS ≈ free + inactive (inactive can be reclaimed)
        free = pages.get("Pages free", 0)
        inactive = pages.get("Pages inactive", 0)
        speculative = pages.get("Pages speculative", 0)
        available = free + inactive + speculative

        used = total - available
        percent = (used / total) * 100 if total else 0.0
        return MemorySnapshot(
            total_bytes=total,
            available_bytes=available,
            used_bytes=used,
            percent_used=round(percent, 2),
            source="vm_stat",
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError):
        return None


def _probe_linux() -> MemorySnapshot | None:
    if platform.system() != "Linux":
        return None
    try:
        info = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                key, _, val = line.partition(":")
                parts = val.strip().split()
                if parts and parts[0].isdigit():
                    info[key.strip()] = int(parts[0]) * 1024  # kB → bytes
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        used = total - available
        percent = (used / total) * 100 if total else 0.0
        return MemorySnapshot(
            total_bytes=total,
            available_bytes=available,
            used_bytes=used,
            percent_used=round(percent, 2),
            source="/proc/meminfo",
        )
    except (OSError, ValueError):
        return None


def snapshot() -> MemorySnapshot | None:
    """Return current memory snapshot, or None if no probe works."""
    for probe in (_probe_psutil, _probe_macos, _probe_linux):
        snap = probe()
        if snap is not None:
            return snap
    return None


def ollama_running() -> bool:
    """Quick stdlib-only liveness check on Ollama."""
    from urllib.request import urlopen
    from urllib.error import URLError
    try:
        with urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return r.status == 200
    except (URLError, TimeoutError, OSError):
        return False


if __name__ == "__main__":
    s = snapshot()
    if s is None:
        print("memory probe unavailable on this platform")
    else:
        print(f"source={s.source}  total={s.total_gb:.2f}GB  "
              f"available={s.available_gb:.2f}GB  used={s.percent_used}%")
    print(f"ollama_alive={ollama_running()}")
