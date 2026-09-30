"""[s3-lines] an observation's `lines` is the LIST of line ids it covers.
The dead-air rescue's INJECT card wrote a COUNT there ("lines": 9), and one
such card on a conversation made /api/system3/line 500 for every line in it:
`line_id in 9` -> TypeError. The Message view's cards then had no rolls and
went straight to the words. Writer: the count is `line_count`. Readers: a
membership test only ever looks inside a list."""
import sys, shutil, ast
MODE = sys.argv[1]
root = "/home/ehm_eckx/pinevoice-stack/spark-agent/"
EDITS = {
 "app.py": [('extra={"road": kind, "lines": len(said)})',
             'extra={"road": kind, "line_count": len(said)})   # [s3-lines] a count is not `lines`')],
 "system3_runtime.py": [
  ('if o.get("family") in ("MEASURE", "SFXREACT", "HOLD") and lid in (o.get("lines") or []):',
   'if o.get("family") in ("MEASURE", "SFXREACT", "HOLD") and lid in _s3_lines(o):   # [s3-lines]'),
  ('                   and (got["line_id"] in (o.get("lines") or [])\n',
   '                   and (got["line_id"] in _s3_lines(o)   # [s3-lines]\n'),
  ('                                 or got["line_id"] in (o.get("lines") or [])],',
   '                                 or got["line_id"] in _s3_lines(o)],   # [s3-lines]'),
 ],
}
HELPER_AT = "\nclass "
HELPER = '''
def _s3_lines(o):
    """[s3-lines] the line ids an observation covers. `lines` is a list of ids;
    a writer that put a count there (the dead-air rescue's INJECT card did) must
    not turn one card into a 500 for every line of its conversation."""
    got = o.get("lines") if isinstance(o, dict) else None
    return got if isinstance(got, (list, tuple, set)) else ()

'''
for name, edits in EDITS.items():
    p = root + name
    s = open(p, encoding="utf-8").read()
    if "[s3-lines]" in s:
        print("already", name); continue
    for old, new in edits:
        assert s.count(old) == 1, (name, old[:60], s.count(old))
        s = s.replace(old, new)
    if name == "system3_runtime.py":
        i = s.index(HELPER_AT)
        s = s[:i] + "\n" + HELPER + s[i+1:]
    ast.parse(s)
    if MODE == "--apply":
        shutil.copy(p, "/tmp/%s.bak-s3lines" % name)
        before = open(p, encoding="utf-8").read()
        with open(p, "r+", encoding="utf-8") as f:
            assert f.read() == before
            f.seek(0); f.write(s); f.truncate()
        print("applied", name)
    else:
        print("ok to apply", name)
