"""Performer sessions: identity, resume, capacity and readiness.

Section 2 of docs/notes/speaker-recording-and-script-assembly.md, sentence by
sentence:

    "Each session records its actor, script revision, ordered assignments,
    renderer configuration, current state and accepted takes. Resume from
    verified work after interruption. An engine capacity limit can constrain
    execution without losing session identity or treating an incomplete
    performance as ready. A whole-conversation job should finish useful
    conversations rather than leave every candidate partly recorded."

Offline and storeless: the manifest store here is the in-memory one, and the
only disk this suite touches is a TemporaryDirectory. No live ledger, larder,
pantry or shelf is read or written.
"""
import json
import tempfile
import unittest
from pathlib import Path

from line_alignment import (MODE_CONTINUOUS, MODE_SEGMENTED, LineCut,
                            ScriptLine)
from speaker_session import (Assignment, AcceptedTake, Capacity,
                             ConversationJob, InMemoryManifestStore,
                             ManifestAdapter, PerformerSession, RendererConfig,
                             allocate, finish_first_order, new_session,
                             persist_session, resume_session)

REV = "rev-2026-09-15-a"


def renderer(mode=MODE_CONTINUOUS, cap=800, voice="vl_a5cc23e4", **kw):
    return RendererConfig(engine="xtts", voice=voice, mode=mode,
                          sample_rate=24000, max_request_chars=cap, **kw)


def assignments(count=4, chars=60, conversation="conv-1", speaker="dj",
                start=0, step=1):
    return [Assignment(f"occ-{start + index * step:02d}",
                       start + index * step, speaker,
                       ("word " * (chars // 5)).strip(), conversation)
            for index in range(count)]


def take(session, occurrence_id, ordinal=0, verdict="verified", **kw):
    fields = {
        "occurrence_id": occurrence_id, "ordinal": ordinal,
        "take_id": f"tk-{occurrence_id}", "master_hash": "sha-master",
        "sample_rate": 24000, "start_sample": 0, "end_sample": 24000,
        "boundary_method": "word_span+gap_split",
        "verification": {"verdict": verdict, "coverage": 1.0},
        "mode": session.renderer.mode, "revision": session.revision,
        "renderer_fingerprint": session.renderer.fingerprint,
    }
    fields.update(kw)
    return AcceptedTake(**fields)


class Identity(unittest.TestCase):

    def test_a_session_is_revision_actor_and_renderer_not_capacity(self):
        rows = assignments()
        first = new_session(REV, "dj", renderer(), rows,
                            capacity=Capacity(max_chars=100))
        second = new_session(REV, "dj", renderer(), rows,
                             capacity=Capacity(max_chars=100000))
        self.assertEqual(first.identity, second.identity)
        first.block("the engine is busy")
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.state, "blocked")

    def test_a_changed_renderer_is_a_different_identity(self):
        rows = assignments()
        base = new_session(REV, "dj", renderer(), rows)
        faster = new_session(REV, "dj", renderer(speech_rate=1.2), rows)
        self.assertNotEqual(base.identity, faster.identity)
        # But a note is not a performance change.
        annotated = new_session(REV, "dj", renderer(notes="tried twice"), rows)
        self.assertEqual(base.identity, annotated.identity)

    def test_two_occurrences_of_the_same_words_are_two_assignments(self):
        rows = [Assignment("occ-00", 0, "dj", "Say that again."),
                Assignment("occ-01", 1, "dj", "Say that again.")]
        session = new_session(REV, "dj", renderer(), rows)
        self.assertEqual(len(session.assignments), 2)
        with self.assertRaises(ValueError):
            new_session(REV, "dj", renderer(),
                        [Assignment("occ-00", 0, "dj", "x"),
                         Assignment("occ-00", 1, "dj", "x")])


class Readiness(unittest.TestCase):

    def test_an_incomplete_session_is_never_ready_and_says_which_line(self):
        session = new_session(REV, "dj", renderer(), assignments(3))
        session.accept(take(session, "occ-00", 0))
        verdict = session.readiness()
        self.assertFalse(verdict)
        self.assertEqual(set(verdict.missing), {"occ-01", "occ-02"})
        self.assertTrue(any("occ-01" in reason for reason in verdict.reasons))

    def test_capacity_blocking_a_session_cannot_make_it_read_as_ready(self):
        session = new_session(REV, "dj", renderer(), assignments(3))
        session.accept(take(session, "occ-00", 0))
        session.block("no engine slot left in this pass")
        self.assertEqual(session.state, "blocked")
        self.assertFalse(session.readiness())
        # Identity intact through the block.
        self.assertEqual(session.revision, REV)
        self.assertEqual(len(session.assignments), 3)

    def test_a_complete_session_is_ready(self):
        session = new_session(REV, "dj", renderer(), assignments(3))
        for index in range(3):
            session.accept(take(session, f"occ-{index:02d}", index))
        self.assertEqual(session.state, "complete")
        self.assertTrue(session.readiness())

    def test_an_unverified_take_cannot_be_accepted_at_all(self):
        session = new_session(REV, "dj", renderer(), assignments(2))
        with self.assertRaises(ValueError) as caught:
            session.accept(take(session, "occ-00", 0, verdict="refused"))
        self.assertIn("not verified", str(caught.exception))
        self.assertFalse(session.takes)

    def test_a_take_from_another_revision_or_mode_is_refused(self):
        session = new_session(REV, "dj", renderer(), assignments(2))
        with self.assertRaises(ValueError):
            session.accept(take(session, "occ-00", 0, revision="rev-other"))
        with self.assertRaises(ValueError):
            session.accept(take(session, "occ-00", 0, mode=MODE_SEGMENTED))
        with self.assertRaises(ValueError):
            session.accept(take(session, "occ-99", 9))

    def test_discarding_a_take_takes_readiness_away_again(self):
        session = new_session(REV, "dj", renderer(), assignments(2))
        for index in range(2):
            session.accept(take(session, f"occ-{index:02d}", index))
        self.assertTrue(session.readiness())
        self.assertTrue(session.discard("occ-01", "failed its cut"))
        self.assertFalse(session.readiness())
        self.assertEqual(session.state, "recording")


class OutOfOrderRecording(unittest.TestCase):
    """The note's four-line exchange: A records 1 and 3, B records 2 and 4,
    and assembly must produce 1, 2, 3, 4."""

    def test_takes_come_back_in_script_order_not_completion_order(self):
        rows = [Assignment("occ-01", 1, "dj", "one"),
                Assignment("occ-03", 3, "dj", "three")]
        session = new_session(REV, "dj", renderer(), rows)
        session.accept(take(session, "occ-03", 3))
        session.accept(take(session, "occ-01", 1))
        self.assertEqual([t.occurrence_id for t in session.ordered_takes()],
                         ["occ-01", "occ-03"])

    def test_two_actors_interleave_by_ordinal(self):
        actor_a = new_session(REV, "dj", renderer(),
                              [Assignment("occ-01", 1, "dj", "one"),
                               Assignment("occ-03", 3, "dj", "three")])
        actor_b = new_session(REV, "cohost", renderer(voice="vl_cbd12b2a"),
                              [Assignment("occ-02", 2, "cohost", "two"),
                               Assignment("occ-04", 4, "cohost", "four")])
        for session, ids in ((actor_a, ("occ-03", "occ-01")),
                             (actor_b, ("occ-02", "occ-04"))):
            for oid in ids:
                session.accept(take(session, oid, int(oid.split("-")[1])))
        merged = sorted(list(actor_a.ordered_takes())
                        + list(actor_b.ordered_takes()),
                        key=lambda t: t.ordinal)
        self.assertEqual([t.ordinal for t in merged], [1, 2, 3, 4])


class CapacityAndPlans(unittest.TestCase):

    def test_requests_are_grouped_under_the_engine_cap_in_reading_order(self):
        session = new_session(REV, "dj", renderer(cap=200),
                              assignments(4, chars=60))
        plan = session.plan()
        self.assertTrue(plan.requests)
        for request in plan.requests:
            self.assertLessEqual(request.chars, 200)
        self.assertEqual(list(plan.covered),
                         [a.occurrence_id for a in session.assignments])

    def test_a_line_longer_than_the_engine_will_perform_is_refused_in_continuous_mode(self):
        rows = [Assignment("occ-00", 0, "dj", "w" * 1200)]
        session = new_session(REV, "dj", renderer(cap=800), rows)
        plan = session.plan()
        self.assertEqual(plan.requests, ())
        self.assertEqual(len(plan.refusals), 1)
        occurrence, why = plan.refusals[0]
        self.assertEqual(occurrence, "occ-00")
        self.assertIn("segmented synthesis", why)

    def test_the_same_line_is_split_with_retained_boundaries_when_segmented(self):
        rows = [Assignment("occ-00", 0, "dj", " ".join(["word"] * 400))]
        session = new_session(REV, "dj", renderer(MODE_SEGMENTED, cap=300),
                              rows)
        plan = session.plan()
        self.assertGreater(len(plan.requests), 1)
        self.assertTrue(all(r.is_split for r in plan.requests))
        self.assertEqual({r.pieces for r in plan.requests},
                         {len(plan.requests)})
        self.assertEqual([r.piece for r in plan.requests],
                         list(range(len(plan.requests))))
        for request in plan.requests:
            self.assertLessEqual(request.chars, 300)

    def test_a_spent_budget_defers_the_rest_rather_than_dropping_it(self):
        session = new_session(REV, "dj", renderer(cap=200),
                              assignments(6, chars=60))
        plan = session.plan(Capacity(max_requests=1))
        self.assertEqual(len(plan.requests), 1)
        self.assertTrue(plan.deferred)
        covered = set(plan.covered)
        everything = {a.occurrence_id for a in session.assignments}
        self.assertEqual(covered | set(plan.deferred), everything)

    def test_a_pass_cap_below_the_engine_cap_is_the_one_that_binds(self):
        session = new_session(REV, "dj", renderer(cap=800),
                              assignments(4, chars=60))
        plan = session.plan(Capacity(max_request_chars=120))
        for request in plan.requests:
            self.assertLessEqual(request.chars, 120)


class Resume(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryManifestStore()
        self.rows = assignments(3)
        self.session = new_session(REV, "dj", renderer(), self.rows)

    def test_verified_work_survives_an_interruption(self):
        self.session.accept(take(self.session, "occ-00", 0))
        self.session.accept(take(self.session, "occ-01", 1))
        self.session.block("interrupted mid-sitting")
        persist_session(self.store, self.session)

        resumed, dropped = resume_session(
            self.store, self.session.session_id, self.rows,
            self.session.renderer, REV)
        self.assertEqual(dropped, ())
        self.assertEqual(set(resumed.takes), {"occ-00", "occ-01"})
        self.assertEqual([a.occurrence_id for a in resumed.outstanding()],
                         ["occ-02"])
        self.assertFalse(resumed.readiness())
        self.assertEqual(resumed.identity, self.session.identity)

    def test_a_new_revision_drops_the_old_takes_and_says_so(self):
        self.session.accept(take(self.session, "occ-00", 0))
        persist_session(self.store, self.session)
        resumed, dropped = resume_session(
            self.store, self.session.session_id, self.rows,
            self.session.renderer, "rev-2026-09-15-b")
        self.assertEqual(resumed.takes, {})
        self.assertTrue(any("occ-00" in reason for reason in dropped))
        self.assertEqual(len(resumed.outstanding()), 3)

    def test_a_changed_renderer_drops_the_old_takes(self):
        self.session.accept(take(self.session, "occ-00", 0))
        persist_session(self.store, self.session)
        resumed, dropped = resume_session(
            self.store, self.session.session_id, self.rows,
            renderer(speech_rate=1.3), REV)
        self.assertEqual(resumed.takes, {})
        self.assertTrue(any("renderer" in reason for reason in dropped))

    def test_a_stored_take_that_no_longer_verifies_is_dropped(self):
        self.session.accept(take(self.session, "occ-00", 0))
        persist_session(self.store, self.session)
        # Corrupt the stored verdict the way a failed recheck would.
        stored = self.store.sessions[self.session.session_id]
        stored["takes"][0]["verification"]["verdict"] = "failed"
        resumed, dropped = resume_session(
            self.store, self.session.session_id, self.rows,
            self.session.renderer, REV)
        self.assertEqual(resumed.takes, {})
        self.assertTrue(any("unverified" in reason for reason in dropped))

    def test_resuming_a_session_that_was_never_stored_is_a_reason_not_a_crash(self):
        resumed, dropped = resume_session(self.store, "ps_nothing")
        self.assertIsNone(resumed)
        self.assertTrue(dropped)

    def test_a_complete_session_resumes_complete(self):
        for index in range(3):
            self.session.accept(take(self.session, f"occ-{index:02d}", index))
        persist_session(self.store, self.session)
        resumed, dropped = resume_session(
            self.store, self.session.session_id, self.rows,
            self.session.renderer, REV)
        self.assertEqual(dropped, ())
        self.assertEqual(resumed.state, "complete")
        self.assertTrue(resumed.readiness())


class FinishingConversations(unittest.TestCase):

    def jobs(self):
        small = new_session(REV, "dj", renderer(),
                            assignments(2, chars=50, conversation="conv-small"))
        medium = new_session(REV, "dj", renderer(),
                             assignments(6, chars=50,
                                         conversation="conv-medium"))
        large = new_session(REV, "dj", renderer(),
                            assignments(20, chars=50,
                                        conversation="conv-large"))
        return [ConversationJob("conv-large", (large,)),
                ConversationJob("conv-small", (small,)),
                ConversationJob("conv-medium", (medium,))]

    def test_closest_to_finished_sorts_first(self):
        order = [j.conversation_id for j in finish_first_order(self.jobs())]
        self.assertEqual(order, ["conv-small", "conv-medium", "conv-large"])

    def test_a_budget_finishes_whole_conversations_and_leaves_the_rest_alone(self):
        jobs = self.jobs()
        budget = jobs[1].outstanding_chars + jobs[2].outstanding_chars
        decided = allocate(jobs, Capacity(max_chars=budget))
        self.assertEqual(set(decided.finish), {"conv-small", "conv-medium"})
        self.assertEqual(decided.untouched, ("conv-large",))
        # Nothing was started on the conversation it cannot finish.
        self.assertNotIn(jobs[0].sessions[0].session_id, decided.plans)

    def test_a_budget_that_fits_nothing_still_starts_the_cheapest_and_blocks_it(self):
        jobs = self.jobs()
        decided = allocate(jobs, Capacity(max_chars=10))
        self.assertEqual(decided.finish, ())
        self.assertIn("blocked", decided.note)
        started = [j for j in jobs if j.conversation_id == "conv-small"][0]
        self.assertEqual(started.sessions[0].state, "blocked")
        self.assertFalse(started.sessions[0].readiness())

    def test_a_conversation_is_ready_only_when_every_performer_is(self):
        dj = new_session(REV, "dj", renderer(),
                         [Assignment("occ-01", 1, "dj", "one", "conv-1")])
        cohost = new_session(REV, "cohost", renderer(voice="vl_cbd12b2a"),
                             [Assignment("occ-02", 2, "cohost", "two",
                                         "conv-1")])
        job = ConversationJob("conv-1", (dj, cohost))
        dj.accept(take(dj, "occ-01", 1))
        self.assertFalse(job.ready)
        cohost.accept(take(cohost, "occ-02", 2))
        self.assertTrue(job.ready)


class Persistence(unittest.TestCase):

    def test_a_session_record_round_trips_through_a_temp_file(self):
        session = new_session(REV, "dj", renderer(), assignments(2))
        session.accept(take(session, "occ-00", 0))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.json"
            path.write_text(json.dumps(session.to_record()), encoding="utf-8")
            back = PerformerSession.from_record(
                json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(back.identity, session.identity)
        self.assertEqual(set(back.takes), {"occ-00"})
        self.assertEqual(back.readiness().missing, ("occ-01",))

    def test_a_take_is_built_straight_from_an_aligner_cut(self):
        config = renderer()
        cut = LineCut(occurrence_id="occ-00", ordinal=0, speaker="dj",
                      start_sample=1200, end_sample=48000, sample_rate=24000,
                      boundary_method="word_span+gap_split",
                      verification={"verdict": "verified", "coverage": 0.97},
                      mode=MODE_CONTINUOUS, master_hash="sha-master")
        built = AcceptedTake.from_line_cut(
            cut, take_id="tk-1", revision=REV,
            renderer_fingerprint=config.fingerprint)
        session = new_session(REV, "dj", config,
                              [Assignment("occ-00", 0, "dj", "hello")])
        session.accept(built)
        self.assertEqual(session.state, "complete")
        self.assertEqual(built.frames, 46800)
        self.assertEqual(built.boundary_method, "word_span+gap_split")

    def test_the_adapter_names_a_call_the_real_store_does_not_have(self):
        class Partial:
            def keep(self, record):
                return record["session_id"]

        adapter = ManifestAdapter(Partial(), {"save_session": "keep"})
        self.assertEqual(adapter.save_session({"session_id": "ps_x"}), "ps_x")
        self.assertFalse(adapter.supports("load_session"))
        with self.assertRaises(NotImplementedError) as caught:
            adapter.load_session("ps_x")
        self.assertIn("load_session", str(caught.exception))
        # An absent pin list is not a fault: nothing is pinned.
        self.assertEqual(list(adapter.pinned_occurrences(REV)), [])

    def test_the_in_memory_store_answers_the_whole_protocol(self):
        store = InMemoryManifestStore()
        session = new_session(REV, "dj", renderer(), assignments(1))
        persist_session(store, session)
        self.assertEqual(len(store.list_sessions(REV, "dj")), 1)
        self.assertEqual(len(store.list_sessions("rev-other")), 0)
        store.save_master({"take_id": "tk-1", "sha256": "abc"})
        self.assertEqual(store.load_master("tk-1")["sha256"], "abc")
        store.save_cut({"revision": REV, "occurrence_id": "occ-00"})
        self.assertEqual(len(store.list_cuts(REV)), 1)
        self.assertEqual(len(store.list_cuts(REV, ["occ-99"])), 0)


if __name__ == "__main__":
    unittest.main()
