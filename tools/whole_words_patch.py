"""[whole-words] nobody is cut off in the middle of a sentence.

"so why is this cut off? what is cutting that off? is that getting cut off
with the hosts?" / "its important people never get cut off in the middle of
sentences"

The popup showed the TOPIC roll landing on "...and took a seat a": every System
3 roll kept its entries' labels as the first 90 characters (80, 120 in places),
wherever that count fell. The hosts were given the whole topic (sentence_cut,
300) on the three prompt roads - but the conversation graph's topic-change
options were the first 120 characters of a board row, and those DO reach a
host; the board's longest row is 273. Now every label is label_cut (whole
sentences, 400), the graph's options and the plan's text and reply are
sentence_cut, and the prompt roads hand over up to 400 - a whole board row.

Usage (ON THE HOST): python3 tools/whole_words_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HELPER_AT = '''def canonical(value):
'''
HELPER = '''LABEL_CHARS = 400                                                    # [whole-words]


def label_cut(text, cap=LABEL_CHARS):
    """[whole-words] a roll's label as the cards and popups show it: whole
    sentences (sentence_cut), never stopped where a character count fell -
    "its important people never get cut off in the middle of sentences"."""
    return sentence_cut(text, cap)


def canonical(value):
'''

S3 = [
    (HELPER_AT, HELPER, 1),
    ('"label": tp.get("text", "")[:90]})', '"label": label_cut(tp.get("text", ""))})', 1),
    ('str(got.get("label") or kind)[:80]', 'label_cut(got.get("label") or kind)', 1),
    ('"text": str(got["text"])[:200], "ref"', '"text": label_cut(got["text"]), "ref"', 1),
    ('conv["subject"]["topic"][:120] or why', 'label_cut(conv["subject"]["topic"]) or why', 1),
    ('" ".join(str(t["text"]).split())[:90]', 'label_cut(t["text"])', 2),
    ('turn["topic_material"]["text"][:120]', 'label_cut(turn["topic_material"]["text"])', 1),
    ('plan["text"][:90]', 'label_cut(plan["text"])', 2),
    ('"not this time: " + r["text"][:80]', '"not this time: " + label_cut(r["text"])', 1),
    ('r["text"][:90]', 'label_cut(r["text"])', 2),
    ('str(fav.get("text") or "")[:90]', 'label_cut(fav.get("text") or "")', 1),
    ('str(plan.get("text") or "")[:90]', 'label_cut(plan.get("text") or "")', 1),
    ('str(c.get("text") or "")[:90]', 'label_cut(c.get("text") or "")', 1),
    # these three reach a host
    ('[str(item.get("text") or "")[:120]', '[sentence_cut(item.get("text") or "", 400)', 1),
    ('" ".join(str(chosen.get("reply") or "").split())[:400]', 'sentence_cut(chosen.get("reply") or "", 400)', 1),
    ('" ".join(str(chosen["text"]).split())[:400]', 'sentence_cut(chosen["text"], 400)', 1),
    ('sentence_cut(topic["text"], 300)', 'sentence_cut(topic["text"], 400)', 3),
]

RT = [
    ('"label": str(label or key)[:90], "text": str(label or key)[:300],',
     '"label": system3.label_cut(label or key), "text": system3.label_cut(label or key),', 1),
    ('str((row or {}).get("label") or label or key)[:90]', 'system3.label_cut((row or {}).get("label") or label or key)', 1),
    ('"label": str(label or key)[:90], "weight": 1.0,', '"label": system3.label_cut(label or key), "weight": 1.0,', 1),
    ('str(cat.get("label") or label or key)[:90]', 'system3.label_cut(cat.get("label") or label or key)', 1),
    ('"label": str(label or key)[:90], "u"', '"label": system3.label_cut(label or key), "u"', 1),
    ('("the manager\'s message: " + res["topic_text"])[:90]', 'system3.label_cut("the manager\'s message: " + res["topic_text"])', 1),
    ('str(r.get("picked") or "")[:90]', 'system3.label_cut(r.get("picked") or "")', 1),
    ('"text": str(val["text"])[:1200], "label": str(val.get("label") or kind)[:80],',
     '"text": system3.sentence_cut(val["text"], 1200), "label": system3.label_cut(val.get("label") or kind),', 1),
    ('str(sel.get("label") or sel.get("id") or "")[:80]', 'system3.label_cut(sel.get("label") or sel.get("id") or "")', 1),
    ('(carry.get("landing") or {}).get("text", "")[:120]', 'system3.label_cut((carry.get("landing") or {}).get("text", ""))', 1),
]

GOLD = [
    ('" ".join(str(g["text"]).split())[:90]', 's3.label_cut(g["text"])', 1),
    ('" ".join(str(picked["text"]).split())[:90]', 's3.label_cut(picked["text"])', 1),
]


def patch(path, edits, mode):
    src = open(path, encoding="utf-8").read()
    if "[whole-words]" in src or (path.endswith("_gold.py") and "s3.label_cut(" in src):
        print(path + ": APPLIED")
        return
    out = src
    for old, new, n in edits:
        got = out.count(old)
        assert got == n, "%s: %r found %d, want %d" % (path, old[:50], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-whole-words" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    patch(ROOT + "/system3.py", S3, mode)
    patch(ROOT + "/system3_runtime.py", RT, mode)
    patch(ROOT + "/system3_gold.py", GOLD, mode)
