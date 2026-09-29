"""[no-repeat-24h] Which OTHER patch tool's stored text would an apply break?

Every tool/test string (>30 chars) present in the base tree's app.py /
system3.py / system3_runtime.py but absent from the patched tree is a text some
other tool checks for. Usage: python3 p3_textcheck.py BASE_DIR PATCHED_DIR"""
import ast
import glob
import os
import sys

base_dir, new_dir = sys.argv[1], sys.argv[2]
files = ("app.py", "system3.py", "system3_runtime.py")
base = {f: open(os.path.join(base_dir, f), encoding="utf-8").read() for f in files}
new = {f: open(os.path.join(new_dir, f), encoding="utf-8").read() for f in files}
n = 0
for tool in sorted(glob.glob(os.path.join(base_dir, "tools", "*.py")) + glob.glob(os.path.join(base_dir, "tests", "*.py"))):
    try:
        tree = ast.parse(open(tool, encoding="utf-8").read())
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 30 and node.value.strip():
            for f in files:
                if node.value in base[f] and node.value not in new[f]:
                    n += 1
                    print(os.path.basename(tool), f, repr(node.value.strip().splitlines()[0][:80]))
print("broken texts:", n)
