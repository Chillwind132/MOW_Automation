"""Bounded detection of newly logged native synchronization failures."""
from pathlib import Path
import re


class SyncLogMonitor:
    PATTERN = re.compile(rb'(?:Desync detected on quant|Out Of Sync at quant) (\d+)')
    MAX_READ = 64 * 1024

    def __init__(self, path, simulation_ticks):
        self.path = Path(path)
        self.started_ticks = simulation_ticks
        self.pending = b''
        self.status = 'observing_new_log_entries'
        try:
            stat = self.path.stat()
            self.identity = stat.st_ino
            self.offset = stat.st_size
        except OSError:
            self.identity = None
            self.offset = 0
            self.status = 'log_unavailable_at_start'

    def poll(self, simulation_ticks):
        if self.identity is None:
            return None
        try:
            with self.path.open('rb') as stream:
                stat = self.path.stat()
                if stat.st_ino != self.identity or stat.st_size < self.offset:
                    self.identity = None
                    self.status = 'log_replaced_or_truncated; association_unproven'
                    return None
                stream.seek(self.offset)
                data = stream.read(self.MAX_READ)
        except OSError:
            self.status = 'log_read_unavailable'
            return None
        start = self.offset - len(self.pending)
        self.offset += len(data)
        combined = self.pending + data
        complete, _, self.pending = combined.rpartition(b'\n')
        if b'\n' not in combined:
            self.pending = combined[-4096:]
            return None
        self.pending = self.pending[-4096:]
        for match in self.PATTERN.finditer(complete):
            quant = int(match[1])
            if self.started_ticks <= quant <= simulation_ticks:
                self.status = 'native_desync_observed'
                return dict(source='new_native_game_log_entry', nativeQuant=quant,
                            observedSimulationTicks=simulation_ticks, logPath=str(self.path),
                            logOffset=start + match.start(), text=match[0].decode('ascii'))
        self.status = 'observing_new_log_entries'
        return None
