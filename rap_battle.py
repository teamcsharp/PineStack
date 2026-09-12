"""#1090: the whole day as one continuous rap battle.

The operator: "I want the entire station being handled and rationalized in
system 2 as a rap battle for the station... a constantly streaming rap battle
between the hosts, callers, manager, sfx guy, and whoever else is added to the
mix."

The station already had every ingredient and no THREAD: each round was written
as if the room had just been introduced to itself. Nothing told the writer who
had held the floor a minute ago, what they had actually said, or that the next
turn was an answer to it - so a caller, a memo from upstairs and a news read
were three unrelated errands rather than three exchanges in one argument.

This module keeps that thread. It stores nothing but what was said, by whom,
and when; it makes no model call and reads no settings. `clause()` turns the
thread into the paragraph a writer needs, and every road that writes dialogue
gets the same paragraph, so the battle is the fabric rather than a segment.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

# The seats that can throw a bar. The SFX guy and the manager are combatants
# too - the operator named them - and a caller enters as a challenger.
COMBATANTS = ("dj", "cohost", "third", "caller", "caller2", "manager", "drop")
SEAT_NAMES = {
    "dj": "the DJ", "cohost": "the co-host", "third": "the third chair",
    "caller": "the caller", "caller2": "the second caller",
    "manager": "the manager upstairs", "drop": "the SFX guy",
}
# How many exchanges the thread remembers. Long enough to answer an answer,
# short enough that the clause stays a paragraph and not a transcript.
THREAD_KEEP = 6
# A bar older than this is not a live exchange any more; the battle continues
# but the next turn opens a new volley rather than answering a stale one.
ANSWER_WINDOW = 900.0
# The night's running sound. Carried in the clause so bars an hour apart still
# rhyme with each other, which is what makes a day sound like one battle.
MOTIFS = (
    "copper", "cathedral", "ledger", "meridian", "furnace", "aperture",
    "quarantine", "cartography", "sediment", "apparatus", "monolith",
    "inventory", "filament", "arbitrage", "reliquary", "escapement",
)


def _words(text):
    return re.findall(r"[A-Za-z][A-Za-z'-]*", str(text or ""))


def _landing(text):
    """The last word of the last bar - what a challenger must not reuse."""
    bars = [b for b in re.split(r"\s*/\s*", str(text or "")) if b.strip()]
    tail = _words(bars[-1]) if bars else _words(text)
    return tail[-1].lower() if tail else ""


class RapBattle:
    """The thread of the night, on disk, safe to read from any thread."""

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.RLock()
        self.state = None

    # --- storage --------------------------------------------------------
    def _blank(self):
        return {"round": 0, "opened_at": self.clock(), "thread": [],
                "standing": {}, "motif": ""}

    def _load(self):
        if self.state is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            self.state = data if isinstance(data, dict) else self._blank()
            self.state.setdefault("round", 0)
            self.state.setdefault("thread", [])
            self.state.setdefault("standing", {})
            self.state.setdefault("motif", "")
            self.state.setdefault("opened_at", self.clock())
        return self.state

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass            # the battle is not worth an exception on the air

    # --- the thread -----------------------------------------------------
    def note(self, who, text, kind=""):
        """A bar went out. Returns the round it became, or 0 if it was not a bar.

        Only a real spoken turn from a combatant counts. Stings, markers and
        the board's noises are the crowd, not the fight.
        """
        who = str(who or "")
        said = " ".join(str(text or "").split())
        if who not in COMBATANTS or len(_words(said)) < 3:
            return 0
        with self.lock:
            state = self._load()
            state["round"] = int(state.get("round") or 0) + 1
            if not state.get("motif"):
                state["motif"] = MOTIFS[state["round"] % len(MOTIFS)]
            state["thread"].append({
                "round": state["round"], "who": who, "kind": str(kind or "")[:24],
                "at": self.clock(), "text": said[:400], "landing": _landing(said),
            })
            del state["thread"][:-THREAD_KEEP]
            seat = state["standing"].setdefault(
                who, {"bars": 0, "answers": 0, "last_at": 0.0})
            seat["bars"] += 1
            seat["last_at"] = self.clock()
            if len(state["thread"]) > 1 and state["thread"][-2]["who"] != who:
                seat["answers"] += 1
            self._save()
            return state["round"]

    def open_round(self):
        """A fresh night. The standing is kept; the volley starts clean."""
        with self.lock:
            state = self._load()
            state.update(thread=[], opened_at=self.clock(),
                         motif=MOTIFS[int(self.clock()) % len(MOTIFS)])
            self._save()
            return state["round"]

    def read(self):
        with self.lock:
            return json.loads(json.dumps(self._load()))

    # --- the paragraph a writer needs ------------------------------------
    def clause(self, up_next=""):
        """The battle, in the words the writer acts on.

        `up_next` is the seat about to write, when the road knows it. The
        clause never invents a fact: it quotes what was actually said and
        says whose turn it is, which is framing, not new material.
        """
        with self.lock:
            state = self._load()
            thread = list(state.get("thread") or [])
            now = self.clock()
            live = [row for row in thread
                    if now - float(row.get("at") or 0) <= ANSWER_WINDOW]
            last = live[-1] if live else None
            standing = state.get("standing") or {}
            ranked = sorted(standing.items(),
                            key=lambda kv: -int(kv[1].get("bars") or 0))[:3]

        head = ("\n\nTHE BATTLE (#1090) — this station is one continuous rap "
                "battle and has been all day. Round "
                + str(int(state.get("round") or 0) + 1)
                + ". Every seat is a combatant: the DJ, the co-host, the third "
                "chair, whoever rings in, the manager upstairs and the SFX guy. "
                "Whatever this segment is for — a record, a call, the news, a "
                "memo — it is ALSO your turn in the battle, and you do the "
                "segment's job in bars aimed at somebody.\n")

        if last:
            who = SEAT_NAMES.get(last["who"], last["who"])
            body = ("ANSWER THIS. " + who + " held the floor last and said:\n\""
                    + last["text"] + "\"\n"
                    "You are replying to that, not starting fresh. Pick up their "
                    "image and turn it against them, or take the sound they landed "
                    "on and beat it with a longer one. ")
            if last.get("landing"):
                body += ("Do not land on \"" + last["landing"] + "\" yourself — "
                         "answering a word with itself is a forfeit. ")
            if up_next and up_next == last["who"]:
                body += ("You are also the one who said it, so this is you "
                         "pressing your own point further, not repeating it. ")
            body += "\n"
        else:
            body = ("You open the volley. Throw the first bar of this round and "
                    "leave it standing where somebody has to answer it.\n")

        if ranked:
            score = ", ".join(
                SEAT_NAMES.get(seat, seat) + " " + str(int(row.get("bars") or 0))
                for seat, row in ranked)
            body += ("The night so far, in bars thrown: " + score
                     + ". Nobody concedes and nobody announces the score.\n")

        motif = str(state.get("motif") or "")
        if motif:
            body += ("Tonight's running sound is \"" + motif + "\" — work it, or "
                     "something that rhymes with it, in where it fits. It is a "
                     "motif, not a subject: do not talk ABOUT it.\n")

        return head + body + (
            "The facts still govern absolutely. This is a battle of WORDING: "
            "keep every name, number, question and refusal the segment owes, "
            "and never invent an insult about a real person's race, sex or "
            "religion. Aim the heat at the argument, the gear and each other.\n")
