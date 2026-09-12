"""Remove identified transcript-repair prompt echoes, never rewrite source prose."""
from __future__ import annotations

import re


# These are the actual instructions in speakbox_harvest, not a generic list
# of imperative language. Cache gems can begin at an individual full sentence.
_CLAUSES = (
    'Below is a rough machine transcript of people talking: no punctuation, no capitals, no sentence breaks, words mis-heard all through it.',
    'Write it out properly: put in the full stops and the capitals, break it into sentences, and repair what has obviously come out wrong.',
    'Put in the full stops and the capitals, break it into sentences, and repair what has obviously come out wrong.',
    'Keep every word and every turn of phrase you can.',
    'Do not summarise it, do not tidy up the language, do not add anything of your own and do not comment on it.',
    'Give back the repaired text and nothing else.',
    # The sentence splitter and model repair sometimes separate these exact
    # component instructions into their own cached gems.
    'Write it out properly.',
    'Put in the full stops and the capitals.',
    'Break it into sentences.',
    'Repair what has obviously come out wrong.',
    'Do not summarise it.',
    'Do not tidy up the language.',
    'Do not add anything of your own.',
    'Do not comment on it.',
)
_SEPARATOR = r'[\s,.;:!?\-–—]+'
_PATTERNS = tuple(re.compile(
    r'\s*' + _SEPARATOR.join(re.escape(word) for word in re.findall(r'\w+', clause))
    + r'\b(?=\s*$|[ \t]*[.!?;:\r\n])[\s,.;:!?\-–—]*', re.IGNORECASE) for clause in _CLAUSES)


def clean_repair_prompt_echo(text: str) -> dict:
    """Return the untouched source after an exact unquoted instruction prefix.

    Only an anchored leading sequence of known full clauses is removed. An
    instruction quoted by a speaker, embedded later in ordinary prose, or
    merely similar to these words is retained. Removed text and offsets are
    returned so callers can retain provenance without changing source files.
    """
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    offset = 0
    removed = []
    while offset < len(text):
        found = next((match for pattern in _PATTERNS
                      if (match := pattern.match(text, offset))), None)
        if found is None:
            break
        end = found.end()
        removed.append({'start': offset, 'end': end, 'text': text[offset:end]})
        offset = end
    return {'text': text[offset:] if removed else text, 'changed': bool(removed),
            'removed': removed}


def strip_repair_prompt_echo(text: str) -> str:
    return clean_repair_prompt_echo(text)['text']
