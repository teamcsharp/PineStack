"""[es-roads] which rows of the live ES tables have no voice block (their turns air
flat), read from the station's own System 3 config (run in the container)."""
import collections
import inspect

import system3
import system3_runtime

rt = system3_runtime.RUNTIME if hasattr(system3_runtime, "RUNTIME") else None
config = None
for name in ("load_config", "config_load", "read_config"):
    fn = getattr(system3_runtime, name, None) or getattr(system3, name, None)
    if callable(fn):
        try:
            config = fn() if not inspect.signature(fn).parameters else None
        except Exception:  # noqa: BLE001
            config = None
        if config:
            print("config from", name)
            break
if not config:
    store = system3_runtime.System3Store("/app/data/system3.sqlite3")
    for name in ("config", "load_config", "get_config"):
        fn = getattr(store, name, None)
        if callable(fn):
            try:
                config = fn()
                print("config from store.%s" % name)
                break
            except Exception as exc:  # noqa: BLE001
                print("store.%s: %s" % (name, exc))
tables = (config or {}).get("tables") or {}
print("tables", len(tables), [t for t in tables if str(t).startswith("ES")][:10])
missing = collections.Counter()
covered = 0
for tid, table in tables.items():
    if not str(tid).startswith("ES"):
        continue
    for cat in table.get("rows") or table.get("categories") or []:
        items = cat.get("items") or cat.get("sub") or [cat]
        for it in items:
            spec = {"table": tid, "category": cat.get("id") or cat.get("label"), "id": it.get("id") or it.get("label"),
                    "label": it.get("label") or it.get("id")}
            try:
                v = system3.es_voice(config, spec)
            except Exception as exc:  # noqa: BLE001
                v = None
                missing["error %s" % type(exc).__name__] += 1
            if v is None:
                missing["%s / %s" % (tid, spec["category"])] += 1
            else:
                covered += 1
print("items with a voice:", covered, "| without:", sum(missing.values()))
for k, n in missing.most_common(25):
    print("  %3d  %s" % (n, k))
