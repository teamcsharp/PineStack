"""Bounded authoring instructions; never edits an accepted script or take."""
import copy
import re


def source_thought(row, cap):
    """Select a whole punctuated source sentence and retain the original evidence.

    This is a syntactic boundary check, not a claim to certify its meaning.
    No fitting complete sentence means no selected text, never a clipped phrase.
    """
    result = copy.deepcopy(row or {})
    original = str(result.get("text") or "")
    if not original.strip():
        return result
    cap = max(1, int(cap))
    selected = ""
    pending = ""
    for match in re.finditer(r"\S[\s\S]*?[.!?](?:[\"'’”)]*)(?=\s|$)", original):
        sentence = (pending + match.group()).strip()
        pending = ""
        if re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|vs|etc)\.$", sentence, re.I):
            # Do not turn an honorific into a complete standalone thought.
            pending = sentence + " "
            continue
        if 4 <= len(sentence.split()) and len(sentence) <= cap:
            selected = sentence
            break
    result["original_source"] = {"text": original,
                                  "lines": copy.deepcopy(result.get("lines") or [])}
    result.update(text=selected, lines=[selected] if selected else [],
                  source_selection="one complete sentence" if selected else "no complete sentence fits")
    return result


def turn_instruction(budget):
    return (f"This is one complete short scene for a {budget['seconds']:g}-second "
            f"programming budget, including pauses and board clips. Write "
            f"{budget['words_low']}–{budget['words_high']} words per ordinary turn, "
            "usually one or two complete sentences. Each turn answers the previous "
            "speaker and develops one concrete point. Keep the introduction, "
            "questions, responses and closing; finish every thought. Source facts "
            "are evidence, not permission to add a monologue or a reading afterward. ")


def scene_complete(turns, expected):
    """A short scene still needs ordered speakers and complete spoken thoughts.

    This replaces only the old long-form size test. Caller/content/rhyme grades
    remain separate and are not weakened by this structural predicate.
    """
    return (len(turns) >= max(2, int(expected) - 1)
            and all(marker in ("A", "B", "C", "D", "E")
                    and len(str(text).split()) >= 6
                    and re.search(r"[.!?…][\"'’”)]*$", str(text).strip())
                    for marker, text in turns))
