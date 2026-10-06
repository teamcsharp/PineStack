"""Bounded System Three shelf lifecycle; transports alone prove delivery."""
from __future__ import annotations
import asyncio
import copy
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

DEFAULTS = dict(mode="trace", ordinary_hours=24, repair_attempts=2,
                delivery_attempts=3, reaction_cap=200, reaction_seconds=1800,
                evergreen_cap=20, evergreen_seconds=3600,
                probation_days=7, unused_days=30)

def entry_of(row):
    entry = row.get("entry")
    return entry if isinstance(entry, dict) else row

def reusable_reaction(text, seconds=0, explicit=False):
    text = " ".join(str(text or "").split())
    if not 2 <= len(text.split()) <= 45 or float(seconds or 0) > 20:
        return False
    if re.search(r"https?://|\b(?:today|yesterday|tomorrow|breaking|upstairs|painting|memo|caller|forecast)\b|\d", text, re.I):
        return False
    return explicit or bool(re.search(r"\b(?:go on|keep going|tell me|hear you|listening|sounds like|fair enough|makes sense|no kidding|well said|hold that thought|that's funny|you bet)\b", text, re.I))

class PantryLifecycle:
    def __init__(self, host, path, clock=time.time):
        self.host, self.path, self.clock = host, Path(path), clock
        self.policy, self.recent, self.counts = dict(DEFAULTS), [], Counter()
        self.active, self.last_tick, self.cache, self.cache_at = set(), 0, None, 0
        self.candidates = []
        self.classifying = False
        self.last_error = ""
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.policy.update({k:v for k,v in saved.get("policy", {}).items() if k in DEFAULTS})
            self.recent = saved.get("recent", [])[-200:]
            self.counts.update(saved.get("counts", {}))
            self.candidates = saved.get("candidates", [])[-200:]
        except (FileNotFoundError, ValueError, OSError):
            pass
    @property
    def enabled(self):
        return self.policy["mode"] == "air"
    def call(self, name, *args, default=None, **kwargs):
        fn = self.host.get(name)
        return fn(*args, **kwargs) if callable(fn) else default
    def runtime(self):
        runtime = self.host.get("_SYSTEM3_RUNTIME")
        return runtime() if callable(runtime) else runtime
    def rows(self):
        seen = set()
        piles = list(self.host.get("_SHELF", {}).items()) + [("banter", self.host.get("_LARDER", []))]
        for kind, rows in piles:
            for row in list(rows or []):
                if isinstance(row, dict) and id(row) not in seen:
                    seen.add(id(row))
                    yield str(kind), row
    def ident(self, kind, row):
        return str(self.call("alt_sid", kind, row) or self.call("retire_id", kind, row)
                   or hashlib.sha1((kind + str(row.get("at")) + str(entry_of(row).get("script") or row.get("text"))).encode()).hexdigest()[:16])
    def meta(self, kind, row):
        meta = row.setdefault("pantry_lifecycle", {})
        meta.setdefault("id", self.ident(kind, row))
        meta.setdefault("created", float(row.get("at") or entry_of(row).get("at") or self.clock()))
        return meta
    def deadline(self, kind, row):
        meta = row.get("pantry_lifecycle") or {}
        created = float(meta.get("created") or row.get("at") or entry_of(row).get("at") or self.clock())
        if self.evergreen(row): return float(meta.get("delivered_at") or created) + float(self.policy["unused_days"]) * 86400
        life = float(self.policy["ordinary_hours"]) * 3600
        if kind == "news": life = min(life, float(self.host.get("NEWS_PREP_LIFE", 3600)))
        if kind == "response": life = min(life, 900)
        return created + life
    def evergreen(self, row):
        return (row.get("pantry_lifecycle") or {}).get("repertoire") == "evergreen"
    def unavailable(self, kind, row):
        if not self.enabled: return False
        meta = row.get("pantry_lifecycle") or {}
        return (meta.get("state") == "retired"
                or (meta.get("state") == "delivered" and not self.evergreen(row))
                or (not self.evergreen(row) and (int(row.get("heard") or 0)>0 or float(row.get("heard_at") or 0)>0))
                or (not self.evergreen(row) and self.clock() >= self.deadline(kind, row)))
    def note(self, kind, row, action, why, **facts):
        event = dict(at=self.clock(), id=self.ident(kind, row), kind=kind, action=action, why=str(why)[:300], **facts)
        self.recent.append(event); self.recent[:] = self.recent[-200:]
        self.counts[action] += 1; self.cache = None
        stamp = entry_of(row).get("system3") or {}
        runtime = self.runtime()
        if runtime and stamp.get("conversation_id"):
            runtime.observe_later(stamp["conversation_id"], "PANTRY", event)
        self.call("pipeline_log", "pantry", action + ": " + str(why), extra=event["id"])
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(policy=self.policy, counts=dict(self.counts), recent=self.recent, candidates=self.candidates), ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
    def flush(self):
        self.call("_pantry_save", True); self.call("_larder_save")
        for name in ("_INVENTORY_PLAN", "_COMMITS", "_COORD_BRIEF"):
            self.host.get(name, {})["at"] = 0.0
        for name in ("_PANTRY_READY_MEMO", "_UNHEARD_MEMO"):
            self.host.get(name, {}).update(at=0.0, value=None)
        self.save()
    def busy(self, row):
        e = entry_of(row)
        return bool(id(row) in self.host.get("_READY_SHELF_BUSY", set()) or e.get("preparing") or e.get("tinting"))
    def retire(self, kind, row, why):
        if self.busy(row): return False
        m = self.meta(kind, row)
        if m.get("state") == "retired": return False
        self.call("pantry_reaction_harvest", entry_of(row), why)
        keys = set(self.call("_row_clip_keys", row, default=set()) or [])
        m.update(state="retired", retired_at=self.clock(), reason=why, lease_until=0)
        for rows in list(self.host.get("_SHELF", {}).values()) + [self.host.get("_LARDER", [])]:
            rows[:] = [r for r in rows if r is not row]
        finish = self.host.get("_FINISH_QUEUE", {})
        if isinstance(finish.get("ids"), list):
            finish["ids"][:] = [rid for rid in finish["ids"] if rid != m["id"]]
        held = set(self.call("pantry_spoken_for", default=set()) or [])
        for key in keys - held: self.host.get("_PANTRY", {}).pop(key, None)
        # Files remain under the transport-aware media pruner, never unlinked here.
        self.note(kind, row, "retired", why)
        return True
    def reserve(self, kind, row, opportunity=""):
        if not self.enabled: return
        m = self.meta(kind, row)
        seconds = float(self.call("cupboard_row_seconds", kind, row, default=60) or 60)
        m.update(state="reserved", lease_until=min(self.deadline(kind, row), self.clock()+max(60,seconds+60)), opportunity=opportunity)
        m["opportunities"] = int(m.get("opportunities") or 0)+1
        self.note(kind, row, "reserved", "compatible opportunity", opportunity=opportunity)
    def queued(self, kind, row):
        if not self.enabled: return
        m = self.meta(kind, row)
        seconds = float(self.call("cupboard_row_seconds", kind, row, default=60) or 60)
        runway = max(self.clock(), float((self.host.get("_PAGE_AIR_UNTIL") or [0])[0]))
        m.update(state="queued", lease_until=runway+seconds+60, queued_at=self.clock())
        m["delivery_attempts"] = int(m.get("delivery_attempts") or 0)+1
        self.note(kind, row, "queued", "published; awaiting complete playback receipt")
        self.flush()
    def failed(self, kind, row, why):
        if not self.enabled: return
        m = self.meta(kind, row)
        m.update(state="ready", lease_until=0, retry_at=self.clock()+20, reason=why)
        m["failures"] = int(m.get("failures") or 0)+1
        self.note(kind, row, "delivery_failed", why); self.flush()
    def confirmed(self, entry):
        if not self.enabled: return
        ident = entry.get("_pantry_lifecycle_id")
        for kind, row in self.rows():
            m = row.get("pantry_lifecycle") or {}
            if ident and m.get("id") == ident:
                receipt = str(entry.get("_pantry_lifecycle_delivery") or m.get("delivery_attempts") or 1)
                if m.get("state") == "delivered" or m.get("last_receipt") == receipt: return
                m["last_receipt"] = receipt
                now = self.clock()
                row["aired_at"] = row["heard_at"] = now
                row["aired"] = int(row.get("aired") or 0)+1
                row["heard"] = int(row.get("heard") or 0)+1
                m.update(state="delivered", delivered_at=now, lease_until=0)
                self.note(kind, row, "delivered", "complete native playback receipt")
                if not self.evergreen(row): self.retire(kind,row,"single-use item delivered")
                else: m.update(state="ready", retry_at=now+14400)
                self.flush(); return
    def compatible(self, kind, row):
        window = self.call("_ready_slot_window", kind)
        if not window or window.get("kind") != kind: return False
        starts = max(self.clock()+5, float((self.host.get("_PAGE_AIR_UNTIL") or [0])[0]), float(self.call("playout_floor", default=0) or 0))
        duration = float(self.call("cupboard_row_seconds",kind,row,default=0) or 0)
        return duration > 0 and starts+duration+5 <= min(float(window.get("deadline") or 0), self.deadline(kind,row))
    def out_of_turn(self, kind, row):
        """[bank-first] A never-aired round past the cupboard's dial may go out OUTSIDE its entry on any
        road the station opens out of turn (RESCUE_ROADS_OPEN) - the sweep's own rule, which this pick
        had replaced with "inside its entry only": 304 overdue rounds stood while it answered
        "nothing unheard is past the dial and airable"."""
        try:
            if kind not in (self.host.get("RESCUE_ROADS_OPEN") or ()) or self.evergreen(row): return False
            if int(row.get("aired") or 0) > 0 or float(row.get("aired_at") or 0) > 0: return False
            after = float(self.call("cupboard_unheard_after", default=7200) or 7200)
            now = self.clock()
            if now - float(row.get("at") or entry_of(row).get("at") or now) <= after: return False
            return self.deadline(kind, row) > now + 30
        except Exception:
            return False
    def pick(self):
        now = self.clock(); pool = []
        for kind,row in self.rows():
            m = row.get("pantry_lifecycle") or {}
            if (self.unavailable(kind,row) or self.busy(row) or float(m.get("lease_until") or 0)>now or float(m.get("retry_at") or 0)>now
                    or not self.call("dialogue_row_ready",kind,row,default=False)
                    or not (self.compatible(kind,row) or self.out_of_turn(kind,row))):   # [bank-first]
                continue
            if not self.evergreen(row) and now-float(row.get("at") or now)<120: continue
            pool.append((kind,row))
        if not pool: return "",None,0.0
        due = [(k,r) for k,r in pool if self.deadline(k,r)-now <= 3600]
        if due:
            kind,row = min(due,key=lambda pair:self.deadline(*pair))
            self.note(kind,row,"deadline_priority","final compatible opportunity before expiry")
        else:
            weights = [1+(now-float(r.get("at") or now))/3600+int((r.get("pantry_lifecycle") or {}).get("misses") or 0) for k,r in pool]
            labels = [self.ident(k,r) for k,r in pool]
            index = self.call("system3_pick","pantry.lifecycle",labels,"aged stock in the current compatible segment",weights)
            if not isinstance(index,int) or not 0<=index<len(pool): return "",None,0.0
            kind,row = pool[index]
            self.note(kind,row,"roulette","compatible aged stock draw",candidates=labels,weights=weights,selected=index)
        for k,r in pool:
            if r is not row:
                m=self.meta(k,r);m["misses"]=int(m.get("misses") or 0)+1
        # Reservation occurs at dispatch, after the transport rechecks readiness.
        return kind,row,max(0,now-float(row.get("at") or now))
    def snapshot(self, fresh=False):
        if not fresh and self.cache is not None and self.clock()-self.cache_at<20: return copy.deepcopy(self.cache)
        counts,reasons,roads,items = Counter(),Counter(),{},[]
        oldest_blocked=0
        for kind,row in self.rows():
            m=row.get("pantry_lifecycle") or {};state=m.get("state","")
            if state not in {"reserved","queued","repairing","retired","delivered"}:
                state="ready" if self.call("dialogue_row_ready",kind,row,default=False) else "blocked"
            counts[state]+=1;counts["expired"]+=int(not self.evergreen(row) and self.clock()>=self.deadline(kind,row))
            roads.setdefault(kind,Counter())[state]+=1
            if state=="blocked":
                oldest_blocked=max(oldest_blocked,self.clock()-float(row.get("at") or self.clock()))
                why=self.call("cupboard_why_row",kind,row,default={}) or {}
                reasons.update(z.get("code") or "unknown" for z in why.get("reasons",[]))
            items.append(dict(id=self.ident(kind,row),kind=kind,state=state,created=float(row.get("at") or self.clock()),deadline=self.deadline(kind,row),reason=m.get("reason",""),repair_attempts=m.get("repair_attempts",0)))
        result=dict(policy=dict(self.policy),states=dict(counts),reasons=dict(reasons),roads={k:dict(v) for k,v in roads.items()},recent=list(self.recent[-30:]),counts=dict(self.counts),items=sorted(items,key=lambda r:r["created"])[:200])
        result["maintenance"] = dict(last_tick=self.last_tick, last_error=self.last_error)
        result["oldest_blocked_seconds"]=max(0,oldest_blocked)
        result["candidate_reactions"]=len(self.candidates)
        result["say"]="%d ready, %d blocked, %d queued; %d past their deadline"%tuple(counts[k] for k in ("ready","blocked","queued","expired"))
        self.cache,self.cache_at=result,self.clock();return copy.deepcopy(result)
    def admit_production(self,entry):
        if not self.enabled:return True
        why=self.call("s3_binding_withheld",entry,default="")
        if why:entry["pantry_lifecycle_blocked"]=why;return False
        entry.pop("pantry_lifecycle_blocked",None);return True
    def backpressure(self,kind):
        if not self.enabled:return False
        rows=[r for k,r in self.rows() if k==kind and not self.unavailable(k,r)]
        blocked=sum(not self.call("dialogue_row_ready",kind,r,default=False) for r in rows)
        return kind not in {"news","response"} and blocked>=8
    def trim_reactions(self,rows):
        if not self.enabled:return
        now=self.clock();keep=[]
        for r in rows:
            explicit=r.get("reuse_kind") in {"reaction","catchphrase","punchline"}
            if not reusable_reaction(r.get("text"),r.get("seconds"),explicit):
                self.consider_reaction(r.get("who") or "dj", r.get("text") or "", r.get("path") or "", r.get("seconds") or 0, r.get("source"))
                continue
            if not self.call("gold_source",r) or not r.get("path"):continue
            r.setdefault("created_at", float(r.get("at") or now))
            age=now-float(r["created_at"]);last=float(r.get("last") or r.get("at") or now)
            if not r.get("fired") and age>float(self.policy["probation_days"])*86400:continue
            if r.get("fired") and now-last>float(self.policy["unused_days"])*86400:continue
            keep.append(r)
        keep.sort(key=lambda r:(bool(r.get("fired")),float(r.get("last") or 0),float(r.get("at") or 0)),reverse=True)
        bounded=[];seconds=0
        for r in keep:
            duration=float(r.get("seconds") or 0)
            if len(bounded)<int(self.policy["reaction_cap"]) and seconds+duration<=float(self.policy["reaction_seconds"]):bounded.append(r);seconds+=duration
        removed=len(rows)-len(bounded);rows[:]=bounded
        if removed:self.counts["reactions_retired"]+=removed;self.cache=None
    def consider_reaction(self, who, text, path, seconds, source, reuse_kind=""):
        if not self.enabled: return True
        if not path or not self.call("gold_source", {"source":source}): return False
        explicit = reuse_kind in {"reaction","catchphrase","punchline"}
        if reusable_reaction(text, seconds, explicit): return True
        words = str(text).split()
        if not 2 <= len(words) <= 45 or float(seconds or 0)>20: return False
        key=hashlib.sha1(str(text).lower().encode()).hexdigest()[:16]
        if any(r["key"]==key for r in self.candidates): return False
        self.candidates.append(dict(key=key,who=who,text=text,path=path,seconds=seconds,source=source,at=self.clock(),attempts=0))
        self.candidates[:]=self.candidates[-200:]
        return False
    async def classify_reactions(self):
        self.classifying=True
        batch=self.candidates[:10]
        try:
            prompt=("Classify reusable radio conversational reactions. Keep standalone acknowledgments, funny reactions, "
                    "catchphrases, high-impact punchlines and rhyming reactions that fit many conversations. "
                    "Reject statements about specific people, places, incidents, products, callers, dates, or news. "
                    "Reject factual claims and lines needing their original story. Return JSON only: "
                    '{"items":[{"key":"...","kind":"reaction|catchphrase|punchline|reject"}]}.\n'
                    +json.dumps([dict(key=r["key"],text=r["text"]) for r in batch]))
            answer=await asyncio.wait_for(self.call("ask_model",prompt,limit=2000,spice=0.1,result_contract="json",mark={"kind":"pantry reaction admission"}),60)
            raw=str(answer or "");start=raw.find("{");end=raw.rfind("}")
            labels={str(r.get("key")):str(r.get("kind")) for r in json.loads(raw[start:end+1]).get("items",[])}
            for r in batch:
                label=labels.get(r["key"])
                if label in {"reaction","catchphrase","punchline"} and reusable_reaction(r["text"],r["seconds"],True):
                    self.call("gold_note",r["who"],r["text"],r["path"],r["seconds"],source=r["source"],reuse_kind=label)
                if label in {"reaction","catchphrase","punchline","reject"}:
                    self.candidates[:]=[c for c in self.candidates if c["key"]!=r["key"]]
                else:r["attempts"]=int(r.get("attempts") or 0)+1
            self.counts["reaction_candidates_reviewed"]+=len(batch)
        except Exception:
            for r in batch:r["attempts"]=int(r.get("attempts") or 0)+1
        finally:
            self.candidates[:]=[r for r in self.candidates if int(r.get("attempts") or 0)<2 and self.clock()-float(r.get("at") or 0)<86400]
            self.classifying=False;self.save()
    async def repair(self,kind,row):
        m=self.meta(kind,row);ident=m["id"];self.active.add(ident)
        m.update(state="repairing",repair_started=self.clock());m["repair_attempts"]=int(m.get("repair_attempts") or 0)+1
        try:
            repaired=await asyncio.wait_for(self.call("pantry_lifecycle_repair",kind,row),180)
            m.update(state="ready" if repaired else "blocked",retry_at=self.clock()+300)
            if self.clock() >= self.deadline(kind,row):
                self.retire(kind,row,"deadline passed during bounded repair")
            self.note(kind,row,"repair_finished","ready" if repaired else "repair did not complete admission")
        except Exception as exc:
            m.update(state="blocked",retry_at=self.clock()+300,reason=type(exc).__name__)
            self.note(kind,row,"repair_failed",type(exc).__name__)
        finally:self.active.discard(ident);self.flush()
    async def tick(self):
        now=self.clock()
        if now-self.last_tick<30:return
        self.last_tick=now
        if not self.enabled:self.snapshot(fresh=True);return
        changed=False;repair_pool=[];evergreen=[]
        self.candidates[:]=[r for r in self.candidates if int(r.get("attempts") or 0)<2 and now-float(r.get("at") or 0)<86400]
        review_due=bool(self.candidates and int(now//30)%3==0)
        for kind,row in list(self.rows()):
            await asyncio.sleep(0)  # yield between backlog items so transport keeps moving
            m=self.meta(kind,row)
            if self.busy(row) or m["id"] in self.active:continue
            if self.evergreen(row):
                evergreen.append((kind,row))
                if now-float(m.get("delivered_at") or m["created"])>float(self.policy["unused_days"])*86400:changed|=self.retire(kind,row,"evergreen unused beyond retention")
                continue
            if int(row.get("heard") or 0)>0 or float(row.get("heard_at") or 0)>0:
                changed|=self.retire(kind,row,"ordinary item already has playback evidence");continue
            if now>=self.deadline(kind,row):changed|=self.retire(kind,row,"lifecycle freshness deadline");continue
            if m.get("state")=="delivered":changed|=self.retire(kind,row,"single-use item delivered");continue
            if float(m.get("lease_until") or 0) and float(m["lease_until"])<=now:self.failed(kind,row,"reservation or playback receipt timed out");changed=True
            if float(m.get("lease_until") or 0)>now:continue
            if int(m.get("failures") or 0)>=int(self.policy["delivery_attempts"]):changed|=self.retire(kind,row,"delivery retry budget exhausted");continue
            if not self.call("dialogue_row_ready",kind,row,default=False):
                m["state"]="blocked"
                if int(m.get("repair_attempts") or 0)<int(self.policy["repair_attempts"]) and float(m.get("retry_at") or 0)<=now:repair_pool.append((kind,row))
        if not self.active and not self.classifying and not review_due and repair_pool and self.call("pantry_window",default=False) and not self.call("prep_should_stop",default=""):
            kind,row=min(repair_pool,key=lambda pair:self.deadline(*pair))
            self.active.add(self.meta(kind,row)["id"])
            self.call("fire_and_forget",self.repair(kind,row))
        evergreen.sort(key=lambda pair:float((pair[1].get("pantry_lifecycle") or {}).get("delivered_at") or 0),reverse=True)
        seconds=0
        for i,(kind,row) in enumerate(evergreen):
            seconds+=float(self.call("cupboard_row_seconds",kind,row,default=0) or 0)
            if i>=int(self.policy["evergreen_cap"]) or seconds>float(self.policy["evergreen_seconds"]):changed|=self.retire(kind,row,"evergreen repertoire cap")
        gold=self.call("_gold_rows",default=[]);before=len(gold);self.trim_reactions(gold)
        if len(gold)!=before:self.call("_gold_save");changed=True
        # Cache ownership is bounded too: a forgotten external reference
        # cannot make ordinary rendered audio immortal. Files themselves stay
        # under the existing queued-playback-aware media pruner.
        protected=set()
        for kind,row in self.rows():
            if not self.unavailable(kind,row) or self.evergreen(row) or self.busy(row):
                protected.update(self.call("_row_clip_keys",row,default=set()) or [])
        for row in self.host.get("_BOX_HOLD",[]):
            protected.update(self.call("_row_clip_keys",row,default=set()) or [])
        reusable_files={str(r.get("path") or "").rsplit("/",1)[-1].split("?")[0] for r in gold}
        reusable_files.update(str(r.get("path") or "").rsplit("/",1)[-1].split("?")[0] for r in self.candidates)
        expired_keys=[]
        for key,row in list(self.host.get("_PANTRY",{}).items()):
            name=str((row.get("clip") or {}).get("path") or "").rsplit("/",1)[-1].split("?")[0]
            if (key not in protected and name not in reusable_files
                    and now-float(row.get("at") or now)>=float(self.policy["ordinary_hours"])*3600):
                expired_keys.append(key)
        for key in expired_keys:self.host["_PANTRY"].pop(key,None)
        if expired_keys:
            self.counts["cache_retired"]+=len(expired_keys);changed=True
        if changed:self.flush()
        self.save()
        if not self.active and (review_due or not repair_pool) and not self.classifying and self.candidates and self.call("pantry_window",default=False):
            self.classifying=True
            self.call("fire_and_forget",self.classify_reactions())
        self.snapshot(fresh=True)
