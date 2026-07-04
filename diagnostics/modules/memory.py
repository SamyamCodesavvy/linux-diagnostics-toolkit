from __future__ import annotations
 
import logging
from dataclasses import dataclass
 
from diagnostics.utils.proc_reader import read_lines
from diagnostics.utils.formatting import kb_to_bytes

logger = logging.getLogger(__name__)

MEMINFO_FILE = '/proc/meminfo'

@dataclass
class MemoryInfo:
    total: int
    free: int
    available: int
    used: int
    buffers: int
    cached: int
    swap_total: int
    swap_free: int
    swap_used: int

@property
def percent_used(self) -> float:
    if self.total == 0:
        return 0.0
    return round((self.used / self.total) * 100, 1)
 
@property
def swap_percent_used(self) -> float:
    if self.swap_total == 0:
        return 0.0
    return round((self.swap_used / self.swap_total) * 100, 1)

def read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    for line in read_lines(MEMINFO_FILE):
        if ':' not in line:
            continue
        label, _, rest = line.partition(':')
        value_str = rest.strip().split(' ')[0]
        try:
            result[label.strip()] = int(value_str)
        except ValueError:
            logger.warning('Could not parse meminfo line: %s', line)
    return result

def get_memory_info() -> MemoryInfo:
    raw = read_meminfo()
 
    total_kb = raw.get('MemTotal', 0)
    free_kb = raw.get('MemFree', 0)
    buffers_kb = raw.get('Buffers', 0)
    cached_kb = raw.get('Cached', 0)
    swap_total_kb = raw.get('SwapTotal', 0)
    swap_free_kb = raw.get('SwapFree', 0)
 

    if 'MemAvailable' in raw:
        available_kb = raw['MemAvailable']
    else:
        logger.warning(
            'MemAvailable missing; falling back to an approximation'
        )
        available_kb = free_kb + buffers_kb + cached_kb
 
    used_kb = total_kb - available_kb
    swap_used_kb = swap_total_kb - swap_free_kb
 
    return MemoryInfo(
        total=kb_to_bytes(total_kb),
        free=kb_to_bytes(free_kb),
        available=kb_to_bytes(available_kb),
        used=kb_to_bytes(used_kb),
        buffers=kb_to_bytes(buffers_kb),
        cached=kb_to_bytes(cached_kb),
        swap_total=kb_to_bytes(swap_total_kb),
        swap_free=kb_to_bytes(swap_free_kb),
        swap_used=kb_to_bytes(swap_used_kb),
    )

if __name__ == '__main__':
    from diagnostics.utils.formatting import bytes_to_human as human
 
    logging.basicConfig(level=logging.INFO)
    mem = get_memory_info()
    print(f'Total      : {human(mem.total)}')
    print(f'Used       : {human(mem.used)} ({mem.percent_used}%)')
    print(f'Available  : {human(mem.available)}')
    print(f'Free       : {human(mem.free)}')
    print(f'Buffers    : {human(mem.buffers)}')
    print(f'Cached     : {human(mem.cached)}')
    print(
        f'Swap       : {human(mem.swap_used)} / {human(mem.swap_total)} '
        f'({mem.swap_percent_used}%)'
    )