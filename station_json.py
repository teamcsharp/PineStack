"""Keep ordinary station responses fast and oversized random seeds exact."""
from fastapi.responses import ORJSONResponse
from fastapi.encoders import jsonable_encoder
from collections import deque
import threading
import time

_FEED_ERRORS = deque(maxlen=16)
_FEED_ERROR_LOCK = threading.Lock()


def voice_feed_health():
    with _FEED_ERROR_LOCK:
        recent = [dict(e) for e in _FEED_ERRORS if 0 <= time.time() - e['at'] < 120]
    return {'state': 'degraded' if recent else 'healthy', 'recent_errors': recent}


def _seed_safe(value):
    # Only called when the native encoder rejects a payload. Decimal text
    # preserves the full random seed; a browser number would round it.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value) if abs(value) > (2**53-1) else value
    if isinstance(value, dict):
        return {_seed_safe(k): _seed_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_seed_safe(v) for v in value]
    return value


class PineJSONResponse(ORJSONResponse):
    def render(self, content):
        try:
            return super().render(content)
        except TypeError as exc:
            if 'Integer exceeds 64-bit range' not in str(exc):
                raise
            return super().render(_seed_safe(content))


def voice_feed_response(payload, response_class=PineJSONResponse):
    """One malformed clip cannot disable every other approved performance.

    The fast path encodes the same complete response. On a clip-specific
    error, keep valid clips and explicitly report the bad occurrences; their
    source inventory stays owed. A broken envelope remains a visible failure.
    Called on a worker thread, outside the broadcast event loop.
    """
    try:
        return response_class(jsonable_encoder(payload))
    except (TypeError, ValueError, OverflowError):
        if not isinstance(payload, dict) or not isinstance(payload.get('clips'), list):
            raise
    envelope = {k: v for k, v in payload.items() if k != 'clips'}
    encoded = jsonable_encoder(envelope)
    response_class(encoded)  # Do not disguise a broken global transport cursor.
    accepted, errors = [], []
    for clip in payload['clips']:
        try:
            row = jsonable_encoder(clip)
            response_class(row)
            accepted.append(row)
        except (TypeError, ValueError, OverflowError) as exc:
            ident = clip.get('delivery_id') if isinstance(clip, dict) else None
            error = {'at': time.time(), 'delivery_id': str(ident or '')[:100], 'error_type': type(exc).__name__}
            errors.append(error)
            with _FEED_ERROR_LOCK:
                _FEED_ERRORS.append(error)
    return response_class({**encoded, 'clips': accepted, 'feed_errors': errors[:16], 'feed_error_count': len(errors)})
