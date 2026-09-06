"""Image subjects become distinct local situations, including offline copy."""
from __future__ import annotations

import re

ANIMALS = re.compile(r"\b(?:cat|dog|bird|heron|horse|fox|deer|moose|duck|orangutan|monkey|ape|bull|cow|goat|sheep|rabbit|bear|wolf|lion|tiger|penguin|owl|animal)s?\b", re.I)
PEOPLE = re.compile(r"\b(?:woman|women|man|men|person|people|girl|boy|child|children|resident|portrait|face|faces|figure|figures|robot|android)\b", re.I)
PLACES = re.compile(r"\b(?:street|building|shop|house|bridge|park|city|cafe|church|cathedral|station|harbour|garden)\b", re.I)
PRESENTATION = re.compile(r"\b(?:listen up|listen to this|holding up|I am holding|I'm holding|I’ve got|I've got|this (?:image|picture)|rendered|photograph|pixels|picture here)\b", re.I)


def clean_description(text):
    """Remove the presenter's delivery and medium, retaining visible details."""
    text = " ".join(str(text or "").replace("’", "'").split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for sentence in sentences:
        sentence = re.sub(r"^Listen(?: up| to this)?(?:,? folks)?[!,.:]*\s*", "", sentence, flags=re.I)
        # A short factual 'photograph of a red bicycle' still has a subject.
        sentence = re.sub(r"^(?:(?:I(?:'m| am|'ve)|we're)\b.*?\b)?(?:an? |the |this )?(?:image|picture|photograph|painting|portrait) of\s+", "", sentence, flags=re.I)
        sentence = re.sub(r"^(?:(?:It's|It is)|The (?:image|picture|photograph) is) (?:an? )?(?:portrait|picture|image|photograph) of\s+", "", sentence, flags=re.I)
        sentence = re.sub(r"^(?:It's|It is|The (?:foreground|image|picture) is) dominated by\s+", "", sentence, flags=re.I)
        if PRESENTATION.search(sentence) or re.search(r"\b(?:paper grain|camera|photographic texture)\b", sentence, re.I):
            continue
        sentence = re.sub(r"^(?:In the (?:foreground|center|centre),?\s*(?:there (?:is|are)|sits?|stands?)?\s*|The central figure is\s+)", "", sentence, flags=re.I)
        sentence = sentence.strip(" ,;:-")
        if sentence and len(sentence.split()) >= 3:
            kept.append(sentence[0].upper() + sentence[1:])
    if not kept:
        # Descriptions consisting of one spoken sentence may still name the
        # subject after 'showing'. Never put the presenter back into the paper.
        tail = re.split(r"\b(?:showing|depicting|revealing)\b", text, flags=re.I)[-1]
        if tail != text and not PRESENTATION.search(tail):
            kept = [tail.strip(" ,.").capitalize() + "."]
    return " ".join(kept).strip() or "An unfamiliar arrival with details still being checked."


def subject_role(description):
    animal, person = ANIMALS.search(description), PEOPLE.search(description)
    if animal and (not person or animal.start() < person.start() or person.group().lower() in ("figure", "figures")):
        return "neighbourhood animal"
    if person:
        return "resident"
    return "local place" if PLACES.search(description) else "goods or service"


def subject_label(description, role):
    if role == "neighbourhood animal":
        animals = list(dict.fromkeys(m.group().lower() for m in ANIMALS.finditer(description)
                                    if m.group().lower() not in ("animal", "animals")))
        by_species = {}
        for animal in animals:
            by_species.setdefault(animal[:-1] if animal.endswith('s') else animal, animal)
        if set(by_species) & {'heron', 'duck', 'owl', 'penguin'}:
            by_species.pop('bird', None)
        animals = list(by_species.values())
        if animals:
            return " and ".join(animals[:2])
    if role == "resident":
        person = re.search(r"\b(woman|women|man|men|girl|boy|child|robot|android)\b", description, re.I)
        who = person.group().lower() if person else "resident"
        for pattern, template in (
            (r"\b(red|blond|blonde|white|black|brown|silver|blue|green) hair\b", " with {} hair"),
            (r"\b(copper|white|blue|green|red) apron\b", " in a {} apron"),
            (r"\b(football|naval|military) uniform\b", " in a {} uniform"),
            (r"\b(obsidian|bronze|silver)\b", " with {} features"),
        ):
            if match := re.search(pattern, description, re.I):
                return who + template.format(match.group(1).lower())
        return who
    if role == "neighbourhood animal":
        return "neighbourhood animal"
    if role == "goods or service":
        if re.search(r"\b(?:lettering|words|text)\b", description, re.I):
            return "lettered panel"
        item = re.search(r"\b(?:bicycle|bike|cube|glasses|box|pot|trunk|chair|table|lamp|book|bottle|radio|telephone|clock|car|boat|vase|cabinet|machine|device|console)\b", description, re.I)
        if item:
            return item.group().lower()
        return "unidentified object"
    finder = ANIMALS if role == "neighbourhood animal" else PEOPLE if role == "resident" else PLACES if role == "local place" else None
    match = finder.search(description) if finder else None
    text = description[match.start():] if match else description
    text = re.split(r"[.!?,;]|\s+(?:is|are|was|were|stands?|sits?|has|had)\s+", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"^(?:an? |the )", "", text, flags=re.I)
    if len(text.split()) > 8:
        text = re.split(r"\s+(?:with|in|on|that|against|showing|revealing)\s+", text, maxsplit=1, flags=re.I)[0]
    return text.strip(" ,:;-") or role


_THEMES = (
    (r"machete|scream|escape|feather|emergency|danger", "safety", "a neighbourhood safety check"),
    (r"batter|electric|power zone|turbo cell", "energy", "the station battery exchange"),
    (r"power(?!\s+zone)|protector|control|election|vote", "public decisions", "the residents' decision-making forum"),
    (r"concrete|shed|trailer|property|construction|repair", "building", "the neighbourhood building project"),
    (r"joke|comedy|shows|comedian|punchline", "comedy", "the neighbourhood comedy evening"),
    (r"signal|transmitter|jammer|broadcast|radio tower", "reception", "the station reception survey"),
    (r"frequency|frequenc|spectrum|mixing|mixes|individual track|audio", "sound", "the station sound workshop"),
    (r"rubber|washer|metal pot|tool|hardware", "repairs", "the shared repair table"),
    (r"masculin|feminis|gender|strength", "community roles", "the discussion on community roles"),
    (r"club|nightlife|bouncer|dance", "nightlife", "the courtyard social evening"),
    (r"water|faucet|plumb|pipe", "water", "water arrangements"),
    (r"music|record|song|band|sing|guitar", "music", "a neighbourhood rehearsal"),
    (r"muffin|food|cook|kitchen|bread|beef|dinner", "food", "the communal supper"),
    (r"book|read|library|story", "books", "the lending-library evening"),
    (r"office(?!r)|manager|job|work|team", "work", "the local shift exchange"),
    (r"boat|river|travel|road|route|train", "travel", "the neighbourhood route meeting"),
    (r"money|price|cost|bill|financial|dollar", "money", "the district repair fund"),
    (r"school|child|family|parent", "family", "the after-school open day"),
    (r"game|play|character|champion|sport", "games", "the evening games club"),
    (r"dog|cat|pet|animal", "animals", "the animal-care rota"),
    (r"court|legal|police|law|prison|judge|FBI|officer", "records", "the public-records discussion"),
    (r"furious|anger|argument|threat|kick|hell|ass\b", "disagreement", "the neighbourhood mediation meeting"),
)


def seed_theme(seed):
    text = re.sub(r"\[[^\]]*\]", "", str(seed.get("text") or ""))
    found = [(m.start(), topic, event, m.group()) for pattern, topic, event in _THEMES
             if (m := re.search(r"\b(?:" + pattern + r")[a-z]*\b", text, re.I))]
    if found:
        _, topic, event, evidence = min(found)
        return topic, event, evidence
    # A stray adjective or transcript fragment is never a printable topic.
    # The exact passage remains available to the writer and source receipt.
    return "neighbourhood life", "the neighbourhood open meeting", ""


_OPENINGS = (
    "At the market gate, {who} became the focus of {event}.",
    "Plans for {event} took a turn when {who} reached the station courtyard.",
    "A place beside the switchboard has been set aside for {who} during {event}.",
    "The back-street committee brought {who} into its preparations for {event}.",
    "Across from the transmitter, {who} gave {event} an unexpected subject.",
    "The workshop's latest conversation about {event} now centres on {who}.",
    "Word of {who} travelled along the high street ahead of {event}.",
    "The noticeboard outside the record shop links {who} with {event}.",
    "A gathering at the riverside steps put {who} at the heart of {event}.",
    "Discussion of {event} spilled into the square after neighbours noticed {who}.",
    "The evening desk has opened a local file on {who} and {event}.",
    "Behind the station, arrangements for {event} changed around {who}.",
)
_ENDS = (
    "Neighbours are comparing notes before the next station bulletin.",
    "The courtyard volunteers will bring their answer to the evening meeting.",
    "A handwritten update is expected at the record-shop window.",
    "The route past the station will stay open while the details are settled.",
    "The next neighbourhood round will follow what the committee decides.",
    "The workshop has kept a space clear for the promised follow-up.",
    "Questions from the surrounding streets are already on the desk.",
    "The organisers will return with a practical arrangement after supper.",
    "A neighbour has agreed to carry the update back to the square.",
    "The conversation continues at the market rather than ending at the microphone.",
    "The station's evening visitors will hear how the plan develops.",
    "The district now has a small decision to make before nightfall.",
)

_DETAILS = (
    "Neighbours described {detail}.", "Witnesses noticed {detail}.",
    "The account centres on {detail}.", "Visitors encountered {detail}.",
    "One detail stood out: {detail}.", "Reports mentioned {detail}.",
    "Attention settled on {detail}.", "The local account includes {detail}.",
    "Onlookers pointed out {detail}.", "The day's unusual detail was {detail}.",
    "Notes from the scene describe {detail}.", "Neighbours singled out {detail}.",
)


def fallback_story(subject, seed, index, station):
    topic, event, evidence = seed_theme(seed)
    label = subject_label(subject["subject"], subject["role"])
    who = "the " + label[0].lower() + label[1:]
    # Different actions as well as openings; adjacent portraits must not end
    # with the same boilerplate sentence when the writer has no room.
    actions = {
        "resident": ("The resident will hear proposals at the courtyard table.", "Neighbours have asked the resident to demonstrate the practical details.", "The visitor has a place on the evening discussion list."),
        "neighbourhood animal": ("A keeper is checking the animal's route through the district.", "The gathering will leave a quiet corner clear for the animal.", "Nearby households are comparing sightings before anyone moves the animal."),
        "local place": ("Volunteers are checking access to the site.", "The site will be discussed at the next residents' meeting.", "The opening arrangements are being passed around the neighbouring shops."),
        "goods or service": ("The owner is inviting offers after a condition check.", "The workshop will test the item before arranging a loan.", "Collection will be settled with a neighbour who can use the goods."),
    }
    action = actions[subject["role"]][index % 3]
    details = re.split(r"(?<=[.!?])\s+", subject["subject"].strip())
    subject_pattern = (re.compile(r"\b(?:lettering|words|text)\b", re.I) if label == "lettered panel" else
                       ANIMALS if subject["role"] == "neighbourhood animal" else
                       PEOPLE if subject["role"] == "resident" else
                       re.compile(r"\b" + re.escape(label) + r"\b", re.I))
    detail = next((part for part in details if subject_pattern.search(part)), details[0]).rstrip(" ,;:-.")
    main = re.split(r"\b(?:that|which|whose)\b", detail, maxsplit=1, flags=re.I)[0]
    if not re.search(r"\b(?:is|are|was|were|sits?|stands?|rests?|wears?|holds?|catch(?:es)?|glows?|stares?)\b|\b(?:it|there)'s\b", main, re.I):
        detail = _DETAILS[index % len(_DETAILS)].format(detail=detail[0].lower() + detail[1:])
    else:
        detail += "."
    body = " ".join((_OPENINGS[index % len(_OPENINGS)].format(who=who, event=event), detail, action, _ENDS[index % len(_ENDS)]))
    locations = ("Market Gate", "Station Courtyard", "Switchboard Table", "Back Street", "Transmitter Row", "Workshop", "High Street", "Record Shop", "Riverside Steps", "Town Square", "Evening Desk", "Station Yard")
    return {"headline": f"{label.capitalize()} at {locations[index % len(locations)]}: {topic}",
            "body": body, "source": dict(seed), "source_image": subject.get("name"),
            "subject_role": subject["role"], "topic": topic, "topic_evidence": evidence,
            "station": station, "copy_origin": "local fallback"}


def sentences(text):
    return {" ".join(re.findall(r"[a-z0-9]+", part.lower())) for part in re.split(r"(?<=[.!?])\s+|\n+", str(text))
            if len(part.split()) >= 6}


def accept_story(candidate, fallback, subject, seen):
    """Reject repeated/presenter copy and retain the independently seeded story."""
    if not isinstance(candidate, dict):
        return fallback
    body, head = str(candidate.get("body") or "").strip(), str(candidate.get("headline") or "").strip()
    visual = set(re.findall(r"[a-z]{4,}", subject["subject"].lower())) - {"with", "that", "this", "there", "from", "have", "into"}
    tokens = set(re.findall(r"[a-z]{4,}", body.lower()))
    if (not 6 <= len(head) <= 100 or not 25 <= len(body.split()) <= 95
            or PRESENTATION.search(body + " " + head) or not visual & tokens
            or not any(w in body.lower() for w in (fallback["topic"], fallback["topic_evidence"]) if w)
            or sentences(body) & seen):
        return fallback
    return {**fallback, "headline": head, "body": body, "copy_origin": "writer"}
