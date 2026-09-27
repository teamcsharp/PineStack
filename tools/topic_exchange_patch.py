"""The topic desk's numbered exchange (operator, 2026-09-27): "allow me to use
1 and 2 number with topics to set a topic and a response that is offered to
the next conversational line ... I want to be able to type
    1. This is my studio
    2. That's what you think
and that is an exchange that is used in the dialogue in the studio when that
topic is used."

A saved topic keeps the answer as its own `reply` field (never a newline in
`text`: the line inspector edits the bank one topic per line). Everywhere a
topic reaches the writer - the queued scenario, "Use this scenario now", the
station's own draw - the exchange rides along: the angle states it word for
word with A raising it, the seed draw steps aside (a passage would take row
1), and System 3 puts the two lines on rows 1 and 2 of its running order.

Idempotent: --check exits 0 ready / 2 applied / 1 anchor missing; --apply
writes. Run on the host:
    cat tools/topic_exchange_patch.py | ssh HOST 'cd ~/pinevoice-stack/spark-agent && python3 - --apply app.py'
"""
import sys

EDITS = [
    ("split-and-add",
     '''def add_bombshell(text: str, kind: str = "topic", by: str = "operator",
                  source: str = "") -> dict[str, Any]:
    """A line or a topic to drop on air."""''',
     '''def split_exchange(text: str) -> tuple[str, str]:
    """[topic-exchange] "1. This is my studio / 2. That's what you think" ->
    (the line the round opens on, the answer to it). Anything else is a
    plain topic with no answer."""
    raw = str(text or "").strip()
    m = re.match(r"^\\s*1\\s*[.)]\\s*(.+?)\\s*(?:\\n|\\s)\\s*2\\s*[.)]\\s*(.+?)\\s*$", raw, re.S)
    if not m:
        return raw, ""
    return " ".join(m.group(1).split()), " ".join(m.group(2).split())


def add_bombshell(text: str, kind: str = "topic", by: str = "operator",
                  source: str = "", reply: str = "") -> dict[str, Any]:
    """A line or a topic to drop on air."""'''),
    ("row-reply",
     '''            **({"source": str(source)[:120]} if source else {}),
        }
        rows.insert(0, row)''',
     '''            **({"source": str(source)[:120]} if source else {}),
            # [topic-exchange] the answer to it, word for word
            **({"reply": " ".join(str(reply).split())[:400]} if str(reply or "").strip() else {}),
        }
        rows.insert(0, row)'''),
    ("angle-signature",
     '''def bombshell_angle(text: str, shape: str = "") -> str:''',
     '''def bombshell_angle(text: str, shape: str = "", reply: str = "") -> str:'''),
    ("angle-exchange",
     '''    variety, including the ones written before this existed."""
    first = random.choice(["A", "B"])''',
     '''    variety, including the ones written before this existed."""
    if str(reply or "").strip():
        # [topic-exchange] the operator wrote the opening exchange: A says
        # the first line as written, B answers with the second as written,
        # and the round grows out of that. No shape roll, no random raiser.
        _open = " ".join(str(text).split())
        _back = " ".join(str(reply).split())
        return ("THE TOPIC, DROPPED INTO THIS ROUND: \\"" + _open + "\\"\\n"
                + "THE EXCHANGE THAT OPENS IT, WORD FOR WORD:\\n"
                + "A says: " + json.dumps(_open) + "\\n"
                + "B answers: " + json.dumps(_back) + "\\n"
                + "HOW IT GOES (" + TOPIC_STARTER_SHAPE + "): A opens the round with those exact "
                  "words, B answers with those exact words, and the conversation comes out "
                  "of that exchange.\\n"
                + "Never read this instruction out loud. Say both lines exactly as written - "
                  "they are the operator's own.")
    first = random.choice(["A", "B"])'''),
    ("queue",
     '''    shape = bombshell_shape_for(row)
    entry = {
        "id": uuid.uuid4().hex[:10],
        "kind": "rant",
        "round": "bombshell",
        "face": "the operator's scenario",
        "premise": bombshell_angle(text, shape),''',
     '''    shape = bombshell_shape_for(row)
    _reply = " ".join(str((row or {}).get("reply") or "").split())   # [topic-exchange]
    entry = {
        "id": uuid.uuid4().hex[:10],
        "kind": "rant",
        "round": "bombshell",
        "face": "the operator's scenario",
        "premise": bombshell_angle(text, shape, _reply),
        "exchange": ({"opener": text, "reply": _reply} if _reply else {}),'''),
    ("add-route",
     '''    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Give them something")
    row = await asyncio.to_thread(
        add_bombshell, text, str(payload.get("kind") or "topic"))''',
     '''    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Give them something")
    # [topic-exchange] "1. ... 2. ..." is a line and the answer to it
    text, _reply = split_exchange(text)
    _reply = _reply or " ".join(str(payload.get("reply") or "").split())
    row = await asyncio.to_thread(
        add_bombshell, text, str(payload.get("kind") or "topic"), "operator", "", _reply)'''),
    ("drop-route",
     '''    lines = await dj_banter(_RADIO.get("now"),
                            angle=bombshell_angle(row["text"], _shape))''',
     '''    _reply = " ".join(str(row.get("reply") or "").split())   # [topic-exchange]
    lines = await dj_banter(_RADIO.get("now"),
                            angle=bombshell_angle(row["text"], _shape, _reply),
                            exchange=({"opener": row["text"], "reply": _reply} if _reply else None))'''),
    ("writer-signature",
     '''                    news_titles: str = "",
                    ) -> list[str]:
    """A short exchange between the two, spoken in their own voices.''',
     '''                    news_titles: str = "",
                    # [topic-exchange] {opener, reply}: the operator's opening
                    # exchange, said word for word on rows 1 and 2
                    exchange: dict[str, Any] | None = None,
                    # [s3-roads] which road this round is: System 3 plans it
                    # from that road's own structure and records it as such
                    road: str = "",
                    ) -> list[str]:
    """A short exchange between the two, spoken in their own voices.'''),
    ("seed-steps-aside",
     '''    if not caller_name and not seed and not own_material and (
            force_seed or random.random() < box_rate_now(dj["speakbox_rate"])):''',
     '''    if not caller_name and not seed and not own_material and not exchange and (   # [topic-exchange]
            force_seed or random.random() < box_rate_now(dj["speakbox_rate"])):'''),
    ("dropped-topic",
     '''    elif dropped:
        angle = bombshell_angle(dropped["text"],
                                dropped.get("shape") or "")''',
     '''    elif dropped:
        _dreply = " ".join(str(dropped.get("reply") or "").split())   # [topic-exchange]
        angle = bombshell_angle(dropped["text"],
                                dropped.get("shape") or "", _dreply)
        if _dreply and not exchange:
            exchange = {"opener": dropped["text"], "reply": _dreply}'''),
    ("to-system3",
     '''                    call_sheet=call_sheet)''',
     '''                    call_sheet=call_sheet, exchange=exchange)   # [topic-exchange]'''),
    ("loop-reset",
     '''            _chosen = switchboard_take()
            _RADIO["switch_angle"] = ""''',
     '''            _chosen = switchboard_take()
            _RADIO["switch_angle"] = ""
            _RADIO["switch_exchange"] = {}   # [topic-exchange]'''),
    ("loop-set",
     '''                _RADIO["switch_angle"] = str(_chosen.get("premise") or "")''',
     '''                _RADIO["switch_angle"] = str(_chosen.get("premise") or "")
                _RADIO["switch_exchange"] = dict(_chosen.get("exchange") or {})   # [topic-exchange]'''),
    ("loop-interject",
     '''                    # own bombshell exactly as the schedule would have.
                    _RADIO["switch_angle"] = ""''',
     '''                    # own bombshell exactly as the schedule would have.
                    _RADIO["switch_angle"] = ""
                    _RADIO["switch_exchange"] = {}   # [topic-exchange]'''),
    ("loop-bombshell",
     '''                    angle = str(_RADIO.get("switch_angle") or "")
                    if not angle:
                        shell = drop_bombshell()
                        angle = (bombshell_angle(shell["text"],
                                                 shell.get("shape") or "")
                                 if shell and shell.get("text") else "")
                    aired = bool(await dj_banter(
                        track, angle=angle or None,
                        render_stream=bool(dj.get("stream_show", True))))''',
     '''                    angle = str(_RADIO.get("switch_angle") or "")
                    _exch = dict(_RADIO.get("switch_exchange") or {}) if angle else {}   # [topic-exchange]
                    if not angle:
                        shell = drop_bombshell()
                        _sreply = " ".join(str((shell or {}).get("reply") or "").split())
                        angle = (bombshell_angle(shell["text"],
                                                 shell.get("shape") or "", _sreply)
                                 if shell and shell.get("text") else "")
                        if _sreply and shell and shell.get("text"):
                            _exch = {"opener": shell["text"], "reply": _sreply}
                    aired = bool(await dj_banter(
                        track, angle=angle or None,
                        render_stream=bool(dj.get("stream_show", True)),
                        exchange=_exch or None))'''),
]


def check(text):
    applied = sum(1 for _n, _o, new in EDITS if new in text)
    missing = [name for name, old, new in EDITS if new not in text and text.count(old) != 1]
    return applied, missing


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "app.py"
    text = open(path, "rb").read().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if applied == len(EDITS):
        print("already applied (%d edits)" % applied)
        return 2
    if missing:
        print("anchors missing or not unique: " + ", ".join(missing))
        return 1
    for _name, old, new in EDITS:
        if new not in text:
            text = text.replace(old, new, 1)
    if "--apply" not in sys.argv:
        print("ready: %d edits" % (len(EDITS) - applied))
        return 0
    import ast
    ast.parse(text)
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    print("applied %d edits" % (len(EDITS) - applied))
    return 0


if __name__ == "__main__":
    sys.exit(main())
