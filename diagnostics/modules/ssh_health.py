from __future__ import annotations
 
import logging
from dataclasses import dataclass, field
 
import paramiko

from dotenv import load_dotenv
import os

load_dotenv()
logger = logging.getLogger(__name__)
 
DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 10  
 
@dataclass
class RemoteHealthInfo:
 
    hostname: str
    uptime_seconds: float | None = None
    load_average: tuple[float, float, float] | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    errors: list[str] = field(default_factory=list)

def connect(
    hostname: str,
    username: str,
    key_filename: str | None = None,
    password: str | None = None,
    port: int = DEFAULT_PORT,
    timeout: int = DEFAULT_TIMEOUT,
    auto_add_unknown_hosts: bool = False,
) -> paramiko.SSHClient:
    
    client = paramiko.SSHClient()
    client.load_system_host_keys()
 
    if auto_add_unknown_hosts:
        logger.warning(
            'Auto-trusting unknown host keys for %s — this disables '
            'protection against man-in-the-middle attacks',
            hostname,        
            )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
 
    client.connect(
    hostname=hostname,
    port=port,
    username=username,
    key_filename=key_filename,
    password=password,
    passphrase=os.getenv("SSH_KEY_PASSPHRASE"),
    )
    return client

def run_remote_command(
    client: paramiko.SSHClient, command: str, timeout: int = DEFAULT_TIMEOUT,
) -> tuple[str, str, int]:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdout_text = stdout.read().decode(errors='replace')
    stderr_text = stderr.read().decode(errors='replace')
    exit_status = stdout.channel.recv_exit_status()
    return stdout_text, stderr_text, exit_status

def parse_remote_uptime(output: str) -> float:
    return float(output.split()[0])
 
 
def parse_remote_loadavg(output: str) -> tuple[float, float, float]:
    one, five, fifteen = output.split()[:3]
    return float(one), float(five), float(fifteen)

def parse_remote_memory(output: str) -> tuple[int, int]:
    for line in output.splitlines():
        if line.startswith('Mem:'):
            fields = line.split()
            total = int(fields[1])
            available = int(fields[6]) if len(fields) > 6 else int(fields[3])
            return total, total - available
    raise ValueError('Mem: line not found in free output')

def parse_remote_disk(output: str) -> tuple[int, int]:

    lines = output.strip().splitlines()
    if len(lines) < 2:
        raise ValueError('unexpected df output')
    fields = lines[1].split()
    total = int(fields[1])
    used = int(fields[2])
    return total, used

def collect_remote_health(
    hostname: str,
    username: str,
    key_filename: str | None = None,
    password: str | None = None,
    port: int = DEFAULT_PORT,
    auto_add_unknown_hosts: bool = False,
) -> RemoteHealthInfo:

    info = RemoteHealthInfo(hostname=hostname)
 
    try:
        client = connect(
            hostname, username, key_filename, password, port,
            auto_add_unknown_hosts=auto_add_unknown_hosts,
        )
    except paramiko.AuthenticationException:
        info.errors.append('Authentication failed — check username/key')
        return info
    except (paramiko.SSHException, OSError) as exc:
        info.errors.append(f'Could not connect: {exc}')
        return info
 
    try:
        commands = {
            'uptime': ('cat /proc/uptime', parse_remote_uptime),
            'loadavg': ('cat /proc/loadavg', parse_remote_loadavg),
            'memory': ('free -b', parse_remote_memory),
            'disk': ('df -B1 /', parse_remote_disk),
        }
        parsed = {}
        for key, (command, parser) in commands.items():
            try:
                stdout_text, stderr_text, exit_status = run_remote_command(
                    client, command,
                )
                if exit_status != 0:
                    raise RuntimeError(
                        f'exit code {exit_status}: {stderr_text.strip()}'
                    )
                parsed[key] = parser(stdout_text)
            except Exception as exc: 
                info.errors.append(f'{key} check failed: {exc}')
 
        if 'uptime' in parsed:
            info.uptime_seconds = parsed['uptime']
        if 'loadavg' in parsed:
            info.load_average = parsed['loadavg']
        if 'memory' in parsed:
            info.memory_total_bytes, info.memory_used_bytes = parsed['memory']
        if 'disk' in parsed:
            info.disk_total_bytes, info.disk_used_bytes = parsed['disk']
    finally:
        client.close()
 
    return info

if __name__ == '__main__':
    import os
 
    logging.basicConfig(level=logging.INFO)

    # put SSH credentials in a .env file
    hostname = os.getenv("SSH_HOST")   
    username = os.getenv("SSH_USERNAME")  
    port = int(os.getenv("SSH_PORT", "22"))
    key_filename = os.getenv("SSH_KEY") or None
    password = os.getenv("SSH_PASSWORD") or None

    result = collect_remote_health(
    hostname=hostname,
    username=username,
    key_filename=key_filename,
    password=password,
    port=port,
)
    print(f'Host          : {result.hostname}')
    print(f'Uptime (s)    : {result.uptime_seconds}')
    print(f'Load average  : {result.load_average}')
    print(f'Memory        : {result.memory_used_bytes} / {result.memory_total_bytes} bytes')
    print(f'Disk          : {result.disk_used_bytes} / {result.disk_total_bytes} bytes')
    if result.errors:
        print('Errors:')
        for err in result.errors:
            print(f'  - {err}')