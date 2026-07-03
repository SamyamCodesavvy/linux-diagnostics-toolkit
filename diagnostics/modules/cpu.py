from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass, field
 
from diagnostics.utils.proc_reader import read_lines
 
logger = logging.getLogger(__name__)
 
STAT_FILE = '/proc/stat'
CPUINFO_FILE = '/proc/cpuinfo'
LOADAVG_FILE = '/proc/loadavg'
 
_STAT_FIELDS = (
    'user', 'nice', 'system', 'idle', 'iowait',
    'irq', 'softirq', 'steal', 'guest', 'guest_nice',
)
 
@dataclass
class CPUTimes:
    user: int = 0
    nice: int = 0
    system: int = 0
    idle: int = 0
    iowait: int = 0
    irq: int = 0
    softirq: int = 0
    steal: int = 0
    guest: int = 0
    guest_nice: int = 0
 
    @property
    def idle_total(self) -> int:
        return self.idle + self.iowait
 
    @property
    def total(self) -> int:
        return (
            self.user + self.nice + self.system + self.idle +
            self.iowait + self.irq + self.softirq + self.steal +
            self.guest + self.guest_nice
        )

@dataclass
class CPUInfo: 
    overall_usage_percent: float
    per_core_usage_percent: dict[str, float] = field(default_factory=dict)
    load_average_1min: float = 0.0
    load_average_5min: float = 0.0
    load_average_15min: float = 0.0
    model_name: str = 'Unknown'
    frequency_mhz: float = 0.0
    logical_core_count: int = 0
 
def _parse_stat_line(line: str) -> CPUTimes:
    parts = line.split()
    values = [int(v) for v in parts[1:]]
    padded = values + [0] * (len(_STAT_FIELDS) - len(values))
    return CPUTimes(**dict(zip(_STAT_FIELDS, padded)))

def get_all_cpu_times() -> dict[str, CPUTimes]:
    result: dict[str, CPUTimes] = {}
    for line in read_lines(STAT_FILE):
        if not line.startswith('cpu'):
            break
        label, _, _rest = line.partition(' ')
        result[label] = _parse_stat_line(line)
    return result

def calculate_usage_percent(start: CPUTimes, end: CPUTimes) -> float:
    total_delta = end.total - start.total
    if total_delta <= 0:
        return 0.0
    idle_delta = end.idle_total - start.idle_total
    busy_delta = total_delta - idle_delta
    return round((busy_delta / total_delta) * 100, 1)

def get_cpu_usage(interval: float = 1.0) -> float:
    start = get_all_cpu_times()['cpu']
    time.sleep(interval)
    end = get_all_cpu_times()['cpu']
    return calculate_usage_percent(start, end)

def get_per_core_usage(interval: float = 1.0) -> dict[str, float]:
    start = get_all_cpu_times()
    time.sleep(interval)
    end = get_all_cpu_times()
    return {
        label: calculate_usage_percent(start[label], end[label])
        for label in start
        if label != 'cpu'
    }

def get_load_average() -> tuple[float, float, float]:
    line = read_lines(LOADAVG_FILE)[0]
    one, five, fifteen = line.split()[:3]
    return float(one), float(five), float(fifteen)

def get_cpu_model() -> str:
    for line in read_lines(CPUINFO_FILE):
        if line.startswith('model name'):
            _, _, value = line.partition(':')
            return value.strip()
    logger.warning('model name not found in %s', CPUINFO_FILE)
    return 'Unknown'

def get_cpu_frequency_mhz() -> float:
    for line in read_lines(CPUINFO_FILE):
        if line.startswith('cpu MHz'):
            _, _, value = line.partition(':')
            return float(value.strip())
    logger.warning('cpu MHz not found in %s', CPUINFO_FILE)
    return 0.0

def get_logical_core_count() -> int:
    return os.cpu_count() or 1
 
 
def collect_cpu_info(interval: float = 1.0) -> CPUInfo:
    start_all = get_all_cpu_times()
    time.sleep(interval)
    end_all = get_all_cpu_times()
 
    overall = calculate_usage_percent(start_all['cpu'], end_all['cpu'])
    per_core = {
        label: calculate_usage_percent(start_all[label], end_all[label])
        for label in start_all
        if label != 'cpu'
    }
    load_1, load_5, load_15 = get_load_average()
    return CPUInfo(
        overall_usage_percent=overall,
        per_core_usage_percent=per_core,
        load_average_1min=load_1,
        load_average_5min=load_5,
        load_average_15min=load_15,
        model_name=get_cpu_model(),
        frequency_mhz=get_cpu_frequency_mhz(),
        logical_core_count=get_logical_core_count(),
    )

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    info = collect_cpu_info(interval=1.0)
    print(f'Model            : {info.model_name}')
    print(f'Logical cores    : {info.logical_core_count}')
    print(f'Frequency        : {info.frequency_mhz:.0f} MHz')
    print(f'Overall usage    : {info.overall_usage_percent}%')
    for core, pct in sorted(info.per_core_usage_percent.items()):
        print(f'  {core:<6} : {pct}%')
    print(
        f'Load average     : {info.load_average_1min} '
        f'{info.load_average_5min} {info.load_average_15min} (1m, 5m, 15m)'
    )