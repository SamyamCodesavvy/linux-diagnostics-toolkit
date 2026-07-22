"""
Phase 9: Log Monitoring module. (Patched for rsyslog-less Kali installs.)

Provides rotation-aware live tailing of plain-text log files (with
failed-login and keyword detection), plus reading and following the
systemd journal via journalctl.

WHY THIS PATCH EXISTS
----------------------
Recent Kali Linux releases do not install rsyslog by default. Logging
goes straight to journald, so /var/log/auth.log and /var/log/syslog
simply never exist unless rsyslog is installed and enabled:

    sudo apt install rsyslog
    sudo systemctl enable --now rsyslog

If you would rather NOT install rsyslog, this version detects that
AUTH_LOG is missing and automatically falls back to following the
journal instead, running the exact same parse_log_line() detection
logic against each journal entry's MESSAGE field. Either path produces
the same LogEvent objects.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Iterator

logger = logging.getLogger(__name__)

AUTH_LOG = '/var/log/auth.log'

DEFAULT_KEYWORDS = ('error', 'failed', 'denied', 'unauthorized', 'critical')

FAILED_LOGIN_PATTERN = re.compile(
    r'Failed password for (?:invalid user )?(?P<user>\S+) '
    r'from (?P<ip>[0-9a-fA-F.:]+)'
)


@dataclass
class LogEvent:
    """One parsed line from a monitored log source."""

    source: str
    raw_line: str
    is_failed_login: bool = False
    username: str | None = None
    source_ip: str | None = None
    matched_keyword: str | None = None


def parse_log_line(source: str, line: str, keywords=DEFAULT_KEYWORDS) -> LogEvent:
    """Inspect one raw log line for a failed-login pattern and any
    configured keyword. Works identically whether the line came from a
    plain-text file or a journald MESSAGE field.
    """
    event = LogEvent(source=source, raw_line=line)

    match = FAILED_LOGIN_PATTERN.search(line)
    if match:
        event.is_failed_login = True
        event.username = match.group('user')
        event.source_ip = match.group('ip')

    lowered = line.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            event.matched_keyword = keyword
            break

    return event


class LogTailer:
    """Follows a plain-text log file, correctly surviving log rotation.

    Only used when the target file actually exists. See auth_log_available().
    """

    def __init__(self, path: str):
        self.path = path
        self._file = None
        self._inode: int | None = None
        self._partial_line = ''
        self._open_at_end()

    def _open_at_end(self) -> None:
        """Open the file fresh and seek to its current end, matching
        `tail -f`'s default behavior of not dumping full history.
        """
        self._file = open(self.path, 'r', errors='replace')
        self._file.seek(0, os.SEEK_END)
        self._inode = os.fstat(self._file.fileno()).st_ino

    def _reopen_if_rotated(self) -> None:
        """Detect a rotation via inode change (rename+create) or a
        shrunk file size (copytruncate), and reopen if either happened.
        """
        try:
            current_inode = os.stat(self.path).st_ino
        except FileNotFoundError:
            # Mid-rotation: the old file may already be renamed away
            # and the new one not yet created. Try again next poll.
            return

        if current_inode != self._inode:
            logger.info('Detected log rotation for %s', self.path)
            self._file.close()
            self._file = open(self.path, 'r', errors='replace')
            self._inode = current_inode
            return

        if os.fstat(self._file.fileno()).st_size < self._file.tell():
            logger.info('Detected truncation (copytruncate) for %s', self.path)
            self._file.seek(0)

    def poll_new_lines(self) -> list[str]:
        """Return every complete new line appended since the last
        call, handling rotation first and buffering any incomplete
        trailing line for next time.
        """
        self._reopen_if_rotated()
        chunk = self._partial_line + self._file.read()
        if not chunk:
            return []

        lines = chunk.split('\n')
        # The last element is either an empty string (chunk ended
        # cleanly on a newline) or an incomplete trailing line.
        self._partial_line = lines.pop()
        return lines

    def close(self) -> None:
        self._file.close()


def auth_log_available(path: str = AUTH_LOG) -> bool:
    """Return True if the classic plain-text auth log actually exists
    on this machine.

    On Kali installs without rsyslog, this is False by default -- that
    is expected, not an error. See the module docstring.
    """
    return os.path.exists(path)


def _tail_file_and_scan(
    path: str, keywords, interval: float, max_iterations: int | None,
) -> Iterator[LogEvent]:
    """Tail a real, on-disk log file. Internal helper for tail_and_scan()."""
    tailer = LogTailer(path)
    iterations = 0
    try:
        while max_iterations is None or iterations < max_iterations:
            for line in tailer.poll_new_lines():
                yield parse_log_line(path, line, keywords)
            time.sleep(interval)
            iterations += 1
    finally:
        tailer.close()


def _tail_journal_and_scan(
    keywords, max_iterations: int | None,
) -> Iterator[LogEvent]:
    """Follow the full journal and run the same detection logic against
    every entry's MESSAGE field. Used automatically when AUTH_LOG does
    not exist. Internal helper for tail_and_scan().
    """
    count = 0
    for entry in follow_journal():
        message = entry.get('MESSAGE', '')
        # journald represents non-UTF-8 messages as a list of byte
        # values instead of a string; normalize that rare case too.
        if isinstance(message, list):
            message = ''.join(chr(b) for b in message)
        yield parse_log_line('journald', message, keywords)
        count += 1
        if max_iterations is not None and count >= max_iterations:
            break


def tail_and_scan(
    path: str = AUTH_LOG,
    keywords=DEFAULT_KEYWORDS,
    interval: float = 1.0,
    max_iterations: int | None = None,
) -> Iterator[LogEvent]:
    """Continuously watch for auth-related events, yielding a LogEvent
    for each one.

    Automatically uses `path` if it exists (classic rsyslog setup), or
    falls back to following the systemd journal directly if it does
    not (the default on modern, rsyslog-less Kali installs). Pass
    max_iterations to stop after a fixed number of polls/entries
    (used for demos and tests); leave it None to run forever.
    """
    if auth_log_available(path):
        yield from _tail_file_and_scan(path, keywords, interval, max_iterations)
    else:
        logger.info(
            '%s not found -- this is normal on Kali installs without '
            'rsyslog. Falling back to the systemd journal instead.',
            path,
        )
        yield from _tail_journal_and_scan(keywords, max_iterations)


def read_journal_since(
    since: str = '1 hour ago',
    unit: str | None = None,
    priority: str | None = None,
) -> list[dict]:
    """Return recent journal entries as a list of dicts, using
    `journalctl --output=json`. Each line of output is one independent
    JSON object, not one big JSON array, so each is parsed separately.
    """
    command = ['journalctl', '--output=json', '--no-pager', '--since', since]
    if unit:
        command += ['-u', unit]
    if priority:
        command += ['-p', priority]

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    entries = []
    for line in result.stdout.splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning('Could not parse journal line: %s', line)
    return entries


def follow_journal(unit: str | None = None) -> Iterator[dict]:
    """Follow the journal live, yielding one dict per new entry as it
    is written. Uses Popen, not run(), because `journalctl -f` never
    exits on its own.
    """
    command = ['journalctl', '-f', '--output=json', '--no-pager']
    if unit:
        command += ['-u', unit]

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, text=True, bufsize=1,
    )
    try:
        for line in process.stdout:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning('Could not parse journal line: %s', line)
    finally:
        process.terminate()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    source = AUTH_LOG if auth_log_available() else 'systemd journal (fallback)'
    print(f'Watching {source} for 10 events/polls (Ctrl+C to stop earlier)...')
    print('Tip: in another terminal, run `ssh invaliduser@localhost` to test detection.')

    try:
        for event in tail_and_scan(max_iterations=10):
            if event.is_failed_login:
                print(f'FAILED LOGIN: user={event.username} ip={event.source_ip}')
            elif event.matched_keyword:
                print(f'KEYWORD [{event.matched_keyword}]: {event.raw_line}')
    except PermissionError:
        print(f'Cannot read {AUTH_LOG} -- try running with sudo or joining the adm group.')