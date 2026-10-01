"""[h3-overview] THE TECHNICAL OVERVIEW: an hourly H3 ad that sells one of the
station's own features, presented at a whiteboard.

"Whenever this preset is active, I want the person coming out giving a technical
presentation on a whiteboard presenting one of the features mentioned in the
release log ... animated ... a dynamic list of gestures ... randomly grab a
feature of the release log, send it through an LLM call to extend out the
details of it while providing it with detailed information about the particular
Git info ... For the system prompt for the LLM ... stored in a database where
we're able to cycle between multiple variants ... constructed using systems that
we have built so that way we're able to reassemble it in any other way."
                                                        - the operator, 2026-10-01
His answers: the changelog's tagged features; one 10-second clip; the presenter
rolled from a cast list; 1 to 3 actions.

Pure: no station, no network, no clock. app.py's door (h3_overview_prepare)
rolls every choice through System 3's dice doors over tabled pools the desk
edits - the feature (h3.overview_feature), the presenter (h3.overview_presenter),
how many actions (h3.overview_action_count) and which (h3.overview_action), the
props an action carries - takes the system prompt from the segment-prompt book
(kind "h3_overview", its alternatives rolled by weight) and asks the model. What
comes back is the hour's words: `say` (spoken, whole sentences, within the
clip's word cap) and the whiteboard scene for `goal`.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

PROMPT_KIND = "h3_overview"
TAG = re.compile(r"^((?:\[[\w:.-]+\]\s*)+)")
SKIP_SUBJECTS = re.compile(r"^(handoff|merge|revert)\b", re.I)

# the operator's list, as the pool starts; the desk adds, weights and retires
ACTIONS = (
    "comes out swinging their arms",
    "snaps a crisp salute",
    "whistles a jaunty tune",
    "throws punches at a second presenter, who throws them back",
    "carries in a box of kittens",
    "carries in a framed picture from the Pine Box gallery: {gallery}",
    "carries in a billboard of the git log reading: {gitlog}",
    "carries in a billboard of the DJs' dialogue reading: {dialogue}",
)
PRESENTERS = (
    "a wild-haired scientist in a lab coat",
    "a fast-talking used-car salesman",
    "a nervous intern on their first day",
    "a stern drill sergeant",
    "a game-show host with a sparkling smile",
    "a sleep-deprived engineer in a hoodie",
    "a late-night infomercial pitchman",
    "a theatrical magician in a cape",
)
ACTION_COUNTS = ("1", "2", "3")

# the system prompts the book starts with (kind "h3_overview"); the operator
# adds, edits, weights and switches them off over /api/segment/prompts
SYSTEM_PROMPTS = (
    ("Infomercial pitch",
     "You write the spoken words and the stage direction for a 10-second animated video ad in which a presenter "
     "at a whiteboard sells ONE technical feature of the Pine Box FM radio station's own software. You are given "
     "the feature's git history: its tag, commit subjects and messages, the files it touched and its size. Turn "
     "the engineering into a benefit a listener would cheer for, with infomercial energy and one concrete, true "
     "detail from the commits. Never invent features that are not in the history."),
    ("TED talk",
     "You write a 10-second animated whiteboard presentation for Pine Box FM. A presenter explains ONE feature of "
     "the station's software, drawn from its git history, like the most important idea of the century: grave, "
     "inspired, slightly absurd. Use one real detail from the commits - a number, a file, a behaviour - and make "
     "it sound world-changing."),
    ("Hard sell",
     "You write a 10-second hard-sell video ad, delivered at a whiteboard, for ONE feature of the Pine Box FM "
     "station software. You get the feature's commits. Sell it like it is going off the market tonight: urgent, "
     "loud, funny, specific. Name the feature in plain words a listener understands, and keep every claim true "
     "to the commits."),
)

REPLY_SHAPE = ('Answer with ONE JSON object and nothing else: {"say": "<the spoken words: whole sentences, at most '
               '%d words, every sentence a complete one of at least five words>", "do": "<one or two sentences of stage direction for the presenter at the whiteboard: '
               'what they draw, point at and do>"}')


def tag_of(subject: Any) -> str:
    """The first tag of a commit subject ("[s3-callarc] ..." -> "s3-callarc"), or ""."""
    m = TAG.match(str(subject or "").strip())
    if not m:
        return ""
    first = re.match(r"\[([\w:.-]+)\]", m.group(1))
    return first.group(1) if first else ""


def features(rows: Iterable[dict[str, Any]], most: int = 160) -> dict[str, dict[str, Any]]:
    """Changelog rows (changelog.ChangeLog._row) grouped by their first tag - one
    feature per tag, newest first, with every commit under it."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        git = r.get("git") if isinstance(r.get("git"), dict) else {}
        subject = str(git.get("subject") or r.get("task_name") or "").strip()
        tag = tag_of(subject)
        if not tag or SKIP_SUBJECTS.match(subject) or SKIP_SUBJECTS.match(tag):
            continue
        f = out.get(tag)
        if f is None:
            if len(out) >= most:
                continue
            f = out[tag] = {"tag": tag, "commits": [], "files": {}, "insertions": 0, "deletions": 0}
        f["commits"].append({"commit": str(r.get("short_commit") or str(r.get("commit") or "")[:8]),
                             "subject": TAG.sub("", subject).strip(),
                             "body": str(git.get("body") or r.get("result") or "")[:2400],
                             "at": str(git.get("committed_label") or r.get("completed_label") or "")})
        for fl in r.get("files") or []:
            if isinstance(fl, dict) and fl.get("path"):
                f["files"][str(fl["path"])] = f["files"].get(str(fl["path"]), 0) + int(fl.get("added") or 0) \
                    + int(fl.get("deleted") or 0)
        f["insertions"] += int(r.get("insertions") or 0)
        f["deletions"] += int(r.get("deletions") or 0)
    return out


def feature_label(f: dict[str, Any]) -> str:
    first = (f.get("commits") or [{}])[0]
    return "[%s] %s" % (f.get("tag"), str(first.get("subject") or "")[:90])


def brief(f: dict[str, Any], most_chars: int = 5000) -> str:
    """Everything the model needs to know about one feature, from git."""
    lines = ["FEATURE TAG: [%s]" % f.get("tag"),
             "SIZE: %d commit(s), +%d / -%d lines" % (len(f.get("commits") or []), int(f.get("insertions") or 0),
                                                     int(f.get("deletions") or 0))]
    files = sorted((f.get("files") or {}).items(), key=lambda kv: -kv[1])[:12]
    if files:
        lines.append("FILES TOUCHED: " + ", ".join("%s (%d lines)" % (p, n) for p, n in files))
    for c in (f.get("commits") or [])[:6]:
        lines.append("")
        lines.append("COMMIT %s %s: %s" % (c.get("commit"), c.get("at") or "", c.get("subject")))
        if c.get("body"):
            lines.append(str(c["body"]).strip())
    return "\n".join(lines)[:most_chars]


def messages(system: str, feature_brief: str, presenter: str, actions: list[str], words: int) -> list[dict[str, str]]:
    user = (feature_brief + "\n\nTHE PRESENTER: " + presenter + ".\nWHAT THEY DO DURING IT (work these in): "
            + "; ".join(actions) + ".\n\n" + (REPLY_SHAPE % max(6, int(words))))
    return [{"role": "system", "content": str(system or SYSTEM_PROMPTS[0][1])},
            {"role": "user", "content": user}]


def parse(reply: Any, words: int) -> dict[str, str]:
    """The model's JSON, or the best reading of what it wrote. `say` is cut to
    whole sentences inside the word cap; {} when there is no usable `say`."""
    text = re.sub(r"<think>.*?</think>", "", str(reply or ""), flags=re.S).strip()
    got: dict[str, Any] = {}
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            got = json.loads(m.group(0))
        except ValueError:
            got = {}
    if not isinstance(got, dict) or not str(got.get("say") or "").strip():
        say_m = re.search(r'"?say"?\s*[:=]\s*"([^"]+)"', text)
        do_m = re.search(r'"?do"?\s*[:=]\s*"([^"]+)"', text)
        got = {"say": say_m.group(1) if say_m else "", "do": do_m.group(1) if do_m else ""}
    say = " ".join(str(got.get("say") or "").split())
    do = " ".join(str(got.get("do") or "").split())[:400]
    if not say:
        return {}
    return {"say": cut_words(say, words), "do": do}


def keep_whole(say: str, why: Any) -> str:
    """Only the sentences `why` (h3_speak.speech_why) passes, in order."""
    sents = [x.strip() for x in re.findall(r"[^.!?]+[.!?]+[\"')\]]*", str(say or ""))]
    return " ".join(x for x in sents if x and not why(x))


def fallback_say(station: str, f: dict[str, Any], words: int) -> str:
    """The pitch when the model gives none: the feature's own first subject."""
    first = (f.get("commits") or [{}])[0]
    what = str(first.get("subject") or f.get("tag") or "something new").strip().rstrip(".!?")
    return cut_words("%s just got better. %s!" % (station or "Pine Box FM", what[:1].upper() + what[1:]), words)


def cut_words(text: str, words: int) -> str:
    """Whole sentences inside `words`; one sentence cut and closed when even the
    first is longer."""
    sents = re.findall(r"[^.!?]+[.!?]+[\"')\]]*", text) or [text]
    out: list[str] = []
    n = 0
    for s in sents:
        w = len(s.split())
        if n + w > words:
            break
        out.append(s.strip())
        n += w
    if out:
        return " ".join(out)
    first = " ".join(sents[0].split()[:max(3, words)]).rstrip(",;:- ")
    return first if re.search(r"[.!?]$", first) else first + "."


def fill_action(action: str, props: dict[str, str]) -> str:
    out = str(action or "")
    for k, v in (props or {}).items():
        out = out.replace("{" + k + "}", str(v or ""))
    return re.sub(r"\{[a-z_]+\}", "", out).strip().rstrip(":").strip()


def scene(presenter: str, f: dict[str, Any], do: str, actions: list[str]) -> str:
    """The whiteboard scene - the hour's `goal`, which the roads' directions wrap."""
    head = ("A technical presentation at a whiteboard: %s presents the Pine Box feature [%s] to camera, "
            "animated and full of energy." % (presenter, f.get("tag")))
    body = (" " + do) if do else ""
    acts = (" During it the presenter " + "; then ".join(actions) + ".") if actions else ""
    return (head + body + acts).strip()
