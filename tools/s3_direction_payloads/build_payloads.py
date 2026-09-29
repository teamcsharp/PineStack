#!/usr/bin/env python3
"""[s3-direction] Build the table payloads from the LIVE config (read-only copy):

  ES1.before.json   the live ES1, as it is (the rollback: PUT it back)
  ES1.after.json    ES1 v3: every category and item gets `acting` (act, blurts,
                    says, wants); every item's text is its over-the-top direction;
                    every voice block's distance from neutral x VOICE_GAIN, inside
                    ES_VOICE_BOUNDS. Ids, labels, weights, badges, dims, arousal,
                    valence, modifiers, after_lean unchanged -> the draws are the same.

    python3 build_payloads.py live_config.json outdir/
"""
import copy
import json
import sys
from pathlib import Path

VOICE_GAIN = 1.4
BOUNDS = {"tempo": (0.85, 1.15), "pitch": (-2.0, 2.0), "range": (0.6, 1.5),
          "energy": (-0.8, 0.8), "pause": (0.7, 1.5), "temp": (-0.1, 0.1)}
NEUTRAL = {"tempo": 1.0, "pitch": 0.0, "range": 1.0, "energy": 0.0, "pause": 1.0, "temp": 0.0}
LEAD = "{name} processes this as {feeling}: "

# category -> acting. `act` is written for a WRITER (words, punctuation, shape):
# the voice's pitch and pace are the render's job (the `voice` block).
CAT = {
    "surprise": {
        "act": "REACT out loud - it hits them mid-breath: a blurted exclamation first, then quick short "
               "fragments, questions stacked on questions, the news-word hit in CAPS",
        "blurts": ["Wait, WHAT?", "No way!", "Hold on, hold on!", "You're kidding me!"],
        "says": ["seriously", "since when", "hold on", "no way", "are you telling me"],
        "wants": "to hear it again and drag the whole story out of them, right now"},
    "anger": {
        "act": "BLOW UP at them - hot, short, slammed sentences, the offending word thrown back in CAPS, "
               "at least one '!', swearing at the situation is fine, and never cooling down inside the line",
        "blurts": ["Oh, come ON!", "Are you KIDDING me?!", "No. No, no, no!", "Enough!"],
        "says": ["ridiculous", "unbelievable", "garbage", "how dare", "I am done"],
        "wants": "to make them back down and admit they are wrong, on air, right now"},
    "fear": {
        "act": "PANIC ON THE PAGE - breathless fragments, questions tumbling out, '?!' together, the scary "
               "word said twice, begging somebody to do something",
        "blurts": ["Oh no. Oh no, no, no!", "Wait, wait, WAIT!", "Are you hearing this?!"],
        "says": ["what if", "we have to", "this is bad", "right now", "I am not okay"],
        "wants": "for somebody to take this seriously and fix it before it is too late"},
    "sadness": {
        "act": "BREAK DOWN - openly heartbroken: short trembling fragments, a sentence that trails off and "
               "starts again, the sad word said twice, nothing hidden",
        "blurts": ["Oh, man...", "That just... that kills me.", "No... no."],
        "says": ["it hurts", "I can't", "gone", "for nothing", "why"],
        "wants": "comfort - for somebody to tell them it was not all for nothing"},
    "joy": {
        "act": "CELEBRATE - bursting with it: stacked exclamations, gushing superlatives, laughing words, one "
               "word in CAPS, talking over themselves with glee",
        "blurts": ["YES!", "Oh, I LOVE this!", "Are you kidding? That's amazing!"],
        "says": ["amazing", "the best thing", "love it", "incredible", "come on!"],
        "wants": "everybody in the room as thrilled as they are"},
    "disgust": {
        "act": "RECOIL - grossed out and loud about it: 'that is DISGUSTING', graphic words for the gross "
               "part, refusing to go anywhere near it",
        "blurts": ["Oh, that's DISGUSTING!", "Ew, no. Absolutely not.", "Why would you SAY that?!"],
        "says": ["gross", "vile", "nasty", "revolting", "sick"],
        "wants": "for them to stop talking about it this second"},
    "interest": {
        "act": "INTERROGATE - leaning right in: rapid pointed questions, 'wait, go back', the key word "
               "repeated in CAPS, not letting it drop",
        "blurts": ["Wait, go back!", "Hold on, say that again!", "Okay, now I'm interested!"],
        "says": ["how exactly", "why", "prove it", "walk me through it", "and then what"],
        "wants": "to get the one detail they are hiding"},
    "social": {
        "act": "SQUIRM - painfully self-conscious and loud about it: 'oh God, okay', a stammered restart, "
               "over-explaining, laughing at themselves, one word in CAPS",
        "blurts": ["Oh God. Okay.", "Well, THIS is awkward!", "Can we not? Please?"],
        "says": ["I mean", "look", "honestly", "it's not what it sounds like"],
        "wants": "to get out of the spotlight without losing face"},
    "low_arousal": {
        "act": "CHECK OUT, theatrically - an enormous verbal shrug: deadpan, one-word answers, 'whatever', "
               "dripping with not caring so everybody notices",
        "blurts": ["Whatever.", "Cool. Great. Anyway.", "Wake me up when it's over."],
        "says": ["whatever", "sure", "fine", "who cares", "riveting"],
        "wants": "to make it painfully obvious they could not care less"},
}

# item label -> its own acting keys (over the category's)
ITEM = {
    # surprise
    "shock": {"act": "REEL - stopped dead: 'What?!' first, a broken restart, the key word repeated in CAPS",
              "blurts": ["WHAT?!", "Excuse me?!", "Say that again!"]},
    "astonishment": {"blurts": ["Oh my God!", "Are you serious?!", "Unbelievable!"],
                     "says": ["incredible", "unreal", "insane", "never in my life"]},
    "amazement": {"blurts": ["Oh my God!", "That's INSANE!", "Get out of here!"],
                  "says": ["incredible", "unreal", "insane", "never in my life"]},
    "disbelief": {"act": "REFUSE TO BUY IT - scoffing, their claim repeated back as a mocking question, "
                         "'come ON' energy",
                  "blurts": ["Oh, come ON.", "You cannot be serious!", "Get out of here!"],
                  "wants": "to make them admit they made it up"},
    "bewilderment": {"act": "FLOUNDER - lost and loud about it: half-sentences that restart, questions that go "
                            "nowhere, 'what does that even MEAN'",
                     "blurts": ["I'm sorry, what?", "Hang on, I'm lost!", "What does that even MEAN?"],
                     "wants": "for somebody, anybody, to make it make sense"},
    "confusion": {"act": "FLOUNDER - lost and loud about it: half-sentences that restart, questions that go "
                         "nowhere, 'what does that even MEAN'",
                  "blurts": ["I'm sorry, what?", "Hang on, I'm lost!", "What does that even MEAN?"],
                  "wants": "for somebody, anybody, to make it make sense"},
    "curiosity": {"act": "LEAN IN - hungry: rapid-fire questions, 'tell me more' energy, one word in CAPS",
                  "blurts": ["Oh, wait!", "Hold on, tell me more!", "Okay, now I NEED to know!"],
                  "wants": "to pry the juicy detail out of them"},
    "intrigue": {"act": "LEAN IN - hungry: rapid-fire questions, 'tell me more' energy, one word in CAPS",
                 "blurts": ["Oh, wait!", "Hold on, tell me more!", "Okay, now I NEED to know!"],
                 "wants": "to pry the juicy detail out of them"},
    # anger
    "annoyance": {"act": "SNAP - clipped, testy, exasperated: one sharp jab and an eye-roll you can hear",
                  "blurts": ["Oh, for crying out loud!", "Seriously?!", "Here we go again!"],
                  "wants": "to shut this down so it stops getting on their nerves"},
    "irritation": {"act": "SNAP - clipped, testy, exasperated: one sharp jab and an eye-roll you can hear",
                   "blurts": ["Oh, for crying out loud!", "Seriously?!", "Here we go again!"],
                   "wants": "to shut this down so it stops getting on their nerves"},
    "frustration": {"act": "VENT - exasperated: the same point hammered twice, 'how many TIMES' energy",
                    "blurts": ["How many TIMES?!", "I swear to God!", "Unbelievable!"]},
    "indignation": {"act": "TAKE OFFENCE - personally insulted: 'excuse me?!', demanding respect",
                    "blurts": ["Excuse me?!", "How DARE you!", "Oh, I don't think so!"],
                    "wants": "an apology, out loud, on air"},
    "outrage": {"act": "EXPLODE - full-volume rage on the page: short slammed sentences, CAPS on the worst "
                       "word, several '!', swearing at the situation, the offending word thrown back at them",
                "blurts": ["Are you out of your MIND?!", "Oh, HELL no!", "That is it, I'm DONE!"],
                "says": ["disgrace", "insane", "outrageous", "unacceptable"],
                "wants": "to put them in their place so hard the room goes quiet"},
    "fury": {"act": "EXPLODE - full-volume rage on the page: short slammed sentences, CAPS on the worst word, "
                    "several '!', swearing at the situation, the offending word thrown back at them",
             "blurts": ["Are you out of your MIND?!", "Oh, HELL no!", "That is it, I'm DONE!"],
             "says": ["disgrace", "insane", "outrageous", "unacceptable"],
             "wants": "to put them in their place so hard the room goes quiet"},
    "resentment": {"act": "SEETHE - bitter and needling: every word a dig, old grievances dragged back in",
                   "blurts": ["Oh, sure. Of COURSE.", "Typical!", "Here it comes!"],
                   "wants": "to make them feel every slight they have ever dealt out"},
    "contempt": {"act": "SNEER - icy superiority: cutting sarcasm, a mock-polite 'oh, how cute' before the knife",
                 "blurts": ["Oh, how adorable.", "Wow. Just wow.", "Please."],
                 "wants": "to make them feel small"},
    # fear
    "unease": {"act": "SWEAT IT - nervous and jittery: second-guessing out loud, 'okay, but what if', a nervous "
                      "laugh in the words",
               "blurts": ["Okay, that's... that's not great.", "Guys? Guys.", "I do NOT like this."],
               "wants": "to be told it is going to be fine"},
    "apprehension": {"act": "SWEAT IT - nervous and jittery: second-guessing out loud, 'okay, but what if', a "
                            "nervous laugh in the words",
                     "blurts": ["Okay, that's... that's not great.", "Guys? Guys.", "I do NOT like this."],
                     "wants": "to be told it is going to be fine"},
    "anxiety": {"act": "SWEAT IT - nervous and jittery: second-guessing out loud, 'okay, but what if', a nervous "
                       "laugh in the words",
                "blurts": ["Okay, that's... that's not great.", "Guys? Guys.", "I do NOT like this."],
                "wants": "to be told it is going to be fine"},
    "dread": {"act": "DOOM - grim, heavy certainty it is all about to go wrong, 'this is how it ends' energy",
              "blurts": ["Oh, this is bad.", "We're finished.", "I KNEW it."]},
    "panic": {"act": "RAISE THE ALARM - screaming on the page: rapid broken fragments, CAPS, '!' after every "
                     "bit, begging for action",
              "blurts": ["Oh my GOD!", "Somebody DO something!", "No, no, NO!"]},
    "alarm": {"act": "RAISE THE ALARM - screaming on the page: rapid broken fragments, CAPS, '!' after every "
                     "bit, begging for action",
              "blurts": ["Oh my GOD!", "Somebody DO something!", "No, no, NO!"]},
    "horror": {"act": "RECOIL IN HORROR - appalled and scared at once: 'that is the worst thing I have ever "
                      "heard', graphic words",
               "blurts": ["Oh God, NO!", "That's horrifying!", "Stop, stop, STOP!"]},
    # sadness
    "disappointment": {"act": "DEFLATE - the air goes right out of them: 'wow... okay', letdown words, a bitter "
                              "little laugh",
                       "blurts": ["Wow. Okay.", "Great. Just great.", "I really thought..."]},
    "discouragement": {"act": "DEFLATE - the air goes right out of them: 'wow... okay', letdown words, a bitter "
                              "little laugh",
                       "blurts": ["Wow. Okay.", "Great. Just great.", "I really thought..."]},
    "grief": {"act": "GRIEVE OUT LOUD - raw and halting: the loss named plainly, the words breaking",
              "blurts": ["I can't... I can't do this.", "Oh God.", "It's gone. It's just gone."]},
    "despair": {"act": "PLEAD WITH THE UNIVERSE - hopeless: 'what is the POINT', the same question asked twice, "
                       "reaching for anybody",
                "blurts": ["What's the POINT?", "Why does this keep happening?!", "I give up!"]},
    "melancholy": {"act": "ACHE - wistful, a long look back, 'remember when' words, a sigh in the sentence",
                   "blurts": ["Remember when...", "God, I miss that.", "It was never going to last."]},
    "sympathy": {"act": "POUR IT OUT - gushing sympathy: 'oh, you poor thing', over-the-top tenderness",
                 "blurts": ["Oh, you poor thing!", "Oh no, honey.", "That's awful, I'm so sorry!"],
                 "wants": "to wrap them up and make it better"},
    "pity": {"act": "POUR IT OUT - gushing, slightly condescending pity: 'oh, bless your heart'",
             "blurts": ["Oh, bless your heart.", "Oh, you poor, poor thing.", "Aw, sweetie. No."],
             "wants": "to make it very clear how sorry they feel for them"},
    # joy
    "pleasure": {"act": "SAVOUR IT SHAMELESSLY - luxurious, smug contentment: 'oh, that's the stuff'",
                 "blurts": ["Oh, that is BEAUTIFUL.", "Now THAT's what I'm talking about.", "Oh, yes."]},
    "satisfaction": {"act": "SAVOUR IT SHAMELESSLY - luxurious, smug contentment: 'oh, that's the stuff'",
                     "blurts": ["Oh, that is BEAUTIFUL.", "Now THAT's what I'm talking about.", "Oh, yes."]},
    "delight": {"act": "GO NUTS - over the moon: stacked exclamations, 'oh my God, oh my God', CAPS, rushing ahead",
                "blurts": ["Oh my God, YES!", "No WAY! That's incredible!", "I can't even!"]},
    "excitement": {"act": "GO NUTS - over the moon: stacked exclamations, 'oh my God, oh my God', CAPS, rushing "
                          "ahead",
                   "blurts": ["Oh my God, YES!", "No WAY! That's incredible!", "I can't even!"]},
    "enthusiasm": {"act": "GO NUTS - over the moon: stacked exclamations, CAPS, rushing ahead, selling it hard",
                   "blurts": ["Oh, I am SO in!", "Let's GO!", "That's the best idea I've ever heard!"]},
    "amusement": {"act": "CRACK UP - laughing through the line: the funny bit repeated back, can barely get the "
                         "words out",
                  "blurts": ["Oh, that's HILARIOUS!", "Stop, I can't breathe!", "No, you did NOT!"]},
    "relief": {"act": "SAG WITH RELIEF - a huge exhale on the page: 'oh, thank God', gushing gratitude",
               "blurts": ["Oh, thank GOD!", "Oh, finally!", "Oh, what a relief!"]},
    # disgust
    "distaste": {"act": "WRINKLE THE NOSE - snooty and dismissive, 'no thank you' disdain",
                 "blurts": ["No thank you.", "Hard pass!", "Oh, please."]},
    "aversion": {"act": "WRINKLE THE NOSE - snooty and dismissive, 'no thank you' disdain",
                 "blurts": ["No thank you.", "Hard pass!", "Oh, please."]},
    "moral disgust": {"act": "CONDEMN - righteous and appalled: 'that is WRONG', preaching at them",
                      "blurts": ["That is just WRONG!", "Shame on you!", "Have you no decency?!"],
                      "wants": "to make them ashamed of themselves"},
    # interest
    "skepticism": {"act": "SMELL A RAT - narrow-eyed: 'oh, sure, SURE', poking holes, their claim repeated back "
                          "as a mocking question",
                   "blurts": ["Oh, sure. SURE.", "Oh, REALLY?", "Nice story. Now tell the true one."],
                   "wants": "to catch them in the lie"},
    "suspicion": {"act": "SMELL A RAT - narrow-eyed: 'oh, sure, SURE', poking holes, their claim repeated back as "
                         "a mocking question",
                  "blurts": ["Oh, sure. SURE.", "Oh, REALLY?", "Nice story. Now tell the true one."],
                  "wants": "to catch them in the lie"},
    "uncertainty": {"act": "WAFFLE DRAMATICALLY - torn in two: 'I mean... but then again', flip-flopping mid-line",
                    "blurts": ["I mean... I don't know!", "Okay, but then again...", "Wait, no, maybe?"]},
    "fascination": {"act": "GEEK OUT - enthralled, gushing about the detail: 'that is SO cool'",
                    "blurts": ["Oh, that is SO cool!", "Wait, that's fascinating!", "Tell me EVERYTHING."]},
    # social
    "embarrassment": {"act": "SQUIRM - mortified: stammered restarts ('I- I mean'), over-explaining, begging "
                             "them to drop it",
                      "blurts": ["Oh no. Oh, no, no.", "Okay, can we NOT?", "I want to crawl under the desk!"]},
    "awkwardness": {"act": "SQUIRM - mortified: stammered restarts ('I- I mean'), over-explaining, begging them "
                           "to drop it",
                    "blurts": ["Oh no. Oh, no, no.", "Okay, can we NOT?", "Well, THIS is awkward!"]},
    "shame": {"act": "SQUIRM - mortified: stammered restarts ('I- I mean'), over-explaining, begging them to drop it",
              "blurts": ["Oh no. Oh, no, no.", "Okay, can we NOT?", "I want to crawl under the desk!"]},
    "guilt": {"act": "CONFESS - guilt pouring out: 'okay, FINE, it was me', over-apologising",
              "blurts": ["Okay, FINE, it was me!", "I'm sorry, okay?!", "I know, I KNOW!"],
              "wants": "to be forgiven before anybody else finds out"},
    "pride": {"act": "BRAG - chest puffed out: 'that's RIGHT', taking all the credit, a victory lap in words",
              "blurts": ["That's RIGHT!", "You're welcome!", "Who called it? ME."],
              "wants": "for everybody to admit how brilliant they are"},
    "admiration": {"act": "GUSH - starstruck: over-the-top praise, superlatives, 'you're a GENIUS'",
                   "blurts": ["You are a GENIUS!", "Oh, that's brilliant!", "I bow down!"],
                   "wants": "for the other one to know they are in awe"},
    "envy": {"act": "GREEN WITH IT - bitter and petty: 'must be NICE', backhanded compliments",
             "blurts": ["Oh, must be NICE!", "Well, la-di-da!", "Good for YOU."],
             "wants": "to knock them down a peg"},
    "jealousy": {"act": "GREEN WITH IT - bitter and petty: 'must be NICE', backhanded compliments",
                 "blurts": ["Oh, must be NICE!", "Well, la-di-da!", "Good for YOU."],
                 "wants": "to knock them down a peg"},
    "defensiveness": {"act": "BRISTLE - hackles up: 'whoa, whoa, hold on', denying hard, turning it back on them",
                      "blurts": ["Whoa, whoa, WHOA!", "Excuse me?!", "Don't you put that on me!"],
                      "wants": "to win the point back"},
    # low arousal
    "calm": {"act": "BE THE ZEN MASTER - absurdly, smugly serene: slow soothing words that clearly wind the "
                    "others up",
             "blurts": ["Everybody breathe.", "It's fine. It's ALL fine.", "Let it go, man."],
             "wants": "to be the calmest person in the room and make sure everybody notices"},
    "acceptance": {"act": "BE THE ZEN MASTER - absurdly, smugly serene: slow soothing words that clearly wind "
                          "the others up",
                   "blurts": ["It is what it is.", "It's fine. It's ALL fine.", "Let it go, man."],
                   "wants": "to be the calmest person in the room and make sure everybody notices"},
    "exhaustion": {"act": "COLLAPSE - wrung out: 'I can't. I just can't.', giving up on the argument out loud",
                   "blurts": ["I can't. I just can't.", "Fine. You win.", "I'm too tired for this."]},
    "resignation": {"act": "COLLAPSE - wrung out: 'fine, whatever, you win', giving up on the argument out loud",
                    "blurts": ["Fine. You win.", "Sure. Why not.", "I'm too tired for this."]},
    "boredom": {"act": "YAWN AT THEM - exaggerated boredom: 'are we done?', 'riveting', sarcasm dripping",
                "blurts": ["Riveting.", "Are we done yet?", "Wow. Thrilling stuff."]},
}


ITEM_SAYS = {'envy': ['must be nice', 'lucky you', 'good for you', 'la-di-da'], 'jealousy': ['must be nice', 'lucky you', 'good for you', 'la-di-da'], 'pride': ["that's right", 'nailed it', "you're welcome", 'called it'], 'admiration': ['genius', 'brilliant', 'legend', 'I bow down'], 'guilt': ['my fault', "I'm sorry", 'I know, I know', 'okay, fine'], 'defensiveness': ['hold on', "that's not fair", "don't you dare", 'I never said that'], 'calm': ['breathe', "it's all good", 'let it go', 'relax'], 'acceptance': ['it is what it is', "it's all good", 'let it go', 'relax'], 'exhaustion': ["I can't", 'fine', 'whatever you say', "I'm done"], 'resignation': ['fine', 'whatever you say', 'you win', "I'm done"], 'boredom': ['riveting', 'thrilling', 'wake me', 'are we done'], 'sympathy': ['poor thing', 'oh, honey', "I'm so sorry", "that's awful"], 'pity': ['poor thing', 'bless your heart', 'oh, sweetie', 'how sad'], 'amusement': ['hilarious', "I'm dying", 'stop it', 'oh my God'], 'relief': ['thank God', 'finally', 'what a relief', 'phew, okay'], 'pleasure': ['beautiful', "that's the stuff", 'perfect', 'oh, yes'], 'satisfaction': ['beautiful', "that's the stuff", 'perfect', 'nailed it'], 'disappointment': ['great, just great', 'figures', 'of course', 'I really thought'], 'discouragement': ['great, just great', 'figures', "what's the use", 'I really thought'], 'curiosity': ['tell me more', 'wait, what', 'how', 'and then what'], 'intrigue': ['tell me more', 'wait, what', 'how', 'and then what'], 'uncertainty': ['I mean', 'maybe', 'then again', "I don't know"], 'contempt': ['how cute', 'adorable', 'please', 'bless'], 'resentment': ['typical', 'of course', 'as usual', 'again'], 'annoyance': ['seriously', 'for crying out loud', 'again', 'enough'], 'irritation': ['seriously', 'for crying out loud', 'again', 'enough'], 'distaste': ['no thank you', 'hard pass', 'please', 'not for me'], 'aversion': ['no thank you', 'hard pass', 'please', 'not for me'], 'moral disgust': ['wrong', 'shameful', 'disgrace', 'decency'], 'dread': ['doomed', 'this is it', 'I knew it', "we're finished"], 'unease': ['what if', "I don't like this", 'okay, but', 'guys'], 'apprehension': ['what if', "I don't like this", 'okay, but', 'guys'], 'anxiety': ['what if', "I don't like this", 'okay, but', 'guys'], 'melancholy': ['remember when', 'back then', 'I miss it', 'gone'], 'grief': ['gone', "I can't", 'it hurts', 'never again'], 'despair': ["what's the point", 'why', 'I give up', 'nothing works']}
for _k, _v in ITEM_SAYS.items():
    ITEM.setdefault(_k, {})["says"] = list(_v)


def louder(block):
    """A voice block's distance from neutral x VOICE_GAIN, inside the bounds."""
    out = {}
    for k, v in (block or {}).items():
        if k not in NEUTRAL:
            continue
        n = NEUTRAL[k]
        lo, hi = BOUNDS[k]
        out[k] = round(min(hi, max(lo, n + (float(v) - n) * VOICE_GAIN)), 3)
    return out


def es_v3(es):
    t = copy.deepcopy(es)
    t["description"] = ("The emotion each turn is spoken in: guides the wording (DIRECTION FOR THIS LINE: "
                        "act, first words, lexicon, what they want) and the voice. v3: played over the top.")
    for cat in t["categories"]:
        cid = cat["id"]
        base = CAT[cid]
        cat["acting"] = copy.deepcopy(base)
        if isinstance(cat.get("voice"), dict):
            cat["voice"] = louder(cat["voice"])
        for item in cat["items"]:
            own = ITEM.get(item["label"], {})
            if own:
                item["acting"] = copy.deepcopy(own)
            act = own.get("act") or base["act"]
            item["text"] = LEAD + act + "."
            assert len(item["text"]) <= 380, item["id"]
            if isinstance(item.get("voice"), dict):
                item["voice"] = louder(item["voice"])
    return t


def main(argv):
    live = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out = Path(argv[1])
    es = next(t for t in live["tables"] if t["id"] == "ES1")
    (out / "ES1.before.json").write_text(json.dumps(es, indent=1, ensure_ascii=False), encoding="utf-8")
    after = es_v3(es)
    missing = [i["label"] for c in after["categories"] for i in c["items"] if i["label"] not in ITEM]
    (out / "ES1.after.json").write_text(json.dumps(after, indent=1, ensure_ascii=False), encoding="utf-8")
    print("items without their own acting (category acting):", missing)


if __name__ == "__main__":
    main(sys.argv[1:])
