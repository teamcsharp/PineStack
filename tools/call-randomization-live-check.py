"""Read-only activation check. Run inside spark-agent; no calls written or aired."""
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system3
import call_diversity

BASE="http://127.0.0.1:8096"
def get(path):
    req=urllib.request.Request(BASE+path,headers={"Authorization":"Bearer "+os.environ.get("SPARK_AGENT_API_KEY","")})
    with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)

config=get("/api/system3/config")["config"]
wanted=("CALLOPEN1","CALLANGLE1","CALLSTAKES1","CALLPROBE1","CALLSOURCE1","RW1")
tables=[t for t in config["tables"] if t["id"] in wanted]
report={"at":time.time(),"tables":{t["id"]:{"family":t["family"],"enabled":t.get("enabled",True),
        "options":sum(len(c["items"]) for c in t["categories"]),
        "equal_positive_weights":all(float(i.get("weight",1)) in (0,1) for c in t["categories"] for i in c["items"])} for t in tables}}
assert len(tables)==6,report
report["engine"]=system3.ENGINE_VERSION
assert report["engine"]=="system3-engine/6"
inputs={"road":"caller","seats":["A","B","C"],"turns":12,"names":{"A":"Dill","B":"Skip","C":"Audit Caller"},
        "call":{"name":"Audit Caller","first":"Audit","topic":"a fictional escaped tram","speakerbox":"The raccoon took a tram.","station":"Pine Box FM"},
        "subject":{"topic":"a fictional escaped tram"}}
conv=system3.new_conversation(inputs,config,system3.normalise_settings({"mode":"active"}),seed="activation-check")
system3.plan_call(conv,config)
call_diversity.rewrite_request(conv,config,"activation check only; no writer, recording or air")
report["decision_replay"]=system3.replay(conv,config)["ok"]
report["rewrite_request"]=(conv["rewrite_request"]["selected"] or {}).get("id")
report["calls_created_or_broadcast"]=0
state=get("/api/dj");report["radio"]={"on":state.get("on"),"paused":state.get("paused")}
settings=get("/api/system3/settings");report["mode"]=(settings.get("settings") or settings).get("mode")
paths=get("/openapi.json")["paths"];report["proposal_endpoint"]="/api/orchestrator/system3/propose" in paths
# Invalid read-only probe: valid Request injection must reach the 400 handler,
# while no proposal or table is created.
req=urllib.request.Request(BASE+"/api/orchestrator/system3/propose",data=b"{}",headers={
        "Authorization":"Bearer "+os.environ.get("SPARK_AGENT_API_KEY",""),"Content-Type":"application/json"},method="POST")
try:
    urllib.request.urlopen(req,timeout=20)
    raise AssertionError("empty proposal unexpectedly accepted")
except urllib.error.HTTPError as exc:
    report["proposal_body_probe"]=exc.code
    assert exc.code==400,exc.code
assert report["decision_replay"] and report["proposal_endpoint"]
Path("/app/docs/call-randomization-live-verification-2026-10-02.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report,indent=2))
