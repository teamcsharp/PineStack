#!/usr/bin/env python3
"""[cut-anyway] [speech-idle] A supercut is assembled from what the clips say; the clips are listened to in idle time. 2026-10-05.

The operator: "why are the supercuts unable to be assembled? When I ask for a
supercut, I want a task to be dispatched that's able to do whatever it takes
to locate whatever is needed to assemble that supercut ... We can increase the
randomness of the clips that are used in the supercuts or how accurate on the
fly" (and #1579: "idle time being used for indexing and transcribing").

Measured on the live station that afternoon:
  * 356,952 playable clips, 18,810 with a transcript (5.3%). Eight clips were
    listened to in the last 24 hours: the listener (sfx_speech_bite) runs only
    when POST /api/sfx/speech is pressed, forty clips a press. Nothing took
    the bites its own comment promises.
  * both custom supercuts on the desk were "incomplete": every requested word
    had to be found AND a second ASR pass on the estimated word window had to
    return exactly those words, or the whole job was dropped - and the
    renderer refused any custom plan that was not word-for-word verified.

What this changes:
  app.py
    - sfx_speech_clock: the listener takes a bite on its own clock whenever
      the writing room has nothing waiting (ten clips, thirty seconds apart;
      forty and five while the station is paused), and tells the match index
      every twentieth bite. GET /api/sfx/speech shows it working.
  sfx_supercut_custom.py
    - an accuracy dial per request (0-100, default 70; 100 is the old rule).
      Below 100 a trimmed window is accepted when the requested words were
      heard inside it or nearly; a phrase no window was heard cleanly for is
      cut where its clip's own transcript puts it, marked unverified; and a
      word no clip says is listed and left out instead of ending the job.
      A job with at least one cut is rendered and says what it could not find.
  sfx_supercut.py
    - the renderer takes a custom plan below accuracy 100 without the
      word-for-word proof.

Usage:  cut_anyway_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        cut_anyway_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------- app.py
CLOCK_OLD = r'''@app.get("/api/sfx/speech")
async def sfx_speech_look_api(                                 # [#1386]
'''
CLOCK_NEW = r'''# --- [speech-idle] THE LISTENER TAKES ITS BITES ON ITS OWN CLOCK -------------------
# "I want idle time being used for indexing and transcribing and understanding
# clips" (the operator, #1579, 2026-10-05). The note above says the listener
# "takes it in bites, only when the writing room has nothing waiting" - and
# nothing ever took them: a bite ran only when POST /api/sfx/speech was pressed.
# Measured that day: 18,810 of 356,952 playable clips had words (5.3%), eight
# listened to in 24 hours - which is why a supercut could not find its words.
SFX_SPEECH_IDLE_BITE = int(os.getenv("PINE_SPEECH_IDLE_BITE", "10"))
SFX_SPEECH_IDLE_REST = float(os.getenv("PINE_SPEECH_IDLE_REST", "30"))


async def sfx_speech_clock() -> None:
    """A bite of clips whenever the writing room has nothing waiting. Small on
    air (the transcriber also answers the microphones), larger while paused."""
    await asyncio.sleep(150)
    bites = 0
    while True:
        rest = SFX_SPEECH_IDLE_REST
        try:
            if _SFX_SPEECH.get("running"):
                pass                                    # a pressed bite is still listening
            else:
                waiting = 0
                try:
                    waiting = sum(1 for j in (writing_room_state().get("jobs") or [])
                                  if j.get("state") == "waiting")
                except Exception:  # noqa: BLE001
                    waiting = 0
                if waiting:
                    _SFX_SPEECH["why"] = ("idle listening stands aside: %d job(s) waiting in the writing room"
                                          % waiting)
                else:
                    paused = bool(radio_paused())
                    _SFX_SPEECH.update({"running": True, "why": ""})
                    try:
                        await asyncio.to_thread(sfx_speech_bite, SFX_SPEECH_IDLE_BITE * (4 if paused else 1))
                    finally:
                        _SFX_SPEECH["running"] = False
                    bites += 1
                    _SFX_SPEECH["idle_bites"] = bites
                    if bites % 20 == 0:
                        sfx_match_kick()                # what he can hear has changed
                    if paused:
                        rest = 5.0
        except Exception as exc:  # noqa: BLE001
            _SFX_SPEECH["why"] = "idle listening: %s: %s" % (type(exc).__name__, str(exc)[:120])
        await asyncio.sleep(rest)


@app.get("/api/sfx/speech")
async def sfx_speech_look_api(                                 # [#1386]
'''

WORKER_OLD = r'''    radio_worker_start("flow_release", flow_release_clock)      # [s3-flow-open] the held rounds go back
'''
WORKER_NEW = r'''    radio_worker_start("flow_release", flow_release_clock)      # [s3-flow-open] the held rounds go back
    radio_worker_start("sfx_speech", sfx_speech_clock)          # [speech-idle] the clips are listened to in idle time
'''

# ---------------------------------------------------------------------------- sfx_supercut_custom.py
HELP_OLD = r'''def recursive(source):
'''
HELP_NEW = r'''# [cut-anyway] HOW EXACT A CUT HAS TO BE IS A DIAL, NOT A WALL. 100 is the old
# rule: a second ASR pass on the trimmed window must return exactly the words
# asked for, and one word that fails ends the whole job. Below 100 the job is
# assembled from what the clips say: a window is taken when the words were heard
# inside it (or nearly - the dial is the similarity wanted), a phrase no window
# was heard cleanly for is cut where its clip's own transcript puts it, and a
# word no clip says is listed and left out.
import difflib

DEFAULT_ACCURACY = 70.


def heard_close(heard, want, accuracy):
    """May a trimmed window heard as `heard` stand for the words `want`?"""
    if heard == want:
        return True
    if accuracy >= 100. or not heard or not want:
        return False
    size = len(want)
    if any(heard[at:at + size] == want for at in range(len(heard) - size + 1)):
        return True                     # the words are in there, with a neighbour's syllable around them
    return difflib.SequenceMatcher(None, ' '.join(heard), ' '.join(want)).ratio() * 100. >= accuracy


def recursive(source):
'''

CREATE_OLD = r'''            'target_seconds':max(.06,min(120.,cut._number(raw.get('target_seconds'),60.))),
'''
CREATE_NEW = r'''            'target_seconds':max(.06,min(120.,cut._number(raw.get('target_seconds'),60.))),
            'accuracy':max(0.,min(100.,cut._number(raw.get('accuracy'),DEFAULT_ACCURACY))),   # [cut-anyway] 100 = exact words only
'''

VISIT_OLD = r'''        wanted=tokens(row['words'])
        transcriber=getattr(self.host.get('clip_speech'),'transcribe_file',None)
'''
VISIT_NEW = r'''        wanted=tokens(row['words'])
        accuracy=cut._number(row.get('accuracy'),DEFAULT_ACCURACY)   # [cut-anyway] a job from before the dial is not exact-only
        transcriber=getattr(self.host.get('clip_speech'),'transcribe_file',None)
'''

ACCEPT_OLD = r'''                            if tokens(proof['said'])==wanted[cursor:cursor+size]:
                                selected={**source,**proof,'from_s':start,'until_s':end,
                                    'role':'sell','requested_words':phrase,'timing_basis':basis,
                                    'transcript_scope':'current_trimmed_window_asr','why':{'exact_requested_words':phrase,'verified_audio':True}}
'''
ACCEPT_NEW = r'''                            if heard_close(tokens(proof['said']),wanted[cursor:cursor+size],accuracy):   # [cut-anyway]
                                selected={**source,**proof,'from_s':start,'until_s':end,
                                    'role':'sell','requested_words':phrase,'timing_basis':basis,
                                    'transcript_scope':'current_trimmed_window_asr','why':{'exact_requested_words':phrase,
                                        'verified_audio':tokens(proof['said'])==wanted[cursor:cursor+size],'heard':str(proof['said'])[:120]}}
'''

MISSING_OLD = r'''                if not selected:
                    word=wanted[cursor]
                    row['missing_words'].append(word);row['missing_phrases'].append(word);row['cursor']+=1
                self.persist(row)
            if row['missing_words']:
                row.update(status='incomplete',why='Some requested words have no verified trimmed source audio. Edit the words or retry after new clips arrive.')
                self.persist(row);return
'''
MISSING_NEW = r'''                if not selected and accuracy<100.:
                    # [cut-anyway] NO WINDOW WAS HEARD CLEANLY: the clip whose own transcript says
                    # these words is cut where the words are estimated to be, and marked unverified
                    for size in range(min(8,len(wanted)-cursor),0,-1):
                        phrase=' '.join(wanted[cursor:cursor+size])
                        pool=row['scan']['phrases'].get(phrase,[])
                        if pool:
                            source=pool[0];start,end,basis=source['windows'][0]
                            selected={**source,'from_s':start,'until_s':end,'role':'sell','requested_words':phrase,
                                'timing_basis':basis,'said':phrase,'source_audio_verified':False,'word_cut_verified':False,
                                'source_window':[start,end],'transcript_scope':'source_transcript_estimate',
                                'why':{'exact_requested_words':phrase,'verified_audio':False}}
                            for name in ('windows','word_timestamps','word_offset','word_count','mtime'):
                                selected.pop(name,None)
                            row['cuts'].append(selected);row['cursor']+=size;row['matched_words']+=size
                            row['unverified_words']=int(row.get('unverified_words') or 0)+size
                            break
                if not selected:
                    word=wanted[cursor]
                    row['missing_words'].append(word);row['missing_phrases'].append(word);row['cursor']+=1
                self.persist(row)
            if row['missing_words'] and (accuracy>=100. or not row['cuts']):   # [cut-anyway] below 100 a job with any cut is still assembled
                row.update(status='incomplete',why=('Some requested words have no verified trimmed source audio. Edit the words or retry after new clips arrive.'
                    if accuracy>=100. else 'No clip that has been listened to says any of these words yet. The idle listener is still working through the collection; retry later or change the words.'))
                self.persist(row);return
'''

PLAN_OLD = r'''                'item':row['product'],'custom':{'id':ident,'words':row['words'],'max_seconds':row['target_seconds']}})
'''
PLAN_NEW = r'''                'item':row['product'],'custom':{'id':ident,'words':row['words'],'max_seconds':row['target_seconds'],
                    'accuracy':accuracy}})   # [cut-anyway] the renderer reads the same dial
'''

READY_OLD = r'''            row.update(status='ready',why='',archive_id=result['archive_id'],archive=result['archive'],updated_at=time.time())
'''
READY_NEW = r'''            row.update(status='ready',archive_id=result['archive_id'],archive=result['archive'],updated_at=time.time(),
                why=('' if not (row['missing_words'] or row.get('unverified_words')) else   # [cut-anyway] it says what it could not find
                    'Assembled at accuracy %d: %d of %d words are in it%s%s.' % (int(accuracy),row['matched_words'],row['total_words'],
                        (', %d of them cut on the transcript\'s estimate' % int(row.get('unverified_words') or 0)) if row.get('unverified_words') else '',
                        ('; no listened clip says: '+', '.join(row['missing_words'][:12])) if row['missing_words'] else '')))
'''

PROOF_OLD = r''''structure':{'exact_requested_words_verified':True},'source_analysis':'''
PROOF_NEW = r''''structure':{'exact_requested_words_verified':bool(accuracy>=100. or not (row['missing_words'] or row.get('unverified_words'))),
                    'missing_words':list(row['missing_words']),'unverified_words':int(row.get('unverified_words') or 0)},'source_analysis':'''

# ---------------------------------------------------------------------------- sfx_supercut.py
RENDER_OLD = r'''        if not all(p.get('word_cut_verified') and p.get('source_audio_verified') for p in clips):
            raise ValueError('Every custom word cut needs verified trimmed source audio')
        if tokens(' '.join(p.get('said') or '' for p in clips)) != tokens(custom.get('words')):
            raise ValueError('The custom audio differs from the exact requested words')
'''
RENDER_NEW = r'''        exact = _number(custom.get('accuracy'), 100.) >= 100.     # [cut-anyway] the request's own dial; 100 is word for word
        if exact and not all(p.get('word_cut_verified') and p.get('source_audio_verified') for p in clips):
            raise ValueError('Every custom word cut needs verified trimmed source audio')
        if exact and tokens(' '.join(p.get('said') or '' for p in clips)) != tokens(custom.get('words')):
            raise ValueError('The custom audio differs from the exact requested words')
'''

EDITS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "app.py": [
        ("the idle listener", CLOCK_OLD, CLOCK_NEW, "async def sfx_speech_clock(", 1),
        ("its worker", WORKER_OLD, WORKER_NEW, 'radio_worker_start("sfx_speech"', 1),
    ],
    "sfx_supercut_custom.py": [
        ("the dial and its test", HELP_OLD, HELP_NEW, "def heard_close(heard, want, accuracy):", 1),
        ("a request carries it", CREATE_OLD, CREATE_NEW, "# [cut-anyway] 100 = exact words only", 1),
        ("the visit reads it", VISIT_OLD, VISIT_NEW, "# [cut-anyway] a job from before the dial is not exact-only", 1),
        ("a close window is taken", ACCEPT_OLD, ACCEPT_NEW, "accuracy):   # [cut-anyway]", 1),
        ("a job is assembled anyway", MISSING_OLD, MISSING_NEW, "# [cut-anyway] NO WINDOW WAS HEARD CLEANLY", 1),
        ("the plan carries the dial", PLAN_OLD, PLAN_NEW, "# [cut-anyway] the renderer reads the same dial", 1),
        ("it says what it left out", READY_OLD, READY_NEW, "# [cut-anyway] it says what it could not find", 1),
        ("the plan's proof is honest", PROOF_OLD, PROOF_NEW, "'unverified_words':int(row.get('unverified_words') or 0)},'source_analysis':", 1),
    ],
    "sfx_supercut.py": [
        ("the renderer honours the dial", RENDER_OLD, RENDER_NEW, "# [cut-anyway] the request's own dial", 1),
    ],
}


def _read(path: Path) -> tuple[str, bool]:
    text = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise SystemExit("%s has bare carriage returns; refusing to guess" % path)
    return text, crlf


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            _n, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-24s %-30s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for _n, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _n)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _n, "probe")
        if todo:
            tmp = path.with_name(path.name + ".cutanyway.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
