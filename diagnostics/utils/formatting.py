from __future__ import annotations
 
 
def bytes_to_human(num_bytes: float, unit_base: int = 1024) -> str:
    value = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if abs(value) < unit_base:
            return f'{value:.1f} {unit}' if unit != 'B' else f'{value:.0f} {unit}'
        value /= unit_base
    return f'{value:.1f} EB'
 
 
def kb_to_bytes(kb: int) -> int:
    return kb * 1024