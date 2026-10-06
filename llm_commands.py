"""[llm-command] The LLM command book: every spoken command the station understands, counted. 2026-10-06.

"when it comes to LLM commands, I want a popup where I am mapping them and
their behavior and am able to view them on a table and adjust them. Call the
popup 'LLM command' and I want to be able to add commands that then are able
to be expanded on and used with the Nabu / Pine box. List every command we
have assigned so far and keep a count of how many times I use commands
through the LLM assistant."

generate_answer() in app.py is the spoken-command dispatcher: every sentence
the Nabu, the panel or the desk hands the assistant is first offered to a
chain of parsers (parse_show_doctor, parse_what_happened, parse_export_command,
parse_directive, te_manual_intent, is_memory_command, is_system_query, ...)
and the first one to answer owns the turn; only a sentence none of them wants
reaches the chat model. Those parsers ARE the station's LLM commands, and
until now they lived only as regexes scattered over 283k lines.

This module is the book of them:

  BUILTINS      one row per parser, in the order generate_answer asks them,
                with what it does (read off the code) and example sentences
                that were run against the real regexes.
  ORCHESTRATOR  one row per verb of orch_command_run (the line at the foot of
                the orchestrator glass): help, more/less/ease/drop, <verb>:<arg>,
                run, hear, retire, why, why #code, s3 ...
  CUSTOM        the operator's own commands: {name, triggers, does} where
                triggers are whole sentences or /regex/ and does is one of
                  {"as": "<a sentence the built-in parsers understand>"}
                  {"say": "<a fixed reply>"}
                  {"orchestrator": "<a verb line for orch_command_run>"}

Counting: watch(g, names) wraps each parser global in app.py's namespace so a
truthy return records a hit - ONE hit per utterance (the first parser in chain
order to answer the same text inside HIT_WINDOW_S), with count, last_at and
the first 160 characters of the sentence. orch_command_run is wrapped the same
way, keyed by its verb. Nothing here decides anything about the air: a
disabled built-in answers falsy and the chain moves on; everything else is a
reading of what the station already does, plus the operator's aliases.

Persisted atomically to data/llm_commands.json (counts, notes, disabled
built-ins, custom commands).

Routes (install(app, g)):
  GET    /api/llm-commands                everything, with counts and a `say`
  PUT    /api/llm-commands/custom         upsert a custom command
  DELETE /api/llm-commands/custom/{id}
  PUT    /api/llm-commands/note/{id}      {notes} and/or {enabled} on any row
  POST   /api/llm-commands/try            {text} -> who would answer; dry run
"""
from __future__ import annotations

import inspect
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

try:
    from fastapi import Header, HTTPException, Request
except Exception:  # pragma: no cover - the unit tests do not need FastAPI
    Header = HTTPException = Request = None  # type: ignore

HIT_WINDOW_S = 2.0          # one hit per utterance: the same text inside this window is the same turn
LAST_TEXT_CHARS = 160
FILE_NAME = "llm_commands.json"
SAVE_DELAY_S = 1.0

# The parsers generate_answer asks, in the order it asks them. The first truthy one owns the turn
# (the real chain has a few extra gates - settings switches, "not memory and not system" - but
# the ORDER is this one, and it is the order the usage count follows).
CHAIN: tuple[str, ...] = (
    "parse_show_doctor", "parse_what_happened", "parse_export_command", "parse_directive",
    "te_manual_intent", "is_memory_command", "is_system_query", "parse_service_command",
    "parse_broadcast_command", "parse_paper_command", "is_services_query", "is_comfy_status_query",
    "is_weather_query", "is_song_query", "is_te_query", "is_library_query", "is_tv_query",
    "is_game_query", "is_research_query",
)

# verified: "regex" = the examples were run through the parser's own code with no station state;
# "runtime" = the parser reads station state (manuals on disk, the shelf index, the crystals), so
# the examples show the SHAPE and the live station decides.
BUILTINS: list[dict[str, Any]] = [
    {"id": "parse_show_doctor", "name": "Show doctor", "model": "show-doctor",
     "does": "Runs the show doctor: is the station on and not paused, who is listening, did lines go out "
             "unheard, how long has nobody talked, is the voice engine finishing voices, is the routing "
             "sane. Cures what the station owns (hands the air over, asks the writers for a live round) "
             "and says what it found.",
     "returns": "True when the sentence asks where the DJs went or says nobody is being heard",
     "examples": ["where are the DJs", "I'm not hearing the DJs", "what happened to the show",
                  "the DJs are quiet", "fix the show", "no dialogue"],
     "verified": "regex"},
    {"id": "parse_what_happened", "name": "What happened", "model": "script-report",
     "does": "Reads the newest script report's verdict and explanation and the last ten minutes of gaps, "
             "and says them plainly. A question about the running order, kept under the commands and "
             "above the model.",
     "returns": "True for 'what/why ... happened / went wrong / jumped / glitched / broke / erratic / script'",
     "examples": ["what happened", "what just happened to the script", "why did it jump",
                  "what went wrong there", "pine box, why was that so erratic"],
     "verified": "regex"},
    {"id": "parse_export_command", "name": "Export a cut of the broadcast", "model": "export",
     "does": "Saves out a window of the air: the last N seconds / minutes / hours of talk or of the full "
             "mix, the last N sentences, 'this dialogue', a bare 'export the broadcast' (the last five "
             "minutes of audio), a named screen's recording (the pine tab, the pine app, the pine cam, "
             "the PiP), or sets the export folder. Imperative-verb gated and held to the rule that the "
             "order must BE the sentence.",
     "returns": "{seconds, kind} | {seconds, screen} | {sentences} | {dir} | None",
     "examples": ["export the last five minutes", "grab the last two sentences", "export this dialogue",
                  "export the broadcast", "export the last ten minutes of the pine tab",
                  "export directory is /mnt/exports"],
     "verified": "regex"},
    {"id": "parse_directive", "name": "Standing instruction", "model": "directive",
     "does": "A standing order about the show. It must ADDRESS the station ('from now on', 'as a rule', "
             "'orchestrator:', 'remember that I like ...'), must name a road (callers, gallery, news, ads, "
             "memos, station IDs, track talk, banter, music, or the show), must not be a question, and "
             "once the order and the pleasantries are stripped nothing may be left. It is written into "
             "the policy book and, for a road with a dial, moves it more or less.",
     "returns": "{text, road, move, shape} | None",
     "examples": ["from now on fewer adverts", "orchestrator: more callers",
                  "remember that I like the gallery rounds", "from here on out no more station ids",
                  "as a rule, more news"],
     "verified": "regex"},
    {"id": "te_manual_intent", "name": "Show a gear manual page", "model": "manual",
     "does": "A DISPLAY order for the gear manuals: 'show me the sidekick manual', 'pull up the EQ page' "
             "puts the matching section of a Teenage Engineering manual on the panel and says which pages "
             "went up. Needs a device the box holds a manual for (or one opened in the last 15 minutes); "
             "'read me the front page' is the Gazette, not a manual.",
     "returns": "the section hit {slug, title, topic, pages} | None",
     "examples": ["show me the sidekick manual", "pull up the OP-1 sequencer page",
                  "open the EP-133 guide", "let me see the sidekick EQ section"],
     "verified": "runtime", "depends": "the device names in data/te/index.json (te_devices)"},
    {"id": "is_memory_command", "name": "Remember this", "model": "memory",
     "does": "'remember that ...', 'note ...', 'keep in mind ...', 'don't forget ...', 'make a note ...': "
             "files the rest of the sentence as a long-term memory the assistant reads back into every "
             "chat. A 'remember that I like <a road>' is a standing instruction instead.",
     "returns": "the thing to remember, or None",
     "examples": ["remember that my birthday is in June", "note: the garage code is 4411",
                  "keep in mind I prefer short answers", "don't forget the dentist on Friday"],
     "verified": "regex"},
    {"id": "is_system_query", "name": "System status", "model": "system",
     "does": "How the box itself is doing: RAM, CPU, GPU, VRAM, disk, load average, uptime, hardware, "
             "'how are you'. Answered from the host's own readings.",
     "returns": "True when a system word is in the sentence",
     "examples": ["how are you doing", "how is the spark doing", "how much ram is free",
                  "what is the gpu temperature", "system status", "what's your uptime"],
     "verified": "regex"},
    {"id": "parse_service_command", "name": "Restart a service", "model": "steward",
     "does": "'restart <service>' in plain words - restart / reboot / relaunch / bounce / revive / kick a "
             "named home service: ollama (the llm), comfyui (the image engine), searxng (web search), home "
             "assistant, whisper, piper, voice lab, open webui, xtts (the clones), bgutil, the agent "
             "itself. A command, so it outranks every status question.",
     "returns": "the census name of the service, or ''",
     "examples": ["restart comfyui", "reboot the llm", "bounce home assistant", "relaunch web search",
                  "kick whisper"],
     "verified": "regex"},
    {"id": "parse_broadcast_command", "name": "Route the broadcast", "model": "routing",
     "does": "The routing selectors, spoken: 'broadcast to the Nabu', 'send the music to the pine box', "
             "'route the replies here', 'broadcast to both', 'send the show nowhere'. A named stream "
             "(music, voices, replies) moves alone; otherwise the whole broadcast moves.",
     "returns": "the /api/dj/output payload {music|voice|reply: route, _said} | None",
     "examples": ["broadcast to the nabu", "send the music to the pine box", "route the replies here",
                  "broadcast to both", "switch the show to the app"],
     "verified": "regex"},
    {"id": "parse_paper_command", "name": "The Gazette", "model": "paper",
     "does": "The Pine Box Gazette by name: 'print the paper' / 'publish a new edition' prints a fresh "
             "edition; 'read me the front page' / 'what's in the gazette' reads the latest one.",
     "returns": "'print' | 'read' | ''",
     "examples": ["print the paper", "publish a new edition", "read me the front page",
                  "what's in the gazette", "show me the headlines"],
     "verified": "regex"},
    {"id": "is_services_query", "name": "Services census", "model": "steward",
     "does": "'how are the services doing' and its cousins: the census of every home service, OK or DOWN "
             "with a reason, plus the host's RAM in use and GPU temperature.",
     "returns": "True for a services / stack / containers status question",
     "examples": ["how are the services doing", "status of the stack", "are the containers running",
                  "check on the services", "service status"],
     "verified": "regex"},
    {"id": "is_comfy_status_query", "name": "ComfyUI status", "model": "comfy",
     "does": "'what's going on with ComfyUI' and every cousin: a question about the image engine (status, "
             "running, down, broken, fix, check on) is answered ABOUT the engine and never handed to it as "
             "a render request.",
     "returns": "True when comfy / the image engine is named together with an asking word",
     "examples": ["what's going on with comfyui", "is comfy running", "comfyui status",
                  "is the image engine down", "check on comfy"],
     "verified": "regex"},
    {"id": "is_weather_query", "name": "Weather", "model": "weather",
     "does": "Weather, forecast, temperature, rain / snow / wind / humidity, sunny / cloudy / storms, "
             "sunrise / sunset, or 'is it cold outside': looked up for the place named at the end of the "
             "sentence, else Home Assistant's home location.",
     "returns": "True when a weather word is in the sentence",
     "examples": ["what's the weather like", "will it rain tomorrow", "is it cold outside",
                  "forecast for Austin this weekend", "when is sunset"],
     "verified": "regex"},
    {"id": "is_song_query", "name": "A song in the crystal library", "model": "songsight",
     "does": "Fires when a song the station has analysed (a SongSight crystal) is named, or the library "
             "itself is asked about ('what songs do you know'); answers from the analysis: tempo, key, "
             "chords, instruments, lyrics. A musical word alone is not enough.",
     "returns": "True when a held song is named or the library is asked about",
     "examples": ["what songs do you know", "which tracks have you analysed",
                  "tell me about <a song title the station holds>"],
     "verified": "runtime", "depends": "the crystals under data (read_crystals); the library question is a regex"},
    {"id": "is_te_query", "name": "Gear manual question", "model": "manual",
     "does": "A question naming a Teenage Engineering device the box holds a manual for (OP-1, OP-Z, "
             "EP-133, the K.O. Sidekick ...), or a follow-up about a page / section / knob while a manual "
             "is open: answered from the cached official pages, citing page numbers.",
     "returns": "True when a device is named, or the open manual is being asked about",
     "examples": ["how do I set the tempo on the OP-1", "what does the EQ do on the sidekick",
                  "how do I sample on the EP-133", "which page covers the sequencer"],
     "verified": "runtime", "depends": "the device names in data/te/index.json (te_devices); the last example needs an open manual"},
    {"id": "is_library_query", "name": "The Library shelf", "model": "library",
     "does": "Worth asking the shelf? Any question the indexed documents on the shelf can answer - "
             "library.shelf_question is the judge (a question whose every word is in every book is "
             "refused). A document named outright always wins, even over the gear manuals.",
     "returns": "True when the shelf has an opinion",
     "examples": ["what does the mixing book say about compression",
                  "according to the manual on the shelf, how is sidechain set up",
                  "does anything on the shelf cover tape saturation"],
     "verified": "runtime", "depends": "the shelf index (library.index) and the library switch"},
    {"id": "is_tv_query", "name": "TV lookup", "model": "tv",
     "does": "Television: a show's episodes, seasons, premieres, finales, renewals and cancellations, "
             "where it streams (Netflix, HBO, Hulu ...), Rotten Tomatoes / IMDb - searched on the web and "
             "read back from the first screenful of each page.",
     "returns": "True when a television word is in the sentence",
     "examples": ["when does the new season of severance come out", "is the show renewed or cancelled",
                  "what's on netflix tonight", "when does the finale air",
                  "rotten tomatoes score for the bear"],
     "verified": "regex"},
    {"id": "is_game_query", "name": "Video game help", "model": "game",
     "does": "Cheats, walkthroughs, level selects, speedruns, unlocks, secrets, easter eggs, console "
             "commands, boss fights, move lists and combos, and any named franchise or console (Sonic, "
             "Zelda, Mario, Mortal Kombat, Sega, Nintendo, PlayStation ...) - searched on the web and kept "
             "in the cheats library.",
     "returns": "True when a game word, franchise or console is in the sentence",
     "examples": ["cheat codes for sonic 2", "how do I beat the first boss in zelda",
                  "level select on the genesis", "mortal kombat fatalities",
                  "skyrim console command for gold"],
     "verified": "regex"},
    {"id": "is_research_query", "name": "Documentation research", "model": "research",
     "does": "'documentation / datasheet / spec sheet / schematic / service manual / teardown / repair "
             "guide' or 'how does X work inside': a deep search through the web, the library and the "
             "feed snapshots, answered with sources.",
     "returns": "True when a documentation word is in the sentence",
     "examples": ["find the datasheet for the sn76489", "teardown of the game gear",
                  "service manual for the walkman", "how does a tape echo work internally"],
     "verified": "regex"},
]

# orch_command_run's verbs (ORCH_COMMAND_VERBS in app.py), one row per verb. The policy verbs and
# the rung keys are read live from the station at install time when it has them.
ORCH_FALLBACK_POLICY = ("noop", "ballast", "innings", "rest", "stock", "prefer", "postpone", "repeats",
                        "live", "skip", "tint", "drive", "piperok", "thin", "judgment")
ORCHESTRATOR: list[dict[str, Any]] = [
    {"id": "orch:help", "name": "help", "verb": "help | ? | verbs",
     "does": "List every verb the orchestrator's command line understands, the policy verbs and the rungs.",
     "examples": ["help", "verbs"]},
    {"id": "orch:more", "name": "more", "verb": "more <road>",
     "does": "Turn the judgment dial UP for a road (caller, gallery, news, ad, manager, station_id, track_talk, "
             "banter); the same dial the logic graph turns, and the turn lands in the judgment book.",
     "examples": ["more banter", "more callers"]},
    {"id": "orch:less", "name": "less", "verb": "less <road>",
     "does": "Turn the judgment dial DOWN for a road.", "examples": ["less ad", "less news"]},
    {"id": "orch:ease", "name": "ease", "verb": "ease <road>",
     "does": "Ease the judgment dial for a road a step back toward neutral.", "examples": ["ease gallery"]},
    {"id": "orch:drop", "name": "drop", "verb": "drop <road>",
     "does": "Drop the judgment dial for a road hard.", "examples": ["drop station_id"]},
    {"id": "orch:policy", "name": "a standing policy", "verb": "<verb>:<arg>",
     "does": "A standing policy for the orchestrator, applied and saved to the policy book: drive:banter, "
             "thin:0.5, drive:none ... The verbs are read off orch_apply.",
     "examples": ["drive:banter", "thin:0.5", "drive:none"]},
    {"id": "orch:run", "name": "run a rung", "verb": "run <rung>",
     "does": "Run one rung of the broadcast ladder by its key (triangulate, repair, look, keeper, comfy, onair, "
             "relieve, speed, reload_pages, flush, skip, handover, produce ...).",
     "examples": ["run look", "run repair"]},
    {"id": "orch:hear", "name": "hear a round now", "verb": "hear <id> | play <id>",
     "does": "Put that cupboard round on the air now, out of turn (the station must be on and not paused).",
     "examples": ["hear 3f9a1c2b7d6e5a40"]},
    {"id": "orch:retire", "name": "retire a round", "verb": "retire <id>",
     "does": "Take that round out of the cupboard.", "examples": ["retire 3f9a1c2b7d6e5a40"]},
    {"id": "orch:why", "name": "why a road is empty", "verb": "why <road>",
     "does": "Why that road has nothing behind it: the director's reading, with the last entries' labels, "
             "commits and reasons.", "examples": ["why news", "why caller"]},
    {"id": "orch:why-code", "name": "why a message", "verb": "why #<code>",
     "does": "One message's life story across every store (/api/why), by its message code.",
     "examples": ["why #a1b2c3d4"]},
    {"id": "orch:s3", "name": "System 3's desk", "verb": "s3 [know|playbook|survey|findings|untraced|coverage|mp4|display|receivers|tables|cupboard|files|tree <segment>|proposals|faculties]",
     "does": "Read System 3's desk: what it is made of, what is wrong with it, where it may act.",
     "examples": ["s3 know", "s3 findings", "s3 tree news"]},
    {"id": "orch:s3-propose", "name": "propose a System 3 change", "verb": "s3 table <ID> set <path>=<value> | s3 section <name> set <path>=<value> | s3 cupboard <id> cue|uncue|finish|retire|remove",
     "does": "Propose a System 3 change - it is shown, not made, until confirmed.",
     "examples": ["s3 table T01 set weight=2", "s3 cupboard 3f9a1c2b cue"]},
    {"id": "orch:s3-confirm", "name": "confirm / undo / hold a proposal", "verb": "s3 confirm <proposal> | s3 undo <proposal> | s3 hold <proposal>",
     "does": "Make a proposal, take it back, or leave it waiting.",
     "examples": ["s3 confirm p12", "s3 undo p12"]},
]

_CODE_RX = re.compile(r"^#?[0-9a-f]{6,32}(-p\d+)?$")
_LEAD_RX = re.compile(r"^(?:(?:hey|ok|okay|please|so|right|yo|pine ?box|pinebox|nabu)[,\s]+)*")
_TAIL_RX = re.compile(r"(?:[,\s]+(?:please|now|thanks|thank you|cheers))*[\s.!?,]*$")
_ID_RX = re.compile(r"[^a-z0-9]+")


class BookError(ValueError):
    """A request the book refuses (bad trigger, missing name); the route turns it into a 400."""


def _norm(text: Any) -> str:
    """Whitespace-collapsed, lower-cased, trailing punctuation gone: how two sayings are the same."""
    return " ".join(str(text or "").split()).lower().rstrip(" .!?,")


def _bare(text: Any) -> str:
    """_norm with the lead ('hey pine box,') and the pleasantries ('please', 'thanks') taken off."""
    said = _norm(text)
    said = _LEAD_RX.sub("", said, count=1)
    said = _TAIL_RX.sub("", said)
    return said.strip()


def _slug(name: str) -> str:
    return _ID_RX.sub("-", str(name or "").lower()).strip("-")[:48] or "command"


def _falsy_like(got: Any) -> Any:
    """What a disabled parser answers: a falsy value of the shape its callers test."""
    if isinstance(got, str):
        return ""
    if isinstance(got, bool):
        return False
    return None


def orch_id_for(line: str, policy_verbs: tuple[str, ...] | None = None) -> str:
    """Which orchestrator row a typed line belongs to ('' when the line is not a verb)."""
    raw = " ".join(str(line or "").split())
    if not raw:
        return ""
    head = raw.split(" ")[0].lower()
    arg = raw[len(head):].strip()
    first = arg.split(" ")[0].lower() if arg else ""
    if head in ("help", "?", "verbs"):
        return "orch:help"
    if head in ("more", "less", "ease", "drop") and arg:
        return "orch:" + head
    if head == "why" and arg:
        return "orch:why-code" if _CODE_RX.match(first) else "orch:why"
    if head in ("s3", "sys3", "system3"):
        if first in ("table", "section", "cupboard"):
            return "orch:s3-propose"
        if first in ("confirm", "undo", "hold"):
            return "orch:s3-confirm"
        return "orch:s3"
    if head in ("hear", "play") and arg:
        return "orch:hear"
    if head == "retire" and arg:
        return "orch:retire"
    if head in ("run", "step", "rung") and arg:
        return "orch:run"
    if ":" in raw:
        verb = raw.partition(":")[0].strip().lower()
        if verb in (policy_verbs or ORCH_FALLBACK_POLICY):
            return "orch:policy"
    return ""


class Trigger:
    """One trigger of a custom command: a whole sentence ('*' matches anything) or /regex/."""

    def __init__(self, raw: str):
        self.raw = str(raw or "").strip()
        if not self.raw:
            raise BookError("an empty trigger")
        if len(self.raw) > 300:
            raise BookError("a trigger longer than 300 characters")
        if len(self.raw) >= 2 and self.raw.startswith("/") and self.raw.endswith("/"):
            try:
                self.rx = re.compile(self.raw[1:-1], re.I)
            except re.error as exc:
                raise BookError("the regex %s does not compile: %s" % (self.raw, exc)) from None
            self.kind = "regex"
        else:
            self.kind = "phrase"
            bare = _bare(self.raw)
            if not bare:
                raise BookError("the phrase %r has no words" % self.raw)
            if "*" in bare:
                pattern = ".*?".join(re.escape(p).replace(r"\ ", r"\s+") for p in bare.split("*"))
                self.rx = re.compile(r"^\s*" + pattern.strip() + r"\s*$", re.I | re.S)
            else:
                self.rx = re.compile(r"^" + re.escape(bare).replace(r"\ ", r"\s+") + r"$", re.I)

    def matches(self, text: str) -> bool:
        if self.kind == "regex":
            return bool(self.rx.search(_norm(text)))
        return bool(self.rx.match(_bare(text)))


class CommandBook:
    def __init__(self, g: dict[str, Any]):
        self.g = g
        self._lock = threading.RLock()
        self._raw: dict[str, Any] = {}          # the parsers as they were before watch()
        self._last: dict[str, Any] = {"text": None, "at": 0.0, "id": ""}
        self._timer: threading.Timer | None = None
        self.counts: dict[str, dict[str, Any]] = {}
        self.notes: dict[str, str] = {}
        self.disabled: set[str] = set()
        self.custom: list[dict[str, Any]] = []
        self._triggers: dict[str, list[Trigger]] = {}
        self.loaded_at = 0.0
        self.load()

    # ---------------------------------------------------------------- the file
    def path(self) -> Path:
        fn = self.g.get("data_path")
        try:
            return Path(fn(FILE_NAME)) if callable(fn) else Path(self.g.get("DATA_DIR") or ".") / FILE_NAME
        except Exception:  # noqa: BLE001
            return Path(FILE_NAME)

    def load(self) -> None:
        try:
            raw = json.loads(self.path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        with self._lock:
            counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
            self.counts = {str(k): {"count": int((v or {}).get("count") or 0),
                                    "last_at": float((v or {}).get("last_at") or 0),
                                    "last_text": str((v or {}).get("last_text") or "")[:LAST_TEXT_CHARS]}
                           for k, v in counts.items() if isinstance(v, dict)}
            notes = raw.get("notes") if isinstance(raw.get("notes"), dict) else {}
            self.notes = {str(k): str(v)[:2000] for k, v in notes.items() if str(v or "").strip()}
            self.disabled = {str(x) for x in (raw.get("disabled") or []) if str(x)}
            self.custom = []
            self._triggers = {}
            for row in (raw.get("custom") or []):
                try:
                    clean = self._clean_custom(row)
                except BookError:
                    continue
                self.custom.append(clean)
            self.loaded_at = time.time()

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"version": 1, "saved_at": time.time(), "counts": json.loads(json.dumps(self.counts)),
                    "notes": dict(self.notes), "disabled": sorted(self.disabled),
                    "custom": json.loads(json.dumps(self.custom))}

    def save(self) -> Path:
        """Write the book atomically (tmp + replace)."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        path = self.path()
        data = json.dumps(self._snapshot(), indent=1, sort_keys=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except OSError:
                # a handle still on the file (Windows: an indexer, a reader): a moment, then again
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
        return path

    def save_soon(self) -> None:
        """Coalesce writes off the event loop: hits arrive on the loop, the file is written a second later."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            t = threading.Timer(SAVE_DELAY_S, self._save_quietly)
            t.daemon = True
            self._timer = t
            t.start()

    def _save_quietly(self) -> None:
        try:
            self.save()
        except Exception:  # noqa: BLE001
            pass

    def flush(self) -> None:
        self.save()

    # ---------------------------------------------------------------- counting
    def hit(self, cmd_id: str, text: Any) -> bool:
        """Record one use. The same text inside HIT_WINDOW_S is the same utterance: not counted twice."""
        norm = _norm(text)
        now = time.time()
        with self._lock:
            if norm and norm == self._last.get("text") and now - float(self._last.get("at") or 0) < HIT_WINDOW_S:
                return False
            self._last = {"text": norm, "at": now, "id": cmd_id}
            row = self.counts.setdefault(cmd_id, {"count": 0, "last_at": 0.0, "last_text": ""})
            row["count"] = int(row.get("count") or 0) + 1
            row["last_at"] = now
            row["last_text"] = " ".join(str(text or "").split())[:LAST_TEXT_CHARS]
        self.save_soon()
        return True

    def count_of(self, cmd_id: str) -> dict[str, Any]:
        with self._lock:
            row = self.counts.get(cmd_id) or {}
            return {"count": int(row.get("count") or 0), "last_at": float(row.get("last_at") or 0),
                    "last_text": str(row.get("last_text") or "")}

    def policy_verbs(self) -> tuple[str, ...]:
        fn = self.g.get("orch_verbs")
        try:
            got = tuple(str(v) for v in fn()) if callable(fn) else ()
        except Exception:  # noqa: BLE001
            got = ()
        return got or ORCH_FALLBACK_POLICY

    def rung_keys(self) -> list[str]:
        steps = self.g.get("BROADCAST_STEPS")
        try:
            return [str(s.get("key") or "") for s in (steps or []) if isinstance(s, dict) and s.get("key")]
        except Exception:  # noqa: BLE001
            return []

    def watch(self, names: tuple[str, ...] | list[str] | None = None) -> list[str]:
        """Wrap each parser global in g so a truthy return is a hit. Returns the names wrapped."""
        wrapped: list[str] = []
        for name in (names or CHAIN):
            fn = self.g.get(name)
            if not callable(fn) or getattr(fn, "_llm_watch", False):
                continue
            self._raw[name] = fn
            self.g[name] = self._wrap_sync(name, fn)
            wrapped.append(name)
        return wrapped

    def watch_orchestrator(self, name: str = "orch_command_run") -> bool:
        fn = self.g.get(name)
        if not callable(fn) or getattr(fn, "_llm_watch", False):
            return False
        self._raw[name] = fn
        book = self
        if inspect.iscoroutinefunction(fn):
            async def wrapped(text: str, *a: Any, **kw: Any) -> Any:
                got = await fn(text, *a, **kw)
                book._orch_hit(text, got)
                return got
        else:
            def wrapped(text: str, *a: Any, **kw: Any) -> Any:  # type: ignore[misc]
                got = fn(text, *a, **kw)
                book._orch_hit(text, got)
                return got
        wrapped._llm_watch = True  # type: ignore[attr-defined]
        wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapped.__name__ = getattr(fn, "__name__", name)
        wrapped.__doc__ = getattr(fn, "__doc__", None)
        self.g[name] = wrapped
        return True

    def _orch_hit(self, text: Any, got: Any) -> None:
        try:
            if isinstance(got, dict) and got.get("ok"):
                cmd_id = orch_id_for(str(text or ""), self.policy_verbs())
                if cmd_id:
                    self.hit(cmd_id, text)
        except Exception:  # noqa: BLE001
            pass

    def _wrap_sync(self, name: str, fn: Any) -> Any:
        book = self

        def wrapped(*a: Any, **kw: Any) -> Any:
            got = fn(*a, **kw)
            if got:
                if name in book.disabled:
                    return _falsy_like(got)
                text = a[0] if a else kw.get("text", "")
                book.hit(name, text)
            return got
        wrapped._llm_watch = True  # type: ignore[attr-defined]
        wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapped.__name__ = getattr(fn, "__name__", name)
        wrapped.__doc__ = getattr(fn, "__doc__", None)
        return wrapped

    def raw_parser(self, name: str) -> Any:
        fn = self._raw.get(name)
        if fn is None:
            fn = self.g.get(name)
            if getattr(fn, "_llm_watch", False):
                fn = getattr(fn, "__wrapped__", fn)
        return fn if callable(fn) else None

    # ---------------------------------------------------------------- custom commands
    def _clean_custom(self, row: Any, keep_id: str = "") -> dict[str, Any]:
        if not isinstance(row, dict):
            raise BookError("a command is an object")
        name = " ".join(str(row.get("name") or "").split())[:80]
        if not name:
            raise BookError("a command needs a name")
        raw_triggers = row.get("triggers")
        if isinstance(raw_triggers, str):
            raw_triggers = raw_triggers.splitlines()
        triggers = [" ".join(str(t).split()) for t in (raw_triggers or []) if str(t or "").strip()]
        if not triggers:
            raise BookError("a command needs at least one trigger sentence (or /regex/)")
        if len(triggers) > 40:
            raise BookError("more than 40 triggers")
        compiled = [Trigger(t) for t in triggers]
        does = row.get("does") if isinstance(row.get("does"), dict) else {}
        kinds = [k for k in ("as", "say", "orchestrator") if str(does.get(k) or "").strip()]
        if len(kinds) != 1:
            raise BookError("does must be exactly one of {as: sentence} {say: reply} {orchestrator: line}")
        kind = kinds[0]
        body = " ".join(str(does[kind]).split()) if kind != "say" else str(does[kind]).strip()
        if len(body) > (1200 if kind == "say" else 300):
            raise BookError("the %s text is too long" % kind)
        cmd_id = str(row.get("id") or keep_id or "").strip()
        if not cmd_id:
            cmd_id = "custom:" + _slug(name)
        elif not cmd_id.startswith("custom:"):
            cmd_id = "custom:" + _slug(cmd_id)
        enabled = bool(row.get("enabled", True))
        notes = str(row.get("notes") or "")[:2000]
        clean = {"id": cmd_id, "name": name, "triggers": triggers, "does": {kind: body},
                 "notes": notes, "enabled": enabled,
                 "created_at": float(row.get("created_at") or time.time()), "updated_at": time.time()}
        self._triggers[cmd_id] = compiled
        return clean

    def custom_upsert(self, row: Any) -> dict[str, Any]:
        clean = self._clean_custom(row)
        with self._lock:
            ids = [c["id"] for c in self.custom]
            if clean["id"] in ids:
                old = self.custom[ids.index(clean["id"])]
                clean["created_at"] = float(old.get("created_at") or clean["created_at"])
                self.custom[ids.index(clean["id"])] = clean
            else:
                # a fresh name that collides with an older command's id gets a numbered id
                base, n = clean["id"], 2
                while clean["id"] in ids:
                    clean["id"] = "%s-%d" % (base, n)
                    n += 1
                if clean["id"] != base:
                    self._triggers[clean["id"]] = self._triggers.pop(base)
                self.custom.append(clean)
        self.save()
        return dict(clean)

    def custom_delete(self, cmd_id: str) -> bool:
        with self._lock:
            before = len(self.custom)
            self.custom = [c for c in self.custom if c["id"] != cmd_id]
            self._triggers.pop(cmd_id, None)
            self.counts.pop(cmd_id, None)
            self.notes.pop(cmd_id, None)
            gone = len(self.custom) < before
        if gone:
            self.save()
        return gone

    def note(self, cmd_id: str, notes: Any = None, enabled: Any = None) -> dict[str, Any]:
        known = {r["id"] for r in BUILTINS} | {r["id"] for r in ORCHESTRATOR} | {c["id"] for c in self.custom}
        if cmd_id not in known:
            raise BookError("no command with id %r" % cmd_id)
        with self._lock:
            custom = next((c for c in self.custom if c["id"] == cmd_id), None)
            if notes is not None:
                text = str(notes or "")[:2000]
                if custom is not None:
                    custom["notes"] = text
                elif text.strip():
                    self.notes[cmd_id] = text
                else:
                    self.notes.pop(cmd_id, None)
            if enabled is not None:
                if custom is not None:
                    custom["enabled"] = bool(enabled)
                elif bool(enabled):
                    self.disabled.discard(cmd_id)
                else:
                    self.disabled.add(cmd_id)
        self.save()
        return self.row(cmd_id) or {}

    def match_custom(self, text: Any) -> tuple[dict[str, Any] | None, str]:
        """The first enabled custom command one of whose triggers matches, and the trigger that did."""
        if not str(text or "").strip():
            return None, ""
        with self._lock:
            rows = [dict(c) for c in self.custom if c.get("enabled", True)]
            trig = {k: list(v) for k, v in self._triggers.items()}
        for c in rows:
            for t in trig.get(c["id"]) or []:
                try:
                    if t.matches(text):
                        return c, t.raw
                except Exception:  # noqa: BLE001
                    continue
        return None, ""

    def rewrite(self, text: Any) -> tuple[str, dict[str, Any] | None]:
        """(the sentence the parsers should see, the custom command that said so or None)."""
        cmd, _trigger = self.match_custom(text)
        if cmd and "as" in cmd["does"]:
            self.hit(cmd["id"], text)
            return str(cmd["does"]["as"]), cmd
        return str(text or ""), None

    def fixed_reply(self, text: Any) -> str:
        cmd, _trigger = self.match_custom(text)
        if cmd and "say" in cmd["does"]:
            self.hit(cmd["id"], text)
            return str(cmd["does"]["say"])
        return ""

    def orchestrator_line(self, text: Any) -> str:
        cmd, _trigger = self.match_custom(text)
        if cmd and "orchestrator" in cmd["does"]:
            self.hit(cmd["id"], text)
            return str(cmd["does"]["orchestrator"])
        return ""

    # ---------------------------------------------------------------- reading the book
    def row(self, cmd_id: str) -> dict[str, Any] | None:
        for r in self.rows():
            if r["id"] == cmd_id:
                return r
        return None

    def rows(self) -> list[dict[str, Any]]:
        verbs = self.policy_verbs()
        rungs = self.rung_keys()
        out: list[dict[str, Any]] = []
        for order, spec in enumerate(BUILTINS, 1):
            r = dict(spec)
            r.update(kind="builtin", order=order, enabled=spec["id"] not in self.disabled,
                     notes=self.notes.get(spec["id"], ""), present=callable(self.g.get(spec["id"])),
                     watched=bool(getattr(self.g.get(spec["id"]), "_llm_watch", False)))
            r.update(self.count_of(spec["id"]))
            out.append(r)
        for order, spec in enumerate(ORCHESTRATOR, 1):
            r = dict(spec)
            if spec["id"] == "orch:policy":
                r["does"] = r["does"] + " Verbs now: " + ", ".join(verbs) + "."
            if spec["id"] == "orch:run" and rungs:
                r["does"] = "Run one rung of the broadcast ladder by its key: " + ", ".join(rungs) + "."
            r.update(kind="orchestrator", order=order, enabled=True, notes=self.notes.get(spec["id"], ""),
                     present=callable(self.g.get("orch_command_run")),
                     watched=bool(getattr(self.g.get("orch_command_run"), "_llm_watch", False)))
            r.update(self.count_of(spec["id"]))
            out.append(r)
        with self._lock:
            customs = [dict(c) for c in self.custom]
        for order, c in enumerate(customs, 1):
            kind = next(iter(c["does"]))
            r = dict(c)
            r.update(kind="custom", order=order, how=kind, text=c["does"][kind],
                     does=self._custom_words(kind, c["does"][kind]), examples=list(c["triggers"]),
                     present=True, watched=True)
            r.update(self.count_of(c["id"]))
            out.append(r)
        return out

    @staticmethod
    def _custom_words(kind: str, body: str) -> str:
        if kind == "as":
            return 'Says it to the station as: "%s" (the built-in parsers then answer it).' % body
        if kind == "say":
            return 'Answers with a fixed reply: "%s".' % body
        return 'Runs the orchestrator line: "%s".' % body

    def summary(self) -> dict[str, Any]:
        rows = self.rows()
        kinds = {"builtin": 0, "orchestrator": 0, "custom": 0}
        hits = 0
        for r in rows:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
            hits += int(r.get("count") or 0)
        top = sorted((r for r in rows if r.get("count")), key=lambda r: -int(r["count"]))[:3]
        say = ("%d commands on the book: %d built-in, %d orchestrator verbs, %d custom; used %d time(s)"
               % (len(rows), kinds["builtin"], kinds["orchestrator"], kinds["custom"], hits))
        if top:
            say += " - most used: " + ", ".join("%s %d" % (r["name"], r["count"]) for r in top)
        say += "."
        return {"at": time.time(), "rows": rows, "chain": list(CHAIN), "kinds": kinds, "hits": hits,
                "file": str(self.path()), "say": say}

    def try_text(self, text: Any) -> dict[str, Any]:
        """Dry run: which command would answer this sentence. No hit, no side effect."""
        said = " ".join(str(text or "").split())
        out: dict[str, Any] = {"text": said, "custom": None, "rewritten": "", "builtin": "", "also": [],
                               "skipped": [], "orchestrator": "", "say": ""}
        if not said:
            out["say"] = "say something first."
            return out
        cmd, trigger = self.match_custom(said)
        probe = said
        if cmd:
            kind = next(iter(cmd["does"]))
            out["custom"] = {"id": cmd["id"], "name": cmd["name"], "how": kind, "trigger": trigger,
                             "text": cmd["does"][kind]}
            if kind == "say":
                out["say"] = 'your command "%s" answers with its fixed reply.' % cmd["name"]
                return out
            if kind == "orchestrator":
                out["orchestrator"] = cmd["does"][kind]
                out["say"] = 'your command "%s" runs the orchestrator line "%s" (%s).' % (
                    cmd["name"], cmd["does"][kind], orch_id_for(cmd["does"][kind], self.policy_verbs()) or "not a verb")
                return out
            probe = cmd["does"]["as"]
            out["rewritten"] = probe
        for name in CHAIN:
            fn = self.raw_parser(name)
            if fn is None:
                continue
            try:
                got = fn(probe)
            except Exception:  # noqa: BLE001
                got = None
            if got:
                (out["skipped"] if name in self.disabled else out["also"]).append(name)
        names = {r["id"]: r["name"] for r in BUILTINS}
        if out["also"]:
            out["builtin"] = out["also"][0]
            lead = ('your command "%s" says it as "%s", and then ' % (cmd["name"], probe)) if cmd else ""
            out["say"] = lead + "%s (%s) answers" % (names.get(out["builtin"], out["builtin"]), out["builtin"])
            if len(out["also"]) > 1:
                out["say"] += "; %s would also have matched" % ", ".join(out["also"][1:])
            out["say"] += "."
        elif out["skipped"]:
            out["say"] = "%s would answer but is switched off, so the chat model gets it." % ", ".join(out["skipped"])
        else:
            lead = ('your command "%s" says it as "%s", but ' % (cmd["name"], probe)) if cmd else ""
            out["say"] = lead + "no built-in command claims it: the chat model answers."
        return out


# ---------------------------------------------------------------- module-level doors app.py calls
_BOOK: CommandBook | None = None


def book() -> CommandBook | None:
    return _BOOK


def rewrite(text: Any) -> tuple[str, dict[str, Any] | None]:
    """[llm-command] generate_answer's first stop: a custom 'as' alias becomes the sentence the parsers see."""
    if _BOOK is None:
        return str(text or ""), None
    try:
        return _BOOK.rewrite(text)
    except Exception:  # noqa: BLE001
        return str(text or ""), None


def fixed_reply(text: Any) -> str:
    if _BOOK is None:
        return ""
    try:
        return _BOOK.fixed_reply(text)
    except Exception:  # noqa: BLE001
        return ""


def orchestrator_line(text: Any) -> str:
    if _BOOK is None:
        return ""
    try:
        return _BOOK.orchestrator_line(text)
    except Exception:  # noqa: BLE001
        return ""


def watch(g: dict[str, Any], names: tuple[str, ...] | list[str] | None = None) -> list[str]:
    """Wrap the named parser globals of g (default: the whole chain) so their truthy returns count."""
    global _BOOK
    bk = g.get("LLM_COMMANDS")
    if not isinstance(bk, CommandBook):
        bk = CommandBook(g)
        g["LLM_COMMANDS"] = bk
    if _BOOK is None:
        _BOOK = bk
    return bk.watch(names)


def install(app: Any, g: dict[str, Any]) -> CommandBook:
    """Build the book on g, watch the parsers and the orchestrator line, and mount the routes."""
    global _BOOK
    if isinstance(g.get("LLM_COMMANDS"), CommandBook):
        return g["LLM_COMMANDS"]
    bk = CommandBook(g)
    g["LLM_COMMANDS"] = bk
    _BOOK = bk
    bk.watch()
    bk.watch_orchestrator()
    if app is None or Header is None:
        return bk

    def _auth(authorization: str | None, write: bool) -> None:
        fn = g.get("require_auth" if write else "require_read_auth")
        if callable(fn):
            fn(authorization)

    async def _body(request: Any) -> dict[str, Any]:
        try:
            got = await request.json()
        except Exception:  # noqa: BLE001
            got = {}
        return got if isinstance(got, dict) else {}

    @app.get("/api/llm-commands")
    async def api_llm_commands(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """[llm-command] Every command the assistant understands, with its usage count."""
        _auth(authorization, False)
        return bk.summary()

    # The write doors answer PUT / DELETE and a POST twin each: the desk's preload bridge
    # carries get and post, and the popup must work from the desk, the PiP and the tablet alike.
    @app.put("/api/llm-commands/custom")
    @app.post("/api/llm-commands/custom")
    async def api_llm_commands_custom_put(request: Request,
                                          authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """[llm-command] Add or change one of the operator's own commands."""
        _auth(authorization, True)
        body = await _body(request)
        try:
            row = bk.custom_upsert(body)
        except BookError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "row": bk.row(row["id"]) or row, "say": 'saved "%s".' % row["name"]}

    @app.delete("/api/llm-commands/custom/{cmd_id}")
    @app.post("/api/llm-commands/custom/{cmd_id}/delete")
    async def api_llm_commands_custom_delete(cmd_id: str,
                                             authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """[llm-command] Remove one of the operator's own commands."""
        _auth(authorization, True)
        gone = bk.custom_delete(cmd_id)
        if not gone:
            raise HTTPException(status_code=404, detail="no custom command with id %r" % cmd_id)
        return {"ok": True, "id": cmd_id, "say": "removed."}

    @app.put("/api/llm-commands/note/{cmd_id}")
    @app.post("/api/llm-commands/note/{cmd_id}")
    async def api_llm_commands_note(cmd_id: str, request: Request,
                                    authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """[llm-command] {notes} and/or {enabled} on any row of the book."""
        _auth(authorization, True)
        body = await _body(request)
        try:
            row = bk.note(cmd_id, notes=body.get("notes") if "notes" in body else None,
                          enabled=body.get("enabled") if "enabled" in body else None)
        except BookError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "row": row, "say": "noted."}

    @app.post("/api/llm-commands/try")
    async def api_llm_commands_try(request: Request,
                                   authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """[llm-command] Which command would answer this sentence - a dry run, nothing counted."""
        _auth(authorization, False)
        body = await _body(request)
        return bk.try_text(str(body.get("text") or "")[:600])

    return bk
