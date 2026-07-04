from __future__ import annotations
 
import fcntl
import logging
import os
import pwd
import socket
import struct
from dataclasses import dataclass
 
from diagnostics.utils.proc_reader import read_file, read_lines
 
logger = logging.getLogger(__name__)
 
SYS_CLASS_NET = '/sys/class/net'
PROC_NET_DEV = '/proc/net/dev'
PROC_NET_ROUTE = '/proc/net/route'
PROC_NET_TCP = '/proc/net/tcp'
PROC_NET_TCP6 = '/proc/net/tcp6'
PROC_NET_ARP = '/proc/net/arp'
RESOLV_CONF = '/etc/resolv.conf'
 
SIOCGIFADDR = 0x8915 

TCP_STATES = {
    '01': 'ESTABLISHED', '02': 'SYN_SENT',   '03': 'SYN_RECV',
    '04': 'FIN_WAIT1',   '05': 'FIN_WAIT2',   '06': 'TIME_WAIT',
    '07': 'CLOSE',       '08': 'CLOSE_WAIT',  '09': 'LAST_ACK',
    '0A': 'LISTEN',      '0B': 'CLOSING',
}
 
@dataclass
class InterfaceInfo: 
    name: str
    ip_address: str | None
    state: str
    rx_bytes: int
    tx_bytes: int

@dataclass
class ConnectionInfo: 
    protocol: str
    local_address: str
    local_port: int
    remote_address: str
    remote_port: int
    state: str
    owner: str
 
 
@dataclass
class NetworkInfo: 
    interfaces: list[InterfaceInfo]
    default_gateway: str | None
    dns_servers: list[str]
    connections: list[ConnectionInfo]
    listening_ports: list[ConnectionInfo]


def _hex_to_ip(hex_str: str) -> str:

    packed = struct.pack('<L', int(hex_str, 16))
    return socket.inet_ntoa(packed)
 
 
# def _decode_address(hex_ip_port: str) -> tuple[str, int]:
#     ip_hex, port_hex = hex_ip_port.split(':')
#     return _hex_to_ip(ip_hex), int(port_hex, 16)

def _decode_address(hex_ip_port: str) -> tuple[str, int]:
    ip_hex, port_hex = hex_ip_port.split(':')

    if len(ip_hex) == 8:
        # IPv4
        packed = struct.pack("<L", int(ip_hex, 16))
        ip = socket.inet_ntoa(packed)

    elif len(ip_hex) == 32:
        # IPv6
        packed = bytes.fromhex(ip_hex)

        # Linux stores IPv6 words little-endian in /proc/net/tcp6
        packed = b"".join(
            packed[i:i+4][::-1]
            for i in range(0, 16, 4)
        )

        ip = socket.inet_ntop(socket.AF_INET6, packed)

    else:
        ip = "unknown"

    return ip, int(port_hex, 16)

def _resolve_username(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)
    
def list_interfaces() -> list[str]:
    return sorted(os.listdir(SYS_CLASS_NET))
 
 
def get_interface_state(name: str) -> str:
    try:
        return read_file(f'{SYS_CLASS_NET}/{name}/operstate').strip()
    except FileNotFoundError:
        return 'unknown'
    

def get_interface_ip(name: str) -> str | None:
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        request = struct.pack('256s', name[:15].encode('utf-8'))
        response = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, request)
        return socket.inet_ntoa(response[20:24])
    except OSError:
        return None
    finally:
        sock.close()

def read_interface_stats() -> dict[str, tuple[int, int]]:

    stats: dict[str, tuple[int, int]] = {}
    lines = read_lines(PROC_NET_DEV)[2:] 
    for line in lines:
        name, _, rest = line.partition(':')
        fields = rest.split()
        if len(fields) < 9:
            continue
        rx_bytes = int(fields[0])
        tx_bytes = int(fields[8])
        stats[name.strip()] = (rx_bytes, tx_bytes)
    return stats

def collect_interfaces() -> list[InterfaceInfo]:
    stats = read_interface_stats()
    interfaces = []
    for name in list_interfaces():
        rx_bytes, tx_bytes = stats.get(name, (0, 0))
        interfaces.append(InterfaceInfo(
            name=name,
            ip_address=get_interface_ip(name),
            state=get_interface_state(name),
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
        ))
    return interfaces
 
 
def get_default_gateway() -> str | None:
    try:
        lines = read_lines(PROC_NET_ROUTE)[1:]  
    except FileNotFoundError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        destination, gateway = fields[1], fields[2]
        if destination == '00000000':
            return _hex_to_ip(gateway)
    return None

def get_dns_servers() -> list[str]:
    servers = []
    try:
        for line in read_lines(RESOLV_CONF):
            if line.strip().startswith('nameserver'):
                parts = line.split()
                if len(parts) >= 2:
                    servers.append(parts[1])
    except FileNotFoundError:
        logger.warning('%s not found', RESOLV_CONF)
    return servers


def parse_proc_net_tcp(path: str, protocol: str) -> list[ConnectionInfo]:
   
    try:
        lines = read_lines(path)[1:]  
    except FileNotFoundError:
        return []
 
    connections = []
    for line in lines:
        fields = line.split()
        if len(fields) < 8:
            continue
        local_ip, local_port = _decode_address(fields[1])
        remote_ip, remote_port = _decode_address(fields[2])
        state = TCP_STATES.get(fields[3], fields[3])
        uid = int(fields[7])
        connections.append(ConnectionInfo(
            protocol=protocol,
            local_address=local_ip,
            local_port=local_port,
            remote_address=remote_ip,
            remote_port=remote_port,
            state=state,
            owner=_resolve_username(uid),
        ))
    return connections


def collect_connections() -> list[ConnectionInfo]:
    return (
        parse_proc_net_tcp(PROC_NET_TCP, 'tcp') +
        parse_proc_net_tcp(PROC_NET_TCP6, 'tcp6')
    )
 
 
def get_listening_ports(
    connections: list[ConnectionInfo],
) -> list[ConnectionInfo]:
    return [c for c in connections if c.state == 'LISTEN']
 
def read_arp_table() -> list[dict[str, str]]:
    
    entries = []
    try:
        lines = read_lines(PROC_NET_ARP)[1:]  
    except FileNotFoundError:
        return entries
    for line in lines:
        fields = line.split()
        if len(fields) < 6:
            continue
        entries.append({
            'ip_address': fields[0],
            'mac_address': fields[3],
            'device': fields[5],
        })
    return entries

def collect_network_info() -> NetworkInfo:
    connections = collect_connections()
    return NetworkInfo(
        interfaces=collect_interfaces(),
        default_gateway=get_default_gateway(),
        dns_servers=get_dns_servers(),
        connections=connections,
        listening_ports=get_listening_ports(connections),
    )

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    info = collect_network_info()
 
    for iface in info.interfaces:
        print(f'{iface.name:<8} {iface.state:<6} {iface.ip_address or "(no address)":<15} '
              f'rx={iface.rx_bytes} tx={iface.tx_bytes}')
 
    print(f'Default gateway : {info.default_gateway}')
    print(f'DNS servers     : {", ".join(info.dns_servers)}')
 
    print('Listening ports:')
    for conn in info.listening_ports:
        print(f'  {conn.protocol:<5} {conn.local_address}:{conn.local_port:<6} '
              f'owner={conn.owner}')