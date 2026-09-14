"""Exact, occurrence-linked diagnostics for crystal work. Never changes a grade."""
from __future__ import annotations

import contextvars
import functools
import inspect
import queue
import threading
import time
import uuid


class LabRuntime:
    # #1398: THE TRACE IS WRITTEN OFF THE LOOP.
    #
    # record() is called from the event loop - from ask_model on every
    # tint-wired model call, from line_review_capture, from the learning
    # desks - and store.append_trace is a SQLite INSERT with a commit,
    # which is an fsync, on a disk that also carries the pantry flusher's
    # dumps and the clip book's commits. /api/pulse caught ask_model on
    # the main thread for 11.0 s - past the host watchdog's 8-second
    # probe, the one that restarts the station. A trace is inspection,
    # and this class already promises it must never stop audio; a write
    # that can take seconds on the loop breaks that promise the hard way.
    #
    # So the trace id is read HERE, synchronously (it lives in a
    # ContextVar a thread would not see), and the write goes to one
    # daemon thread, in order. A caller that needs the row back - one
    # exists: line_review_capture keeps the step's seq - says wait=True
    # and pays the write as before.
    DESK_MOST = 4000

    def __init__(self, store):
        self.store = store
        self.scope = contextvars.ContextVar('rejection_lab_trace', default=None)
        self.call = contextvars.ContextVar('rejection_lab_model_call', default='')
        self.errors = 0
        self.last_error = ''
        self._desk = queue.Queue()
        self._desk_lock = threading.Lock()
        self._desk_thread = None
        self.deferred = 0
        self.dropped = 0

    def _desk_worker(self):
        while True:
            trace_id, kind, details = self._desk.get()
            try:
                self.store.append_trace(trace_id, {'kind': kind, 'details': details})
            except Exception as error:
                self.errors += 1
                self.last_error = type(error).__name__
            finally:
                self._desk.task_done()

    def _desk_post(self, trace_id, kind, details):
        with self._desk_lock:
            t = self._desk_thread
            if t is None or not t.is_alive():
                t = threading.Thread(target=self._desk_worker, name='lab-desk', daemon=True)
                self._desk_thread = t
                t.start()
        if self._desk.qsize() >= self.DESK_MOST:
            self.dropped += 1
            return
        self._desk.put_nowait((trace_id, kind, details))
        self.deferred += 1

    def current_id(self):
        return (self.scope.get() or {}).get('trace_id', '')

    def record(self, kind, details, wait=False):
        trace_id = self.current_id()
        if not trace_id:
            return None
        if not wait:
            try:
                self._desk_post(trace_id, kind, details)
            except Exception as error:
                self.errors += 1
                self.last_error = type(error).__name__
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
