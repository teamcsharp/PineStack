"""[whole-words:hosts] what the hosts are handed is cut at a sentence, never
where a character count fell.

The second half of [whole-words] (tools/whole_words_patch.py did the labels):
"its important people never get cut off in the middle of sentences". A sweep of
System 3 for raw slices of text a host is given: the subject's topic (a
Speakerbox seed passage was its first 400 characters), the angle, the seed, the
graph node's and call leg's protocol, the exchange opener and reply ("as
written"), favourites and directives, the landing, material passages. Each is
now whole_cut (the text untouched when it fits; past the cap, cut at a sentence
end, then a clause, then a word - its own line breaks kept) or sentence_cut
where the old code folded whitespace anyway. The caps are the same, so no
prompt grows. Slices used as equality probes (repeat and copy checks) are left
exactly as they were: both sides of a comparison must cut the same way.

Usage (ON THE HOST): python3 tools/whole_words2_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[whole-words:hosts]"

HELPER_AT = '''def canonical(value):
'''
HELPER = '''def whole_cut(text, cap):
    """[whole-words:hosts] `text` as it is when it fits in `cap`; past it, cut
    where a sentence ends (failing that a clause, failing that a word). Unlike
    sentence_cut it keeps the text's own line breaks - for prompts laid out."""
    s = str(text or "")
    cap = int(cap or 0)
    if cap <= 0 or len(s) <= cap:
        return s
    head = s[:cap + 1]
    floor = int(cap * 0.25)
    best = -1
    for m in _SENTENCE_END.finditer(head):
        if m.end() - 1 <= cap:
            best = m.end() - 1
    if best >= floor:
        return head[:best].rstrip()
    clause = max(head.rfind(", ", 0, cap), head.rfind("; ", 0, cap), head.rfind(": ", 0, cap))
    if clause >= floor:
        return head[:clause].rstrip(",;: ")
    space = max(head.rfind(" ", 0, cap), head.rfind("\\n", 0, cap))
    return head[:space if space > 0 else cap].rstrip()


def canonical(value):
'''

S3 = [
    (HELPER_AT, HELPER, 1),
    ('"subject": {"topic": str(subject.get("topic") or "")[:400],', '"subject": {"topic": whole_cut(subject.get("topic"), 400),', 1),
    ('"active_angle": str(subject.get("angle") or "")[:300],', '"active_angle": whole_cut(subject.get("angle"), 300),', 1),
    ('" ".join(str(landing.get("text") or "").split())[:400]', 'sentence_cut(landing.get("text"), 400)', 1),
    ('" ".join(str(step["topic"]).split())[:400]', 'sentence_cut(step["topic"], 400)', 1),
    ('" ".join(str(_t["text"]).split())[:400]', 'sentence_cut(_t["text"], 400)', 1),
    ('_legs_words(item.get("text"), inputs)[:400]', 'whole_cut(_legs_words(item.get("text"), inputs), 400)', 1),
    ('_legs_words(node["prompt"], inputs)[:600]', 'whole_cut(_legs_words(node["prompt"], inputs), 600)', 1),
    ('_call_words(leg.get("act"), call, _callend_words(conv, _end, seat))[:700]',
     'whole_cut(_call_words(leg.get("act"), call, _callend_words(conv, _end, seat)), 700)', 1),
    ('_call_words(leg.get("act"), call)[:400]', 'whole_cut(_call_words(leg.get("act"), call), 400)', 1),
    ('_legs_words(leg.get("act"), inputs)[:400]', 'whole_cut(_legs_words(leg.get("act"), inputs), 400)', 2),
    ('"topic": conv["subject"]["topic"][:120],', '"topic": label_cut(conv["subject"]["topic"], 120),', 1),
]

RT = [
    ('opener = " ".join(str(ex.get("opener") or "").split())[:400]', 'opener = system3.sentence_cut(ex.get("opener"), 400)', 1),
    ('reply = " ".join(str(ex.get("reply") or "").split())[:400]', 'reply = system3.sentence_cut(ex.get("reply"), 400)', 1),
    ('words = " ".join(str(text or "").split())[:400]', 'words = system3.sentence_cut(text, 400)', 1),
    ('line = " ".join(m.group("line").split())[:400]', 'line = system3.sentence_cut(m.group("line"), 400)', 1),
    ('"label": line[:60], "text": line,', '"label": system3.label_cut(line), "text": line,', 1),
    ('"label": text[:60], "text": text[:500],', '"label": system3.label_cut(text), "text": system3.whole_cut(text, 500),', 1),
    ('topic = (angle or seed_text or news)[:400]', 'topic = system3.whole_cut(angle or seed_text or news, 400)', 1),
    ('"angle": angle[:300],', '"angle": system3.whole_cut(angle, 300),', 1),
    ('" ".join(seed_text.split())[:1500]', 'system3.sentence_cut(seed_text, 1500)', 1),
    ('"text": text[:400]}', '"text": system3.whole_cut(text, 400)}', 1),
    ('" ".join(str(landing.get("text") or "").split())[:400]', 'system3.sentence_cut(landing.get("text"), 400)', 1),
    ('"topic": str(meta.get("topic") or "")[:400],', '"topic": system3.whole_cut(meta.get("topic"), 400),', 1),
    ('" ".join(str(r.get("reply") or "").split())[:400]', 'system3.sentence_cut(r.get("reply"), 400)', 1),
    ('"subject": {"topic": context[:400],', '"subject": {"topic": system3.whole_cut(context, 400),', 1),
    ('" ".join(str(ctx.get("text") or "").split())[:600]', 'system3.sentence_cut(ctx.get("text"), 600)', 1),
    ('"text": mat["text"][:600], "door"', '"text": system3.whole_cut(mat["text"], 600), "door"', 1),
    ('"text": str(x)[:600]} for m, x in turns', '"text": system3.whole_cut(x, 600)} for m, x in turns', 1),
    ('"topic": str(s.get("topic") or "")[:120],', '"topic": system3.label_cut(s.get("topic") or "", 120),', 1),
    ('"topic": str((conv.get("subject") or {}).get("topic") or "")[:240],',
     '"topic": system3.label_cut((conv.get("subject") or {}).get("topic") or "", 240),', 1),
    ('"topic": str(conv["subject"].get("topic") or "")[:160],', '"topic": system3.label_cut(conv["subject"].get("topic") or "", 160),', 1),
]


def patch(path, edits, mode, first=False):
    src = open(path, encoding="utf-8").read()
    if MARK in src or (not first and "system3.whole_cut(" in src):
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
    shutil.copy(path, "/tmp/%s.bak-whole-words2" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    patch(ROOT + "/system3.py", S3, mode, first=True)
    patch(ROOT + "/system3_runtime.py", RT, mode)
