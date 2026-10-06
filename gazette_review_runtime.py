"""Gazette Review at the existing System2 preparation and station air doors."""
from __future__ import annotations

import asyncio
import copy
import json
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
from threading import RLock

import gazette_prompt
import gazette_review
import segment_prompts

SCOPE = ContextVar("gazette_issue_scope", default=None)


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".gazette.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


def migrate_files(data_dir):
    """Idempotent persisted timing update. No audio, queue, voice or operator prompt is removed."""
    base = Path(data_dir)
    changes = []
    for name, migrate in (("schedule.json", gazette_review.migrate_store),
                          ("dynamic_segments_schedule.json", gazette_review.migrate_book_windows)):
        path = base / name
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        new = migrate(old)
        if old != new:
            _save(path, new)
            changes.append(name)
    path = base / "segment_prompts.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return changes
    if old.get("gazette_review_revision") != gazette_review.MIGRATION:
        for alt in ((old.get("kinds") or {}).get("book_time") or {}).get("alternatives") or []:
            config = alt.get("config") or {}
            if config.get("target_seconds"):
                config["target_seconds"] = max(300.0, float(config["target_seconds"]) - 60.0)
        old["gazette_review_revision"] = gazette_review.MIGRATION
        _save(path, old)
        changes.append("segment_prompts.json")
    return changes


class GazetteReview:
    def __init__(self, g):
        self.g = g
        self.path = Path(g["DATA_DIR"]) / "gazette_review_scopes.json"
        self.lock = RLock()
        self.memo = OrderedDict()
        try:
            self.memo.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass

    def rows(self):
        return self.g["h3_slot_shelf"]("gazette")

    def receipt(self, occurrence="", participant=""):
        with self.lock:
            if occurrence and occurrence in self.memo:
                return copy.deepcopy(self.memo[occurrence])
            result = gazette_review.select(self.rows(), self.g["s3_weighted"], participant=participant)
            if result and result.get("participant") == "caller":
                callers = self.g.get("read_callers", lambda: [])() or []
                callers = [x for x in callers if isinstance(x, dict) and x.get("name") and x.get("enabled", True)]
                if callers:
                    labels = [str(x["name"]) for x in callers]
                    at = self.g["s3_weighted"]("gazette.review.caller", labels, [1.0] * len(labels), "which station caller reviews this Gazette topic")
                    at = at if isinstance(at, int) and 0 <= at < len(callers) else 0
                    result["caller"] = {"name": labels[at], "voice": str(callers[at].get("voice") or "")}
                else:
                    result["caller"] = {"name": "Pinebox Gazette reader", "voice": ""}
            if result and occurrence:
                self.memo[occurrence] = result
                while len(self.memo) > 180:
                    self.memo.popitem(last=False)
                _save(self.path, self.memo)
            return copy.deepcopy(result)

    def flush(self):
        with self.lock:
            _save(self.path, self.memo)

    async def messages(self, messages):
        positions = [i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "user"]
        last_user = positions[-1] if positions else -1
        selected = [i for i, m in enumerate(messages) if isinstance(m, dict)
                    and (m.get("role") == "system" or i == last_user)
                    and isinstance(m.get("content"), str) and gazette_prompt.TOKEN.search(m["content"])]
        if not selected:
            return messages
        try:
            rows = await asyncio.to_thread(self.rows)
            expanded = gazette_review.expand_fields([messages[i]["content"] for i in selected], rows,
                self.g["s3_weighted"], receipt=SCOPE.get())
            out = list(messages)
            for i, words in zip(selected, expanded["texts"]):
                out[i] = dict(messages[i], content=words)
            return out
        except Exception as exc:
            log = self.g.get("pipeline_log")
            if log:
                log("drop", "Gazette topic roulette waits: " + type(exc).__name__)
            return [dict(m, content=gazette_prompt.TOKEN.sub("[Gazette article unavailable]", m["content"]))
                    if i in selected else m for i, m in enumerate(messages)]

    async def caller_premise(self):
        result = await asyncio.to_thread(self.receipt, participant="caller")
        if not result:
            raise ValueError("there is no readable published Gazette issue")
        article = result["article"]
        return (result["prompt"] + "\nPUBLISHED ARTICLE: " + gazette_prompt.phrase(article),
                {"gazette_issue": result["edition"], "gazette_topic": result,
                 "topic_text": result["topic"], "topic_id": "gazette:" + result["edition"] + ":" + str(result["file"])})

    def manager_material(self, got):
        if not isinstance(got, dict) or (got.get("topic") or {}).get("item_id") != "gazette_issue":
            return got
        result = self.receipt(participant="manager")
        if not result:
            # Explicit absence is preferable to inventing an unpublished issue.
            return None
        out = copy.deepcopy(got)
        article = result["article"]
        old_topic = str(got.get("topic_text") or "")
        out["topic_text"] = f"Gazette issue {result['edition']}: {result['topic']}"[:300]
        source = gazette_prompt.phrase(article) + "\n" + result["prompt"]
        for key in ("direction", "memo_direction", "sheet"):
            out[key] = str(out.get(key) or "").replace(old_topic, out["topic_text"]) + "\n" + source
        if isinstance(out.get("sub"), dict):
            out["sub"]["text"] = str(out["sub"].get("text") or "").replace(old_topic, out["topic_text"])
        out["topic"]["gazette"] = result  # rides existing durable manager topic receipts
        return out

    def request(self, bank):
        if bank:
            getter = self.g.get("system2_current_work")
            work = getter() if getter else None
            template = (work or {}).get("template") or {}
            if template.get("slot_kind") == gazette_review.KIND:
                return str((work or {}).get("slot_id") or "")
            return ""
        slot = (self.g.get("_RADIO") or {}).get("sched_slot") or {}
        if slot.get("kind") != gazette_review.KIND and slot.get("slot_kind") != gazette_review.KIND:
            return ""
        pos = (self.g.get("_RADIO") or {}).get("sched_pos") or {}
        return str(pos.get("occurrence") or "") or str(slot.get("id") or "") + "@" + str(pos.get("started") or 0)

    def banked(self, receipt):
        """[bank-first] A finished review round on the shelf written for this edition, oldest first."""
        edition = str((receipt or {}).get("edition") or "")
        ready = self.g.get("dialogue_row_ready")
        busy = self.g.get("_READY_SHELF_BUSY") or set()
        best = None
        for row in list((self.g.get("_SHELF") or {}).get(gazette_review.KIND) or []):
            if not isinstance(row, dict) or id(row) in busy or row.get("aired_at") or int(row.get("aired") or 0):
                continue
            entry = row.get("entry") if isinstance(row.get("entry"), dict) else row
            if str(((entry.get("gazette_review") or {}).get("edition")) or "") != edition:
                continue
            if callable(ready) and not ready(gazette_review.KIND, row):
                continue
            if best is None or float(row.get("at") or 0) < float(best.get("at") or 0):
                best = row
        return best

    async def cast(self, receipt, kw):
        participant = receipt.get("participant")
        if participant == "manager":
            name = self.g.get("manager_call_name", lambda: "Manager from upstairs")()
            voice_fn = self.g.get("manager_call_voice")
            voice = str((receipt.get("caller") or {}).get("voice") or "")
            if not voice:
                voice, _pinned = await voice_fn() if voice_fn else ("", False)
            kw.update(caller_name=name, caller_voice=voice, caller_seat="manager")
        elif participant == "caller":
            row = receipt.get("caller") or {}
            if not isinstance(row, dict):
                row = {}
            name = str(row.get("name") or "Pinebox Gazette reader")
            voice_fn = self.g.get("caller_line_voice")
            voice = str(row.get("voice") or "") or (await voice_fn(name) if voice_fn else "")
            kw.update(caller_name=name, caller_voice=voice)
        if kw.get("caller_name"):
            if not kw.get("caller_voice"):
                raise ValueError("The rolled Gazette participant needs an available voice")
            kw["lines"] = max(11, int(kw.get("lines") or 0))
            receipt.setdefault("caller", {})["voice"] = kw["caller_voice"]
            kw["call_meta"] = {**(kw.get("call_meta") or {}), "gazette_topic": receipt,
                               "topic": receipt["topic"], "topic_id": "gazette:" + receipt["edition"]}
        return kw


def install(app, g):
    if g.get("GAZETTE_REVIEW_RUNTIME"):
        return g["GAZETTE_REVIEW_RUNTIME"]
    runtime = GazetteReview(g)
    g["GAZETTE_REVIEW_RUNTIME"] = runtime
    g["gazette_prompt_messages"] = runtime.messages
    g["gazette_topic_premise"] = runtime.caller_premise
    kinds = g.get("SCHEDULE_KINDS") or []
    if not any(x.get("kind") == gazette_review.KIND for x in kinds):
        kinds.append({"kind": gazette_review.KIND, "label": "Gazette Review",
                      "blurb": "Four minutes reviewing the current Gazette through issue-topic and emotional response nodes."})
    g["SCHEDULE_KIND_NAMES"] = tuple(x["kind"] for x in kinds)
    g.setdefault("SCHEDULE_PROMPT_SEED", {})[gazette_review.KIND] = gazette_review.PROMPT
    g.setdefault("SCHED_PREP_KIND", {})[gazette_review.KIND] = "banter"
    original_defaults = g.get("schedule_defaults")
    if original_defaults:
        def defaults():
            return gazette_review.migrate_store(original_defaults())
        g["schedule_defaults"] = defaults
    original_manager = g.get("_s3_manager_topic")
    if original_manager:
        def manager(*args, **kw):
            return runtime.manager_material(original_manager(*args, **kw))
        g["_s3_manager_topic"] = manager
    original_react = g.get("_s3_manager_topic_react")
    if original_react:
        def react(made):
            base = original_react(made)
            receipt = (((made or {}).get("mgr_topic") or {}).get("topic") or {}).get("gazette") or {}
            if receipt:
                base += " Gazette response node: answer the actual published topic with " + str(receipt.get("reply_emotion")) + "."
            return base
        g["_s3_manager_topic_react"] = react
    original_banter = g.get("dj_banter")
    if original_banter:
        async def banter(*args, **kw):
            occurrence = runtime.request(bool(kw.get("bank")))
            if not occurrence:
                return await original_banter(*args, **kw)
            receipt = await asyncio.to_thread(runtime.receipt, occurrence)
            if not receipt:
                return []
            if not kw.get("bank"):                      # [bank-first] the kitchen's review of this edition first
                banked = runtime.banked(receipt)
                door = g.get("_ready_shelf_air")
                if banked is not None and door is not None:
                    try:
                        said = await door(gazette_review.KIND, (g.get("_RADIO") or {}).get("now"), pick=banked)
                    except Exception:  # noqa: BLE001
                        said = []
                    if said:
                        return said
            angle = str(kw.get("angle") or "")
            expanded = gazette_review.expand_fields([angle or gazette_review.PROMPT], [], g["s3_weighted"], receipt=receipt)
            kw.update(angle=expanded["texts"][0] + "\n" + gazette_prompt.phrase(receipt["article"]) + "\n" + receipt["prompt"],
                      own_material=True, road=gazette_review.KIND)
            kw = await runtime.cast(receipt, kw)
            with runtime.lock:
                runtime.memo[occurrence] = copy.deepcopy(receipt)
            await asyncio.to_thread(runtime.flush)
            pile = kw.get("bank_to")
            start = len(pile) if isinstance(pile, list) else 0
            token = SCOPE.set(receipt)
            try:
                result = await original_banter(*args, **kw)
                if isinstance(pile, list):
                    for entry in pile[start:]:
                        if isinstance(entry, dict):
                            entry["gazette_review"] = copy.deepcopy(receipt)
                return result
            finally:
                SCOPE.reset(token)
        g["dj_banter"] = banter
    return runtime
