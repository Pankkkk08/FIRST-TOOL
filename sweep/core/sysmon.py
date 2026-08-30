"""Live system resource snapshot (CPU, memory, disk).

Uses `psutil` if it's installed; degrades gracefully to "unavailable" data
rather than crashing the whole app if it isn't, since this is the one
optional third-party dependency in the project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when psutil is absent
    psutil = None
    PSUTIL_AVAILABLE = False


@dataclass
class DiskInfo:
    mountpoint: str
    total: int
    used: int
    percent: float


@dataclass
class Snapshot:
    available: bool
    cpu_percent: float = 0.0
    mem_total: int = 0
    mem_used: int = 0
    mem_percent: float = 0.0
    disks: list[DiskInfo] = field(default_factory=list)
    error: str = ""


def get_snapshot() -> Snapshot:
    """Take one point-in-time reading of CPU/memory/disk usage."""
    if not PSUTIL_AVAILABLE:
        return Snapshot(available=False, error="psutil is not installed")

    try:
        cpu = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        disks: list[DiskInfo] = []
        seen_devices: set[str] = set()
        for part in psutil.disk_partitions(all=False):
            if part.device in seen_devices:
                continue
            seen_devices.add(part.device)
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            disks.append(
                DiskInfo(
                    mountpoint=part.mountpoint,
                    total=usage.total,
                    used=usage.used,
                    percent=usage.percent,
                )
            )
        return Snapshot(
            available=True,
            cpu_percent=cpu,
            mem_total=vm.total,
            mem_used=vm.used,
            mem_percent=vm.percent,
            disks=disks,
        )
    except Exception as exc:  # pragma: no cover - defensive, platform dependent
        return Snapshot(available=False, error=str(exc))
