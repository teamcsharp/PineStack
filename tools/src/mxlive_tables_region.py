

# --- [s3-live-event] STATION EVENTS, FIRST-CLASS IN THE WHEELS ----------------------
#
# 2026-09-28, the operator: "When it comes to music based nodes in System3. I want
# there to be options added to have dialogue made for the live event and to have the
# DJs able to dicuss the event in segments in passing and having it as an option in
# the relevant roulette wheels (when relevant). Events should be able to be
# activatable and used in generated conversational node trees without uptrooting the
# entire system." And: during a PineLive set the DJs TALK OVER IT, ducked - so the
# rows below are relevant while the set is live, not only afterwards.
#
# An EVENT is a registry entry (DEFAULT_EVENTS; the live copy is config["events"]):
# an id, a name, where its on/off comes from (`source`: "pinelive" follows the
# PineLive event switch, "manual" is System 3's own switch), its facts, and an
# optional window (starts_at / ends_at, epoch seconds, 0 = none).
#
# Its ROWS are ordinary table rows, tagged: `"event": "<id>"` on a table, and
# `"event_stages"` on a category for the part of the event it fits -
#   upcoming  armed, waiting for the first sound (or a window not yet started)
#   live      on the air: the live input is the music, the station's records wait
#   fallback  running, but the input dropped out and the station has the air back
#   after     finished within the event's after_window
# While the event is on, its rows join their wheels. While it is off they are taken
# out BEFORE any weight is computed (system3.event_view), so with no event on every
# draw is today's draw. A row that talks about an event never lands on a banked
# round (it could air after the event has changed) unless the table says
# "event_banked": true.
#
# NOTHING HERE TOUCHES DEFAULT_TABLES OR DEFAULT_BLOCKS: default_config()'s hash is
# pinned (tests/test_system3.py) and these rows reach the LIVE config once, through
# the runtime's add_missing_default_tables / add_missing_station_events - saved as a
# version with a note, editable in Tables, deletable for good.
#
# The wheels MX Live joins:
#   MXLIVE1       EVENT       in passing, inside a segment's exchange (banter, mixtape,
#                             recap, the open, fan mail, the gallery, upstairs, a guest):
#                             reactions to the set, shout-outs, the trail, the dropout,
#                             the look back - each kind its own die (seed|round:EVENT:...)
#   MXLIVECALL1   EVENT       on a call: the caller reacts to the set, asks after it;
#                             the host tells the caller it is on
#   MXLIVECTS1    CTS         a topic change: the subject turns to the live set
#   MXLIVETRACK1  TRACK_TALK  the live record comment: the banter's TRACK_TALK moment
#                             talks about the set while the station's record is held -
#                             never the held record. The track_talk control is still
#                             the die; only the comment's direction is one of these.
#   MXLIVEID1     EVENT       a station ID drawn while it is live (the station_id
#                             road's LINE wheel; a banked ID never takes one)
#   MXLIVEANGLE1  ANGLE       a free banter round's whole angle: joins the station's
#                             stock-angle wheel (`pool` names it: banter.stock_angle)
EVENT_STAGES = ("upcoming", "live", "fallback", "after")
EVENT_SOURCES = ("pinelive", "manual")

DEFAULT_EVENTS = {
    "mxlive": {
        "id": "mxlive", "name": "MX Live", "source": "pinelive", "enabled": True,
        "what": "PineLive: MX playing live into the station while the station's own records wait",
        "facts": {
            "what": "MX's live set - MX playing live into the station, with the station's own records held until it ends",
            "who": "MX",
            "device": "EP-133 K.O. II",
            "notes": ["There is no track list for a live set: never name a title or an artist for what is being "
                      "played live - talk about the sound, the energy and what MX is doing with the machine."],
        },
        "after_window": 1800,           # seconds the "after" rows stay eligible once it ends
        "starts_at": 0, "ends_at": 0,   # an optional window (epoch seconds; 0 = none)
    },
}


def default_events():
    return copy.deepcopy(DEFAULT_EVENTS)


_MX_TALK_ROADS = ["banter", "mixtape", "recap", "open_show", "fan_mail", "gallery", "manager", "guest"]

MXLIVE1 = {
    "id": "MXLIVE1", "family": "EVENT", "label": "MX Live: in passing (a segment's exchange)", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "roads": list(_MX_TALK_ROADS), "max_events": 1,
    "description": "While MX Live is on, one of the DJs may mention it in passing inside the exchange - a reaction "
                   "to the set playing underneath, a shout-out, the trail before it starts, the dropout, the look "
                   "back. Each kind is its own die per segment; a hit lands on one host turn and the next turn "
                   "answers it like any other line. Invisible to the dice while the event is off.",
    "categories": [
        {"id": "reacts", "label": "MX Live: reacts to the set", "weight": 1.0, "odds": 0.35, "seat": "host",
         "place": "any", "event_stages": ["live"],
         "items": _items([
             {"id": "hears_it", "label": "Hears something in it",
              "text": "reacts in passing to the live set playing underneath them - one specific thing MX just did "
                      "with the sound - and carries straight on"},
             {"id": "breaks_off", "label": "Breaks off for a second",
              "text": "breaks off for a second because the live set underneath just did something - a drop, a switch, "
                      "a build - says so in a few words, then comes back to the conversation"},
             {"id": "nodding", "label": "Has been nodding along",
              "text": "admits in passing they have been nodding along to the live set the whole time, and says what it "
                      "is doing to the room"},
         ])},
        {"id": "shout_out", "label": "MX Live: a shout-out", "weight": 1.0, "odds": 0.2, "seat": "host",
         "place": "any", "event_stages": ["live", "fallback"],
         "items": _items([
             {"id": "shout", "label": "Shouts out MX",
              "text": "gives MX a shout-out on air for playing live on the station right now, in one line, then back "
                      "to the conversation"},
             {"id": "stay_put", "label": "Tells the listeners to stay put",
              "text": "tells the listeners in passing to stay put, because MX is live on the station right now"},
         ])},
        {"id": "trail", "label": "MX Live: the trail", "weight": 1.0, "odds": 0.2, "seat": "host",
         "place": "any", "event_stages": ["upcoming"],
         "items": _items([
             {"id": "coming", "label": "It is switched on for today",
              "text": "mentions in passing that MX Live is armed - MX is about to play live into the station - "
                      "without promising a time"},
         ])},
        {"id": "dropout", "label": "MX Live: the input dropped out", "weight": 1.0, "odds": 0.5, "seat": "host",
         "place": "any", "event_stages": ["fallback"],
         "items": _items([
             {"id": "back_soon", "label": "The station has the air for a moment",
              "text": "notes in passing that the live set dropped out for a moment and the station has the air until "
                      "it comes back - no fuss, straight back to the conversation"},
         ])},
        {"id": "after", "label": "MX Live: looking back", "weight": 1.0, "odds": 0.3, "seat": "host",
         "place": "any", "event_stages": ["after"],
         "items": _items([
             {"id": "that_was", "label": "One moment that stuck",
              "text": "looks back in passing on the live set MX just finished - one moment of it that stuck with them"},
         ])},
    ],
}

MXLIVECALL1 = {
    "id": "MXLIVECALL1", "family": "EVENT", "label": "MX Live: on a call", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "roads": ["caller"], "max_events": 1,
    "description": "While MX Live is on, a caller may bring it up, or a host may tell the caller it is on. {first} is "
                   "the caller's first name. Invisible to the dice while the event is off.",
    "categories": [
        {"id": "caller_live", "label": "MX Live: the caller has it on", "weight": 1.0, "odds": 0.3, "seat": "caller",
         "place": "any", "event_stages": ["live", "fallback"],
         "items": _items([
             {"id": "has_it_on", "label": "Has the set on",
              "text": "{first} says in passing they have MX's live set on right now, and what they make of it so far"},
             {"id": "tell_mx", "label": "Asks them to tell MX something",
              "text": "{first} asks the hosts to tell MX one thing about the live set, in passing"},
         ])},
        {"id": "caller_upcoming", "label": "MX Live: the caller asks after it", "weight": 1.0, "odds": 0.15,
         "seat": "caller", "place": "any", "event_stages": ["upcoming"],
         "items": _items([
             {"id": "when", "label": "Asks when it starts",
              "text": "{first} asks in passing when MX goes live, and the hosts cannot promise a time"},
         ])},
        {"id": "host_live", "label": "MX Live: the host tells the caller", "weight": 1.0, "odds": 0.15,
         "seat": "host", "place": "any", "event_stages": ["live"],
         "items": _items([
             {"id": "its_on", "label": "Tells the caller MX is live",
              "text": "tells {first} in passing that MX is live on the station right now, underneath this very call"},
         ])},
    ],
}

MXLIVECTS1 = {
    "id": "MXLIVECTS1", "family": "CTS", "label": "MX Live: topics", "version": 1,
    "enabled": True, "weight": 0.6, "event": "mxlive",
    "description": "While MX Live is on, a change of subject may turn to it (beside CTS1, at this table's weight). "
                   "Invisible to the dice while the event is off.",
    "categories": [
        {"id": "live_set", "label": "MX Live: the set on the air", "weight": 1.0, "resolver": "direction",
         "event_stages": ["live", "fallback"],
         "items": _items([
             {"id": "the_set", "label": "The live set itself",
              "text": "turns to MX Live - the set MX is playing live into the station right now - and what they make "
                      "of it; the live set comes up in passing, the exchange stays theirs"},
             {"id": "live_vs_records", "label": "Live against the records",
              "text": "turns to what it is like having MX live instead of the station's own records tonight - which "
                      "they would rather have"},
         ])},
        {"id": "upcoming", "label": "MX Live: switched on, not started", "weight": 1.0, "resolver": "direction",
         "event_stages": ["upcoming"],
         "items": _items([
             {"id": "what_he_plays", "label": "What MX will play",
              "text": "turns to MX Live, armed for today - what they expect MX to do when the set starts, "
                      "without promising a time"},
         ])},
        {"id": "after", "label": "MX Live: just finished", "weight": 1.0, "resolver": "direction",
         "event_stages": ["after"],
         "items": _items([
             {"id": "looks_back", "label": "Looks back on the set",
              "text": "turns back to the live set MX just finished and what they made of it"},
         ])},
    ],
}

MXLIVETRACK1 = {
    "id": "MXLIVETRACK1", "family": "TRACK_TALK", "label": "MX Live: the live record comment", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive",
    "description": "The banter's TRACK_TALK moment (a passing comment on what is playing underneath) while MX is "
                   "live: the station's record is held, so the comment is about the live set - one of these rows, "
                   "drawn on its own stream. The track_talk control is still the die. Invisible while the event "
                   "is off.",
    "categories": [
        {"id": "live_set", "label": "MX Live: what is being played live", "weight": 1.0, "event_stages": ["live"],
         "items": _items([
             {"id": "the_sound", "label": "The sound of it",
              "text": "the live set MX is playing underneath them right now - one specific thing about its sound: "
                      "the drums, the texture, a change it just made"},
             {"id": "the_energy", "label": "Where it has gone",
              "text": "where MX's live set has gone in the last few minutes - the energy of it, underneath them"},
             {"id": "the_machine", "label": "What MX is doing with the machine",
              "text": "what MX is doing with the EP-133 K.O. II right now - the chops, the loops, the pads - as the "
                      "set plays underneath"},
         ])},
    ],
}

MXLIVEID1 = {
    "id": "MXLIVEID1", "family": "EVENT", "label": "MX Live: station IDs", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "roads": ["station_id"], "max_events": 1,
    "description": "While MX is live, the station-ID road's LINE wheel offers these beside the stock IDs (the words "
                   "as written; {station} is the station's name). A banked ID never takes one - it could air after "
                   "the set. Invisible while the event is off.",
    "categories": [
        {"id": "id", "label": "MX Live: the ID", "weight": 1.0, "odds": 0.5, "seat": "any", "place": "any",
         "event_stages": ["live"],
         "items": _items([
             {"id": "right_now", "label": "Right now", "text": "MX Live. Right now. Only on {station}."},
             {"id": "dont_touch", "label": "Do not touch that dial",
              "text": "{station}. MX is live. Do not touch that dial."},
             {"id": "no_net", "label": "No net", "text": "This is MX Live on {station}. Loud, live, no net."},
         ])},
    ],
}

MXLIVEANGLE1 = {
    "id": "MXLIVEANGLE1", "family": "ANGLE", "label": "MX Live: banter angles", "version": 1,
    "enabled": True, "weight": 1.0, "event": "mxlive", "pool": "banter.stock_angle",
    "description": "While MX Live is on, the station's stock-angle wheel for a free banter round (the POOLS row "
                   "banter.stock_angle) offers these rows too: the round is ABOUT the event. The round's own node "
                   "chain is unchanged - an initial message, a response from each seat, the rebuttal. Invisible "
                   "while the event is off.",
    "categories": [
        {"id": "live", "label": "MX Live: while it is live", "weight": 1.0, "event_stages": ["live"],
         "items": _items([
             {"id": "side_of_stage", "label": "Side of the stage",
              "text": "MX is live on the station right now - talk over the set like two people at the side of the "
                      "stage: what MX is doing, what it does to the room, whether either of you could do it"},
             {"id": "live_vs_records", "label": "Live against the records",
              "text": "argue about live sets against records, with MX's live set going out underneath you as "
                      "exhibit A"},
         ])},
        {"id": "upcoming", "label": "MX Live: before it starts", "weight": 1.0, "event_stages": ["upcoming"],
         "items": _items([
             {"id": "what_will_he_play", "label": "What MX will play",
              "text": "MX Live is armed for today - speculate about what MX will do when the set starts, "
                      "without promising a time"},
         ])},
        {"id": "after", "label": "MX Live: after it ends", "weight": 1.0, "event_stages": ["after"],
         "items": _items([
             {"id": "moments", "label": "The moments that stuck",
              "text": "MX just finished playing live on the station - trade the moments of the set that stuck "
                      "with you"},
         ])},
    ],
}

# The event tables reach the LIVE config once (runtime add_missing_default_tables),
# never default_config(): its hash is pinned.
EVENT_TABLES = [MXLIVE1, MXLIVECALL1, MXLIVECTS1, MXLIVETRACK1, MXLIVEID1, MXLIVEANGLE1]


def default_event_tables():
    return copy.deepcopy(EVENT_TABLES)


# THE EVENT'S FACTS ARE A NODE. They reach the writer as their own block, marked
# where System 3's running order enters the prompt, and only when a roll in this
# round landed on an event row claims it (kind "claimed" - system3.decide_blocks);
# otherwise the block is never built. Never a wedge. Reaches config["blocks"] once
# through the runtime (add_missing_station_events), never DEFAULT_BLOCKS.
EVENT_BLOCKS = {
    "event_facts": {
        "kind": "claimed", "label": "A station event's facts (MX Live ...)",
        "helper": "system3_event_facts (the runtime's event_facts_text)",
        "what": "sent only when a roll in the round landed on an event row (MXLIVE1, MXLIVECTS1 ...)"},
}


def default_event_blocks():
    return copy.deepcopy(EVENT_BLOCKS)
