#!/usr/bin/env python3
"""[pinelink-radio] The camera's radio is a setting, not a constant.

Operator 2026-09-29 swapped in a Netgear A6210 (MT7612U, 2x2) for range. The
supervisor had the TP-Link T2U Plus's interface and USB vendor hard-coded.
Both are now read from data/pinelink_radio.json when it exists:
    {"iface": "wlx94a67e766943", "vendor": "0846"}
and fall back to the old values when it does not, so reverting is deleting
one file (or writing the old pair back) and restarting pinelink.service.

usage: edit_pinelink_radio.py --check|--apply <tools/pinelink.py>
exit 0 ready, 2 already applied, 1 anchor missing
"""
import sys
from pathlib import Path

MARK = "[pinelink-radio]"
A1 = 'SPARE_IF = "wlx984827b6b478"\n'
N1 = ('SPARE_IF = "wlx984827b6b478"\n'
      '# [pinelink-radio] data/pinelink_radio.json names the radio when it exists\n'
      '# ({"iface": ..., "vendor": ...}); the constants are the fallback.\n'
      'def _pinelink_radio() -> dict:\n'
      '    try:\n'
      '        import json as _json\n'
      '        got = _json.loads((Path(__file__).resolve().parent.parent / "data" / "pinelink_radio.json").read_text())\n'
      '        return got if isinstance(got, dict) else {}\n'
      '    except Exception:  # noqa: BLE001\n'
      '        return {}\n'
      '_RADIO_CFG = _pinelink_radio()\n'
      'SPARE_IF = str(_RADIO_CFG.get("iface") or SPARE_IF)\n')
A2 = 'ADAPTER_VENDOR = "2357"\n'
N2 = ('ADAPTER_VENDOR = "2357"\n'
      'ADAPTER_VENDOR = str(_RADIO_CFG.get("vendor") or ADAPTER_VENDOR)   # [pinelink-radio]\n')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    p = Path(sys.argv[2])
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if MARK in text:
        print(f"{MARK} already applied"); return 2
    for a in (A1, A2):
        if text.count(a) != 1:
            print(f"{MARK} anchor missing ({text.count(a)}): {a.strip()}"); return 1
    if "from pathlib import Path" not in text and "import pathlib" not in text:
        print(f"{MARK} pinelink.py has no Path import"); return 1
    if mode != "--apply":
        print(f"{MARK} ready"); return 0
    text = text.replace(A1, N1, 1).replace(A2, N2, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))
    print(f"{MARK} applied"); return 2


if __name__ == "__main__":
    sys.exit(main())
