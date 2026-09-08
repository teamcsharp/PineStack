"""Explicit editorial permission over an unchanged machine grade.

Fluid mode tolerates weak transformation and absent style vocabulary, while
still requiring measured meaning, structure, source-copy and rap-rhyme checks.
Those checks remain screening signals, not a proof of semantic fidelity.
This module performs no I/O, model calls, policy changes or review decisions.
"""
from __future__ import annotations

from collections.abc import Mapping
import re


VERSION = 2
MODES = frozenset({'strict', 'fluid'})
STYLE_FAULTS = frozenset({
    'rhetoric was not materially transformed',
    'no new lexicon word drawn from the crystal passage',
})


def _attempt_drift(source, candidate):
    """Find a narrow, positive attempt -> asserted-action change.

    Match verbal try-to, not arbitrary uses of the word try. Only an explicit
    subject plus the same action is treated as accomplishment; a missing
    synonym or a modal phrase is not guessed to be one.
    """
    evidence = []
    for match in re.finditer(r'\b(?:try|tries|tried|trying)\s+to\s+([a-z]+)\b', source, re.I):
        before = re.findall(r"[a-z']+", source[:match.start()].lower())
        if match.group().lower().startswith('try ') and before and before[-1] in {
                'a', 'another', 'the', 'one', 'more', 'first', 'last', 'final', 'each', 'every'}:
            continue  # "another try to ..." is a noun construction.
        verb = match.group(1).lower()
        action = re.escape(verb)
        preserved = re.search(
            r'\b(?:try|tries|tried|trying|attempt|attempts|attempted|attempting|'
            r'aim|aims|aimed|aiming|seek|seeks|seeking|sought)\s+to\s+' + action + r'\b',
            candidate, re.I)
        if preserved:
            continue
        asserted = re.search(
            r'\b(?:i|you|he|she|it|we|they)\s+'
            r'(?:(?:now|just|already|actually)\s+)?' + action + r'(?:s|ed)?\b',
            candidate, re.I)
        if asserted:
            evidence.append({'code': 'attempt_became_asserted_action',
                'source_quote': match.group(), 'candidate_quote': asserted.group(),
                'predicate': verb})
    return evidence


def _orphaned_source_tail(source, candidate):
    """Recognize the retained 'from the.' -> 'from the... dense' failure.

    This is a source-fragment check, not a rule that adjectives cannot end a
    sentence. A style exception cannot invent the missing end of this source.
    """
    source_tail = re.search(
        r'\b(?:from|of|to|with|by|into|on|at|through|for)\s+'
        r'(?:a|an|the|my|your|his|her|our|their|its)\s*[.!?…]*\s*$', source, re.I)
    if not source_tail:
        return []
    words = re.findall(r'[a-z]+', source_tail.group(), re.I)
    prefix = r'\s+'.join(re.escape(word) for word in words)
    candidate_tail = re.search(r'\b' + prefix + r'\s*(?:\.{2,}|…)\s*'
        r'(?:[a-z]+(?:\s+[a-z]+)?)?[.!?…]*\s*$', candidate, re.I)
    if not candidate_tail:
        return []
    return [{'code': 'source_needs_repair', 'source_quote': source_tail.group(),
             'candidate_quote': candidate_tail.group(),
             'reason': 'The retained source ends at a determiner; the proposed rhyme does not establish its missing completion.'}]


def evaluate_acceptance(report, *, source, candidate, mode='strict',
                        usable=True, technical=False):
    """Return permission and its evidence without modifying ``report``.

    ``strict`` retains the current raw verdict. ``fluid`` waives only the two
    named style faults and requires positive rap evidence even at low force.
    The caller supplies its existing output-format/meta-text eligibility via
    ``usable`` and applies any explicit operator override separately afterward.
    """
    if mode not in MODES:
        raise ValueError('mode must be strict or fluid')
    if not isinstance(report, Mapping):
        raise TypeError('report must be a mapping')
    if not isinstance(usable, bool) or not isinstance(technical, bool):
        raise TypeError('usable and technical must be booleans')
    raw_faults = report.get('machine_faults', report.get('faults', []))
    if not isinstance(raw_faults, (list, tuple)) or any(not isinstance(x, str) for x in raw_faults):
        raise TypeError('machine faults must be a list of strings')
    machine_faults = list(raw_faults)
    machine_ok = report.get('machine_ok', report.get('ok')) is True
    blockers = []
    guard_evidence = []

    if technical or report.get('technical'):
        blockers.append('technical failure')
    if not str(source or '').strip():
        blockers.append('original source is empty')
    if not usable or not re.search(r'[^\W_]', str(candidate or '')):
        blockers.append('output is not usable')

    waived = []
    if mode == 'strict':
        blockers.extend(machine_faults)
        if not machine_ok and not machine_faults:
            blockers.append('machine rejection has no classified evidence')
    else:
        semantic = report.get('semantic') or {}
        if (not isinstance(semantic, Mapping) or semantic.get('ok') is not True
                or any(semantic.get(key) is not True for key in ('entities', 'question', 'negation'))):
            blockers.append('semantic checks did not pass')
        for contract in (report.get('call_contract'),
                         semantic.get('call_contract') if isinstance(semantic, Mapping) else None):
            if contract is not None and (not isinstance(contract, Mapping)
                                         or contract.get('ok') is not True):
                blockers.append('caller structure did not pass')
        copying = report.get('copying') or {}
        if (not isinstance(copying, Mapping) or copying.get('ok') is not True
                or copying.get('phrases')):
            blockers.append('source-copy checks did not pass')
        rhyme = report.get('rhyme') or {}
        rap = rhyme.get('rap') if isinstance(rhyme, Mapping) else None
        if not isinstance(rap, Mapping) or rap.get('ok') is not True:
            blockers.append('rap rhyme evidence did not pass')
        waived = [fault for fault in machine_faults if fault in STYLE_FAULTS]
        attempts = _attempt_drift(str(source or ''), str(candidate or ''))
        if attempts:
            blockers.append('attempt became an accomplished action')
            guard_evidence.extend(attempts)
        if waived:
            orphan = _orphaned_source_tail(str(source or ''), str(candidate or ''))
            if orphan:
                blockers.append('source needs repair: dangling determiner and orphaned completion')
                guard_evidence.extend(orphan)
        blockers.extend(fault for fault in machine_faults if fault not in STYLE_FAULTS)
        if not machine_ok and not machine_faults:
            blockers.append('machine rejection has no classified evidence')

    blockers = list(dict.fromkeys(blockers))
    accepted = not blockers and (machine_ok or (mode == 'fluid' and bool(waived)))
    accepted_with_advisories = bool(accepted and waived)
    return {
        'version': VERSION, 'mode': mode, 'ok': accepted,
        'machine_ok': machine_ok, 'machine_faults': machine_faults,
        'accepted_with_advisories': accepted_with_advisories,
        'advisory_faults': waived, 'blocking_faults': blockers,
        'guard_evidence': guard_evidence,
        'reason': ('accepted_with_style_advisories' if accepted_with_advisories else
                   'accepted_current_grade' if accepted else
                   'kept_current_rejection' if mode == 'strict' else 'blocked_required_evidence'),
        'limitations': 'Positive lexical and spelling-rhyme checks do not certify every proposition or spoken rhyme.',
    }
