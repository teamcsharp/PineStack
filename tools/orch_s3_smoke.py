import asyncio, os, sys, time
t=time.time()
assert os.environ.get("SPARK_AGENT_DATA_DIR","").startswith("/tmp/"), "refusing: data dir must be a temp dir"
import app
print("import %.1fs" % (time.time()-t))
print("desk", type(app._ORCH_S3_DESK).__name__, "data", app.DATA_DIR)
v = app.orch_verbs(); print("verbs", [x for x in v if x.startswith("s3")])
paths = sorted(r.path for r in app.app.routes if "orchestrator/system3" in getattr(r, "path", ""))
print("routes", paths)
got = asyncio.run(app.orch_command_run("s3 know")); print("s3 know ->", got["ok"], got["say"], len(got["lines"]))
got = asyncio.run(app.orch_command_run("help")); print("help rows with s3:", sum(1 for l in got["lines"] if "s3" in l or "#<code>" in l))
got = asyncio.run(app.orch_command_run("why #3c4782")); print("why #code ->", got["ok"], got["say"][:120])
got = asyncio.run(app.orch_command_run("why banter")); print("why road still ->", got["ok"], got["say"][:80])
print("apply s3note ->", app.orch_apply("s3note:nothing"))
print("glass system3 key:", "system3" in app.orch_glass_state())
print("scan ->", app.orch_scan())
print("survey findings:", len((app._ORCH_S3_DESK.memo.get("value") or {}).get("findings") or []), "faculties:", sorted(app._ORCH_S3_DESK.faculties()))
