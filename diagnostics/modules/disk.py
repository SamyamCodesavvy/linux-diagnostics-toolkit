from __future__ import annotations

import logging
import os
from dataclasses import dataclass
 
from diagnostics.utils.proc_reader import read_lines
 
logger = logging.getLogger(__name__)
 
MOUNTS_FILE = '/proc/mounts'

PSEUDO_FS_TYPES = frozenset({
    'proc', 'sysfs', 'cgroup', 'cgroup2', 'devpts', 'devtmpfs',
    'securityfs', 'pstore', 'debugfs', 'tracefs', 'mqueue',
    'hugetlbfs', 'bpf', 'autofs', 'binfmt_misc', 'configfs',
    'fusectl', 'rpc_pipefs',
})
 
@dataclass
class PartitionInfo: 
    device: str
    mount_point: str
    fs_type: str
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent_used: float
    inodes_total: int
    inodes_used: int
    inodes_free: int
    inodes_percent_used: float

def read_mounts() -> list[tuple[str, str, str]]:
    mounts = []
    for line in read_lines(MOUNTS_FILE):
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount_point, fs_type = parts[0], parts[1], parts[2]
        mounts.append((device, mount_point, fs_type))
    return mounts

def _percent(used: int, available: int) -> float:
    denominator = used + available
    if denominator == 0:
        return 0.0
    return round((used / denominator) * 100, 1)
 
 
def get_partition_usage(mount_point: str) -> PartitionInfo | None:
    try:
        stats = os.statvfs(mount_point)
    except OSError as exc:
        logger.warning('Could not stat %s: %s', mount_point, exc)
        return None
 
    block_size = stats.f_frsize
    total_bytes = stats.f_blocks * block_size
    free_bytes = stats.f_bfree * block_size 
    avail_bytes = stats.f_bavail * block_size   
    used_bytes = total_bytes - free_bytes
    inodes_total = stats.f_files
    inodes_free = stats.f_ffree
    inodes_avail = stats.f_favail
    inodes_used = inodes_total - inodes_free

    return PartitionInfo(
        device='',  # filled in by the caller, which already has it
        mount_point=mount_point,
        fs_type='',
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        available_bytes=avail_bytes,
        percent_used=_percent(used_bytes, avail_bytes),
        inodes_total=inodes_total,
        inodes_used=inodes_used,
        inodes_free=inodes_free,
        inodes_percent_used=_percent(inodes_used, inodes_avail),
    )

def collect_disk_info() -> list[PartitionInfo]:
    results: list[PartitionInfo] = []
    seen_mount_points: set[str] = set()
 
    for device, mount_point, fs_type in read_mounts():
        if fs_type in PSEUDO_FS_TYPES:
            continue
        if mount_point in seen_mount_points:
            continue
        seen_mount_points.add(mount_point)
 
        info = get_partition_usage(mount_point)
        if info is None:
            continue
        info.device = device
        info.fs_type = fs_type
        results.append(info)
 
    return results

if __name__ == '__main__':
    from diagnostics.utils.formatting import bytes_to_human as human
 
    logging.basicConfig(level=logging.INFO)
    for part in collect_disk_info():
        print(f'{part.device:<14} {part.mount_point:<16} {part.fs_type:<6} '
              f'{human(part.used_bytes):>9} / {human(part.total_bytes):<9} '
              f'({part.percent_used}%)  '
              f'inodes: {part.inodes_used}/{part.inodes_total} '
              f'({part.inodes_percent_used}%)')