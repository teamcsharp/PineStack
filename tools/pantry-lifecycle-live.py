"""Deploy/observe the authorized lifecycle policy without printing credentials."""
import argparse
import datetime
import json
import os
from pathlib import Path
import urllib.request
parser=argparse.ArgumentParser();parser.add_argument("--activate",action="store_true");parser.add_argument("--trace",action="store_true");args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
headers={"Authorization":"Bearer "+os.environ.get("SPARK_AGENT_API_KEY", ""),"Content-Type":"application/json"}
def get(route, body=None):
    request=urllib.request.Request("http://127.0.0.1:8096"+route,headers=headers,data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(request,timeout=35) as response:return json.load(response)
if args.activate:
    archives=list((root/"artifacts/pantry-lifecycle").glob("backlog-before-*/manifest.json"))
    if not archives:raise RuntimeError("A recoverable backlog archive is required before activation")
    get("/api/pantry/lifecycle/policy",{"mode":"air"})
if args.trace:get("/api/pantry/lifecycle/policy",{"mode":"trace"})
report={"captured_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
state=get("/api/pantry/lifecycle")
report["lifecycle"]={k:v for k,v in state.items() if k!="items"}
brief=get("/api/coordinator/brief")
report["coordinator"]={k:brief.get(k) for k in ("on","paused","say","doing")}
receivers=get("/api/air/receivers")
report["receivers"]={"active":receivers.get("active"),"sounding":[r.get("id") for r in receivers.get("receivers",[]) if r.get("sounding")],"say":receivers.get("say")}
report["unheard"]=get("/api/cupboard/unheard")
folder=root/"artifacts/pantry-lifecycle";folder.mkdir(parents=True,exist_ok=True)
filename="activation.json" if args.activate else "live-latest.json"
(folder/filename).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"policy":state["policy"],"states":state["states"],"counts":state["counts"],"candidate_reactions":state.get("candidate_reactions"),"reasons":state.get("reasons"),"coordinator":report["coordinator"],"receivers":report["receivers"],"recent":state.get("recent",[])[-6:]},ensure_ascii=False))
