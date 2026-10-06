#!/usr/bin/env python3
"""[pineex] Install or update the saved H3 prompt preset "pineEX" through the station's own doors.

The live store (data/h3_prompt_presets.json) is only ever changed by the station itself, under its lock,
through POST /api/h3/prompts (create) and POST /api/h3/prompts/{pid} (update) - never by editing the
file under a running station. This tool reads the preset from a JSON file, asks the station what it has
(GET /api/h3/prompts), finds the preset by NAME (case-insensitive; the JSON's "id" is informational -
the store mints its own), and then creates it when there is none or updates the one there, field by
field. Nothing else changes: the active preset, the dice and the pin are left exactly as they are.

Usage:
  pineex_preset_install.py --check [--file pineex_preset.json] [--base http://127.0.0.1:8096] [--key KEY]
  pineex_preset_install.py --apply [--file ...] [--base ...] [--key ...]

  --check   prints what it would do (create / update / nothing), the diff of fields, and every field
            that the store would cut to its limit (H3_PROMPTS_LIMITS, read off the station's answer).
  --apply   does it through the API and prints the preset id.

Environment: SPARK_AGENT_API_KEY (the bearer), SPARK_AGENT_BASE (default http://127.0.0.1:8096).
Exit codes: 0 done / nothing to do; 1 an error (the station refused, the file is bad); 3 the --check
found something to do (so a script can tell "would change" from "in place").
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8096"
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "pineex_preset.json"
# app.py H3_PROMPTS_FIELDS / H3_PROMPTS_LIMITS as of 2026-10-06; the station's own answer wins when it
# carries them (GET /api/h3/prompts -> "fields", "limits").
FIELDS = ("goal", "clip", "gallery", "host", "speech", "style", "constraints", "audio_direction", "kind")
LIMITS = {"name": 60, "goal": 1200, "clip": 1800, "gallery": 1800, "host": 1800,
          "speech": 700, "style": 120, "constraints": 400, "audio_direction": 400, "kind": 20}
ONE_LINE = ("name", "speech", "style", "constraints", "audio_direction", "kind")


def clean(value: Any, field: str, limits: dict[str, int] | None = None) -> str:
    """One field as the store keeps it (app.py _h3_prompts_text): trimmed, the one-line fields
    on one line, a brief keeps its line breaks, and cut to its limit."""
    text = str(value if value is not None else "")
    if field in ONE_LINE:
        text = " ".join(text.split())
    else:
        text = "\n".join(" ".join(line.split()) for line in text.replace("\r", "").split("\n")).strip()
    return text[:(limits or LIMITS).get(field, 600)]


def load_preset(path: Path) -> dict[str, Any]:
    got = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(got, dict) or not str(got.get("name") or "").strip():
        raise ValueError("the preset file must be an object with a name")
    return got


def cuts(preset: dict[str, Any], limits: dict[str, int]) -> list[tuple[str, int, int]]:
    """Every field the store would cut: (field, length, limit)."""
    out = []
    for field in ("name",) + FIELDS:
        text = str(preset.get(field) or "")
        if field in ONE_LINE:
            text = " ".join(text.split())
        else:
            text = "\n".join(" ".join(line.split()) for line in text.replace("\r", "").split("\n")).strip()
        limit = int(limits.get(field, LIMITS.get(field, 600)))
        if len(text) > limit:
            out.append((field, len(text), limit))
    return out


def find(view: dict[str, Any], name: str) -> dict[str, Any] | None:
    want = " ".join(str(name or "").split()).lower()
    for preset in view.get("presets") or []:
        if isinstance(preset, dict) and " ".join(str(preset.get("name") or "").split()).lower() == want:
            return preset
    return None


ROADS = ("goal", "clip", "gallery", "host")


def expected(field: str, wanted: dict[str, Any], limits: dict[str, int],
             defaults: dict[str, Any] | None = None) -> str:
    """What the store will HOLD for this field once the text is sent (app.py h3_prompts_fields):
    the cleaned, cut text; a blank brief or road direction becomes the Default's words; the kind is
    one of the known few. Compared against the raw stored value - the store cuts AFTER cleaning, so a
    stored field can end on a space and cleaning it again would not give it back."""
    text = clean(wanted.get(field), field, limits)
    if field in ROADS and not text and defaults:
        return str(defaults.get(field) or "")
    if field == "kind":
        low = text.lower()
        return "plotline" if low in ("plotline", "activeplot") else "overview" if "overview" in low else ""
    return text


def diff(existing: dict[str, Any] | None, wanted: dict[str, Any], limits: dict[str, int],
         fields: tuple[str, ...] = FIELDS, defaults: dict[str, Any] | None = None) -> list[tuple[str, str, str]]:
    """(field, old, new) for every field the store would end up changing."""
    out = []
    for field in ("name",) + tuple(fields):
        new = expected(field, wanted, limits, defaults)
        old = str((existing or {}).get(field) if (existing or {}).get(field) is not None else "") if existing else None
        if existing is None or old != new:
            out.append((field, old if old is not None else "", new))
    return out


def plan(view: dict[str, Any], wanted: dict[str, Any]) -> dict[str, Any]:
    limits = dict(LIMITS)
    got = view.get("limits") if isinstance(view.get("limits"), dict) else {}
    limits.update({k: int(v) for k, v in got.items() if isinstance(v, (int, float))})
    fields = tuple(str(f) for f in (view.get("fields") or FIELDS))
    defaults = view.get("defaults") if isinstance(view.get("defaults"), dict) else {}
    existing = find(view, str(wanted["name"]))
    changes = diff(existing, wanted, limits, fields, defaults)
    return {"action": "create" if existing is None else ("update" if changes else "none"),
            "id": str((existing or {}).get("id") or ""), "existing": existing, "diff": changes,
            "cuts": cuts(wanted, limits), "limits": limits, "fields": fields, "defaults": defaults}


def body_for(wanted: dict[str, Any], fields: tuple[str, ...], existing: dict[str, Any] | None) -> dict[str, Any]:
    """The request body: the name and every field (a blank field is sent blank, so a stale value on
    the station is cleared). An update carries `was` - the station refuses a save over a newer edit."""
    out: dict[str, Any] = {"name": " ".join(str(wanted["name"]).split())}
    for field in fields:
        out[field] = str(wanted.get(field) if wanted.get(field) is not None else "")
    if existing is not None and existing.get("updated_at") not in (None, ""):
        out["was"] = existing.get("updated_at")
    return out


class Station:
    """GET/POST against the station with the bearer, as urllib. `call(method, path, body)` is
    the only door, so a test can stand a TestClient in its place."""

    def __init__(self, base: str, key: str, timeout: float = 20.0):
        self.base, self.key, self.timeout = base.rstrip("/"), key, timeout

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - the station's own door
                return resp.status, json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"detail": raw[:300]}


def _detail(status: int, payload: Any) -> str:
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    return "HTTP %d: %s" % (status, str(detail)[:300])


def run(station: Any, wanted: dict[str, Any], apply: bool, out: Any = None) -> dict[str, Any]:
    """The whole road: read, plan, say, and (apply) create or update. Returns what happened."""
    say = (lambda s: print(s, file=out or sys.stdout))
    status, view = station.call("GET", "/api/h3/prompts")
    if status != 200 or not isinstance(view, dict):
        raise RuntimeError("the station did not answer GET /api/h3/prompts (%s)" % _detail(status, view))
    p = plan(view, wanted)
    name = " ".join(str(wanted["name"]).split())
    say("station: %d preset(s), active %s, dice %s" % (
        int(view.get("count") or len(view.get("presets") or [])), view.get("active_name"),
        "on" if view.get("dice") else "off"))
    for field, length, limit in p["cuts"]:
        say("CUT: %s is %d characters, the store keeps %d - the rest would be lost" % (field, length, limit))
    if p["action"] == "none":
        say('"%s" is in place (id %s): nothing to change' % (name, p["id"]))
        return dict(p, done=False, saved=p["id"])
    if p["action"] == "create":
        say('would create "%s" (no preset of that name)' % name if not apply else 'creating "%s"' % name)
    else:
        say('would update "%s" (id %s)' % (name, p["id"]) if not apply else 'updating "%s" (id %s)' % (name, p["id"]))
    for field, old, new in p["diff"]:
        if p["action"] == "create":
            say("  %s: %s" % (field, _short(new)))
        else:
            say("  %s:\n    - %s\n    + %s" % (field, _short(old), _short(new)))
    if not apply:
        return dict(p, done=False, saved=p["id"])
    body = body_for(wanted, p["fields"], p["existing"])
    if p["action"] == "create":
        status, answer = station.call("POST", "/api/h3/prompts", body)
    else:
        status, answer = station.call("POST", "/api/h3/prompts/" + p["id"], body)
    if status != 200 or not isinstance(answer, dict):
        raise RuntimeError("the station refused the %s (%s)" % (p["action"], _detail(status, answer)))
    saved = str(answer.get("saved") or p["id"] or "")
    after = find(answer, name)
    say('%s "%s": id %s' % ("created" if p["action"] == "create" else "updated", name, saved))
    if after is not None:
        left = diff(after, wanted, p["limits"], p["fields"], p["defaults"])
        if left:
            say("NOTE: the station kept %d field(s) differently (its own cleaning): %s"
                % (len(left), ", ".join(f for f, _o, _n in left)))
    return dict(p, done=True, saved=saved, after=after)


def _short(text: str, most: int = 160) -> str:
    one = " ".join(str(text or "").split())
    return one if len(one) <= most else one[:most - 3] + "..."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="say what would change; change nothing")
    mode.add_argument("--apply", action="store_true", help="create or update the preset through the API")
    ap.add_argument("--file", default=str(DEFAULT_FILE), help="the preset JSON (default: ../pineex_preset.json)")
    ap.add_argument("--base", default=os.environ.get("SPARK_AGENT_BASE") or DEFAULT_BASE)
    ap.add_argument("--key", default=os.environ.get("SPARK_AGENT_API_KEY") or "")
    args = ap.parse_args(argv)
    if not args.key:
        print("no API key: pass --key or set SPARK_AGENT_API_KEY", file=sys.stderr)
        return 1
    try:
        wanted = load_preset(Path(args.file))
    except (OSError, ValueError) as exc:
        print("the preset file is not usable: %s" % exc, file=sys.stderr)
        return 1
    try:
        got = run(Station(args.base, args.key), wanted, bool(args.apply))
    except (RuntimeError, OSError, urllib.error.URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.check and got["action"] != "none":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
