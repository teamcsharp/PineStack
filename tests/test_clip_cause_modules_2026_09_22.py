import json
import socket

import clip_senses
import clip_speech
import sfx_match
import word_cause_edits


def _socket_event(payload: bytes):
    left, right = socket.socketpair()
    try:
        right.sendall(payload)
        right.close()
        return clip_speech.read_event(left, bytearray())
    finally:
        left.close()


def test_wyoming_frame_keeps_data_out_of_header():
    body = clip_speech.frame("audio-chunk", {"rate": 16000}, b"abc")
    head, rest = body.split(b"\n", 1)
    parsed = json.loads(head.decode("utf-8"))
    assert parsed["type"] == "audio-chunk"
    assert parsed["data_length"] == len(b'{"rate": 16000}')
    assert parsed["payload_length"] == 3
    assert b'"data"' not in head
    assert rest.endswith(b"abc")


def test_wyoming_reader_accepts_data_block_and_payload():
    event = clip_speech.frame("transcript", {"text": "hello there"}, b"pcm")
    assert _socket_event(event) == ("transcript", {"text": "hello there"}, b"pcm")


def test_clip_senses_keeps_antonyms_beside_synonyms():
    widened = clip_senses.widen("good", most=3)
    assert "bad" in widened
    assert widened["bad"] == clip_senses.ANTONYM
    assert clip_senses.senses("bank") > 1


def test_sfx_match_finds_words_added_to_bare_clip_names():
    index = sfx_match.ClipIndex().build([
        (1, "1965 clip serious office desk", "yt", False, 3.0),
        (2, "breakfast pancakes", "yt", False, 3.0),
    ])
    cands = index.score("he is sitting at his desk in the office looking serious")
    assert cands
    assert cands[0].rowid == 1
    why = sfx_match.explain(cands[0])
    assert "desk" in why
    assert "office" in why


def test_word_cause_edits_produces_honest_undo_calls():
    row = word_cause_edits.row(
        "/api/speakbox/weight", key="docs/ylyl.md", was=8, now=3, at=1.0)
    call = word_cause_edits.undo_call(row)
    assert call["endpoint"] == "/api/speakbox/weight"
    assert call["body"] == {"file": "docs/ylyl.md", "weight": 8, "was": 3}

    banned = word_cause_edits.row("/api/phrase/ban", word="handrail", at=2.0)
    assert banned["undoable"] is False
    assert word_cause_edits.undo_call(banned) is None
    assert "cannot be put back" in banned["why_not"]
