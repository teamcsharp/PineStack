"""A noisy camera must not block the recorder's stderr pipe."""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('pinelink_stderr_test', Path(__file__).resolve().parents[1] / 'tools/pinelink.py')
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


class NoisyRecorder(unittest.TestCase):
    def test_diagnostics_larger_than_pipe_capacity_do_not_block_video(self):
        proc = subprocess.Popen([sys.executable, '-c',
            "import sys;sys.stderr.write('decode warning '+('x'*200)+'\\n'*1);"
            "sys.stderr.write(('damaged frame '+('x'*200)+'\\n')*10000);"
            "sys.stderr.write('final camera error\\n');sys.stderr.flush();print('frame delivered')"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            reader, tail = pl.drain_stderr(proc)
            proc.wait(timeout=10)
            reader.join(timeout=2)
            self.assertFalse(reader.is_alive())
            self.assertEqual('frame delivered', proc.stdout.read().strip())
            self.assertEqual(2000, len(tail))
            self.assertEqual('final camera error\n', tail[-1])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()


if __name__ == '__main__':
    unittest.main()
