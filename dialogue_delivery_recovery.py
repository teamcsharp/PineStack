"""Repair silent page transport leases while preserving approved dialogue.

This is transport recovery: no new wording, model calls, synthetic receipts,
or changed roulette choices. Existing media admission still owns publication.
"""
from __future__ import annotations

import asyncio
import copy
import time
import uuid


def _pending(d):
    return d.get('speech') and d.get('state') != 'ended' and not d.get('transport_replaced')


def _audible_recent(ns, now=None, *, dialogue_only=True):
    now = time.time() if now is None else now
    if '_PAGE_ACK_EVENTS' not in ns:
        return bool(ns.get('page_voice_audible_recent', lambda **kw: False)(within=20.0))
    def speech(e):
        delivery = (ns.get('_PAGE_DELIVERIES') or {}).get(str(e.get('delivery_id') or '')) or {}
        clip = delivery.get('clip') or {}
        return bool(delivery.get('speech') and not clip.get('picture_only') and not clip.get('video'))
    return any(e.get('event') == 'playing' and e.get('progressed', True)
               and not e.get('muted') and float(e.get('audible_volume') or 0) > 0
               and now-20 <= float(e.get('at') or 0) <= now
               and (not dialogue_only or speech(e))
               for e in (ns.get('_PAGE_ACK_EVENTS') or [])[-80:])


def delivery_evidence(ns, now=None):
    now = time.time() if now is None else float(now)
    pending = [d for d in (ns.get('_PAGE_DELIVERIES') or {}).values()
               if _pending(d)
               and not (d.get('clip') or {}).get('picture_only')
               and not (d.get('clip') or {}).get('video')]
    try:
        listeners = len(ns['_listeners_live']())
    except Exception:
        listeners = 0
    recent = _audible_recent(ns, now)
    unstarted = [d for d in pending if not any(
        p.get('event') == 'playing' and p.get('progressed', True)
        and float(p.get('audible_volume') or 0) > 0
        and now - float(p.get('at') or 0) <= 20
        for p in (d.get('listeners') or {}).values())]
    state = ns.get('_DIALOGUE_DELIVERY_RECOVERY') or {}
    return {'listeners_present': listeners, 'page_speech_active': recent,
            'page_audio_active': _audible_recent(ns, now, dialogue_only=False),
            'unstarted_deliveries': len(unstarted),
            'unstarted_oldest_seconds': max((max(0, now-float(d.get('at') or now)) for d in unstarted), default=0),
            'page_reserved_seconds': max(0, float((ns.get('_PAGE_AIR_UNTIL') or [0])[0] or 0)-now),
            'delivery_recovery': {k: state.get(k) for k in ('at','runs','republished','preserved','last_error')}}


async def recover_dialogue_delivery(ns):
    state = ns.setdefault('_DIALOGUE_DELIVERY_RECOVERY', {'runs': 0, 'at': 0})
    now = time.time()
    if not (ns.get('_RADIO') or {}).get('on') or ns['radio_paused']():
        return {'ok': False, 'changed': False, 'lines': ['The station is off or paused.']}
    evidence = delivery_evidence(ns, now)
    if not evidence['listeners_present'] or evidence['page_speech_active']:
        return {'ok': True, 'changed': False, 'lines': ['No silent listening page needs a transport reset.']}
    if now-float(state.get('at') or 0) < 90:
        return {'ok': True, 'changed': False, 'pending': True,
                'lines': ['The replacement deliveries are still inside their bounded recovery window.']}
    if state.get('busy'):
        return {'ok': True, 'changed': False, 'pending': True, 'lines': ['This delivery reset is already running.']}
    state['busy'] = True
    try:
        stored = await asyncio.to_thread(ns['page_recovery_read'])
        live = list((ns.get('_PAGE_DELIVERIES') or {}).values())
        candidates = {}
        completed = {str(d.get('delivery_id') or '') for d in live
                     if d.get('state') == 'ended' or d.get('transport_replaced')}
        for clip in stored + [d.get('clip') or {} for d in live if _pending(d)]:
            if not clip.get('url') or not clip.get('delivery_id') or clip.get('picture_only') or clip.get('video'):
                continue
            if not clip.get('speech') or str(clip.get('kind') or '') in ('sfx','reply'):
                continue
            if str(clip['delivery_id']) in completed:
                continue
            candidates[str(clip['delivery_id'])] = copy.deepcopy(clip)
        if not candidates:
            return {'ok': False, 'changed': False, 'lines': ['No preserved approved speech delivery is available to reset.']}
        ordered = sorted(candidates.values(), key=lambda c: int(c.get('broadcast_ms') or c.get('ts') or 0))
        # The asset resolver is the admission gate's own definition of media
        # existence. Do not turn a deleted asset into another unplayable head.
        def viable():
            return [c for c in ordered if ns['_admission_resolve'](str(c['url'])) is not None]
        viable_clips = await asyncio.to_thread(viable)
        if not viable_clips:
            return {'ok': False, 'changed': False, 'lines': ['The preserved speech media needs restoration before it can be delivered.']}
        # Save the complete inventory before invalidating any transport epoch.
        # Preserve missing assets too so the report does not become deletion.
        preserved = copy.deepcopy(ordered)
        for c in preserved:
            c.pop('broadcast_ms', None)
            c['recovery_owed'] = True
        await asyncio.to_thread(ns['page_recovery_write'], preserved)
        if not ns['_RADIO'].get('on') or ns['radio_paused']() or _audible_recent(ns):
            return {'ok': True, 'changed': False, 'lines': ['Speech resumed during diagnosis; its active playback was preserved.']}
        current = {str(d.get('delivery_id') or '') for d in (ns.get('_PAGE_DELIVERIES') or {}).values()
                   if _pending(d)}
        initial = {str(d.get('delivery_id') or '') for d in live if _pending(d)}
        if current != initial:
            return {'ok': True, 'changed': False, 'pending': True,
                    'lines': ['Speech inventory changed during the checkpoint; retrying from the new inventory.']}
        cut = int(time.time()*1000)
        ns['_RADIO']['voice_cut_ms'] = cut
        ns['_PAGE_AIR_UNTIL'][0] = 0.0
        # The seam clock is a second reservation cursor. Leaving its old
        # future endpoint would put the next unseamed message behind the
        # same phantom queue, even after the page cursor was cleared.
        gap = ns.get('_reply_gap')
        if gap is not None:
            booked = getattr(gap, '_BOOKED', None)
            last = getattr(gap, '_LAST_DOOR', None)
            if isinstance(booked, dict):
                booked.clear()
                booked.update(until=0.0, tail=0.0)
            if isinstance(last, dict):
                last.clear()
                last.update(rows=None, start=0.0)
        for old_id in candidates:
            d = (ns.get('_PAGE_DELIVERIES') or {}).get(old_id)
            if d:
                d['state'] = 'error'
                d['transport_replaced'] = True
                d['error'] = 'Unheard transport occurrence replaced; dialogue preserved.'
            ns['playout_tell']('ended', delivery_id=old_id,
                               why='unheard transport reservation replaced by orchestrator')
        owner = ns.get('_FLOOR_OWNER') or {}
        if owner.get('label') == 'preserved page deliveries after reservation repair':
            task = owner.get('task')
            if task is not None and task is not asyncio.current_task() and not task.done():
                # Only the boot transport's wait is cancelled; recording and
                # writing owners retain their jobs. Its finally owns release.
                task.cancel()
        # Earlier committed dialogue is republished in its original FIFO.
        # Fresh delivery IDs and timestamps invalidate client dedup against
        # the silent attempts; the audio, cue IDs and System 3 stamps survive.
        published, replacements = [], {}
        for index, original in enumerate(viable_clips):
            c = copy.deepcopy(original)
            old_id = str(c['delivery_id'])
            c['delivery_id'] = uuid.uuid4().hex[:16]
            c['recovery_of_delivery_id'] = original.get('recovery_of_delivery_id') or old_id
            c['ts'] = cut + index + 1
            c.pop('broadcast_ms', None)
            c.pop('resume_at', None)
            c['delivery_state'] = 'published'
            c['recovery_owed'] = True
            c['air_waited'] = True  # This approved delivery already passed its original air turn.
            did = ns['page_feed_append'](c)
            if did:
                ns['page_recovery_chat_rows'](c, did)
                published.append(c)
                replacements[old_id] = c
        # Keep refused assets owed alongside replacement deliveries.
        remaining = [replacements.get(str(c['delivery_id']), c) for c in preserved]
        remaining = [c for c in remaining if
                     (ns.get('_PAGE_DELIVERIES', {}).get(c['delivery_id']) or {}).get('state') != 'ended']
        await asyncio.to_thread(ns['page_recovery_write'], remaining)
        state.update(at=now, runs=int(state.get('runs') or 0)+1,
                     republished=len(published), preserved=len(remaining), last_error='')
        inject = ns.get('system3_injected_node')
        if callable(inject) and published:
            inject(by='orchestrator delivery recovery', why='Unheard speech reservations were replaced after a verified dialogue gap.',
                   kind='delivery', line_id=str(published[0].get('row_id') or ''),
                   extra={'republished': len(published), 'preserved': len(remaining)})
        return {'ok': bool(published), 'changed': bool(published), 'pending': True,
                'republished': len(published), 'preserved': len(remaining),
                'lines': ['Replaced %d unheard transport occurrences; preserved %d approved deliveries. Playback still requires listener confirmation.'
                          % (len(published), len(remaining))]}
    except Exception as exc:
        state['last_error'] = type(exc).__name__
        raise
    finally:
        state['busy'] = False
