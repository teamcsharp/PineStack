"""[s3-mgrtopics] The station manager's topic roulette.

The operator, 2026-09-28: "have the manager rolling the roulette for saying any
topic from the topics list at random in his message to the DJs downstairs. I
want a node in there rolling for him to choose a topic at random to say to the
cast downstairs from the topic database. I dont want him saying the same
things over and over. I also want the manager to have a topics database of his
own. In that database I want to add topics that are rolled through for the
main topic of the message to the DJs and then a sub message based on the topic
that he uses to further intimidate / ingratiate / horrify / attempt to discuss
with."

Two editable tables on System 3's desk (Tables tab), seeded once into the live
config by the runtime's add_missing_default_tables (never DEFAULT_TABLES: the
default config's hash stays pinned):

  MGRTOPIC1  family MGRTOPIC  his topics database. A category is a group of
             MAIN TOPICS (rows the operator adds, edits, removes or switches
             off); the category marked "source": "board" is the station's own
             topics board (data/banter_topics.json, the Topics board list) -
             its one row switches the board on or off and weighs it, and the
             board's rows are the candidates (each 1/(1+times sprung)).
  MGRSUB1    family MGRSUB    the SUB MESSAGES. A category is an APPROACH
             (intimidate / ingratiate / horrify / discuss: its weight is the
             approach's odds, its "how" what the approach means); an item is
             one sub message ({topic} is the rolled topic). An item may name
             "topics" (ids of MGRTOPIC rows): then it is only drawn for those
             topics, and weighs `own_boost` (x3) when it is.

One manager message = three recorded draws on System 3's dice:
  MGRTOPIC     the source (a topic group, or the board), then the main topic
  MGRAPPROACH  the approach (intimidate / ingratiate / horrify / discuss)
  MGRSUB       the sub message inside that approach
Every candidate is recorded with its weight and why (a topic he said lately
is out, or weighs less; a row switched off never lands), the dice and the
outcome. The anti-repeat reads HIS history (the runtime keeps it in
data/system3_mgrtopics.json, newest first): a topic said in his last
`exclude_last` messages cannot be drawn; one said within `rest_window`
messages weighs `rest_factor`. A sub message said in his last `sub_exclude`
messages cannot be drawn; the approach he used last time weighs
`approach_rest`. The knobs sit on MGRTOPIC1 ("rest").

Nothing here imports the station; the engine's draw helpers are System 3's.
"""
from __future__ import annotations

import copy
import re

import system3

TOPIC_FAMILY = "MGRTOPIC"
SUB_FAMILY = "MGRSUB"
APPROACH_FAMILY = "MGRAPPROACH"          # an event family only: the draw over MGRSUB's categories
TABLE_FAMILIES = (TOPIC_FAMILY, SUB_FAMILY)
APPROACHES = ("intimidate", "ingratiate", "horrify", "discuss")
HISTORY_KEEP = 60
BOARD_MOST = 60
REST_DEFAULTS = {"exclude_last": 6, "rest_window": 20, "rest_factor": 0.25,
                 "sub_exclude": 6, "approach_rest": 0.5, "own_boost": 3.0}
ROLL_KEY = "manager.topic"


def _t(id_, text, **extra):
    row = {"id": id_, "label": text[:60], "text": text, "weight": 1.0}
    row.update(extra)
    return row


# --- MGRTOPIC1: his own topics database --------------------------------------
MGRTOPIC1 = {
    "id": "MGRTOPIC1", "family": TOPIC_FAMILY, "version": 1, "enabled": True, "weight": 1.0,
    "label": "The manager's topics (the main topic of his message downstairs)",
    "description": "What the station manager's message to the booth is about. The roulette draws a group (or the "
                   "station's topics board), then one main topic in it; a topic he said lately is out for his next "
                   "few messages and weighs less for a while after (the 'rest' knobs on this table). Add, edit, "
                   "re-weight or switch off rows; the board row switches the station's topics board in or out.",
    "rest": dict(REST_DEFAULTS),
    "categories": [
        {"id": "work", "label": "The job they are doing", "weight": 1.0, "items": [
            _t("talk_less", "spin more records and talk less"),
            _t("request_line", "the request line is not answering itself"),
            _t("callers_slow", "the callers are being handled far too slowly"),
            _t("lunch_breaks", "the lunch breaks are out of hand and everybody upstairs knows it"),
            _t("dead_air", "the dead air last hour, which he timed with a stopwatch"),
            _t("ratings", "the ratings book came in and he has read every page"),
        ]},
        {"id": "building", "label": "The building and the gear", "weight": 1.0, "items": [
            _t("studio_fire", "who set the studio on fire, and why nobody filed anything"),
            _t("turntable_sold", "the turntable is being sold and people are coming for it this week"),
            _t("after_hours", "somebody has been in the building after hours and it will come out"),
            _t("the_smell", "the smell coming out of the booth, which has reached the third floor"),
            _t("thermostat", "who keeps touching the thermostat"),
        ]},
        {"id": "money", "label": "Money, sponsors, the budget", "weight": 1.0, "items": [
            _t("pay", "neither of them is worth what this station is paying"),
            _t("budget_gone", "the equipment budget is gone and it is going to be somebody's fault"),
            _t("coffee", "the coffee order has been cancelled, permanently, as a lesson"),
            _t("sponsor", "the sponsor who heard last night's show and called him at home"),
        ]},
        {"id": "upstairs", "label": "Upstairs politics", "weight": 1.0, "items": [
            _t("consultant", "a consultant is coming in and neither of them will enjoy it"),
            _t("complaints", "there have been complaints, and they are not going to be shared"),
            _t("owner_visit", "the owner is visiting on Friday and nothing is ready"),
            _t("new_policy", "the new station policy nobody has read, which takes effect tonight"),
        ]},
        {"id": "board", "label": "The station's topics board", "weight": 1.0, "source": "board", "items": [
            _t("board", "anything off the station's topics board (the Topics board list)",
               label="Any topic off the station's topics board"),
        ]},
    ],
}


# --- MGRSUB1: the sub messages, by approach ----------------------------------
MGRSUB1 = {
    "id": "MGRSUB1", "family": SUB_FAMILY, "version": 1, "enabled": True, "weight": 1.0,
    "label": "The manager's sub messages (how he comes at them)",
    "description": "After the main topic, the roulette draws his APPROACH (a category: its weight is its odds) and "
                   "one sub message inside it - the angle he uses on the topic. {topic} is the rolled topic. An item "
                   "that names topics (MGRTOPIC1 row ids) is drawn only for those, and weighs three times as much "
                   "when it is. A sub message he used lately is out for his next few messages.",
    "categories": [
        {"id": "intimidate", "label": "Intimidate", "weight": 1.0,
         "how": "he means to frighten them into line: cold, specific, consequences named",
         "items": [
             _t("file", "he lets them know {topic} is going in their file, and the file is already thick"),
             _t("deadline", "he sets a deadline for {topic} - the end of the hour - and says what happens after it"),
             _t("list", "he says he has been keeping a list about {topic}, and reads out how long it is"),
             _t("replace", "he says upstairs has already discussed replacing whoever is responsible for {topic}"),
             _t("hears", "he reminds them he can hear everything they say, and {topic} is exactly what he heard"),
             _t("consultant_notes", "he says the consultant has been taking notes on both of them by name",
                topics=["consultant"]),
         ]},
        {"id": "ingratiate", "label": "Ingratiate", "weight": 1.0,
         "how": "he is suspiciously warm and wants something from them: flattery that does not fit",
         "items": [
             _t("favour", "he is suspiciously warm about {topic} and slips in a small favour at the very end"),
             _t("compliment", "he compliments them - on the wrong things - and then brings up {topic} as if they are all friends"),
             _t("your_side", "he says he has always been on their side about {topic}, which is news to everyone"),
             _t("pizza", "he promises a pizza party once {topic} is sorted, then takes the pizza back"),
             _t("favourite", "he calls them his favourite team, then admits he told the night cleaner the same thing about {topic}"),
             _t("owner_smile", "he asks them to be charming for the owner, and to practise smiling on the radio",
                topics=["owner_visit"]),
         ]},
        {"id": "horrify", "label": "Horrify", "weight": 1.0,
         "how": "he means to disturb them: a detail too far, said too calmly",
         "items": [
             _t("detail", "he describes, in far too much detail, what he found while looking into {topic}"),
             _t("basement", "he reveals what {topic} has to do with the room in the basement nobody mentions"),
             _t("never_seen", "he mentions the last people who handled {topic} were never seen again, then laughs too late"),
             _t("insurance", "he explains {topic} is why the building's insurance was cancelled, and why nobody should touch the walls"),
             _t("sleeping", "he says he has been sleeping in the office because of {topic}, and something has been sleeping there with him"),
             _t("consultant_shovel", "he says the consultant brought his own chair, and his own shovel",
                topics=["consultant"]),
         ]},
        {"id": "discuss", "label": "Discuss", "weight": 1.0,
         "how": "he genuinely tries to talk it through with them, badly: a real question they have to answer",
         "items": [
             _t("opinion", "he genuinely wants their opinion on {topic} and asks them a direct question to answer on air"),
             _t("thinks_aloud", "he thinks out loud about {topic}, gets it slightly wrong, and asks them to correct him"),
             _t("plan", "he floats a plan about {topic} and wants a yes or a no from each of them"),
             _t("explain", "he admits he does not understand {topic} and asks them to explain it to the listeners, slowly"),
             _t("blame", "he asks which of them is to blame for {topic}, as a real question"),
         ]},
    ],
}


def default_tables():
    """Seeded once into a stored config (runtime add_missing_default_tables)."""
    return [copy.deepcopy(MGRTOPIC1), copy.deepcopy(MGRSUB1)]


def validate_table(table):
    """system3.validate_table for MGRTOPIC / MGRSUB: the pool rules (ids unique,
    weights clamped, every row says something, a category may stand empty),
    then this family's own fields - the rest knobs, an item's `topics`."""
    if not isinstance(table, dict):
        raise ValueError("a table is an object")
    fam = str(table.get("family") or "")
    if fam not in TABLE_FAMILIES:
        raise ValueError("not a manager table: %s" % fam)
    t = copy.deepcopy(table)
    t["family"] = "POOL"
    out = system3.validate_table(t)
    out["family"] = fam
    if not out["categories"]:
        raise ValueError("a table needs at least one category")
    if fam == TOPIC_FAMILY:
        rest = out.get("rest") if isinstance(out.get("rest"), dict) else {}
        out["rest"] = {k: (int(_num(rest.get(k), v, 0, HISTORY_KEEP)) if isinstance(v, int)
                           else _num(rest.get(k), v, 0.0, 20.0 if k == "own_boost" else 1.0))
                       for k, v in REST_DEFAULTS.items()}
    for cat in out["categories"]:
        for it in cat.get("items") or []:
            if "topics" in it:
                got = it["topics"] if isinstance(it["topics"], list) else str(it["topics"] or "").split(",")
                got = [str(x).strip() for x in got if str(x).strip()]
                if got:
                    it["topics"] = got[:40]
                else:
                    it.pop("topics")
    return out


def _num(x, default, low, high):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, v))


def rest_knobs(config):
    """The anti-repeat knobs: MGRTOPIC1's "rest" (the first enabled topic table
    that carries one), each clamped; the defaults where it says nothing."""
    got = {}
    for t in _tables(config, TOPIC_FAMILY):
        if isinstance(t.get("rest"), dict):
            got = t["rest"]
            break
    d = REST_DEFAULTS
    return {"exclude_last": int(_num(got.get("exclude_last"), d["exclude_last"], 0, 50)),
            "rest_window": int(_num(got.get("rest_window"), d["rest_window"], 0, HISTORY_KEEP)),
            "rest_factor": _num(got.get("rest_factor"), d["rest_factor"], 0.0, 1.0),
            "sub_exclude": int(_num(got.get("sub_exclude"), d["sub_exclude"], 0, 50)),
            "approach_rest": _num(got.get("approach_rest"), d["approach_rest"], 0.0, 1.0),
            "own_boost": _num(got.get("own_boost"), d["own_boost"], 0.0, 20.0)}


def _tables(config, family):
    out = []
    for t in (config or {}).get("tables") or []:
        if not isinstance(t, dict) or t.get("family") != family or t.get("enabled", True) is False:
            continue
        if float(t.get("weight", 1.0) or 0) <= 0:
            continue
        out.append(t)
    return out


def _words(text, most=300):
    return " ".join(str(text or "").split())[:most]


def _on(item):
    return isinstance(item, dict) and item.get("enabled", True) is not False and float(item.get("weight", 1.0) or 0) > 0


def _recency(key, recent, knobs):
    """(factor, why, excluded_why) for a key given his history (newest first)."""
    try:
        ago = list(recent).index(key)
    except ValueError:
        return 1.0, [], ""
    n = ago + 1
    said = "said in his last message" if n == 1 else "said %d messages ago" % n
    if n <= knobs["exclude_last"]:
        return 0.0, [], "%s - out for his next %d" % (said, knobs["exclude_last"] - n + 1)
    if n <= knobs["rest_window"]:
        return knobs["rest_factor"], ["%s - weighs x%.2f until %d messages have passed"
                                      % (said, knobs["rest_factor"], knobs["rest_window"])], ""
    return 1.0, [], ""


def _row(id_, label, base, weight, why, **extra):
    r = {"id": str(id_), "label": _words(label, 90), "base": float(base), "weight": float(weight), "why": list(why)}
    r.update(extra)
    return r


def topic_pool(config, board=(), recent=(), knobs=None):
    """Every source (a topic group, or the board) with its eligible topics and
    the ones held out, each with why. A source with no eligible topic is
    returned with weight 0."""
    knobs = knobs or rest_knobs(config)
    sources = []
    for table in _tables(config, TOPIC_FAMILY):
        tw = float(table.get("weight", 1.0) or 0)
        for cat in table.get("categories") or []:
            if not isinstance(cat, dict):
                continue
            items, out = [], []
            if cat.get("source") == "board":
                door = [i for i in cat.get("items") or [] if _on(i)]
                if not door:
                    out.append({"id": "board", "label": "the station's topics board", "why": "switched off in its table"})
                else:
                    door_w = float(door[0].get("weight", 1.0) or 0)
                    for r in list(board or [])[:BOARD_MOST]:
                        if not isinstance(r, dict) or not r.get("id") or not _words(r.get("text")):
                            continue
                        key = "board:%s" % r["id"]
                        used = int(r.get("used") or 0)
                        base = door_w / (1.0 + max(0, used))
                        f, why, ex = _recency(key, recent, knobs)
                        why = ["sprung %d time%s on the board: 1/(1+%d)" % (used, "" if used == 1 else "s", used)] + why
                        row = _row(key, r.get("text"), base, base * f, why, key=key, text=_words(r.get("text"), 400),
                                   rest=f, door=door_w,
                                   source="board", board_id=str(r["id"]))
                        (out.append({"id": key, "label": row["label"], "why": ex}) if ex else items.append(row))
            else:
                for it in cat.get("items") or []:
                    if not isinstance(it, dict) or not str(it.get("id") or "").strip():
                        continue
                    text = _words(it.get("text") or it.get("label"), 400)
                    key = "own:%s" % it["id"]
                    if not _on(it) or not text:
                        out.append({"id": key, "label": _words(it.get("label") or text, 90),
                                    "why": "switched off in its table" if it.get("enabled", True) is False
                                    else "weight 0" if text else "says nothing"})
                        continue
                    base = float(it.get("weight", 1.0) or 0)
                    f, why, ex = _recency(key, recent, knobs)
                    row = _row(key, it.get("label") or text, base, base * f, why, key=key, text=text, rest=f,
                               source="own", item_id=str(it["id"]), lean=it.get("lean"))
                    (out.append({"id": key, "label": row["label"], "why": ex}) if ex else items.append(row))
            cw = tw * float(cat.get("weight", 1.0) or 0)
            live = [i for i in items if i["weight"] > 0]
            # the house rule (weighted_decision): a group weighs its weight times the mean
            # of its eligible topics - so a group he drew from lately weighs less too
            mean = (sum(i.get("rest", 1.0) * (i.get("door", 1.0) if i["source"] == "board" else i["base"])
                        for i in live) / len(live)) if live else 0.0
            sources.append({"id": str(cat.get("id")), "label": _words(cat.get("label") or cat.get("id"), 90),
                            "table": table["id"], "base": cw, "weight": cw * mean if live else 0.0,
                            "why": ["table x%.2f, group x%.2f, mean eligible topic x%.3f"
                                    % (tw, float(cat.get("weight", 1.0) or 0), mean)]
                            if live else ["no topic eligible here now"],
                            "items": live, "excluded": out})
    return sources


def _relax(config, board, recent, knobs):
    """Everything is held out (a tiny database, a long exclusion): the rested
    topics come back at rest_factor squared rather than silence the node."""
    k = dict(knobs, exclude_last=0)
    pool = topic_pool(config, board, recent, k)
    for s in pool:
        for i in s["items"]:
            if i["key"] in list(recent)[:knobs["exclude_last"]]:
                i["weight"] = i["base"] * knobs["rest_factor"] ** 2
                i["why"] = i["why"] + ["every topic was held out - let back at x%.4f" % (knobs["rest_factor"] ** 2)]
    return pool


def sub_pool(config, topic, approach_id=None, recent_subs=(), knobs=None):
    """The approaches (MGRSUB categories) and their eligible sub messages for
    `topic` (the drawn topic row)."""
    knobs = knobs or rest_knobs(config)
    tid = str(topic.get("item_id") or "")
    lean = topic.get("lean") if isinstance(topic.get("lean"), dict) else {}
    cats = []
    for table in _tables(config, SUB_FAMILY):
        tw = float(table.get("weight", 1.0) or 0)
        for cat in table.get("categories") or []:
            if not isinstance(cat, dict) or (approach_id and cat.get("id") != approach_id):
                continue
            items, out = [], []
            for it in cat.get("items") or []:
                if not isinstance(it, dict) or not str(it.get("id") or "").strip():
                    continue
                key = "%s:%s" % (cat.get("id"), it["id"])
                text = _words(it.get("text") or it.get("label"), 400)
                if not _on(it) or not text:
                    out.append({"id": key, "label": _words(it.get("label") or text, 90),
                                "why": "switched off in its table" if it.get("enabled", True) is False else "weight 0"})
                    continue
                only = [str(x) for x in (it.get("topics") or []) if str(x).strip()]
                base = float(it.get("weight", 1.0) or 0)
                why = []
                if only:
                    if tid not in only:
                        out.append({"id": key, "label": _words(it.get("label") or text, 90),
                                    "why": "written for %s, not this topic" % ", ".join(only)})
                        continue
                    base *= knobs["own_boost"]
                    why.append("written for this topic: x%.1f" % knobs["own_boost"])
                try:
                    ago = list(recent_subs).index(key) + 1
                except ValueError:
                    ago = 0
                if ago and ago <= knobs["sub_exclude"]:
                    out.append({"id": key, "label": _words(it.get("label") or text, 90),
                                "why": "used %s - out for his next %d" % (
                                    "in his last message" if ago == 1 else "%d messages ago" % ago,
                                    knobs["sub_exclude"] - ago + 1)})
                    continue
                items.append(_row(key, it.get("label") or text, float(it.get("weight", 1.0) or 0), base, why,
                                  key=key, text=text, item_id=str(it["id"]), table=table["id"]))
            cw = tw * float(cat.get("weight", 1.0) or 0)
            cats.append({"id": str(cat.get("id")), "label": _words(cat.get("label") or cat.get("id"), 60),
                         "how": _words(cat.get("how") or cat.get("text"), 300), "table": table["id"],
                         "base": cw, "weight": cw if items else 0.0, "why": [] if items else ["no sub message eligible"],
                         "items": items, "excluded": out, "lean": float(lean.get(str(cat.get("id")), 1.0) or 0)})
    return cats


def _fill(text, topic_text):
    return re.sub(r"\{topic\}", topic_text, str(text or ""))


def _topic_words(row):
    return _words(row.get("text") or row.get("label"), 240).rstrip(" .")


def roll(config, stream, board=(), recent=(), recent_subs=(), last_approach=""):
    """Draw the manager's message: the main topic, the approach, the sub
    message. `stream` is a System 3 DrawStream (the road's own dice); `recent`
    his topic keys and `recent_subs` his sub-message keys, newest first.
    Returns the result with its three decision events (not yet on a
    conversation), or None when there is nothing to draw from."""
    knobs = rest_knobs(config)
    recent = [str(k) for k in (recent or [])]
    pool = topic_pool(config, board, recent, knobs)
    relaxed = False
    if not any(s["weight"] > 0 for s in pool):
        pool = _relax(config, board, recent, knobs)
        for s in pool:
            live = [i for i in s["items"] if i["weight"] > 0]
            s["items"], s["weight"] = live, (s["base"] if live else 0.0)
        relaxed = True
    live = [s for s in pool if s["weight"] > 0]
    if not live:
        return None
    events = []
    d1 = stream.next("MGRTOPIC:category")
    i = system3.pick_index([s["weight"] for s in live], d1["u"])
    src = live[i]
    st_src = system3._stage("category", live, i, d1, [{"id": s["id"], "label": s["label"], "why": "; ".join(s["why"])}
                                                       for s in pool if s["weight"] <= 0])
    d2 = stream.next("MGRTOPIC:item")
    j = system3.pick_index([x["weight"] for x in src["items"]], d2["u"])
    topic = src["items"][j]
    st_topic = system3._stage("item", src["items"], j, d2, src["excluded"])
    topic_sel = {"table": src["table"], "category": src["id"], "category_label": src["label"],
                 "id": topic["key"], "label": topic["label"], "text": topic["text"], "index": j + 1,
                 "of": len(src["items"]), "source": topic["source"]}
    events.append({"family": TOPIC_FAMILY, "stages": [st_src, st_topic], "selected": topic_sel, "rng": d2,
                   "meta": {"why": "the main topic of the manager's message downstairs: a group (or the station's "
                                   "topics board), then the topic - his last messages' topics held out or rested",
                            "rest": knobs, "relaxed": relaxed, "history": recent[:knobs["rest_window"]]}})
    topic_text = _topic_words(topic)
    # (b) the approach, (c) the sub message
    cats = sub_pool(config, topic, None, recent_subs, knobs)
    for c in cats:
        f = 1.0
        if c["weight"] > 0 and c["lean"] != 1.0:
            f *= c["lean"]
            c["why"].append("this topic leans x%.2f" % c["lean"])
        if c["weight"] > 0 and last_approach and c["id"] == str(last_approach):
            f *= knobs["approach_rest"]
            c["why"].append("his approach last time - x%.2f" % knobs["approach_rest"])
        c["weight"] = c["weight"] * f
    live_c = [c for c in cats if c["weight"] > 0]
    approach = sub = None
    if live_c:
        d3 = stream.next("MGRAPPROACH:category")
        k = system3.pick_index([c["weight"] for c in live_c], d3["u"])
        approach = live_c[k]
        events.append({"family": APPROACH_FAMILY,
                       "stages": [system3._stage("category", live_c, k, d3,
                                                 [{"id": c["id"], "label": c["label"], "why": "; ".join(c["why"])}
                                                  for c in cats if c["weight"] <= 0])],
                       "selected": {"table": approach["table"], "id": approach["id"], "label": approach["label"],
                                    "text": approach["how"], "index": k + 1, "of": len(live_c)},
                       "rng": d3, "meta": {"why": "how the manager comes at them about the topic (MGRSUB's approaches)",
                                           "topic": topic["key"]}})
        d4 = stream.next("MGRSUB:item")
        m = system3.pick_index([x["weight"] for x in approach["items"]], d4["u"])
        sub = dict(approach["items"][m])
        sub["filled"] = _fill(sub["text"], topic_text)
        events.append({"family": SUB_FAMILY,
                       "stages": [system3._stage("item", approach["items"], m, d4, approach["excluded"])],
                       "selected": {"table": sub["table"], "category": approach["id"], "category_label": approach["label"],
                                    "id": sub["key"], "label": sub["label"], "text": sub["filled"], "index": m + 1,
                                    "of": len(approach["items"])},
                       "rng": d4, "meta": {"why": "the sub message he uses on the topic, inside the approach drawn",
                                           "topic": topic["key"], "approach": approach["id"]}})
    out = {"key": topic["key"], "topic_text": topic_text,
           "topic": {k: topic.get(k) for k in ("key", "label", "text", "source", "item_id", "board_id")},
           "group": {"id": src["id"], "label": src["label"], "table": src["table"]},
           "approach": ({"id": approach["id"], "label": approach["label"], "how": approach["how"]} if approach else None),
           "sub": ({"key": sub["key"], "id": sub["item_id"], "label": sub["label"], "text": sub["filled"]} if sub else None),
           "events": events, "relaxed": relaxed}
    out["direction"] = direction(out)
    out["memo_direction"] = memo_direction(out)
    out["sheet"] = sheet_text(out)
    return out


def public(res):
    """The result without its events: what a page row keeps, what the writer is told."""
    return {k: copy.deepcopy(res.get(k)) for k in ("key", "topic_text", "topic", "group", "approach", "sub",
                                                    "direction", "memo_direction", "sheet", "event_ids", "dice")
            if res.get(k) is not None}


def direction(res):
    """The manager's own writer: the rolled topic, approach and sub message, binding."""
    if not res:
        return ""
    s = ("\nSYSTEM 3 ROLLED THIS MESSAGE (binding - the roulette decided it, do not swap it for anything else):\n"
         "- THE MAIN TOPIC: %s.\n" % res["topic_text"])
    ap, sub = res.get("approach"), res.get("sub")
    if ap:
        s += "- YOUR APPROACH: %s - %s. This outranks any default tone below.\n" % (ap["label"].upper(), ap["how"])
    if sub:
        s += "- THE SUB MESSAGE (work it in, in your own words): %s.\n" % sub["text"]
    s += "The whole message is about that topic, told that way. Do not read these labels out.\n"
    return s


def memo_direction(res):
    """The memo road: the pair read HIS memo, so they are told what it says and how."""
    if not res:
        return ""
    ap, sub = res.get("approach"), res.get("sub")
    s = "\nSystem 3 rolled what his memo is about: %s." % res["topic_text"]
    if ap:
        s += " He wrote it to %s them (%s)." % (ap["label"].lower(), ap["how"])
    if sub:
        s += " In it %s." % sub["text"]
    return s + " Deal with THAT - the topic, and the way he came at you.\n"


def sheet_text(res):
    """A line on the running order of the upstairs chapter: the studio's
    replies answer the topic and the approach, not a generic page."""
    if not res:
        return ""
    ap, sub = res.get("approach"), res.get("sub")
    s = "\nTHE MANAGER'S MESSAGE (System 3's MGRTOPIC roll): the main topic is %s" % res["topic_text"]
    if ap:
        s += "; he came at them to %s" % ap["label"].upper()
    if sub:
        s += " - %s" % sub["text"]
    return s + ". The replies answer THAT topic and that approach, by name.\n"


def absorb(conv, rec, before, ctx0):
    """The runtime's _absorb_rolls: the three draws become the conversation's
    events (recorded with their candidates, weights and dice; road rolls are
    not replayed) and conv["mgr_topic"] carries the result for the sheet."""
    res = rec.get("result") or {}
    ids = []
    for ev in res.get("events") or []:
        meta = dict(ev.get("meta") or {})
        meta.update(key=str(rec.get("key") or ROLL_KEY), road_roll=True, road=str(rec.get("road") or ""))
        e = system3._event(conv, ctx0, ev["family"], ev["stages"], ev["selected"], before, meta=meta,
                           rng=dict(ev.get("rng") or {}))
        e["state_after"] = before
        ids.append(e["event_id"])
    mt = public(res)
    mt["event_ids"] = ids
    conv["mgr_topic"] = mt
    return ids


def attach(conv):
    """After the plan: the draws ride the manager's own turn (the opener) - the
    line wears its dice - and the events name that turn."""
    mt = conv.get("mgr_topic") if isinstance(conv.get("mgr_topic"), dict) else {}
    turns = conv.get("turns") or []
    if not mt or not turns:
        return False
    t = next((x for x in turns if not x.get("split_of")), turns[0])
    t["decisions"] = [d for d in t.get("decisions") or [] if d.get("family") not in
                      (TOPIC_FAMILY, APPROACH_FAMILY, SUB_FAMILY)]
    by_id = {e.get("event_id"): e for e in conv.get("decision_events") or []}
    for eid in mt.get("event_ids") or []:
        e = by_id.get(eid)
        if not e:
            continue
        e["turn_id"], e["turn_index"] = t.get("turn_id", ""), t.get("index", 0)
        sel = e.get("selected") or {}
        t["decisions"].append({"family": e["family"], "event_id": eid, "item": sel.get("id"),
                               "label": _words(sel.get("label"), 120), "u": (e.get("rng") or {}).get("u")})
    return True


def sheet_line(conv):
    mt = conv.get("mgr_topic") if isinstance(conv.get("mgr_topic"), dict) else {}
    return str(mt.get("sheet") or "")


def history_note(hist, res, keep=HISTORY_KEEP):
    """His history after this message (newest first)."""
    hist = hist if isinstance(hist, dict) else {}
    out = {"topics": [str(x) for x in hist.get("topics") or []][:keep],
           "subs": [str(x) for x in hist.get("subs") or []][:keep],
           "approaches": [str(x) for x in hist.get("approaches") or []][:keep]}
    if res:
        out["topics"] = ([res["key"]] + out["topics"])[:keep]
        if res.get("sub"):
            out["subs"] = ([res["sub"]["key"]] + out["subs"])[:keep]
        if res.get("approach"):
            out["approaches"] = ([res["approach"]["id"]] + out["approaches"])[:keep]
    return out


def measure(config, seed, n=50, board=(), history=None):
    """Draw `n` messages in a row, each seeing the history the ones before it
    left: distinct topics, the shortest gap between two airings of one topic,
    the most any topic came up. The operator's "not the same things over and
    over", as numbers."""
    hist = history_note(history, None)
    keys, subs = [], []
    stream = system3.DrawStream("mgrtopics|measure|%s" % seed)
    for _ in range(int(n)):
        res = roll(config, stream, board, hist["topics"], hist["subs"],
                   hist["approaches"][0] if hist["approaches"] else "")
        if not res:
            break
        keys.append(res["key"])
        subs.append((res.get("sub") or {}).get("key"))
        hist = history_note(hist, res)
    last, gaps = {}, []
    for i, k in enumerate(keys):
        if k in last:
            gaps.append(i - last[k])
        last[k] = i
    counts = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    return {"draws": len(keys), "distinct": len(counts), "min_gap": min(gaps) if gaps else None,
            "most": max(counts.values()) if counts else 0, "distinct_subs": len(set(subs)), "keys": keys}
