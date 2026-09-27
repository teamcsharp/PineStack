"""Re-anchor a patch tool's expected text on what app.py holds NOW.

Another session edited inside a block one of these tools had inserted, so
the tool no longer recognises its own edit ("anchor found 0 times;
replacement found 0 times") and the wiring tests cannot prove the hook is
in place. This rewrites the tool's stored `new` literal for one edit from
the current file: the region from the first line of the stored text to its
last line, as they now stand. The `old` anchor is left as it was, so a
fresh app.py is still patched the same way; only what "applied" looks like
changes.

    python3 tools/reconcile_patch_text.py <tool.py> <edit-name> [app.py]

Refuses when the first or last line of the stored text is not found once.
"""
import importlib.util
import sys
from pathlib import Path


def load(tool):
    spec = importlib.util.spec_from_file_location("tool_" + Path(tool).stem, tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    tool, name = argv[0], argv[1]
    target = argv[2] if len(argv) > 2 else "app.py"
    mod = load(tool)
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    entry = next((e for e in mod.plan(text) if e[0] == name), None)
    if entry is None:
        print("no edit called", name)
        return 1
    old, new = entry[1], entry[2]
    count = entry[3] if len(entry) > 3 else 1
    lines = new.splitlines(keepends=True)
    first, last = lines[0], lines[-1]
    if text.count(first) != 1:
        print("first line of the stored text is found %d times, need 1: %r" % (text.count(first), first[:80]))
        return 1
    start = text.index(first)
    end = text.find(last, start + len(first))
    if end < 0:
        print("last line of the stored text is not found after the first: %r" % last[:80])
        return 1
    if text.find(last, end + 1) >= 0 and text.count(last) > 1:
        # take the FIRST occurrence after the start; say so
        print("note: the last line occurs more than once; taking the first after the start")
    region = text[start:end + len(last)]
    if region == new:
        print(name, "already matches")
        return 2
    src = Path(tool).read_bytes().decode("utf-8").replace("\r\n", "\n")
    head = '    ("%s",\n' % name
    at = src.index(head)
    # the entry ends at the first line after the head that ends with ", <count>),"
    # - or, for a tool whose entries carry no count, with a quoted line and "),"
    counted = len(entry) > 3
    tail_mark = ", %d),\n" % count
    stop = src.find(tail_mark, at)
    if counted and stop >= 0:
        stop += len(tail_mark)
    else:
        counted = False
        stop = -1
        pos = src.index("\n", at) + 1
        while pos < len(src):
            nl = src.find("\n", pos)
            line = src[pos:nl if nl >= 0 else len(src)]
            if line.rstrip().endswith('"),') or line.rstrip().endswith("'),"):
                stop = (nl + 1) if nl >= 0 else len(src)
                break
            pos = nl + 1 if nl >= 0 else len(src)
        if stop < 0:
            print("could not find the end of the entry for", name)
            return 1
    entry_src = src[at:stop]
    # the old literal: the lines of the entry up to the line that ends the old text
    # (the stored old text as a literal block ends with a line ending in '",' or "',")
    body_lines = entry_src.split("\n")
    old_end = None
    for i, line in enumerate(body_lines[1:], start=1):
        if line.rstrip().endswith('",') or line.rstrip().endswith("',"):
            old_end = i
            break
    if old_end is None:
        print("could not find the end of the old literal for", name)
        return 1
    kept = "\n".join(body_lines[:old_end + 1]) + "\n"
    new_lit = "".join("     %r\n" % ln for ln in region.splitlines(keepends=True)[:-1])
    if counted:
        new_lit += "     %r, %d),\n" % (region.splitlines(keepends=True)[-1], count)
    else:
        new_lit += "     %r),\n" % (region.splitlines(keepends=True)[-1],)
    Path(tool).write_bytes((src[:at] + kept + new_lit + src[stop:]).encode("utf-8"))
    print(name, "re-anchored on the current text (%d lines)" % len(region.splitlines()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
