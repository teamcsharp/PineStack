"""#1064: every line a bar.

"When tinted, I want the scripting process to convert every single line
into an MF Doom style rap." The whole-round pass used to stop at the first
line the grader refused and throw away every bar that had passed; the
grader demanded two kinds of rhyme in every line; and the writer's heat
clause leaked into the bars. The samples below are exact rewrites off the
station's own trail.
"""
import unittest
from contextlib import ExitStack
from unittest import mock

import app

SAMPLES = {
 "good": [
  {
   "plain": "Have your choice, spider-man. And see how a hero is rewarded. The real enemy is out there. I feel their guns moving in the water. Their metal targeting us, americans, soviets. And for what? And then to be reminded what real power is. You had the one that killed her. That's just following orders. I've been at the mercy of men just following orders. Phone call",
   "tinted": "Pick a gate, spider-man—see how the reward is non-existent / This hero’s progress is distant / The real villain's in the water, metal fingers movin' in a blizzard / Targeting Soviets, Americans, little pricks with the wizard / For what? To measure pleasure through power and the stress / You had the tool that left her as a corpse in a mess / Just following orders? Brainsick, tick, tick / I’ve been at the mercy of men playing the trick / Phone call.",
   "chunks": [
    {
     "text": "to flee Both gates look the same—which will it be?\nDemons scream from thought process Enter semen, child born, stress Body want to sleep, but the\nmind can’t rest Measure pleasure through financial progress When it come to currency, love is nonexistent\nFoes multiply, friends become so distant Some hope you die, backstab in an instant Foes I\ndespise, disguised as allies to sabotage Camouflage, loyalty is lies To see God, look into my\nTo see The Devil, then you look into my eyes ‘Cause I’ma Slow it up, speed\nit up, slow it up, speed it up Metal Fingers feed beats, Grimm Reaper eat ‘em\nup Speed ‘em up, slow ‘em up, speed ‘em up, slow it up Brainsick, tick, tick,\nMF blow it up Slow it up, speed it up, slow it up, speed it up\nMetal Fingers feed beats, Grimm Reaper eat it up Speed it up, slow it up, speed"
    },
    {
     "text": "Playing slow, in fact playing so slow\nFaster than light speed, indeed\nNick Junior on mute, tough and bleed at night\nSkeed in the weed hours, deep study in the mix\nOpen up them doors, have em shittin bricks\nIn effect, the verse big box, little pricks\nPause again, fiddle sticks\nTeeny white pill within the skiddle mix\nVillain / Back in the days waitin to get a cake and the biscuit\nFound out a way to the wizard, makin it blizzard"
    }
   ]
  },
  {
   "plain": "The one thing that keeps me warm is the thought that I will look down upon the city. The city.",
   "tinted": "The only thing to keep me warm is the thought I'll be vacancy taking, looking down on the city while the masses are shaking and breaking.",
   "chunks": [
    {
     "text": "But going instinct happens twice when people mention me\nJealousy is tryina take me out but im steadily\nDodging mad agression like if peace was essentially\nEnough to piss the masses off and take it to the next degree\nHopefully they let the instrumental flow successfully\nSkills to demonstrate is what them peope contemplate\nLove or hate the flow thats late to pump up your heart rate\nCause skills to demonstrate is what them people contemplate\nLove or hate the flow thats late to pump up your heart rate\nAint tryina leave a legacy, im tryina take the vacancy"
    },
    {
     "text": "Act as if you believe / This will give the speaker courage to continue\nAnd betray whats up his sleeve\nIf you perceive he only halfway conceals\nExpress doubt. The man will reveal his reserve\nAnd let the truth out / 15\nCrush your enemy totally\nMush him like roadkill. He\nWont be able to heal and avenge the violated\nHell only stay silent if hes iron-plated annihilated\n16 / Absence makes the heart grow fonder"
    }
   ]
  }
 ],
 "bad": [
  {
   "plain": "Dirty River - Cancer by slowerpace 音楽 + Dirty River is coming into focus now. Listen for the shape of the arrangement as it opens, and let the record take the room from here.",
   "tinted": "THE DIAL (#941) — there is a deep shelf of finished audio standing behind this one, so this round can afford to be unhinged. Push it: take the odder angle, follow the tangent rather than the obvious line, let the caller be more specific and more peculiar about whatever they have fixed on, and let the material out of the documents come out further from where anyone would expect it. This is not permission to be random or to break character, and it is not permission to leave English — it is permission to be interesting.",
   "chunks": [
    {
     "text": "Eleven oclock, eleven oclock, Eleven oclock...\nI heard some woman on the radio\nSay the world gonna end and its subliminal\nEleven oclock, eleven oclock, Eleven oclock...\nI hate when she says nothings gonna be alright\nSit right here, dont leave, dont breathe for me\nIll be right back. Thats a lot to say, I think youre a liar\nFeeling really shitty, Im feeling really shot\nCant help but feel this impending doom\nLike theres a man right behind me lurking in the shadows"
    },
    {
     "text": "Keep the bong lightin straight through the song writin\nThe Supervillain AKA the thong bitin, thats inviting all\nTo the reciting thats dope and raw\nHoping all yall come in peace and its open bar\nTear the roof off this Bumba Ras Clot\nBy the end of the night spazz like Shazbot\nSpilt a shot made the pen lines runny\nAn ill plot thats ten times Ben Stein’s money, funny\nHow he rips the scripts with a straight face\nWith more rhymes than is lines in ya database"
    },
    {
     "text": "Theyve bit and dont know their own shine from Shinola\nEverything that glitter aint fishscale\nLemme think, dont let her faint get Ishmael\nA shot of Jack got her back its not an act stack\nForgot about the cackalack, holla back, clack clack blocka\nVillainy, feel him in your heart chakra chart toppa\nStart shit stoppa be a smart shoppa\nShot a cop day around the way bout to stay\nBut whod a know theres two mo that wonder where the shooter go\nBout to jet, get him, not a bet, dead em"
    }
   ]
  },
  {
   "plain": "Phone call Alright, let's hear what the caller has got for us tonight. I'm listening. You want me to read it back to you and then mock it gently? Fine, whatever mess you're trying to shove in here. Let's cut right to the record.",
   "tinted": "MF DOOM, and I am Mister Fantastik Expeditiously I be on my grizzly Feds try to creep me somehow always miss me Mister Fantastik put the busy in the bee Rock from the bottom straight to the tizzy Who is he?",
   "chunks": [
    {
     "text": "MF DOOM, and I am Mister Fantastik\nExpeditiously I be on my grizzly\nFeds try to creep me somehow always miss me\nMister Fantastik put the busy in the bee\nRock from the bottom straight to the tizzy\nWho is he? He need to get out more\nOr either get outta here like some dang outlaw\nStanding like Lurch, no herb in the record bin\nCalled him for a random search from curbside checkin in\nIts on nigga, on and cracking"
    },
    {
     "text": "Part of a new race / Chrome face 24/7 stay screw face\nPlay home base / Youll never come closer to where they want to be\nThe soldiers in the out field\nWith or with out a deal / Is it all about the steal\nYoull never come closer to where they want to be\nAsk yourself the same question\nDont mention it to him or any of his henchmen\nThis flows style in exceptionally\nIt grows wild and splits exponentially\nGo with the wind, nothing can help but me"
    },
    {
     "text": "Decided nuff said for head sweats\nX, this figure of speech\nfigure of speech / figure of speech\nRemain in a frenzy / Stay craze as I pause in ya Benzy\nThen reach in haste to taste\nA sip of this throttle in a bottle\nThen shake ya hip but dont slip into follow\nThe motto goes: sex, drugs and rock n roll\nI prefer: love, hugs and hip hop soul\nAnd thats final, down to the sto"
    }
   ]
  }
 ]
}


class TintRapTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "The station needs a copper plate before midnight."
    TINTED = ("Before midnight, the station needs that copper plate; "
              "operation meets calibration to settle the wait.")
    BAD = SOURCE + " That apparatus hums beside the tall window."
    CHUNKS = [{"text": "Operation, calibration, apparatus and constellation."}]

    def test_real_bars_pass_and_real_garbage_fails_at_full_strength(self):
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            for row in SAMPLES["good"]:
                report = app.tint_evaluate(row["plain"], row["tinted"],
                                           row["chunks"], force=0.88)
                self.assertTrue(report["ok"], (row["tinted"][:60], report["faults"]))
            for row in SAMPLES["bad"]:
                report = app.tint_evaluate(row["plain"], row["tinted"],
                                           row["chunks"], force=0.88)
                self.assertFalse(report["ok"], row["tinted"][:60])
                self.assertIn("semantic preservation failed", report["faults"])

    def test_pool_vocabulary_counts_as_lexicon(self):
        with mock.patch.object(app, "_CRYSTAL_POOL",
                               {"at": 5.0, "rows": [{"text": "operation calibration"}]}):
            app._CRYSTAL_VOCAB.update({"at": -1.0, "words": frozenset()})
            self.assertIn("calibration", app._crystal_vocab())
            report = app.tint_evaluate(self.SOURCE, self.TINTED, [], force=1.0)
        self.assertTrue(report["transformation"]["crystal_lexicon"])

    def tint_patches(self, hold, results):
        return (
            mock.patch.object(app, "crystal_active", return_value=[{"name": "test"}]),
            mock.patch.object(app, "crystal_stanzas", return_value=self.CHUNKS),
            mock.patch.object(app, "crystal_world_prompt", return_value="test"),
            mock.patch.object(app, "crystal_coverage_target", return_value=100),
            mock.patch.object(app, "crystal_force", return_value=1.0),
            mock.patch.object(app, "crystal_tint_holds", return_value=hold),
            mock.patch.object(app, "tint_should_stop", return_value=""),
            mock.patch.object(app, "task_cost", return_value=0.1),
            mock.patch.object(app, "task_note"),
            mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "_tint_flow"),
            mock.patch.object(app, "tint_spend_note"),
            mock.patch.object(app, "trail_note"),
            mock.patch.object(app, "chunk_answer"),
            mock.patch.object(app, "_crystal_vocab", return_value=frozenset()),
            mock.patch.object(app, "crystal_turn", side_effect=results),
        )

    async def test_a_refused_line_is_retried_once_then_the_pass_carries_on(self):
        units = [("A", self.SOURCE), ("B", self.SOURCE), ("A", self.SOURCE)]
        source = "\n".join(f"{m}: {t}" for m, t in units)
        patches = self.tint_patches(False, [self.TINTED, self.BAD, self.BAD, self.TINTED])
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(app, "banter_turns", return_value=units))
            for patch in patches:
                stack.enter_context(patch)
            report = await app.crystal_tint(source, "banter", [], critical=True)
        self.assertTrue(report["ok"], report.get("why"))
        self.assertEqual(report["coverage"]["attempted"], 3)
        self.assertEqual(report["coverage"]["changed"], 2)
        self.assertFalse(report["coverage"]["met"])
        self.assertIn("refused lines air as written", report["why"])
        lines = report["script"].split("\n")
        self.assertEqual(lines[0], "A: " + self.TINTED)
        self.assertEqual(lines[1], "B: " + self.SOURCE)
        self.assertEqual(lines[2], "A: " + self.TINTED)
        self.assertEqual(len(report["approved_lines"]), 2)

    async def test_the_hold_cuts_the_refused_line_before_the_studio(self):
        units = [("A", self.SOURCE), ("B", self.SOURCE), ("A", self.SOURCE)]
        source = "\n".join(f"{m}: {t}" for m, t in units)
        # under the hold a line is asked three times, then cut; the bars air
        patches = self.tint_patches(True, [self.TINTED, self.BAD, self.BAD, self.BAD, self.TINTED])
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(app, "banter_turns", return_value=units))
            for patch in patches:
                stack.enter_context(patch)
            report = await app.crystal_tint(source, "banter", [], critical=True)
        self.assertTrue(report["ok"], report.get("why"))
        self.assertEqual(report["coverage"]["cut"], 1)
        self.assertEqual(report["script"].split("\n"),
                         ["A: " + self.TINTED, "A: " + self.TINTED])

    async def test_the_heat_clause_never_rides_a_tint_prompt(self):
        seen = []

        async def fake_call(**kwargs):
            seen.append(kwargs["messages"][0]["content"])
            return {"message": {"content": "a bar"}}

        with (mock.patch.object(app, "call_ollama", side_effect=fake_call),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "heat_clause", return_value="\n\nTHE DIAL (#941) burn"),
              mock.patch.dict(app._ROUND_MARK, {app._mark_key(): {"heat": 0.9}})):
            await app.ask_model("rewrite this", mark={"kind": "tint turn"})
            await app.ask_model("write a call", mark={"kind": "caller"})
        self.assertEqual(len(seen), 2)
        self.assertNotIn("THE DIAL", seen[0])
        self.assertIn("THE DIAL", seen[1])


if __name__ == "__main__":
    unittest.main()
