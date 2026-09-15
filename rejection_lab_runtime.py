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
    # #1190: how long an answer about the switch stands before it is asked
    # again. A settings read is a SQLite open, and this is consulted on
    # every tint-wired model call, so a guard that is not cached costs what
    # it saves.
    LAB_SETTING_TTL = 5.0

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
        # #1190: the switch, and when it was last read. Starts OFF and
        # unread, so the very first call asks rather than assuming.
        self._on = False
        self._on_at = 0.0
        self.skipped = 0

    def switched_on(self):
        """#1190: IS THE LAB ACTUALLY ON.

        This class has never asked. lab_settings has carried enabled=false
        since 2026-09-08 and the traces kept being written the whole time -
        45,552 rows and 368 MB in the last two days alone, each one an
        fsync-bearing insert, for data nobody reads.

        Worse, one caller pays that write synchronously on the event loop:
        line_review_capture needs the row's sequence number back, so #1398
        left it at wait=True when it moved everything else to the daemon
        thread. Measured over twenty-four hours, that one function is the
        largest named source of event-loop stall on the station - 6,189
        seconds of the 21,162 seconds of stall inside 35,176 seconds of dead
        air.

        The failure direction is OFF on purpose. If the store cannot be
        asked, the lab does not write. A trace is inspection, and the note
        at the top of this file promises that inspection never stops audio;
        guessing ON when the disk is already in trouble breaks exactly that
        promise.
        """
        now = time.monotonic()
        if now - self._on_at < self.LAB_SETTING_TTL:
            return self._on
        self._on_at = now
        try:
            self._on = bool((self.store.settings() or {}).get('enabled'))
        except Exception as error:      # noqa: BLE001
            self.errors += 1
            self.last_error = type(error).__name__
            self._on = False
        return self._on

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
        # #1190: and the switch. Checked here as well as at scoped(),
        # because a trace opened before the operator turned the lab off
        # would otherwise keep writing until it closed.
        if not self.switched_on():
            self.skipped += 1
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
                # #1190: no trace is opened while the lab is off. This is
                # the one that actually stops the writing: current_id()
                # reads this ContextVar, and record() returns early on an
                # empty one, so an unopened trace silences every write
                # underneath it including line_review_capture's
                # synchronous one.
                if owner and not self.switched_on():
                    return await function(*args, **kwargs)
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
