from __future__ import annotations
 
import logging
import subprocess
from dataclasses import dataclass
 
from diagnostics.modules.network import collect_connections, get_listening_ports

logger = logging.getLogger(__name__)
 
# Unit names are distribution-specific.FOLLowing match Debian/Kali.
MONITORED_SERVICES = {
    'ssh':        {'unit': 'ssh.service',        'expected_port': 22},
    'apache':     {'unit': 'apache2.service',     'expected_port': 80},
    'postgresql': {'unit': 'postgresql.service',  'expected_port': 5432},
    'docker':     {'unit': 'docker.service',      'expected_port': None},
}

@dataclass
class ServiceInfo: 
    name: str
    unit: str
    installed: bool
    active_state: str
    sub_state: str
    enabled_state: str
    main_pid: int | None
    port_listening: bool | None  # None when the service has no fixed port

def _run_systemctl(*args: str) -> tuple[str, int]:

    result = subprocess.run(
        ['systemctl', *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip(), result.returncode

def get_unit_properties(unit: str) -> dict[str, str]:
    stdout, _ = _run_systemctl(
        'show', unit,
        '--property=LoadState,ActiveState,SubState,MainPID',
    )
    properties: dict[str, str] = {}
    for line in stdout.splitlines():
        key, _, value = line.partition('=')
        if key:
            properties[key] = value
    return properties
 
 
def get_enabled_state(unit: str) -> str:
    
    stdout, returncode = _run_systemctl('is-enabled', unit)
    if stdout:
        return stdout
    return 'not-found' if returncode != 0 else 'unknown'

def is_port_listening(port: int) -> bool:
    
    listening = get_listening_ports(collect_connections())
    return any(conn.local_port == port for conn in listening)
 
 
def collect_service_info(name: str, config: dict) -> ServiceInfo:
    unit = config['unit']
    expected_port = config['expected_port']
 
    properties = get_unit_properties(unit)
    load_state = properties.get('LoadState', 'not-found')
    installed = load_state == 'loaded'
 
    main_pid_str = properties.get('MainPID', '0')
    main_pid = int(main_pid_str) if main_pid_str not in ('0', '') else None
    port_listening = is_port_listening(expected_port) if expected_port else None
 
    return ServiceInfo(
        name=name,
        unit=unit,
        installed=installed,
        active_state=properties.get('ActiveState', 'unknown'),
        sub_state=properties.get('SubState', 'unknown'),
        enabled_state=get_enabled_state(unit),
        main_pid=main_pid,
        port_listening=port_listening,
    )

def collect_all_services(
    services: dict | None = None,
) -> list[ServiceInfo]:
    
    services = services if services is not None else MONITORED_SERVICES
    return [
        collect_service_info(name, config)
        for name, config in services.items()
    ]
 
 
if __name__ == '__main__':
    
    logging.basicConfig(level=logging.INFO)
    for service in collect_all_services():
        if not service.installed:
            print(f'{service.name:<12} not installed')
            continue
        port_status = (
            'n/a' if service.port_listening is None
            else ('listening' if service.port_listening else 'NOT listening')
        )
        print(f'{service.name:<12} {service.active_state:<10} ({service.sub_state:<8}) '
              f'enabled={service.enabled_state:<10} pid={service.main_pid} '
              f'port={port_status}')
