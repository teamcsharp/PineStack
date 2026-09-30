import ast
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "_CONV_CACHE" in s:
    print("already")
    sys.exit(0)
a = '''def _conv(cid: str) -> Any:
    try:
        rt = _runtime()
        return (rt.recent.get(str(cid)) if rt is not None and cid else None)
    except Exception:  # noqa: BLE001
        return None
'''
b = '''_CONV_CACHE: dict[str, Any] = {}


def _conv(cid: str) -> Any:
    """A System 3 conversation: the runtime's recent ones first, then its store
    ([reply-gap:buildup-real] measured: 8 of 8 rounds were not in rt.recent, so
    their lines had no buildup - but every one is in the store)."""
    try:
        rt = _runtime()
        if rt is None or not cid:
            return None
        got = rt.recent.get(str(cid))
        if got is not None:
            return got
        if str(cid) in _CONV_CACHE:
            return _CONV_CACHE[str(cid)]
        store = getattr(rt, "store", None)
        got = store.conversation(str(cid)) if store is not None else None
        if got is not None:
            _CONV_CACHE[str(cid)] = got
        while len(_CONV_CACHE) > 64:
            _CONV_CACHE.pop(next(iter(_CONV_CACHE)))
        return got
    except Exception:  # noqa: BLE001
        return None
'''
assert s.count(a) == 1
s = s.replace(a, b)
ast.parse(s)
with open(p, "r+", encoding="utf-8") as fh:
    fh.seek(0)
    fh.write(s)
    fh.truncate()
print("applied")
