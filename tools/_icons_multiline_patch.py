"""The four font stacks that wrapped across a newline - the tune page among
them, which is the one in the car."""
import pathlib
import re

p = pathlib.Path("app.py")
s = p.read_text(encoding="utf-8")
o = s

# `font: <size> <families...>,\n  PineIcons;`  ->  PineIcons first.
PAT = re.compile(
    r"(font:\s*)([^;{}]*?),\s*\n(\s*)PineIcons\s*;",
    re.M)


def one(m):
    head = m.group(2)
    bits = head.split(None, 1)          # size token, then the families
    size, families = (bits[0], bits[1]) if len(bits) == 2 else (bits[0], "")
    return f"{m.group(1)}{size} PineIcons, {families};"


s, n = PAT.subn(one, s)
assert n >= 1, f"no wrapped stacks found"
assert s != o
p.write_text(s, encoding="utf-8")
print(f"fixed {n} wrapped font stacks")
