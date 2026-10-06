"""Exercise the update API without importing the running station."""
import asyncio
import pathlib
import re
import time
from typing import Any

class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code

class Request:
    def __init__(self, body): self.body = body
    async def json(self): return self.body

class Routes:
    def get(self, *_): return lambda f: f
    def post(self, *_): return lambda f: f

source = (pathlib.Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
section = source[source.index('_PINETAB_UPDATE_ASK: dict'):source.index('@app.get("/api/tablet/find")')]
ns = dict(Any=Any, Request=Request, Header=lambda **kw: None, app=Routes(), time=time, re=re,
          HTTPException=HTTPException, require_auth=lambda _: None, require_read_auth=lambda _: None,
          pipeline_log=lambda *args: None)
exec(compile(section, "update-api", "exec"), ns)

async def check():
    post = ns["tablet_update_ask_post"]
    stamp = "aaaaaaaaaaaa"
    v = await post(Request({"wanted": stamp}))
    assert not v["open"] and v["wanted"] == stamp and v["ask_at"] == 0
    v = await post(Request({}))
    ask = v["ask_at"]
    assert v["state"] == "asked"
    v = await post(Request({"wanted": "bbbbbbbbbbbb"}))
    assert v["ask_at"] == ask and v["state"] == "asked", "version publishing must not change a build request"
    try:
        await post(Request({"state": "install-requested", "ask_at": ask}))
        raise AssertionError("early install accepted")
    except HTTPException as e:
        assert e.status_code == 409
    for state in ["taken", "running", "ready"]:
        v = await post(Request({"state": state, "ask_at": ask, "line": state}))
        assert v["state"] == state and v["open"]
    v = await post(Request({"state": "running", "ask_at": ask}))
    assert v["state"] == "ready", "late build reports cannot clear ready"
    assert (await post(Request({})))["ask_at"] == ask
    for state in ["install-requested", "installing", "done"]:
        v = await post(Request({"state": state, "ask_at": ask}))
        assert v["state"] == state
    assert not v["open"]
    for state in ["running", "ready", "installing"]:
        assert (await post(Request({"state": state, "ask_at": ask})))["state"] == "done"
    try:
        await post(Request({"wanted": "bad"}))
        raise AssertionError("invalid source stamp accepted")
    except HTTPException as e:
        assert e.status_code == 400
    print("Station update states and version heartbeat: passed")

asyncio.run(check())
