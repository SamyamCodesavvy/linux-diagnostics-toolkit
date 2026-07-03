import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def read_file(path: str) -> str:
    file_path = Path(path)
    try:
        return file_path.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        logger.error('File not found: %s', path)
        raise
    except PermissionError:
        logger.error('Permission denied reading: %s', path)
        raise

def read_lines(path: str) -> list[str]:
    file_path = Path(path)
    try:
        return file_path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        logger.error('File not found: %s', path)
        raise
    except PermissionError:
        logger.error('Permission denied reading: %s', path)
        raise

def parse_key_value_file(path: str, delimiter: str = '=') -> dict[str, str]:
    result: dict[str, str] = {}
    for line in read_lines(path):
        line = line.strip()
        if not line or line.startswith('#') or delimiter not in line:
            continue
        key, _, value = line.partition(delimiter)
        result[key.strip()] = value.strip().strip('"')
    return result