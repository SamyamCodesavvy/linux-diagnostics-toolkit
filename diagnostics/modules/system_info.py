from __future__ import annotations

import logging
import socket
import platform
import datetime as dt
from dataclasses import dataclass, field

import psutil
from diagnostics.utils.proc_reader import read_file, parse_key_value_file

logger = logging.getLogger(__name__)

UPTIME_FILE = '/proc/uptime'
OS_RELEASE_FILE = '/etc/os-release'

@dataclass
class SystemInfo:
    hostname: str
    kernel_version: str
    distro_name: str
    distro_version: str
    architecture: str
    uptime_seconds: float
    boot_time: dt.datetime
    logged_in_users: list[str] = field(default_factory=list)

def get_hostname() -> str:
    return socket.gethostname()

def get_kernel_version() -> str:
    return read_file('/proc/version')

def get_distro_info() -> tuple[str, str]:
    try:
        data = parse_key_value_file(OS_RELEASE_FILE)
    except FileNotFoundError:
        logger.warning('%s not found; distro info unavailable', OS_RELEASE_FILE)
        return 'Unknown', 'Unknown'
    name = data.get('PRETTY_NAME', data.get('NAME', 'Unknown'))
    version = data.get('VERSION_ID', 'Unknown')
    return name, version
 
def get_architecture() -> str:
    return platform.machine()
 
 
def get_uptime_seconds() -> float:
    contents = read_file(UPTIME_FILE)
    uptime_str, _idle_str = contents.split()
    return float(uptime_str)
 
 
def get_boot_time() -> dt.datetime:
    uptime_seconds = get_uptime_seconds()
    return dt.datetime.now() - dt.timedelta(seconds=uptime_seconds)

def get_logged_in_users() -> list[str]:
    try:
        return sorted({session.name for session in psutil.users()})
    except Exception:
        logger.exception('Failed to read logged-in users')
        return []
 
def collect_system_info() -> SystemInfo:
    distro_name, distro_version = get_distro_info()
    return SystemInfo(
        hostname=get_hostname(),
        kernel_version=get_kernel_version(),
        distro_name=distro_name,
        distro_version=distro_version,
        architecture=get_architecture(),
        uptime_seconds=get_uptime_seconds(),
        boot_time=get_boot_time(),
        logged_in_users=get_logged_in_users(),
    )
 
def format_uptime(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f'{days}d')
    if hours or days:
        parts.append(f'{hours}h')
    parts.append(f'{minutes}m')
    return ' '.join(parts)
 
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    info = collect_system_info()
    print(f'Hostname        : {info.hostname}')
    print(f'Kernel          : {info.kernel_version}')
    print(f'Distribution    : {info.distro_name} {info.distro_version}')
    print(f'Architecture    : {info.architecture}')
    print(f'Uptime          : {format_uptime(info.uptime_seconds)}')
    print(f"Boot time       : {info.boot_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Logged-in users : {', '.join(info.logged_in_users) or 'none'}")