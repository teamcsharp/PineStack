"""Yield unpublished legacy speech to verified, allocated dynamic performances.

Reads only native System2 snapshots. Never reserves, starts transport, cancels
published audio, changes debt, or replays a missed occurrence.
"""
import asyncio
import math
import time

KINDS = {'book_time', 'sfx_supercut'}


def number(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


class DynamicFloor:
    def __init__(self, namespace):
        self.g = namespace
        self.last = {}

    def boundary(self, meta=None, *, by_hand=False, whole=False):
        meta = meta if isinstance(meta, dict) else {}
        # Owned native performances keep their complete transport contract.
        if by_hand or whole or meta.get('_system2'):
            return None
        getter = self.g.get('_system2')
        if not callable(getter):
            return None
        try:
            runtime = getter()
        except Exception:
            return None
        if not runtime or not getattr(runtime, 'enabled', False):
            return None
        now = time.time()
        candidates = {str(row.get('id')): row for row in (getattr(runtime, '_candidates', ()) or ()) if isinstance(row, dict)}
        window = meta.get('_ready_slot')
        window = window if isinstance(window, dict) else {}
        owned = str(window.get('occurrence') or meta.get('system2_slot') or '')
        matches = []
        for hour in (getattr(runtime, '_plans', ()) or ()):
            if not isinstance(hour, dict):
                continue
            for slot in (hour.get('slots', ()) or ()):
                if not isinstance(slot, dict):
                    continue
                kind = slot.get('dynamic_kind')
                start, end = number(slot.get('start')), number(slot.get('deadline'))
                if kind not in KINDS or end <= now or not slot.get('enabled', True):
                    continue
                if owned == str(slot.get('id') or ''):
                    continue
                occurrence = str(slot.get('template_id') or '') + '@' + str(int(start))
                if meta.get('dynamic_occurrence') == occurrence:
                    continue
                for allocation in (slot.get('allocations', ()) or ()):
                    if not isinstance(allocation, dict):
                        continue
                    saved = allocation.get('candidate')
                    if not isinstance(saved, dict):
                        continue
                    candidate = candidates.get(str(saved.get('id')))
                    source = (candidate or {}).get('source')
                    source = source if isinstance(source, dict) else {}
                    if (not candidate or not candidate.get('ready') or not candidate.get('eligible')
                            or candidate.get('slot_id') != slot.get('id')
                            or source.get('dynamic_kind') != kind
                            or source.get('dynamic_occurrence') != occurrence):
                        continue
                    matches.append({'kind': kind, 'slot_id': slot['id'], 'start': start,
                        'deadline': end, 'candidate_id': candidate['id']})
                    break
        return min(matches, key=lambda row: row['start']) if matches else None

    def wait_allowed(self, meta=None, *, seconds=0.0, by_hand=False, whole=False):
        """A queued, unhanded automatic round may withdraw without stopping audio."""
        meta = meta if isinstance(meta, dict) else {}
        proof = meta.get('_system2')
        proof = proof if isinstance(proof, dict) else {}
        if by_hand or (proof.get('reservation_id') and (proof.get('awaiting_ack') or meta.get('_dynamic_floor_started'))):
            return True
        if not proof.get('reservation_id'):
            return not self.yield_now(meta, seconds=seconds, by_hand=by_hand, whole=whole)
        window = meta.get('_ready_slot')
        window = window if isinstance(window, dict) else {}
        air = max(0.0, number(seconds))
        try:
            owner = self.g['_system2']()
            candidate = next((row for row in (getattr(owner, '_candidates', ()) or ())
                if isinstance(row, dict) and str(row.get('id')) == str(proof.get('candidate_id'))), {})
            air = max(air, number(candidate.get('air_seconds'), number(candidate.get('seconds'))))
        except Exception:
            pass  # A transient getter/cache problem never stops ordinary air.
        now = time.time()
        deadline = number(window.get('deadline'))
        if meta.get('dynamic_kind') in KINDS and deadline and now + air > deadline:
            self.last = {'at': now, 'why': 'The unhanded dynamic recording no longer fits its own deadline',
                'slot_id': proof.get('slot_id'), 'deadline': deadline}
            return False
        # Preserve ordinary overrun policy unless a real ready allocation for a
        # scheduled dynamic episode needs this floor. An expired old reservation
        # must not own the dispatcher while silently queued behind that floor.
        unowned = {key: value for key, value in meta.items() if key != '_system2'}
        try:
            boundary = self.boundary(unowned, whole=whole)
        except (AttributeError, TypeError, ValueError):
            return True
        if boundary and now + air + 1 >= boundary['start']:
            self.last = dict(boundary, at=now, why='Unhanded queued recording yields to the ready dynamic occurrence')
            return False
        return True

    async def wait_render(self, work, meta=None, *, by_hand=False, whole=False):
        """Await only unpublished render work, checking a ready native boundary."""
        task = asyncio.ensure_future(work)
        try:
            while not task.done():
                if not self.wait_allowed(meta, by_hand=by_hand, whole=whole):
                    task.cancel()  # no audio from this render has been published
                    done, _ = await asyncio.wait({task}, timeout=.25)
                    if done:
                        try:
                            task.result()
                        except (asyncio.CancelledError, Exception):
                            pass
                    else:
                        task.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)
                    return False, None
                await asyncio.wait({task}, timeout=.5)
            return True, task.result()
        finally:
            if not task.done():
                task.cancel()

    def yield_now(self, meta=None, *, seconds=0.0, by_hand=False, whole=False):
        try:
            boundary = self.boundary(meta, by_hand=by_hand, whole=whole)
        except (AttributeError, TypeError, ValueError):
            return False  # Malformed transient cache state must never stop ordinary air.
        if not boundary:
            return False
        now = time.time()
        # Clear the floor before a new clip/burst would cross the boundary.
        # The currently published clip is allowed to finish by the existing
        # _paged_settle door in the caller; this helper has no transport side effects.
        lead = max(0.0, number(self.g.get('VOICE_BROADCAST_LEAD_MS'))) / 1000.0
        published = self.g.get('_PAGE_AIR_UNTIL')
        sold = number(published[0]) if isinstance(published, (list, tuple)) and published else 0.0
        finish = max(now + lead, sold) + max(0.0, number(seconds)) + 1.0
        if finish < boundary['start']:
            return False
        self.last = dict(boundary, at=now, next_seconds=max(0.0, number(seconds)))
        return True


def install(app, namespace):
    existing = namespace.get('DYNAMIC_FLOOR_RUNTIME')
    if existing:
        return existing
    runtime = DynamicFloor(namespace)
    namespace['DYNAMIC_FLOOR_RUNTIME'] = runtime
    namespace['dynamic_floor_yield'] = runtime.yield_now
    namespace['dynamic_floor_wait_allowed'] = runtime.wait_allowed
    namespace['dynamic_floor_render_wait'] = runtime.wait_render
    return runtime
