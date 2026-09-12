"""Audible host-unit cadence. Planning is pure; only playback receipts commit."""
import sqlite3
import threading
from contextlib import closing
from pathlib import Path


class SfxCadence:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, units INTEGER NOT NULL, sample TEXT NOT NULL)')
            self.units, self.samples = db.execute("SELECT COALESCE(SUM(units),0),COALESCE(SUM(sample<>''),0) FROM receipts").fetchone()

    def state(self):
        with self.lock:
            return {'heard_units': self.units, 'heard_samples': self.samples}

    def record(self, rows):
        """Commit complete audible rows once; reject invalid inputs atomically."""
        clean = []
        for row in rows:
            identity = row.get('id')
            units = row.get('units', 0)
            sample = row.get('sample', '')
            if (not isinstance(identity, str) or not identity or len(identity) > 200
                    or type(units) is not int or units not in (0, 1)
                    or not isinstance(sample, str) or len(sample) > 200):
                raise ValueError('invalid cadence receipt')
            clean.append((identity, units, sample))
        added = []
        with self.lock, closing(sqlite3.connect(self.path)) as db:
            units_added = samples_added = 0
            for identity, units, sample in clean:
                if db.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?)', (identity, units, sample)).rowcount:
                    added.append(identity)
                    units_added += units
                    samples_added += bool(sample)
            db.commit()
            self.units += units_added
            self.samples += samples_added
        return added


def due_after(count, interval):
    """The next successfully scheduled host unit completes this interval."""
    return bool(interval > 0 and (int(count) + 1) % int(interval) == 0)
