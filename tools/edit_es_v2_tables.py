"""[es-v2] system3_tables.py gains ES1's second edition: the voices recalibrated
against the science table and the writer's direction as an actor's direction
(emotion engine steps 3 + 7). DATA ONLY: ES1 - the defaults a fresh station seeds
from, and the config hash every golden pins - is not touched. ES1_V2 is ES1 with
the v2 voices and texts; the runtime's one-shot fill (edit_es_v2_runtime.py,
POST /api/system3/es-v2) moves a stored row to it only while that row still holds
exactly its v1 default, so an operator-edited row stays as the operator left it.

Marker-idempotent: --check exits 0 ready / 2 already applied / 1 not the file this
was cut against; --apply appends the region, LF only, atomically.

    python3 tools/edit_es_v2_tables.py [--apply] [system3_tables.py]
"""
import os
import sys
import tempfile
from pathlib import Path

MARKER = "# --- [es-v2] ES1, SECOND EDITION"
NEEDS = ("ES_DIRECTION = ", "_ES_VOICE = {", "_ES_ITEM_VOICE = {", "def _es_item_voice(cid, word):", "\nES1 = {")

REGION = r'''
# --- [es-v2] ES1, SECOND EDITION: how a feeling sounds, recalibrated, and what the
# writer is told, as an actor is directed (emotion engine steps 3 + 7) --------------
#
# THE VOICES (step 3), checked against the master table of emotional prosody
# (Banse & Scherer 1996 z-profiles, Juslin & Laukka 2003's 104-study consensus,
# Burkhardt & Sendlmeier 2000 / Schroeder 2001 synthesis-verified settings,
# Paeschke & Sendlmeier 2000 contours), scaled into the house bounds. The families
# the v1 blocks blurred are split where the literature measures OPPOSITE signs:
#   panic (F0 +1.23z) vs anxiety (-0.58z, the most monotone of 14, quiet);
#   elation (+1.24z) vs contentment (-0.64z, slower, quieter);
#   quiet sorrow (-0.32z, quietest) vs despair (+0.99z, loud, range narrowed);
#   hot anger vs contempt (-1.03z, the lowest F0 of all, quiet).
# Fear keeps its counter-intuitive geometry: register UP, span NOT widened
# (SdF0 -0.63z, accent span 8.6 st vs 9.5 neutral) - no fear row swings wider than
# 1.0 - and its "mixed model" (breath-grabbing pauses inside a fast line) is
# pause > 1 with tempo > 1. Disgust and contempt are darker (energy -), never
# brighter; interest is brisk (the third-fastest articulation) at a neutral pitch;
# the self-conscious family (shame, pride) sits low.
# A block names what it sets; an item's block names only what differs from its
# category (as in v1). An item absent here keeps its v1 block.
ES_V2_VOICE = {
    #               tempo          pitch          range          energy          pause          temp
    "surprise":    {"tempo": 1.05, "pitch": 1.6,  "range": 1.40, "energy": 0.30,  "pause": 0.85, "temp": 0.06},
    "anger":       {"tempo": 1.10, "pitch": 1.0,  "range": 1.35, "energy": 0.60,  "pause": 0.78, "temp": 0.05},
    "fear":        {"tempo": 1.10, "pitch": 1.2,  "range": 0.90, "energy": 0.25,  "pause": 1.08, "temp": 0.05},
    "sadness":     {"tempo": 0.86, "pitch": -1.0, "range": 0.70, "energy": -0.50, "pause": 1.40, "temp": -0.05},
    "joy":         {"tempo": 1.08, "pitch": 1.2,  "range": 1.35, "energy": 0.40,  "pause": 0.90, "temp": 0.05},
    "disgust":     {"tempo": 0.90, "pitch": -0.8, "range": 1.15, "energy": -0.25, "pause": 1.15, "temp": -0.02},
    "interest":    {"tempo": 1.06, "pitch": 0.0,  "range": 1.20, "energy": 0.25,  "pause": 0.92, "temp": 0.03},
    "social":      {"tempo": 0.96, "pitch": -0.4, "range": 0.90, "energy": -0.25, "pause": 1.15, "temp": 0.0},
    "low_arousal": {"tempo": 0.87, "pitch": -1.0, "range": 0.65, "energy": -0.55, "pause": 1.35, "temp": -0.07},
}
ES_V2_ITEM_VOICE = {
    # anger: hot stays hot; contempt is cold, low and quiet; resentment cold and controlled
    "contempt":       {"tempo": 0.95, "pitch": -1.2, "range": 1.10, "energy": -0.20, "pause": 1.10, "temp": 0.0},
    "resentment":     {"tempo": 1.0, "pitch": -0.2, "range": 1.15, "energy": 0.30, "pause": 1.0, "temp": 0.0},
    "anger.disgust":  {"tempo": 0.95, "pitch": -0.5, "range": 1.15, "energy": 0.10, "pause": 1.05},
    # fear: the panic side up and fast, span never widened; the anxious side low, flat, quiet
    "unease":         {"tempo": 1.02, "pitch": -0.2, "range": 0.85, "energy": -0.10, "pause": 1.10, "temp": 0.02},
    "apprehension":   {"tempo": 1.04, "pitch": -0.2, "range": 0.85, "energy": 0.0, "pause": 1.05},
    "anxiety":        {"tempo": 1.04, "pitch": -0.6, "range": 0.70, "energy": -0.25, "pause": 1.15, "temp": 0.0},
    "alarm":          {"tempo": 1.10, "pitch": 1.4, "range": 0.95, "energy": 0.40, "pause": 1.05},
    "dread":          {"tempo": 0.98, "pitch": -0.4, "range": 0.70, "energy": -0.20, "pause": 1.25, "temp": -0.02},
    "panic":          {"tempo": 1.14, "pitch": 1.8, "range": 0.95, "energy": 0.50, "pause": 1.10, "temp": 0.07},
    "horror":         {"tempo": 1.04, "pitch": 1.2, "range": 1.0, "energy": 0.35, "pause": 1.10},
    # sadness: despair is the high, loud, narrowed protest - the sign flips
    "despair":        {"tempo": 0.90, "pitch": 1.0, "range": 0.80, "energy": 0.35, "pause": 1.30, "temp": 0.03},
    # joy: the savouring side (contentment) sits lower, slower and softer than elation
    "pleasure":       {"tempo": 0.98, "pitch": 0.0, "range": 1.20, "energy": -0.10, "pause": 1.0},
    "happiness":      {"tempo": 1.0, "pitch": 0.2, "range": 1.25, "energy": 0.05, "pause": 0.98},
    "satisfaction":   {"tempo": 0.96, "pitch": -0.5, "range": 1.10, "energy": -0.25, "pause": 1.10, "temp": 0.0},
    # disgust: darker, never brighter
    "distaste":       {"tempo": 0.95, "pitch": -0.5, "range": 1.05, "energy": -0.15, "pause": 1.10},
    "revulsion":      {"tempo": 0.90, "pitch": -1.0, "range": 1.25, "energy": -0.10, "pause": 1.20},
    "repulsion":      {"tempo": 0.91, "pitch": -0.9, "range": 1.20, "energy": -0.10, "pause": 1.18},
    "moral disgust":  {"tempo": 0.94, "pitch": -0.6, "range": 1.20, "energy": -0.10, "pause": 1.10},
    # interest: brisk, near the speaker's own pitch
    "fascination":    {"tempo": 1.02, "pitch": 0.4, "range": 1.30, "energy": 0.20},
    "attentiveness":  {"tempo": 1.02, "pitch": 0.2, "range": 1.05, "energy": 0.05, "pause": 1.0},
    # social: pride is low and even, not bright
    "pride":          {"tempo": 1.02, "pitch": -0.2, "range": 1.15, "energy": 0.0, "pause": 1.05, "temp": 0.01},
}

# THE WRITER'S DIRECTION (step 7). The operator, 2026-09-28: "the emotions and
# response acceptances are stages while mentally processing the speakerbox seeded
# text" - so the feeling is written as the stage the speaker is at while taking in
# what was put to them, and the direction is an actor's: a playable verb, the word
# the line leans on, the clause shape (the pause knob: sorrow fragments, anger
# runs on), and what the END of the line leaves open (a fall to the floor is
# certainty; a high, floating end is appeal, alarm, surprise). Valence barely
# travels in the acoustics, so the WORDS carry it: congruent wording per family.
# No sound words and no stage directions (the station strips a leading "ugh",
# #598, and a bracketed one is never said). One sentence, well under the 400-char
# cap; {name} and {feeling} are filled when the turn is planned (es_direction).
ES_V2_DIRECTION_LEAD = "{name} processes this as {feeling}: play it to "
ES_V2_DIRECTION = {
    "surprise":    "REACT - quick short phrases, one big late accent on the news-word, and let the end lift and float, unresolved.",
    "anger":       "CONFRONT - short hard words in one run-on push with no room to breathe, lean on the word that offends, and land the end with a hard fall.",
    "fear":        "WARN - quick broken phrases, a question left hanging, the voice climbing, and leave the end high and open, never settled.",
    "sadness":     "CONFIDE - short, plain, fragmented clauses with room between them, soft words, and let each end fall short and quiet.",
    "joy":         "CELEBRATE - bright, warm, generous words, lift the word that delights, keep it moving, and ride a long smooth fall at the end.",
    "disgust":     "DISMISS - clipped, flat, withholding words, slow down on the word that repels, and drop the end to the floor.",
    "interest":    "PROBE - brisk and precise, a pointed follow-up, light accents on the facts, and keep the end rising so the floor stays open.",
    "social":      "SAVE FACE - hedged, self-aware words, a small qualifier or two, and a soft, unresolved end.",
    "low_arousal": "SHRUG IT OFF - few, flat, unhurried words, nothing exclaimed, and let every end sink to the floor.",
}
ES_V2_ITEM_DIRECTION = {
    "fury":          "THREATEN, boiling - hit every stressed word, no pauses at all, and slam each end down.",
    "outrage":       "THREATEN, boiling - hit every stressed word, no pauses at all, and slam each end down.",
    "contempt":      "DISMISS, icy - controlled, over-precise words, nothing raised, and a low flat end.",
    "resentment":    "NEEDLE - controlled and precise, the grievance under every word, and a low flat end.",
    "anxiety":       "WORRY aloud - soft and even, a hesitation before the point, and a mid, unresolved end.",
    "unease":        "WORRY aloud - soft and even, a hesitation before the point, and a mid, unresolved end.",
    "dread":         "WORRY aloud - slow and low, a hesitation before the point, and an end that hangs.",
    "panic":         "RAISE THE ALARM - rapid fragments with breath-grabbing breaks, and the end high with no fall.",
    "despair":       "PLEAD - broken, reaching phrases that go back over the same point, strained and pitched up, the end falling away.",
    "grief":         "GRIEVE quietly - very plain words, short fragments with long gaps, and a shallow, late-falling end.",
    "pleasure":      "SAVOUR - easy, warm, unhurried words, gentle accents, and a soft settled end.",
    "satisfaction":  "SAVOUR - easy, warm, unhurried words, gentle accents, and a soft settled end.",
    "relief":        "SAVOUR - easy, warm, unhurried words, a breath of release, and a soft settled end.",
    "excitement":    "ENTHUSE - fast, bright, run-together words, a lift on every good thing, and a long smooth fall at the end.",
    "boredom":       "ENDURE - as few words as will do, drawn out and flat, and a steady fall to the floor at the end.",
    "calm":          "SOOTHE - slow, soft, even words, no contrast between them, and a gentle downward end.",
}


def _es_v2_item_voice(cid, word):
    got = ES_V2_ITEM_VOICE.get("%s.%s" % (cid, word), ES_V2_ITEM_VOICE.get(word))
    return dict(got) if got is not None else _es_item_voice(cid, word)


def _es1_v2():
    """ES1 with the v2 voices and directions (same ids, weights, badges, dims)."""
    table = copy.deepcopy(ES1)
    for cat in table["categories"]:
        cid = cat["id"]
        cat["voice"] = dict(ES_V2_VOICE[cid])
        for item in cat["items"]:
            word = item["label"]
            voice = _es_v2_item_voice(cid, word)
            if voice is not None:
                item["voice"] = voice
            item["text"] = ES_V2_DIRECTION_LEAD + ES_V2_ITEM_DIRECTION.get(word, ES_V2_DIRECTION[cid])
    return table


ES1_V2 = _es1_v2()
'''


def main(argv):
    do_apply = "--apply" in argv
    target = Path(next((a for a in argv if not a.startswith("--")), "system3_tables.py"))
    text = target.read_bytes().decode("utf-8")
    if "\r" in text:
        print("system3_tables.py is expected LF-only")
        return 1
    if MARKER in text:
        print("already applied")
        return 2
    missing = [n for n in NEEDS if n not in text]
    if missing:
        print("missing: " + ", ".join(missing))
        return 1
    if not do_apply:
        print("ready")
        return 0
    out = text.rstrip("\n") + "\n\n" + REGION.strip("\n") + "\n"
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(out.encode("utf-8"))
    os.replace(tmp, target)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
