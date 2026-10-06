"""Pure topic-led fictional Gazette desks; the host supplies dice and writer.

No topic-bank writes or invented broadcast facts. Media briefs preserve the
same rolled case and cast for the station's existing Comfy and H3 queues.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import re
from typing import Any, Callable

SCHEMA = "gazette.editorial/1"
MAYOR = "Mayor Vera Bellweather"
CRONIES = ("Deputy Mayor Mavis Pike", "Procurement Chief Lionel Crumb")
RESIDENTS = ("Alma Reed", "Dottie Vale", "Felix Moss", "Nell Quill", "Otis Finch")
VISUAL_IDENTITIES = {
    MAYOR: "a middle-aged woman with a silver bob, plum suit and brass pine brooch",
    CRONIES[0]: "a woman with short auburn hair, green jacket and narrow oval spectacles",
    CRONIES[1]: "a balding man with a curled moustache, tan suit and red pocket square",
}
DEPARTMENTS = (
    "Pinebox Police Department", "City Hall", "Public Works Department",
    "Housing and Permits Office", "Parks and Sanitation Department",
    "City Ethics Office", "Treasury Department",
)
REACTIONS = (
    ("double_down", "doubles down", "defends the original take and announces an even bolder version"),
    ("defend", "defends the take", "insists the remarks were a principled policy decision"),
    ("deny", "denies the context", "claims the recording is missing context while residents produce the rest"),
    ("blame", "blames a crony", "blames the aide beside her, who immediately sends a contradictory reply"),
    ("apologise", "issues a slippery apology", "apologises for the wording while keeping the disputed arrangement"),
    ("reverse", "reverses course", "withdraws the policy after an awkward public confrontation"),
)
ANGLES = (
    "a private favour concealed inside a public contract",
    "an official fee waived for a friend and charged to everyone else",
    "a city committee awarding itself an allowance",
    "a donor receiving the first place in a public queue",
    "a missing receipt that reappears with an official's handwritten instruction",
    "a public service quietly reserved for the mayor's inner circle",
)
DETAILS = (
    "a stamped envelope delivered to the wrong desk",
    "a carbon-copy invoice with a suspicious handwritten amendment",
    "a council microphone left live after the meeting",
    "a queue ticket bearing the deputy mayor's initials",
    "a locked filing cabinet whose key is on a donor's keyring",
    "an expense claim disguised as a neighbourhood consultation",
)
TWISTS = (
    "a resident sends the same question to two departments and receives incompatible answers",
    "a crony contradicts the mayor while trying to defend her",
    "the original complainant offers a suspiciously convenient service in the classifieds",
    "a request for records uncovers a second favour hidden in the same file",
    "a caller recognises an official's phrase and sends the newspaper a correction",
    "a department's reply accidentally includes the internal note it meant to delete",
)
EMOTIONS = ("smug amusement", "defensive irritation", "barely concealed nervousness",
            "indignant confusion", "weary disbelief", "gleeful outrage")
SECTIONS = (
    {"section": "classifieds", "page": 4, "desk": "Small Ads", "style_hint": "classified",
     "forms": ("FOR SALE", "WANTED", "LOST AND FOUND", "PERSONALS", "SERVICES"), "kicker": "CITY CLASSIFIEDS"},
    {"section": "phones", "page": 3, "desk": "Letters and Correspondence", "style_hint": "report",
     "forms": ("a resident's letter and a named official's reply", "two neighbours exchanging messages",
               "a complaint to the police and the police response", "a caller's open letter to City Hall"),
     "kicker": "LETTERS AND REPLIES"},
    {"section": "wire", "page": 3, "desk": "City News", "style_hint": "report",
     "forms": ("a city news brief", "a tabloid investigation", "a neighbourhood hearing", "a public-records revelation"),
     "kicker": "CITY NEWS"},
    {"section": "interview", "page": 5, "desk": "The Mayor's Interview", "style_hint": "interview",
     "forms": ("a combative mayoral interview", "a mayor and crony joint interview", "a doorstep interview after the scandal",
               "a crony's disastrous attempt to defend the mayor"), "kicker": "MAYOR UNDER QUESTION"},
    {"section": "upstairs", "page": 5, "desk": "Department Replies", "style_hint": "minutes",
     "forms": ("an official notice followed by residents' replies", "a department memo accidentally made public",
               "a police statement challenged by a resident", "a City Hall reply and a follow-up demand"),
     "kicker": "FROM THE DEPARTMENTS"},
    {"section": "gallery", "page": 4, "desk": "Caught on Camera", "style_hint": "crime",
     "forms": ("a hidden-camera expose", "a leaked council-room recording", "an undercover corridor conversation",
               "a public confrontation over a secret recording"), "kicker": "CAUGHT ON CAMERA"},
)


def _text(value: Any, cap: int = 500) -> str:
    return " ".join(str(value or "").split())[:cap]


def _number(value: Any, default: float = 1.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def eligible_topics(topics: Any, material: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Only actual active bank rows. A missing bank never gets a fake topic."""
    current = _text((material or {}).get("topic_set") or (material or {}).get("active_topic_set"), 120)
    out, seen = [], set()
    for source in topics or []:
        if not isinstance(source, dict):
            continue
        ident, text = _text(source.get("id"), 120), _text(source.get("text"), 400)
        state = _text(source.get("state") or source.get("status"), 40).lower()
        if (not ident or not text or ident in seen or source.get("enabled") is False
                or source.get("active") is False or source.get("disabled") is True
                or state in {"off", "disabled", "inactive", "binned", "rejected", "pen"}
                or source.get("binned_at") or source.get("rejected_at")):
            continue
        topic_set = _text(source.get("topic_set") or source.get("set"), 120)
        if current and topic_set and current != topic_set:
            continue
        weight = _number(source.get("weight", 1.0))
        if weight <= 0:
            continue
        used = max(0.0, _number(source.get("used", source.get("plays", 0)), 0.0))
        seen.add(ident)
        out.append({"id": ident, "text": text, "reply": _text(source.get("reply"), 400),
                    "kind": _text(source.get("kind") or "topic", 30), "weight": weight, "used": used,
                    "source": _text(source.get("source") or "topics.board", 120),
                    **({"topic_set": topic_set} if topic_set else {})})
    return out


def _previous(previous: Any) -> list[dict[str, Any]]:
    if isinstance(previous, dict):
        if previous.get("kind") == "fictional_city":
            return [previous]
        rows = previous.get("articles") or previous.get("plans") or previous.get("stories") or []
    else:
        rows = previous or []
    found = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        receipt = (row.get("meta") or {}).get("editorial") if isinstance(row.get("meta"), dict) else None
        receipt = receipt if isinstance(receipt, dict) else row
        if receipt.get("kind") == "fictional_city" or receipt.get("schema") == SCHEMA:
            found.append(receipt)
    return found


def _names(material: dict[str, Any]) -> list[str]:
    names = [_text(row.get("name"), 80) for row in list(material.get("calls") or []) + list(material.get("callers") or [])
             if isinstance(row, dict) and _text(row.get("name"), 80)]
    faces = material.get("caller_faces")
    if isinstance(faces, dict):
        names.extend(_text(name, 80) for name in faces if _text(name, 80))
    return list(dict.fromkeys(names + list(RESIDENTS)))[:60]


def _emotion_rows(emotions: Any) -> list[str]:
    rows = []
    for value in emotions or []:
        if isinstance(value, dict):
            value = value.get("acting") or value.get("direction") or value.get("text") or value.get("label")
        if _text(value, 200):
            rows.append(_text(value, 200))
    return list(dict.fromkeys(rows + list(EMOTIONS)))[:80]


def plan(topics: Any, material: dict[str, Any], weighted: Callable, *, seeds: Any = None,
         previous: Any = None, emotions: Any = None, most: int = 6) -> list[dict[str, Any]]:
    """Roll the running order with the station's s3_weighted signature."""
    topics = eligible_topics(topics, material)
    count = max(0, min(len(SECTIONS), int(most)))
    if not topics or not count:
        return []
    history = _previous(previous)
    recent = {str((row.get("topic") or {}).get("id") or row.get("topic_id") or "") for row in history}
    weights = [row["weight"] / (1.0 + row["used"]) * (0.3 if row["id"] in recent else 1.0) for row in topics]
    shared_rolls = []

    def draw(stage, choices, receipts, *, weights=None, labels=None):
        labels = labels or [_text(row, 180) for row in choices]
        effective = list(weights if weights is not None else [1.0] * len(choices))
        key = "gazette.editorial." + stage
        selected = weighted(key, labels, effective, "Gazette: " + stage.replace(".", " "))
        selected = selected if isinstance(selected, int) and 0 <= selected < len(choices) and effective[selected] > 0 else next((i for i, w in enumerate(effective) if w > 0), 0)
        receipts.append({"key": key, "stage": stage, "candidates": list(labels), "weights": effective,
                         "index": selected, "selected": labels[selected]})
        return copy.deepcopy(choices[selected])

    labels = [row["id"] + ": " + row["text"] for row in topics]
    arc_topic = draw("arc.topic", topics, shared_rolls, weights=weights, labels=labels)
    angle = draw("arc.corruption", list(ANGLES), shared_rolls)
    official = draw("arc.official", [MAYOR, *CRONIES], shared_rolls)
    reaction = draw("arc.reaction", list(REACTIONS), shared_rolls, weights=[2.0, 1.5, 1.0, 1.0, 0.8, 0.7],
                    labels=[row[1] for row in REACTIONS])
    evidence = draw("arc.evidence", list(DETAILS), shared_rolls)
    prior_arc = next((row.get("arc") for row in history if isinstance(row.get("arc"), dict)
                      and str((row["arc"].get("topic") or {}).get("id") or "") == arc_topic["id"]), {})
    mode = draw("arc.continuity", ["new scandal", "follow-up to the previous city file"], shared_rolls,
                weights=[2.0, 1.0 if prior_arc else 0.0])
    if mode.startswith("follow-up") and prior_arc:
        angle, evidence, official = (prior_arc.get(key, value) for key, value in
                                     (("corruption", angle), ("evidence", evidence), ("official", official)))
        for receipt in shared_rolls:
            if receipt["stage"] in {"arc.corruption", "arc.evidence", "arc.official"}:
                receipt["used"] = False
                receipt["overridden_by"] = "arc.continuity: retain the published case facts"
    arc_id = (prior_arc.get("id") if mode.startswith("follow-up") else "") or (
        "city-file-" + arc_topic["id"] + "-" + hashlib.sha1((angle + evidence + official).encode()).hexdigest()[:8])
    arc = {"id": arc_id, "topic": arc_topic, "official": official, "mayor": MAYOR, "cronies": list(CRONIES),
           "corruption": angle, "evidence": evidence,
           "reaction": {"id": reaction[0], "label": reaction[1], "direction": reaction[2]}, "continuity": mode,
           "previous": {"id": prior_arc.get("id"), "reaction": prior_arc.get("reaction")}
                       if mode.startswith("follow-up") and prior_arc else {}}
    station = _text(material.get("station") or "Pine Box FM", 120)
    hosts = [name for name in (_text(material.get("host"), 80), _text(material.get("cohost"), 80)) if name]
    residents, feelings = _names(material), _emotion_rows(emotions)
    seeds = [copy.deepcopy(row) for row in seeds or [] if isinstance(row, dict) and _text(row.get("text"))]
    plans = []
    for index, section in enumerate(SECTIONS[:count]):
        slug, rolls = section["section"], copy.deepcopy(shared_rolls)
        theme_weights = [weight * (3.0 if row["id"] == arc_topic["id"] else 1.0) for row, weight in zip(topics, weights)]
        topic = draw(slug + ".topic", topics, rolls, weights=theme_weights, labels=labels)
        form = draw(slug + ".form", list(section["forms"]), rolls)
        resident = draw(slug + ".resident", residents, rolls)
        other = draw(slug + ".correspondent", [name for name in residents if name != resident] or residents, rolls)
        department = draw(slug + ".department", list(DEPARTMENTS), rolls)
        cast_official = draw(slug + ".official", list(dict.fromkeys([official, MAYOR, *CRONIES])), rolls)
        local_angle = draw(slug + ".angle", list(ANGLES), rolls)
        emotion = draw(slug + ".emotion", feelings, rolls)
        reply_emotion = draw(slug + ".reply_emotion", feelings, rolls)
        detail = draw(slug + ".detail", list(DETAILS), rolls)
        twist = draw(slug + ".expansion", list(TWISTS), rolls)
        host_link = draw(slug + ".station_link", ["a letter addressed to the station's hosts",
            "a message left with the request line", "an invitation to a future station interview",
            "a caller's written follow-up to the newspaper", "a notice pinned outside the station"], rolls)
        source_mode = draw(slug + ".speakerbox_mode", ["texture", "contradiction", "official phrasing", "none"], rolls,
                           weights=[2.0, 1.0, 1.0, 0.5] if seeds else [0.0, 0.0, 0.0, 1.0])
        seed = draw(slug + ".speakerbox", seeds, rolls,
                    labels=[_text(row.get("file") or row.get("text"), 160) for row in seeds]) if seeds and source_mode != "none" else {}
        second = draw(slug + ".second_pass", [False, True], rolls, weights=[3.0, 1.0], labels=["first draft", "cohesion pass"])
        item = {"schema": SCHEMA, "kind": "fictional_city", "fictional": True, "index": index,
            "id": "gazette-editorial-" + slug + "-" + topic["id"], "section": slug, "page": section["page"],
            "desk": section["desk"], "style_hint": section["style_hint"], "kicker": section["kicker"],
            "topic": topic, "form": form, "arc": copy.deepcopy(arc),
            "cast": {"resident": resident, "correspondent": other, "official": cast_official, "mayor": MAYOR,
                     "cronies": list(CRONIES), "visual_identities": dict(VISUAL_IDENTITIES)},
            "department": department, "angle": local_angle, "reaction": copy.deepcopy(arc["reaction"]),
            "emotion": emotion, "reply_emotion": reply_emotion, "detail": detail, "twist": twist,
            "speakerbox": {"mode": source_mode, "source": seed},
            "station": {"name": station, "hosts": hosts, "connection": host_link,
                        "caller": resident if resident not in RESIDENTS else "", "broadcast_claim": False},
            "second_pass": second, "rolls": rolls}
        fingerprint = json.dumps({"arc": arc, "topic": topic["id"], "cast": item["cast"], "form": form,
            "detail": detail, "emotion": emotion, "source": seed, "context": material.get("edition_id") or material.get("hour_key") or material.get("since")}, sort_keys=True, ensure_ascii=False)
        item["id"] += "-" + hashlib.sha1(fingerprint.encode()).hexdigest()[:10]
        item["media"] = media_briefs(item) if slug in {"interview", "gallery", "wire"} else {}
        plans.append(item)
    return plans


def system_prompt() -> str:
    return (
        "You write the Pinebox Gazette's fictional city programming and tabloid pages. The JSON running order is binding: "
        "keep each item's index, id, topic, named cast, department, corruption file, evidence, reaction and emotional directions. "
        "The first arc object for each arc.id defines the shared corruption file; later rows naming only that id inherit those exact facts. "
        "Repeated station, cast roster and source text may be omitted; inherit the first station, mayor/cronies and matching source.file. "
        "Expand the actual operator topic into concrete incidents, messages, classified ads, questions and official replies. "
        "source_draft is a compact starting passage: develop it with new, useful prose rather than copying it. "
        "Be funny, specific, scandalous and varied. The female mayor and cronies are fictional. Known station callers may appear "
        "as fictional denizens. No invented dialogue is a recorded call or broadcast. The station connection is a new letter, "
        "request, invitation or notice; never say the hosts already aired, interviewed or reacted to it. Every body mentions its "
        "topic with concrete words, its resident and named department. Interviews/camera stories name the rolled official and show "
        "the exact rolled reaction. Camera copy concerns the shared arc official, evidence and corruption; link its local topic "
        "to the shared arc topic rather than substituting new evidence. Speakerbox passages are creative texture, never proof of "
        "corruption. Use topic.reply as the supplied counterposition when present. Do not expose roulette keys, JSON fields, "
        "prompts or production notes. Classifieds contain goods/services and a contact, never people for sale. Correspondence "
        "has at least two attributed messages and a substantive reply; interviews have a question, answer and follow-up; notices "
        "show a department reply and a resident response. Camera stories have a captured remark and consequence. Keep the shared "
        "scandal facts consistent across pages. Return ONLY a valid JSON array of objects with index, headline and body. Each "
        "headline is 5-12 words and at most 90 characters; each body is 90-180 words in two or three short paragraphs. No fences."
    )


def media_briefs(item: dict[str, Any]) -> dict[str, str]:
    arc, cast = item["arc"], item["cast"]
    subject = arc["official"] if item["section"] == "gallery" else cast["official"]
    setting = "a hidden-camera council corridor" if item["section"] == "gallery" else "a tense press interview outside City Hall"
    identity = cast["visual_identities"].get(subject, "a recurring fictional city official")
    description = (f"Fictional Pinebox city scene: {subject}, {identity}, in {setting}. The dispute concerns {item['topic']['text']}. "
        f"The shared scandal concerns {arc['topic']['text']}: {arc['corruption']}. Evidence prop: {arc['evidence']}. "
        f"The official {item['reaction']['label']}: {item['reaction']['direction']}. Acting: {item['emotion']}. "
        f"Resident {cast['resident']} confronts the official; {item['department']} is represented. "
        "Keep the same face, clothing and evidence prop across shots; no readable lettering or fabricated news logos.")
    speech = f"I stand by this policy on {item['topic']['text']} and I intend to defend it."
    if item["reaction"]["id"] == "double_down":
        speech = f"I stand by this policy on {item['topic']['text']} and I am expanding it further."
    if item["reaction"]["id"] not in {"double_down", "defend"}:
        speech = {"deny": "That recording is missing the context and I want the full account heard.",
                  "blame": "The aide made that arrangement and the department must explain it.",
                  "apologise": "I regret my words, but I am keeping the arrangement in place.",
                  "reverse": "I am withdrawing this policy and asking the department to reopen the file."}[item["reaction"]["id"]]
    return {"image_prompt": description + " Candid editorial newspaper photograph, clear expressions and evidence prop.",
            "video_prompt": description + " A defensive pause, the stated reaction, then the resident's visible response.",
            "speech": speech, "subject": subject, "topic_id": item["topic"]["id"], "arc_id": arc["id"], "state": "planned"}


def _story(item, headline, body, origin, generation):
    receipt = copy.deepcopy(item)
    receipt["generation"] = copy.deepcopy(generation)
    return {"slug": "city-" + item["section"], "meta": {
        "headline": headline[:90], "deck": "Pinebox city fiction: " + item["form"], "section": item["section"],
        "page": item["page"], "priority": 2 if item["section"] == "gallery" else 4, "byline": "The " + item["desk"],
        "kicker": item["kicker"], "style_hint": item["style_hint"], "editorial": receipt, "copy_origin": origin,
        "fictional_city": True, "source_seed": copy.deepcopy(item["speakerbox"].get("source") or {}), "pull": ""}, "body": body}


def fallback(item: dict[str, Any]) -> dict[str, Any]:
    """Printable core facts when the model or writer budget is unavailable."""
    resident, other, official = (item["cast"][key] for key in ("resident", "correspondent", "official"))
    topic, department, arc = item["topic"]["text"], item["department"], item["arc"]
    reaction = item["reaction"]
    evidence = f"The shared file concerns {arc['topic']['text']}: {arc['corruption']}, with {arc['evidence']} at its centre."
    reply = f"{arc['official']} {reaction['label']} and {reaction['direction']}."
    hosts = " and ".join(item["station"]["hosts"]) or "the hosts"
    connection = (f"{resident} has sent {item['station']['name']}'s {hosts} a written request to examine the file; "
                  "an answer is still awaited.")
    feeling = f"{resident}'s message carries {item['emotion']}; the reply arrives with {item['reply_emotion']}."
    section = item["section"]
    number = next(i for i, value in enumerate(SECTIONS) if value["section"] == section)
    connections = (
        f"Answers to {resident}'s offer can be left with {item['station']['name']}'s {hosts} through the request line.",
        f"Copies of the exchange have reached {item['station']['name']}'s {hosts}; a written reply is requested.",
        f"The newspaper has sent this local file to {item['station']['name']}'s {hosts} for a future discussion.",
        f"{resident} invites {item['station']['name']}'s {hosts} to put these questions to the officials at a future interview.",
        f"The department's reply is available outside {item['station']['name']}, where {resident} wants {hosts} to read it.",
        f"{resident} has asked {item['station']['name']}'s {hosts} to review the recording before any future interview.",
    )
    connection = connections[number]
    feelings = (
        f"The advertiser sounds {item['emotion']}, while the answer from the counter brings {item['reply_emotion']}.",
        f"The original letter conveys {item['emotion']}; its answer has the unmistakable tone of {item['reply_emotion']}.",
        f"Local witnesses report {item['emotion']} among the complainants and {item['reply_emotion']} at the official desk.",
        f"The questioning starts with {item['emotion']} and the interview response lands with {item['reply_emotion']}.",
        f"The notice is greeted with {item['emotion']}; the follow-up reply exposes {item['reply_emotion']}.",
        f"The camera captures {item['emotion']}, and the confrontation ends in {item['reply_emotion']}.",
    )
    feeling = feelings[number]
    if section == "classifieds":
        head = f"{item['form']}: A favour needs a receipt"
        opening = {
            "FOR SALE": f"Receipt-copying kit offered by {resident}",
            "WANTED": f"{resident} seeks an honest copy of the city receipt",
            "LOST AND FOUND": f"{resident} is tracing paperwork missing from the public file",
            "PERSONALS": f"{resident} seeks a correspondent to compare the city's contradictory rules",
            "SERVICES": f"Paperwork copying service offered by {resident}",
        }[item["form"]]
        body = (f"{item['form']}: {opening}. The matter is \"{topic}\". "
                f"Applicants needing an honest copy of {item['detail']} should leave their request with {department}; "
                f"fee by agreement, contact the station's request line. {other} replies that originals belong in the public file.\n\n"
                f"{evidence} {reply} {feeling} The advertising desk records a complication: {item['twist']}. {connection}")
    elif section == "phones":
        head = "Two letters leave City Hall another question"
        body = (f"{resident} to {department}: \"Please explain the rules behind {topic}, and publish the receipt.\" "
                f"The department to {resident}: \"Your question has been referred to {official}; the file contains "
                f"{item['detail']}, and the public can inspect it at the next hearing.\"\n\n"
                f"{other} replies: \"Referral is not an answer. Who received the favour?\" {evidence} {reply} {feeling} "
                f"The exchange takes a new turn when {item['twist']}. {connection}")
    elif section == "interview":
        head = "Mayor's inner circle faces the follow-up question"
        body = (f"The Gazette asks {official}: \"What does {topic} have to do with the favour in this file?\" "
                f"{evidence} {official} answers beside {MAYOR}, with {CRONIES[0]} and {CRONIES[1]} listening. {reply}\n\n"
                f"The follow-up comes from {resident}: \"Will {department} publish the original {item['detail']}?\" "
                f"The department's written answer offers inspection at the next hearing. {feeling} Then {item['twist']}. {connection}")
    elif section == "upstairs":
        head = "Department's reply escapes into the public file"
        body = (f"{department} issues a notice to {resident}: \"We have received your complaint about {topic}. "
                f"The decision is under review; bring {item['detail']} to the public counter.\" "
                f"{resident} replies: \"The counter should explain who approved the exception.\"\n\n"
                f"{evidence} {reply} {other} has requested the internal instructions too. {feeling} "
                f"The department faces another problem when {item['twist']}. {connection}")
    elif section == "gallery":
        head = "Secret recording leaves an official defending the favour"
        body = (f"A hidden camera in a fictional City Hall corridor catches {arc['official']} discussing \"{topic}\" "
                f"and promising a private exception. {evidence} {resident} sends the recording to {department}, "
                f"asking why the ordinary queue was bypassed.\n\n{reply} The consequence is a demand for original "
                f"paperwork at the next public hearing. {feeling} {other} adds another complication: {item['twist']}. {connection}")
    else:
        head = "City favour file brings a fresh local dispute"
        body = (f"{resident} has asked {department} to investigate a city decision about {topic}. {evidence} "
                f"The disputed paperwork includes {item['detail']}; {other} wants the complete version at the public counter.\n\n"
                f"{reply} {department} answers that an inspection will be held at the next hearing, and {resident} demands "
                f"that exceptions be read aloud. {feeling} The local story widens when {item['twist']}. {connection}")
    if item["topic"].get("reply"):
        body += f" {other}'s counterposition is: \"{item['topic']['reply']}\"."
    topic_head = " ".join(re.findall(r"[A-Za-z0-9']+", topic)[:4])
    surname = resident.split()[-1]
    head = {
        "classifieds": f"{item['form']}: {surname} seeks a favour receipt",
        "phones": f"{surname}'s letters challenge {topic_head}",
        "wire": f"City favour file widens over {topic_head}",
        "interview": f"Mayor's circle faces {surname}'s follow-up question",
        "upstairs": f"Department's reply to {surname} opens another file",
        "gallery": f"Secret recording: {arc['official'].split()[-1]} {reaction['label']} over {topic_head}",
    }[section]
    return _story(item, head, body, "roulette fallback", {"attempts": 0, "accepted": False})


def _parse(value):
    if isinstance(value, dict):
        value = value.get("body") or value.get("text") or []
    if isinstance(value, str):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", value.strip(), flags=re.I)
        try:
            value = json.loads(text)
        except ValueError:
            begin = text.find("[")
            try:
                value, _ = json.JSONDecoder().raw_decode(text[begin:]) if begin >= 0 else ([], 0)
            except ValueError:
                value = []
    if not isinstance(value, list):
        return {}
    rows = {}
    for row in value:
        if (isinstance(row, dict) and isinstance(row.get("index"), int) and not isinstance(row["index"], bool)
                and row["index"] not in rows):
            rows[row["index"]] = row
    return rows


def _contains_name(text, name):
    tokens = re.findall(r"[a-z]+", name.lower())
    return bool(tokens and (name.lower() in text.lower() or (len(tokens) >= 2 and " ".join(tokens[-2:]) in text.lower())))


def _terms(text):
    stop = {"about", "after", "again", "also", "been", "being", "from", "have", "into", "just", "more", "only", "other",
            "over", "same", "some", "than", "that", "their", "them", "there", "these", "they", "this", "those", "very",
            "what", "when", "where", "which", "with", "would", "inside", "public", "private", "city", "official"}
    return set(re.findall(r"[a-z0-9]{4,}", str(text).lower())) - stop


def _copy_keys(headline, body, item):
    keys = {"headline:" + " ".join(headline.lower().split()), "body:" + " ".join(body.lower().split())}
    evidence_terms = _terms(item["arc"]["evidence"])
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        words = " ".join(sentence.lower().split())
        # The shared recording/evidence and current response intentionally
        # link the sections; all other long repeated sentences are refused.
        common_fact = (len(_terms(sentence) & evidence_terms) >= 2
                       or item["reaction"]["label"] in words
                       or (item["topic"].get("reply") and item["topic"]["reply"].lower() in words))
        if len(words.split()) >= 10 and not common_fact:
            keys.add("sentence:" + words)
    return keys


def _official_sentences(body, item):
    """Include informal references so adding a named anchor cannot hide a reversal."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", body)
    result = []
    for sentence in sentences:
        named = _contains_name(sentence, item["arc"]["official"])
        generic = bool(re.search(r"\b(?:the |our |a )?(?:mayor|official)\b", sentence, re.I))
        pronoun = bool(re.match(r"[\s\"'?]*(?:She|He|They|The official)\b", sentence, re.I))
        if named or generic or pronoun:
            result.append(sentence)
    return result


def _reaction_conflicts(body, item):
    reaction = item["reaction"]["id"]
    conflicts = {
        "double_down": r"apologis|apologiz|withdraw|revers(?:e[sd]?|ing) course|rescind|scrap(?:s|ped)? the (?:policy|arrangement)",
        "defend": r"apologis|apologiz|withdraw|revers(?:e[sd]?|ing) course|rescind|scrap(?:s|ped)? the (?:policy|arrangement)",
        "deny": r"confess|admit(?:s|ted)? (?:that )?(?:the )?(?:recording|remarks|charge|corruption)|withdraw|rescind",
        "blame": r"(?:takes?|accepts?|assumes?) (?:sole |full |all )?responsibility|(?:her|his|their) (?:own |sole )?fault",
        "apologise": r"withdraw|rescind|revers(?:e[sd]?|ing) course|retract(?:s|ed)? (?:the |her |his )?apology",
        "reverse": r"doubl(?:es|ed|ing)? down|stands? by|reaffirms?|defends? (?:the |her |his )?(?:policy|take|arrangement|decision|position)|expands? (?:the |her |his )?(?:policy|arrangement)|keeps? (?:the |her |his )?(?:policy|arrangement)",
    }
    for sentence in _official_sentences(body, item):
        # A demand or negated action is not an accomplished change of response.
        denial = re.search(r"\b(?:refus|not |no |never |won't|will not|asks?|demands?|questions?)", sentence, re.I)
        if re.search(conflicts[reaction], sentence, re.I) and not denial:
            return True
        if reaction in {"apologise", "reverse", "blame"}:
            expected = {"apologise": r"(?:refus\w*|will not|won't|never)\s+(?:to\s+)?apolog|no (?:regret|apology)",
                        "reverse": r"(?:refus\w*|will not|won't|never)\s+(?:to\s+)?(?:withdraw|reverse|rescind|cancel)",
                        "blame": r"(?:refus\w*|will not|won't|never)\s+(?:to\s+)?blam"}[reaction]
            if re.search(expected, sentence, re.I):
                return True
    return False


def _core_conflicts(body, item):
    """Refuse explicit replacement claims, while allowing extra local details."""
    claims = {
        "evidence": r"\b(?:evidence|proof)\s+(?:is|was|consists? of|turned out to be)\s+(?:an? |the )",
        "corruption": r"\b(?:corruption|scandal['?]?s (?:scheme|arrangement))\s+(?:is|was|involves?)\s+(?:an? |the )",
    }
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        for field, marker in claims.items():
            if not re.search(marker, sentence, re.I):
                continue
            required = _terms(item["arc"][field])
            negated = re.search(r"\b(?:not|instead of|rather than)\s+" + re.escape(item["arc"][field]), sentence, re.I)
            if negated or len(required & _terms(sentence)) < min(2, len(required)):
                return "shared " + field + " changed or omitted"
            alternatives = DETAILS if field == "evidence" else ANGLES
            if any(value != item["arc"][field] and value in sentence.lower() for value in alternatives):
                if not re.search(r"additional|also|second|alongside", sentence, re.I):
                    return "shared " + field + " changed or omitted"
    return ""


def _unsafe_copy(body, item):
    problems = []
    if re.search(r"gazette\.editorial|SYSTEM 3 ROLLED|speakerbox_mode|source_draft|copy_origin|\"index\"\s*:|system (?:prompt|message)|ignore (?:all |the |previous )?instructions|as an ai", body, re.I):
        problems.append("production instructions leaked")
    names = [re.escape(name) for name in item["station"]["hosts"] if name]
    hosts = r"(?:hosts?|presenters?" + (("|" + "|".join(names)) if names else "") + ")"
    if (re.search(hosts + r" (?:said|aired|broadcast|interviewed)|(?:on air|on-air|broadcast) (?:yesterday|last|earlier)", body, re.I)
            or re.search(r"(?:already|earlier|yesterday) (?:aired|broadcast|discussed)|(?:discussed|aired|played|reviewed) (?:it |this |the story )?on[- ]air", body, re.I)):
        problems.append("invented broadcast claim")
    if _reaction_conflicts(body, item):
        problems.append("official reaction contradicts the wheel")
    conflict = _core_conflicts(body, item)
    if conflict:
        problems.append(conflict)
    return problems


def _expansion(item, draft, seen):
    """Retain clean model prose inside the section's explicit rolled anchors."""
    if not isinstance(draft, dict):
        return None
    raw = str(draft.get("body") or "").strip()
    if not 45 <= len(raw.split()) <= 320 or _unsafe_copy(raw, item):
        return None
    required = _terms(item["topic"]["text"])
    if required and len(required & _terms(raw)) < min(2, len(required)):
        return None
    core = fallback(item)
    core_sentences = [" ".join(re.findall(r"[a-z0-9]+", line.lower())) for line in re.split(r"(?<=[.!?])\s+|\n+", core["body"])]
    retained = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", raw):
        normal = " ".join(re.findall(r"[a-z0-9]+", sentence.lower()))
        if len(normal.split()) >= 5 and any(normal in known or known.startswith(normal) for known in core_sentences):
            continue
        retained.append(sentence)
    allowance = 320 - len(core["body"].split())
    complete = []
    retained_words = 0
    for sentence in retained:
        sentence = sentence.strip()
        if not re.search(r"[.!?][\"'\u2019\u201d)\]]*$", sentence):
            continue
        count = len(sentence.split())
        if retained_words + count > allowance:
            break
        complete.append(sentence)
        retained_words += count
    prose = " ".join(complete)
    if retained_words < 45:
        return None
    truncated = prose != " ".join(retained).strip()
    parts = core["body"].split("\n\n", 1)
    body = "\n\n".join([parts[0], prose] + parts[1:])
    headline = _text(draft.get("headline"), 200)
    if (not 4 <= len(headline.split()) <= 16 or len(headline) > 90
            or "headline:" + " ".join(headline.lower().split()) in seen):
        headline = core["meta"]["headline"]
    candidate = {"headline": headline, "body": body}
    if _problems(candidate, item, seen):
        return None
    return candidate, {"kind": "anchored expansion", "core_origin": "roulette",
        "retained_writer_words": len(prose.split()), "core_words": len(core["body"].split()),
        "source_writer_words": len(raw.split()), "truncated": truncated,
        "retained_headline": headline == _text(draft.get("headline"), 200)}


def _problems(candidate, item, seen):
    if not isinstance(candidate, dict):
        return ["missing draft"]
    body, head = str(candidate.get("body") or "").strip(), _text(candidate.get("headline"), 200)
    problems = []
    if not 4 <= len(head.split()) <= 16 or len(head) > 90:
        problems.append("headline length")
    if not 70 <= len(body.split()) <= 320:
        problems.append("body length")
    copy_keys = _copy_keys(head, body, item)
    if "headline:" + " ".join(head.lower().split()) in seen:
        problems.append("repeated headline")
    if any(key in seen for key in copy_keys if not key.startswith("headline:")):
        problems.append("repeated copy")
    stop = {"about", "after", "again", "also", "been", "being", "from", "have", "into", "just", "more", "only", "other",
            "over", "same", "some", "than", "that", "their", "them", "there", "these", "they", "this", "those", "very",
            "what", "when", "where", "which", "with", "would"}
    topic_terms = set(re.findall(r"[a-z0-9]{4,}", item["topic"]["text"].lower())) - stop
    if topic_terms and not topic_terms & set(re.findall(r"[a-z0-9]{4,}", body.lower())):
        problems.append("topic omitted")
    if not _contains_name(body, item["cast"]["resident"]):
        problems.append("resident omitted")
    if not _contains_name(body, item["department"]):
        problems.append("department omitted")
    if item["section"] in {"gallery", "interview"}:
        official = item["arc"]["official"] if item["section"] == "gallery" else item["cast"]["official"]
        if not _contains_name(body, official):
            problems.append("official omitted")
    if item["section"] in {"gallery", "interview", "wire"}:
        if not _contains_name(body, item["arc"]["official"]):
            problems.append("shared file official omitted")
        for field in ("evidence", "corruption"):
            required = _terms(item["arc"][field])
            if len(required & _terms(body)) < min(2, len(required)):
                problems.append("shared " + field + " changed or omitted")
    if item["section"] == "gallery" and not re.search(r"camera|recording|recorded|footage|tape", body, re.I):
        problems.append("recording omitted")
    if item["section"] in {"phones", "upstairs"} and not re.search(r"repl(?:y|ies|ied)|answer|respond|wrote|writes|says", body, re.I):
        problems.append("reply omitted")
    if item["section"] == "interview" and "?" not in body:
        problems.append("interview question omitted")
    reaction_words = {"double_down": r"doubl|stands? by|bolder|expand|defen|refus", "defend": r"defen|princip|stands? by|justif",
        "deny": r"deni|den[yi]|context|misunderst", "blame": r"blam|fault|responsib|aide|crony|cronies",
        "apologise": r"apolog|regret|sorry", "reverse": r"revers|withdraw|cancel|rescind|aband|scrap|chang"}
    official_sentences = _official_sentences(body, item)
    reaction_copy = " ".join(official_sentences)
    if not re.search(reaction_words[item["reaction"]["id"]], reaction_copy, re.I):
        problems.append("rolled official reaction omitted")
    if item["section"] in {"phones", "upstairs"} and (body.count('"') < 4 and not re.search(r".+\s(?:to|replies to|writes to)\s.+:", body)):
        problems.append("attributed correspondence omitted")
    if item["section"] == "classifieds" and not re.search(r"sale|wanted|lost|found|personals|service|offer|contact|request line", body, re.I):
        problems.append("classified offer or contact omitted")
    problems.extend(problem for problem in _unsafe_copy(body, item) if problem not in problems)
    return problems


def _budget(budget_left):
    try:
        return max(0.0, float(budget_left() if callable(budget_left) else budget_left if budget_left is not None else 120.0))
    except (TypeError, ValueError):
        return 0.0


def _response_info(value, rows):
    """Content-free diagnostics distinguish malformed output from no response."""
    if isinstance(value, dict):
        value = value.get("body") or value.get("text") or ""
    text = value.strip() if isinstance(value, str) else ""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    form = "array" if isinstance(value, list) or text.startswith("[") else "object" if isinstance(value, dict) or text.startswith("{") else "empty" if not text else "text"
    return {"format": form, "chars": len(text), "parsed_rows": len(rows)}


def writer_brief(item: dict[str, Any]) -> dict[str, Any]:
    """Only selected story constraints go to the model; audit stays on disk."""
    topic, arc, cast = item["topic"], item["arc"], item["cast"]
    source = item["speakerbox"].get("source") or {}
    passage = " ".join(str(source.get("text") or "").split()[:120])
    return {"index": item["index"], "id": item["id"], "section": item["section"], "form": item["form"],
        "topic": {key: topic[key] for key in ("id", "text", "reply") if topic.get(key)},
        "cast": {key: copy.deepcopy(cast[key]) for key in ("resident", "correspondent", "official", "mayor", "cronies")},
        "department": item["department"], "angle": item["angle"], "detail": item["detail"], "twist": item["twist"],
        "emotion": item["emotion"], "reply_emotion": item["reply_emotion"], "reaction": copy.deepcopy(item["reaction"]),
        "arc": {"id": arc["id"], "topic": {"id": arc["topic"]["id"], "text": arc["topic"]["text"]},
                "official": arc["official"], "corruption": arc["corruption"], "evidence": arc["evidence"],
                "reaction": copy.deepcopy(arc["reaction"]), "continuity": arc["continuity"]},
        "speakerbox": {"mode": item["speakerbox"]["mode"],
                       "source": {"file": _text(source.get("file"), 120), "text": passage[:300]}},
        "station": copy.deepcopy(item["station"]), "source_draft": _text(fallback(item)["body"], 720)}


def writer_briefs(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Share identical case facts once while retaining the indexed row shape."""
    rows, cases, sources = [], set(), set()
    for item in plans:
        row = writer_brief(item)
        case_id = row["arc"]["id"]
        if case_id in cases:
            row["arc"] = {"id": case_id}
        else:
            cases.add(case_id)
        if rows:
            row["cast"].pop("mayor", None)
            row["cast"].pop("cronies", None)
            if row["station"] == rows[0]["station"]:
                row.pop("station")
        source = row["speakerbox"]["source"]
        source_key = (source["file"], source["text"])
        if source_key in sources:
            source.pop("text", None)
        else:
            sources.add(source_key)
        rows.append(row)
    return rows


async def generate(plans: list[dict[str, Any]], write: Callable, budget_left: Callable | float | None = None) -> list[dict[str, Any]]:
    """One batch plus at most one budgeted pass; bad revisions keep good copy."""
    if not plans:
        return []
    results = [fallback(item) for item in plans]
    attempts, first, failures, seen = 0, {}, {}, set()
    brief_rows = writer_briefs(plans)
    first_material = json.dumps(brief_rows, ensure_ascii=False, separators=(",", ":"))
    input_sizes = {"first": len(first_material.encode("utf-8")), "second": 0}
    output_shapes = {"first": {"format": "not requested"}, "second": {"format": "not requested"}}
    if _budget(budget_left) > 2.0:
        attempts = 1
        try:
            reply = write("Gazette Roulette", system_prompt(), first_material,
                          words=(90 * len(plans), 180 * len(plans)))
            reply = await reply if inspect.isawaitable(reply) else reply
            first = _parse(reply)
            output_shapes["first"] = _response_info(reply, first)
        except Exception as exc:
            failures[-1] = ["writer unavailable: " + type(exc).__name__]
            output_shapes["first"] = {"format": "writer error", "error_type": type(exc).__name__}
    for i, item in enumerate(plans):
        draft = first.get(item["index"])
        reasons = _problems(draft, item, seen)
        framed = _expansion(item, draft, seen) if reasons else None
        if reasons and not framed:
            failures[item["index"]] = reasons
        else:
            copy_row, framing = framed if framed else (draft, None)
            body = str(copy_row["body"]).strip()
            seen.update(_copy_keys(_text(copy_row["headline"], 90), body, item))
            generation = {"attempts": attempts, "accepted": True, "pass": 1, "problems": []}
            if framing:
                generation.update({"framing": framing, "first_pass_problems": reasons})
            results[i] = _story(item, _text(copy_row["headline"], 90), body,
                                "writer expansion" if framing else "writer", generation)
    if attempts and (failures or any(item.get("second_pass") for item in plans)) and _budget(budget_left) > 12.0:
        attempts += 1
        revisions = []
        for i, item in enumerate(plans):
            original = first.get(item["index"])
            safe_original = isinstance(original, dict) and not _unsafe_copy(str(original.get("body") or ""), item)
            actual = original if safe_original and results[i]["meta"]["editorial"]["generation"]["accepted"] else {}
            row_plan = copy.deepcopy(brief_rows[i])
            draft_body = str(actual.get("body") or "").strip()
            if draft_body:
                row_plan.pop("source_draft", None)
            # The accepted full story remains untouched if an excerpt repair fails.
            excerpt = len(draft_body) > 1000
            if excerpt:
                draft_body = draft_body[:1000].rsplit(" ", 1)[0]
            revisions.append({"plan": row_plan, "draft": {"index": item["index"],
                "headline": _text(actual.get("headline"), 90), "body": draft_body, "excerpt": excerpt},
                "repair": failures.get(item["index"], []),
                "revise": bool(item.get("second_pass") or item["index"] in failures)})
        brief = (system_prompt() + " This is the single cohesion pass. Repair marked omissions and connect the shared file "
                 "while retaining every rolled identity, topic, evidence and reaction. Keep unmarked good drafts. "
                 "Return each item with its ORIGINAL index, headline and body; never return plan objects.")
        try:
            second_material = json.dumps(revisions, ensure_ascii=False, separators=(",", ":"))
            input_sizes["second"] = len(second_material.encode("utf-8"))
            reply = write("Gazette Roulette Coherence", brief, second_material,
                          words=(90 * len(plans), 180 * len(plans)))
            reply = await reply if inspect.isawaitable(reply) else reply
            revised = _parse(reply)
            output_shapes["second"] = _response_info(reply, revised)
        except Exception as exc:
            revised = {}
            output_shapes["second"] = {"format": "writer error", "error_type": type(exc).__name__}
        seen = set()
        for i, item in enumerate(plans):
            draft = revised.get(item["index"])
            reasons = _problems(draft, item, seen)
            framed = _expansion(item, draft, seen) if reasons else None
            if (not reasons or framed) and (item.get("second_pass") or item["index"] in failures):
                copy_row, framing = framed if framed else (draft, None)
                generation = {"attempts": attempts, "accepted": True, "pass": 2, "problems": [],
                              "first_pass_problems": failures.get(item["index"], [])}
                if framing:
                    generation.update({"framing": framing, "second_pass_problems": reasons})
                results[i] = _story(item, _text(copy_row["headline"], 90), str(copy_row["body"]).strip(),
                    "writer expansion second pass" if framing else "writer second pass", generation)
            seen.update(_copy_keys(results[i]["meta"]["headline"], results[i]["body"], item))
    for item, story in zip(plans, results):
        generation = story["meta"]["editorial"]["generation"]
        generation["attempts"] = attempts
        generation["writer_input_bytes"] = dict(input_sizes)
        generation["writer_output"] = copy.deepcopy(output_shapes)
        if not generation["accepted"]:
            generation["problems"] = failures.get(item["index"], ["writer budget unavailable"])
    return results


def validate_story(article: dict[str, Any], body: str | None = None) -> list[str]:
    """Check assembled copy against its durable rolled plan, without mutation.

    Empty means valid. Ordinary Gazette articles have no editorial binding
    and are outside this check. Downstream rewrite/cut callers can supply a
    candidate full body before changing the accepted story.
    """
    meta = article.get("meta") or {}
    item = meta.get("editorial")
    if item is None:
        return []
    if not isinstance(item, dict) or item.get("schema") != SCHEMA or item.get("kind") != "fictional_city":
        return ["invalid editorial receipt"]
    try:
        return _problems({"headline": meta.get("headline"),
                          "body": article.get("body") if body is None else body}, item, set())
    except (KeyError, TypeError, AttributeError, IndexError):
        return ["invalid editorial receipt"]
