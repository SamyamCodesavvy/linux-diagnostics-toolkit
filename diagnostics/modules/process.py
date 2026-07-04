from __future__ import annotations
 
import logging
import os
import pwd
import signal
import time
from dataclasses import dataclass
 
from diagnostics.modules.memory import get_memory_info
from diagnostics.utils.proc_reader import read_file, read_lines
 
logger = logging.getLogger(__name__)
PROC_DIR = '/proc'
CLK_TCK = os.sysconf('SC_CLK_TCK') 
PROCESS_STATES = {
    'R': 'Running',
    'S': 'Sleeping',
    'D': 'Uninterruptible sleep',
    'T': 'Stopped',
    't': 'Tracing stop',
    'Z': 'Zombie',
    'X': 'Dead',
}

@dataclass
class ProcessInfo:
 
    pid: int
    ppid: int
    user: str
    state: str
    state_description: str
    cpu_percent: float
    memory_percent: float
    command: str
 
 
def list_pids() -> list[int]:
    pids = []
    for name in os.listdir(PROC_DIR):
        if name.isdigit():
            pids.append(int(name))
    return pids

def _read_stat_fields(pid: int) -> list[str] | None:
    try:
        content = read_file(f'{PROC_DIR}/{pid}/stat')
    except (FileNotFoundError, ProcessLookupError):
        return None
    last_paren = content.rfind(')')
    if last_paren == -1:
        return None
    return content[last_paren + 2:].split()

def get_process_state_and_ppid(pid: int) -> tuple[str, int] | None:
    
    fields = _read_stat_fields(pid)
    if fields is None:
        return None
    state = fields[0]           
    ppid = int(fields[1])    
    return state, ppid

def get_process_cpu_time(pid: int) -> float | None:
    fields = _read_stat_fields(pid)
    if fields is None:
        return None
    utime = int(fields[11])     
    stime = int(fields[12])    
    return (utime + stime) / CLK_TCK
 
 
def get_process_memory_percent(pid: int, total_bytes: int) -> float:
    try:
        lines = read_lines(f'{PROC_DIR}/{pid}/status')
    except (FileNotFoundError, ProcessLookupError):
        return 0.0
 
    for line in lines:
        if line.startswith('VmRSS:'):
            rss_kb = int(line.split()[1])
            rss_bytes = rss_kb * 1024
            return round((rss_bytes / total_bytes) * 100, 1) if total_bytes else 0.0
    return 0.0

def get_process_owner(pid: int) -> str:
    try:
        lines = read_lines(f'{PROC_DIR}/{pid}/status')
    except (FileNotFoundError, ProcessLookupError):
        return '?'
 
    for line in lines:
        if line.startswith('Uid:'):
            uid = int(line.split()[1])  
            try:
                return pwd.getpwuid(uid).pw_name
            except KeyError:
                return str(uid)
    return '?'

def get_process_command(pid: int) -> str:
    try:
        raw = read_file(f'{PROC_DIR}/{pid}/cmdline')
    except (FileNotFoundError, ProcessLookupError):
        return '[unknown]'
 
    if raw.strip('\x00'):
        return raw.replace('\x00', ' ').strip()
 
    try:
        comm = read_file(f'{PROC_DIR}/{pid}/comm').strip()
        return f'[{comm}]'
    except (FileNotFoundError, ProcessLookupError):
        return '[unknown]'
 
 
def collect_processes(interval: float = 0.5) -> list[ProcessInfo]:
    total_ram = get_memory_info().total
    pids = list_pids()
    start_times: dict[int, float] = {}
    for pid in pids:
        cpu_time = get_process_cpu_time(pid)
        if cpu_time is not None:
            start_times[pid] = cpu_time
 
    start_wall = time.time()
    time.sleep(interval)
    elapsed = time.time() - start_wall
 
    results: list[ProcessInfo] = []
    for pid in pids:
        if pid not in start_times:
            continue 
 
        end_cpu_time = get_process_cpu_time(pid)
        state_info = get_process_state_and_ppid(pid)
        if end_cpu_time is None or state_info is None:
            continue 
 
        state, ppid = state_info
        cpu_percent = round(
            ((end_cpu_time - start_times[pid]) / elapsed) * 100, 1
        ) if elapsed > 0 else 0.0
 
        results.append(ProcessInfo(
            pid=pid,
            ppid=ppid,
            user=get_process_owner(pid),
            state=state,
            state_description=PROCESS_STATES.get(state, 'Unknown'),
            cpu_percent=max(cpu_percent, 0.0),
            memory_percent=get_process_memory_percent(pid, total_ram),
            command=get_process_command(pid),
        ))
    return results

def sort_processes(
    processes: list[ProcessInfo], by: str = 'cpu_percent', descending: bool = True
    ) -> list[ProcessInfo]:
    return sorted(processes, key=lambda proc: getattr(proc, by), reverse=descending)

def filter_processes(
    processes: list[ProcessInfo],
    name_contains: str | None = None,
    user: str | None = None,
    min_cpu_percent: float | None = None,
    ) -> list[ProcessInfo]:
    
    result = processes
    if name_contains is not None:
        result = [p for p in result if name_contains.lower() in p.command.lower()]
    if user is not None:
        result = [p for p in result if p.user == user]
    if min_cpu_percent is not None:
        result = [p for p in result if p.cpu_percent >= min_cpu_percent]
    return result

def kill_process(pid: int, sig: signal.Signals = signal.SIGTERM) -> bool:
    
    try:
        os.kill(pid, sig)
        logger.info('Sent %s to PID %d', sig.name, pid)
        return True
    except ProcessLookupError:
        logger.warning('PID %d no longer exists', pid)
        return False
    except PermissionError:
        logger.warning('Not permitted to signal PID %d', pid)
        return False
 
 
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    procs = sort_processes(collect_processes(interval=0.5), by='cpu_percent')
    print(f'{"PID":>7} {"PPID":>7} {"USER":<10} {"%CPU":>6} {"%MEM":>6} {"S":<2} COMMAND')
    for proc in procs[:15]:
        print(f'{proc.pid:>7} {proc.ppid:>7} {proc.user:<10} '
              f'{proc.cpu_percent:>6} {proc.memory_percent:>6} '
              f'{proc.state:<2} {proc.command[:60]}')