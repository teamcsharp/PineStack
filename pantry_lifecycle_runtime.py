"""Host adapters and reviewable API for System Three pantry lifecycle."""
import asyncio
from asyncio import sleep
import copy
import json
import math
import time
from fastapi import Header, HTTPException, Request
from pantry_lifecycle import PantryLifecycle, entry_of, reusable_reaction, DEFAULTS

async def lifecycle_clock(manager):
    """Housekeeping must outlive radio preparation and paused/off-air sessions."""
    while True:
        try:
            previous_tick = manager.last_tick
            await manager.tick()
            if manager.last_tick != previous_tick:
                manager.last_error = ""
                manager.cache = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            manager.last_error = type(exc).__name__ + ": " + str(exc)[:200]
            manager.cache = None
            manager.call("pipeline_log", "pantry", "lifecycle maintenance failed: " + manager.last_error)
        await sleep(6)

def install(app, host):
    manager = PantryLifecycle(host, host["data_path"]("pantry_lifecycle.json"))
    host["_PANTRY_LIFECYCLE"] = manager
    task = None

    @app.on_event("startup")
    async def start_lifecycle():
        nonlocal task
        if task is None or task.done():
            task = asyncio.create_task(lifecycle_clock(manager), name="pantry:lifecycle")

    @app.on_event("shutdown")
    async def stop_lifecycle():
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


    def single_contract(entry):
        runtime=manager.runtime()
        stamp=entry.get("system3") or {}
        if not runtime or entry.get("prep_kind") not in ("ad","station_id"):
            return False
        conv=runtime.recent.get(str(stamp.get("conversation_id") or ""))
        planned=(conv or {}).get("turns") or []
        if not conv or conv.get("mode")!="active" or len(planned)!=1:
            return False
        turns=host["banter_turns"](str(entry.get("script") or ""))
        if len(turns)!=1 or turns[0][0]!=planned[0]["speaker"]:
            return False
        tid=planned[0]["turn_id"]
        if str((stamp.get("turns") or {}).get("0") or "")!=tid:
            return False
        dice=host["_turn_dice_map"](entry)
        if str((dice.get(0,{}).get("s3") or {}).get("turn_id") or "")!=tid:
            return False
        actual=conv.get("actual") or []
        text=str(actual[0].get("text") or "") if len(actual)==1 else str(planned[0].get("text") or "")
        return bool(text and " ".join(text.split())==" ".join(turns[0][1].split()))

    host["pantry_single_contract"] = single_contract

    async def repair(kind, row):
        if manager.unavailable(kind,row) or manager.busy(row): return False
        entry = entry_of(row)
        runtime = manager.runtime()
        if not runtime or not runtime.ready: return False
        from system3_runtime import Handle
        import system3
        candidate = copy.deepcopy(entry)
        candidate["prep_kind"] = kind
        stamp = candidate.get("system3") or {}
        cid = stamp.get("conversation_id")
        conv = runtime.recent.get(str(cid)) if cid else None
        if not conv and cid:
            conv = await asyncio.to_thread(runtime.store.conversation, cid, False)
        if not conv and kind in ("ad", "station_id"):
            line = await host["system3_direct_line"](road=kind, text=str(row.get("text") or ""), bank=True)
            if line and line.active:
                runtime.bind_line(line, str(row.get("text") or ""))
                conv = line.conv
        if not conv or conv.get("mode") != "active": return False
        config = runtime.config
        if system3.config_hash(config) != conv.get("config_hash"):
            config = await asyncio.to_thread(runtime.store.config_by_hash, conv.get("config_hash"))
        if not config: return False
        if kind in ("ad","station_id") and len(conv.get("turns") or [])==1 and not row.get("entry"):
            runtime.recent[str(conv["identity"]["conversation_id"])]=conv
            words=str(row.get("text") or "")
            planned=conv["turns"][0]
            if not words:return False
            # Source words and the original single-turn plan stay unchanged.
            candidate.update(script=planned["speaker"]+": "+words,script_plain=planned["speaker"]+": "+words,lines=1)
            candidate["system3"]={"mode":"active","conversation_id":conv["identity"]["conversation_id"],"planned_turns":1,"turns":{"0":planned["turn_id"]}}
            candidate["turn_dice"]={"0":{"s3":{"turn_id":planned["turn_id"]}}}
            candidate["prep_kind"]=kind
            if not single_contract(candidate):return False
            row["system3"]=candidate["system3"]
            row["turn_dice"]=candidate["turn_dice"]
            runtime.persist(conv)
            return host["dialogue_row_ready"](kind,row)
        handle = Handle(runtime, copy.deepcopy(conv), config, True)
        handle.bank = True
        original_script = str(candidate.get("script") or "")
        runtime.bind_entry(candidate, handle)
        if host["s3_binding_withheld"](candidate):
            # The original plan remains authoritative; never lower its turn
            # count to disguise missing turns or invent retrospective stamps.
            sheet = system3.render_sheet(handle.conv)
            rewritten = await host["ask_model"](
                "Repair this stored broadcast conversation against its original System Three plan. "
                "Return only complete dialogue lines with the exact planned speaker markers, one per turn. "
                "Keep factual anchors and verbatim quotations. Do not say directions or turn numbers. "
                "Finish the exchange coherently.\nPLAN:\n" + sheet + "\nDRAFT:\n" + str(candidate.get("script") or row.get("text") or ""),
                limit=8000, spice=0.25, num_ctx=16384, result_contract="structured_turns",
                mark={"kind":"pantry lifecycle repair"})
            candidate["script"] = str(rewritten or "")
            candidate["script_plain"] = candidate["script"]
            candidate["lines"] = len(host["banter_turns"](candidate["script"], str(candidate.get("caller_name") or ""), str(candidate.get("caller2_name") or "")))
            runtime.bind_entry(candidate, handle)
            if host["s3_binding_withheld"](candidate): return False
            # Every changed recording and grading result must be rebuilt.
            for key in ("takes","keys","stats","tint","tint_progress","script_tinted","tint_ok","frozen","prepared","production","production_lines","cue_map"):
                candidate.pop(key,None)
            candidate.update(chunks=0,made=0,partial=True,freshened=True,preparing=False,tinting=False)
        if str(candidate.get("script") or "") != original_script:
            for key in ("takes","keys","stats","tint","tint_progress","script_tinted","tint_ok","frozen","prepared","production","production_lines","cue_map"):
                candidate.pop(key,None)
            candidate.update(chunks=0,made=0,partial=True,freshened=True,preparing=False,tinting=False)
        if manager.clock() >= manager.deadline(kind,row): return False
        if str(entry.get("script") or "") != original_script:
            return False  # another producer changed the source while this repair awaited
        if not any(held is row for _kind, held in manager.rows()):
            return False
        # A repair must not silently clear editorial rejection flags.
        if row.get("off_brief") or entry.get("off_brief") or row.get("review_cancel_pending"): return False
        if entry is row and kind in ("ad","station_id"):
            row["entry"] = candidate
            entry = candidate
        else:
            entry.clear(); entry.update(candidate)
        if not await host["ensure_entry_tinted"](entry,kind,critical=False): return False
        if not manager.admit_production(entry): return False
        if not host["dialogue_audio_ready"](kind,row):
            await host["recording_sitting"]([entry],45.0)
        return host["dialogue_row_ready"](kind,row)

    def harvest(entry, why=""):
        kept=0
        for key in host["_row_clip_keys"](entry):
            row=host["_PANTRY"].get(str(key)) or {}
            text=str(row.get("text") or "")
            clip=row.get("clip") or {}
            source=host["bank_line_stamp"](entry,text,str(row.get("who") or "dj"))
            if text and clip.get("path") and source:
                kept+=int(host["gold_note"](str(row.get("who") or "dj"),text,str(clip["path"]),float(clip.get("seconds") or 0),source=source))
        return kept

    host["pantry_reaction_harvest"] = harvest
    host["pantry_lifecycle_repair"] = repair

    @app.get("/api/pantry/lifecycle")
    async def state(authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        return manager.snapshot()

    @app.post("/api/pantry/lifecycle/policy")
    async def policy(request: Request, authorization: str | None = Header(default=None)):
        host["require_auth"](authorization)
        body = await request.json()
        if not isinstance(body,dict) or set(body)-set(DEFAULTS):
            raise HTTPException(400,"Unknown lifecycle policy field")
        changed = dict(manager.policy)
        for key,value in body.items():
            if key == "mode":
                if value not in ("off","trace","air"): raise HTTPException(400,"mode must be off, trace or air")
            else:
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                    raise HTTPException(400,"Policy bounds must be finite positive numbers")
                if key.endswith("cap") or key.endswith("attempts"):
                    if int(value)!=value:raise HTTPException(400,"Counts must be integers")
                if value>max(float(DEFAULTS[key])*4,24):raise HTTPException(400,"Policy bound exceeds four times its default")
            changed[key]=value
        manager.policy=changed;manager.cache=None;manager.flush()
        return manager.snapshot(fresh=True)

    @app.post("/api/pantry/lifecycle/nominate")
    async def nominate(request: Request, authorization: str | None = Header(default=None)):
        host["require_auth"](authorization)
        body = await request.json()
        ident,kind = str(body.get("id") or ""),str(body.get("kind") or "")
        if kind in ("reaction","catchphrase","punchline"):
            row=next((r for r in host["_gold_rows"]() if str(r.get("key"))==ident),None)
            if not row or not reusable_reaction(row.get("text"),row.get("seconds"),True) or not host["gold_source"](row):
                raise HTTPException(400,"Reaction needs standalone wording, a fitting take and a valid System Three source")
            row["reuse_kind"]=kind;manager.trim_reactions(host["_gold_rows"]());host["_gold_save"]()
        elif kind == "evergreen":
            pair=next(((k,r) for k,r in manager.rows() if manager.ident(k,r)==ident),None)
            if not pair or pair[0] in ("caller","news","response","recap") or not host["dialogue_row_ready"](*pair):
                raise HTTPException(400,"Evergreen nomination needs ready, non-time-sensitive stock")
            k,row=pair
            m=manager.meta(k,row);m["repertoire"]="evergreen"
            manager.note(k,row,"nominated","operator selected evergreen repertoire")
        else:raise HTTPException(400,"kind must be reaction, catchphrase, punchline or evergreen")
        manager.flush();return manager.snapshot(fresh=True)
    return manager
