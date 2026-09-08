"""Exact, occurrence-linked diagnostics for crystal work. Never changes a grade."""
from __future__ import annotations

import contextvars
import functools
import inspect
import time
import uuid


class LabRuntime:
    def __init__(self, store):
        self.store = store
        self.scope = contextvars.ContextVar('rejection_lab_trace', default=None)
        self.call = contextvars.ContextVar('rejection_lab_model_call', default='')
        self.errors = 0
        self.last_error = ''

    def current_id(self):
        return (self.scope.get() or {}).get('trace_id', '')

    def record(self, kind, details):
        trace_id = self.current_id()
        if not trace_id:
            return None
        try:
            return self.store.append_trace(trace_id, {'kind': kind, 'details': details})
        except Exception as error:
            # Inspection failure must not create another rejection or stop audio.
            self.errors += 1
            self.last_error = type(error).__name__
            return None

    def scoped(self, stage):
        def decorate(function):
            signature = inspect.signature(function)

            @functools.wraps(function)
            async def run(*args, **kwargs):
                bound = signature.bind(*args, **kwargs)
                owner = self.scope.get() is None
                token = self.scope.set({'trace_id': uuid.uuid4().hex}) if owner else None
                detail = {key: value for key, value in bound.arguments.items()
                          if key in {'text', 'script', 'kind', 'world', 'model', 'answering', 'lesson'}}
                detail['stage'] = stage
                self.record('stage_started', detail)
                started = time.monotonic()
                try:
                    result = await function(*args, **kwargs)
                    self.record('stage_finished', {'stage': stage,
                        'elapsed_ms': round((time.monotonic() - started) * 1000),
                        'result': result})
                    return result
                except BaseException as error:
                    self.record('stage_failed', {'stage': stage, 'error': str(error),
                        'error_type': type(error).__name__,
                        'elapsed_ms': round((time.monotonic() - started) * 1000)})
                    raise
                finally:
                    if token is not None:
                        self.scope.reset(token)
            return run
        return decorate

    def model_call(self, function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        async def run(*args, **kwargs):
            if not self.current_id():
                return await function(*args, **kwargs)
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            call_id = uuid.uuid4().hex
            token = self.call.set(call_id)
            self.record('model_request', {'call_id': call_id, **bound.arguments})
            started = time.monotonic()
            try:
                result = await function(*args, **kwargs)
                self.record('model_response', {'call_id': call_id,
                    'elapsed_ms': round((time.monotonic() - started) * 1000),
                    'response': result})
                return result
            except BaseException as error:
                self.record('model_error', {'call_id': call_id,
                    'elapsed_ms': round((time.monotonic() - started) * 1000),
                    'error_type': type(error).__name__, 'error': str(error)})
                raise
            finally:
                self.call.reset(token)
        return run
