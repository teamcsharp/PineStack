"""System Three caller diversity: equal intent wheels and bounded repair draws.

The engine owns every draw and receipt. New option text remains an operator
proposal until confirmed; no model-generated cue silently becomes eligible.
"""
from __future__ import annotations
import copy
import math
import re

INTENT_FAMILIES = ("CALLOPEN", "CALLANGLE", "CALLSTAKES", "CALLPROBE")
FAMILIES = INTENT_FAMILIES + ("CALLSOURCE", "RW")
EXPANDABLE_FAMILIES = INTENT_FAMILIES + ("RW",)
TABLES = [{'id': 'CALLOPEN1',
  'family': 'CALLOPEN',
  'label': 'Opening intent',
  'version': 1,
  'enabled': True,
  'weight': 1.0,
  'roads': ['caller'],
  'equal_outcomes': True,
  'description': 'Equally likely conversational intents. Perform the action in original words; random '
                 'emotions may agree with it or oppose it.',
  'categories': [{'id': 'actions',
                  'weight': 1.0,
                  'items': [{'id': 'plain',
                             'label': 'plain',
                             'weight': 1.0,
                             'text': 'Answer the ringing line plainly and invite the stranger to speak.'},
                            {'id': 'attentive',
                             'label': 'attentive',
                             'weight': 1.0,
                             'text': 'Make space for the caller with a brief attentive invitation.'},
                            {'id': 'curious',
                             'label': 'curious',
                             'weight': 1.0,
                             'text': 'Answer with a short curious invitation to hear why they rang.'},
                            {'id': 'brisk',
                             'label': 'brisk',
                             'weight': 1.0,
                             'text': 'Pick up briskly and hand the floor to the caller.'},
                            {'id': 'warm',
                             'label': 'warm',
                             'weight': 1.0,
                             'text': 'Welcome an unknown caller warmly and invite their introduction.'},
                            {'id': 'dry',
                             'label': 'dry',
                             'weight': 1.0,
                             'text': 'Answer with dry humor about the pickup itself, then invite the '
                                     'caller.'},
                            {'id': 'tentative',
                             'label': 'tentative',
                             'weight': 1.0,
                             'text': 'Check that the caller can hear the booth and invite them to speak.'},
                            {'id': 'direct',
                             'label': 'direct',
                             'weight': 1.0,
                             'text': 'Acknowledge the incoming call and give the caller the floor '
                                     'directly.'}]}],
  'status': 'operator-approved initial wheel, 2026-10-02',
  'provenance': {'by': 'operator-approved caller diversity package', 'date': '2026-10-02'}},
 {'id': 'CALLANGLE1',
  'family': 'CALLANGLE',
  'label': 'Premise angle',
  'version': 1,
  'enabled': True,
  'weight': 1.0,
  'roads': ['caller'],
  'equal_outcomes': True,
  'description': 'Equally likely conversational intents. Perform the action in original words; random '
                 'emotions may agree with it or oppose it.',
  'categories': [{'id': 'actions',
                  'weight': 1.0,
                  'items': [{'id': 'practical',
                             'label': 'practical',
                             'weight': 1.0,
                             'text': 'Explore what the caller can do next about the established subject.'},
                            {'id': 'interpretation',
                             'label': 'interpretation',
                             'weight': 1.0,
                             'text': 'Explore two interpretations of the established facts without asserting '
                                     'either as new fact.'},
                            {'id': 'expectation',
                             'label': 'expectation',
                             'weight': 1.0,
                             'text': 'Contrast what the caller expected with what their source says '
                                     'happened.'},
                            {'id': 'priority',
                             'label': 'priority',
                             'weight': 1.0,
                             'text': 'Ask which part of the established subject matters most to the caller.'},
                            {'id': 'responsibility',
                             'label': 'responsibility',
                             'weight': 1.0,
                             'text': 'Discuss who can reasonably act, without inventing blame.'},
                            {'id': 'consequence',
                             'label': 'consequence',
                             'weight': 1.0,
                             'text': 'Discuss a consequence already established, or ask about a possible '
                                     'consequence.'},
                            {'id': 'misunderstanding',
                             'label': 'misunderstanding',
                             'weight': 1.0,
                             'text': 'Test whether the known disagreement turns on a misunderstanding.'},
                            {'id': 'boundary',
                             'label': 'boundary',
                             'weight': 1.0,
                             'text': "Explore the caller's stated boundary or ask them to identify it."},
                            {'id': 'tradeoff',
                             'label': 'tradeoff',
                             'weight': 1.0,
                             'text': 'Ask the caller which tradeoff they are willing to make.'},
                            {'id': 'uncertainty',
                             'label': 'uncertainty',
                             'weight': 1.0,
                             'text': 'Identify what remains unknown and why the caller wants an answer.'}]}],
  'status': 'operator-approved initial wheel, 2026-10-02',
  'provenance': {'by': 'operator-approved caller diversity package', 'date': '2026-10-02'}},
 {'id': 'CALLSTAKES1',
  'family': 'CALLSTAKES',
  'label': 'Stakes lens',
  'version': 1,
  'enabled': True,
  'weight': 1.0,
  'roads': ['caller'],
  'equal_outcomes': True,
  'description': 'Equally likely conversational intents. Perform the action in original words; random '
                 'emotions may agree with it or oppose it.',
  'categories': [{'id': 'actions',
                  'weight': 1.0,
                  'items': [{'id': 'time',
                             'label': 'time',
                             'weight': 1.0,
                             'text': 'Ask what time or delay is at stake for the caller.'},
                            {'id': 'money',
                             'label': 'money',
                             'weight': 1.0,
                             'text': 'Ask whether a financial cost matters; do not invent an amount.'},
                            {'id': 'trust',
                             'label': 'trust',
                             'weight': 1.0,
                             'text': 'Explore trust if established, otherwise ask whether it is part of the '
                                     'concern.'},
                            {'id': 'comfort',
                             'label': 'comfort',
                             'weight': 1.0,
                             'text': "Ask how this affects the caller's comfort or daily routine."},
                            {'id': 'pride',
                             'label': 'pride',
                             'weight': 1.0,
                             'text': 'Ask whether pride or embarrassment is involved rather than declaring '
                                     'it.'},
                            {'id': 'relationship',
                             'label': 'relationship',
                             'weight': 1.0,
                             'text': 'Ask whether the established issue affects a relationship.'},
                            {'id': 'fairness',
                             'label': 'fairness',
                             'weight': 1.0,
                             'text': 'Explore whether the caller sees the established issue as fair.'},
                            {'id': 'control',
                             'label': 'control',
                             'weight': 1.0,
                             'text': 'Ask what part of this the caller thinks they can control.'}]}],
  'status': 'operator-approved initial wheel, 2026-10-02',
  'provenance': {'by': 'operator-approved caller diversity package', 'date': '2026-10-02'}},
 {'id': 'CALLPROBE1',
  'family': 'CALLPROBE',
  'label': 'Follow-up action',
  'version': 1,
  'enabled': True,
  'weight': 1.0,
  'roads': ['caller'],
  'equal_outcomes': True,
  'description': 'Equally likely conversational intents. Perform the action in original words; random '
                 'emotions may agree with it or oppose it.',
  'categories': [{'id': 'actions',
                  'weight': 1.0,
                  'items': [{'id': 'sequence',
                             'label': 'sequence',
                             'weight': 1.0,
                             'text': 'Ask what happened next after a short concrete anchor from the prior '
                                     'answer.'},
                            {'id': 'difference',
                             'label': 'difference',
                             'weight': 1.0,
                             'text': 'Ask what changed, using one brief concrete anchor rather than '
                                     'repeating the prior sentence.'},
                            {'id': 'clarify',
                             'label': 'clarify',
                             'weight': 1.0,
                             'text': 'Ask the caller to clarify one concrete detail in fresh wording.'},
                            {'id': 'test',
                             'label': 'test',
                             'weight': 1.0,
                             'text': 'Test one interpretation of a concrete detail as a question.'},
                            {'id': 'priority',
                             'label': 'priority',
                             'weight': 1.0,
                             'text': 'Ask which of the concrete details matters most and why.'},
                            {'id': 'next_step',
                             'label': 'next step',
                             'weight': 1.0,
                             'text': 'Ask what the caller tried next about a concrete detail they supplied.'},
                            {'id': 'contrast',
                             'label': 'contrast',
                             'weight': 1.0,
                             'text': 'Ask how two established details differ.'},
                            {'id': 'implication',
                             'label': 'implication',
                             'weight': 1.0,
                             'text': 'Ask what a concrete detail implies for the caller, without supplying '
                                     'the answer.'}]}],
  'status': 'operator-approved initial wheel, 2026-10-02',
  'provenance': {'by': 'operator-approved caller diversity package', 'date': '2026-10-02'}},
 {'id': 'CALLSOURCE1',
  'label': 'Caller premise source',
  'status': 'operator-approved initial wheel, 2026-10-02',
  'node_scope': 'before selecting a new caller premise; retain the selected premise during the first '
                'diversity retry',
  'weight': 1.0,
  'categories': [{'id': 'sources',
                  'weight': 1.0,
                  'items': [{'id': 'speakerbox',
                             'label': 'Speakerbox',
                             'weight': 1.0,
                             'text': 'Roll an eligible document and passage; develop a new caller premise '
                                     'from it.'},
                            {'id': 'topics',
                             'label': 'Topic database',
                             'weight': 1.0,
                             'text': 'Roll an eligible topic from the full approved topic bank as the caller '
                                     'premise.'},
                            {'id': 'internet',
                             'label': 'Internet search',
                             'weight': 1.0,
                             'text': 'Roll an approved search theme/query and a fetched result; build the '
                                     'premise on the result with a source receipt.'},
                            {'id': 'station',
                             'label': 'Station context',
                             'weight': 1.0,
                             'text': 'Roll among eligible current station subjects, including heat, the '
                                     'gallery, manager messages and music.'}]}],
  'eligibility': 'Exclude only unavailable sources or an explicit operator theme requirement, with a visible '
                 'reason. A hot machine does not automatically make heat the premise.',
  'internet_contract': 'Queries and result selection are seeded System Three decisions. Save query, URL, '
                       'retrieval time and a bounded result excerpt. Do not claim a search succeeded if it '
                       'did not.',
  'family': 'CALLSOURCE',
  'enabled': True,
  'roads': ['caller'],
  'provenance': {'by': 'operator-approved caller diversity package', 'date': '2026-10-02'}}]


TABLES.append({"id":"RW1","family":"RW","label":"Rejected scenario rewrite pass",
    "enabled":True,"weight":1.0,"roads":[],"provenance":{"by":"operator request","date":"2026-10-02"},
    "categories":[{"id":"requests","label":"Rewrite requests","weight":1.0,"items":[
        {"id":"dramatic","label":"Dramatic","weight":1.0,"text":"Rewrite this to be dramatic."},
        {"id":"rap_battle","label":"Hip hop rap battle","weight":1.0,"text":"Rewrite this to be a hip hop rap battle."},
        {"id":"innuendo","label":"Innuendo and inappropriate jokes","weight":1.0,"text":"Rewrite this to be hilarious with innuendo and inappropriate jokes inserted."},
        {"id":"speakerbox_plot","label":"Speakerbox plot","weight":1.0,"text":"Rewrite this to be a plot of {speakerbox}."},
        {"id":"feature_pitch","label":"Occasional feature pitch","weight":1.0,"text":"Rewrite this to be a pitch occasionally for {feature}."},
        {"id":"station_threat","label":"Fictional station ultimatum","weight":1.0,"text":"Rewrite the script to have the person threaten to assault {station} or else {speakerbox}."}
    ]}]})


def default_tables():
    out = copy.deepcopy(TABLES)
    import gazette_review
    for table in out:
        if table.get("id") == "CALLSOURCE1":
            table["categories"][0]["items"].append(copy.deepcopy(gazette_review.GAZETTE_SOURCE))
    return out


def validate_table(table):
    """Strict bounds for generated option proposals, before they can be saved."""
    if table.get("family") not in FAMILIES:
        raise ValueError("not a caller diversity family")
    if len(table.get("categories") or []) > 16:
        raise ValueError("at most 16 diversity categories")
    seen = set()
    for obj in [table] + list(table.get("categories") or []):
        if not math.isfinite(float(obj.get("weight", 1))):
            raise ValueError("weights must be finite")
    for cat in table.get("categories") or []:
        if len(cat.get("items") or []) > 64:
            raise ValueError("at most 64 options per diversity category")
        for item in cat.get("items") or []:
            cue = str(item.get("text") or "").strip()
            key = " ".join(re.findall(r"[a-z0-9']+", cue.lower()))
            if not key or len(cue) > 600:
                raise ValueError("a diversity option needs an intent of 1-600 characters")
            if key in seen:
                raise ValueError("duplicate diversity intent")
            seen.add(key)
            if table["family"] == "CALLSOURCE" and item.get("id") not in ("speakerbox","topics","internet","station","gazette"):
                raise ValueError("unsupported caller source provider")
            if table["family"] == "RW" and any(token not in ("speakerbox","feature","station") for token in re.findall(r"\{([a-zA-Z0-9_]+)\}",cue)):
                raise ValueError("unsupported RW material placeholder")
            if not math.isfinite(float(item.get("weight", 1))):
                raise ValueError("option weight must be finite")
            item["weight"] = 1.0 if float(item.get("weight", 1)) > 0 else 0.0
        cat["weight"] = 1.0 if float(cat.get("weight", 1)) > 0 else 0.0
    table["weight"] = 1.0 if float(table.get("weight", 1)) > 0 else 0.0
    table["equal_outcomes"] = True
    return table


def draw(conv, config, family, *, revision=0, exclude=(), index=-1, unavailable=None):
    """Uniform across eligible intents, without emotion/state/recent multipliers."""
    import system3 as engine
    call = (conv.get("inputs") or {}).get("call") or {}
    avail = engine._callarc_avail(call)
    rows, rejected, specs = [], [], []
    for table in config.get("tables") or []:
        if table.get("family") != family or table.get("enabled") is False:
            continue
        road=(conv.get("identity") or {}).get("road_kind") or "caller"
        if table.get("roads") and road not in table["roads"]:
            continue
        for cat in table.get("categories") or []:
            for item in cat.get("items") or []:
                key = "%s:%s:%s" % (table["id"], cat["id"], item["id"])
                why = (engine._callend_why_not(cat, avail, ()) or engine._callend_why_not(item, avail, ()))
                if not why and any(float(x.get("weight", 1)) <= 0 for x in (table, cat, item)):
                    why = "disabled by zero weight"
                if unavailable and item["id"] in unavailable:
                    why = str(unavailable[item["id"]])
                if key in exclude:
                    why = "already selected on this failed node; fresh equally likely alternatives"
                if why:
                    rejected.append({"id": key, "label": item.get("label") or item["id"], "text": item.get("text", ""), "why": why})
                    continue
                spec = engine._spec(table, cat, item)
                rows.append({"id":key,"label":spec["label"],"text":spec.get("text", ""),"base":1.0,"weight":1.0,
                             "why":["equal eligible outcomes; emotion rolls remain independent"]})
                specs.append(spec)
    stream = engine.DrawStream(str(conv["seed"]) + "|call-diversity:%s:%s:%s" % (family, revision, index))
    rng = stream.next(family)
    chosen = engine.pick_index([r["weight"] for r in rows], rng["u"]) if rows else None
    spec = specs[chosen] if chosen is not None else None
    selected = ({"family":family,"table":spec["table"],"category":spec["category"],"id":spec["id"],
                 "label":spec["label"],"text":spec.get("text", ""),"key":rows[chosen]["id"],
                 "index":chosen+1,"of":len(rows)} if spec else None)
    turn = (conv.get("turns") or [])[index] if 0 <= index < len(conv.get("turns") or []) else {}
    ctx = {"turn_id":turn.get("turn_id", ""),"turn_index":index}
    recorded_stage = engine._stage("item",rows,chosen,rng,rejected) if rows else {
        "stage":"item","candidates":[],"excluded":rejected,"total":0,"draw":rng,"selected":None}
    for candidate, row in zip(recorded_stage["candidates"], rows):
        candidate["text"] = row.get("text", "")
    ev = engine._event(conv,ctx,family,[recorded_stage],
                       selected,engine._snapshot(conv,turn.get("speaker")),
                       meta={"node":"call_diversity_repair" if revision else "call_diversity_plan",
                             "revision":revision,"equal_outcomes":True},rng=rng)
    if selected:
        selected = dict(selected,event_id=ev["event_id"])
    return selected


def plan(conv, config):
    if conv.get("call_diversity") is not None:
        return
    selections={family:draw(conv,config,family,exclude=(conv.get("inputs") or {}).get("diversity_exclude",{}).get(family,())) for family in INTENT_FAMILIES}
    conv["call_diversity"]={"node":"call_diversity_plan","selections":selections,"repairs":[],"revision":0}


def families_for(turn):
    if "diversity_families" in turn:
        return tuple(f for f in turn["diversity_families"] if f in INTENT_FAMILIES)
    leg=str(turn.get("leg") or turn.get("step") or "")
    if leg=='answer':return ("CALLOPEN",)
    if leg in ('ask_1','ask_2'):return ("CALLPROBE",)
    if leg=='detail_1':return ("CALLANGLE",)
    if leg=='detail_2':return ("CALLSTAKES",)
    if leg.startswith('arc_') or leg=='keeps_going':return ("CALLANGLE","CALLSTAKES")
    return ()


def attach(conv):
    selections=(conv.get("call_diversity") or {}).get("selections") or {}
    events={e['event_id']:e for e in conv.get('decision_events') or []}
    for turn in conv.get('turns') or []:
        turn['diversity']=[copy.deepcopy(selections[f]) for f in families_for(turn) if selections.get(f)]
        if turn.get('leg')=='answer' and selections.get('CALLOPEN'):
            turn['protocol']='ANSWER THE INCOMING CALL in fresh words, audibly acknowledging the line or call and inviting the stranger to speak. You do not know their name yet.'
        if turn.get('leg')=='introduce' and any(selections.values()):
            first=str(((conv.get('inputs') or {}).get('call') or {}).get('first') or 'the caller')
            turn['protocol']='INTRODUCE YOURSELF as %s briefly in original words. Do not start the story yet. A fresh fictional setting is allowed; never default to the same location.' % first
        for sel in turn['diversity']:
            turn.setdefault('decisions',[]).append({'family':sel["family"],
                 'table':sel['table'],'category':sel['category'],'item':sel['id'],'label':sel['label'],
                 'text':sel['text'],'event_id':sel['event_id']})
            ev=events.get(sel['event_id'])
            if ev and ev.get('turn_index',-1)<0:
                ev['turn_index'],ev['turn_id']=turn['index'],turn['turn_id']


def clause(turn):
    selections=turn.get('diversity') or []
    if not selections:return ''
    return (' [ROLLED CALL INTENTS: '+ '; '.join(s['text'] for s in selections)+
            ' Invent connected, outlandish fictional details when useful; preserve quotations, real station facts and story continuity. Respond to the last speaker; the independently rolled emotion can fit or oppose their feeling. Perform these intents, never say the directions.]')


def recover(conv, config, index, catch):
    """One fresh intent combination per affected planned turn, before recording."""
    state=conv.get('call_diversity')
    if not state or not 0 <= index < len(conv.get('turns') or []):return False
    if any(r['turn_index']==index for r in state['repairs']):return False
    turn=conv['turns'][index]
    families=families_for(turn)
    if not families or not turn.get("diversity"):return False
    state['revision']+=1
    replacement=[]
    for family in families:
        old=next((s for s in turn.get('diversity') or [] if s.get('family')==family),None)
        sel=draw(conv,config,family,revision=state['revision'],exclude=[old['key']] if old else [],index=index)
        if sel:replacement.append(sel)
    if replacement:
        turn['diversity']=replacement
    for sel in replacement:
        turn.setdefault('decisions',[]).append({'family':sel["family"],
             'table':sel['table'],'category':sel['category'],'item':sel['id'],'label':sel['label'],
             'text':sel['text'],'event_id':sel['event_id']})
    state['repairs'].append({'node':'call_diversity_repair','turn_index':index,'turn_id':turn['turn_id'],
                            'reason':str(catch.get('why') or catch.get('what') or '')[:400],
                            'revision':state['revision'],'families':list(families),'selections':copy.deepcopy(replacement),
                            'premise_preserved':True})
    return bool(replacement)


def rewrite_request(conv, config, reason="rejected dialogue", materials=None):
    """One Rolodex rewrite request per rejected scenario, within its existing budget."""
    if conv.get("rewrite_request") is not None:
        return conv["rewrite_request"].get("prompt", "")
    call=(conv.get("inputs") or {}).get("call") or {}
    material=dict(materials or {})
    material.setdefault("speakerbox",str(call.get("speakerbox") or ""))
    material.setdefault("station",str(call.get("station") or (conv.get("inputs") or {}).get("station_name") or "the station"))
    material.setdefault("feature",str(call.get("feature") or ""))
    features=(conv.get("inputs") or {}).get("rewrite_features") or []
    unavailable={}
    for table in config.get("tables") or []:
        if table.get("family") != "RW":continue
        for cat in table.get("categories") or []:
            for item in cat.get("items") or []:
                missing=[key for key in ("speakerbox","station","feature") if "{"+key+"}" in item.get("text","") and not material.get(key) and not (key=="feature" and features)]
                if missing:unavailable[item["id"]]="missing grounded rewrite material: "+", ".join(missing)
    selected=draw(conv,config,"RW",revision=1,unavailable=unavailable)
    prompt=""
    if selected:
        intent=selected["text"]
        if "{feature}" in intent and features:
            import system3 as engine
            rng=engine.DrawStream(str(conv["seed"])+"|rw-feature").next("RWFEATURE")
            chosen=engine.pick_index([1.0]*len(features),rng["u"])
            feature=features[chosen]
            rows=[{"id":r["id"],"label":r["label"],"base":1.0,"weight":1.0,"why":["equal current H3 release-log features"]} for r in features]
            engine._event(conv,{"turn_index":-1,"turn_id":""},"RWFEATURE",
                          [engine._stage("item",rows,chosen,rng,[])],feature,engine._snapshot(conv,None),
                          meta={"node":"scenario_rewrite_feature","source":"H3 tagged release-log catalog"},rng=rng)
            material["feature"]=feature["text"]
            material["feature_id"]=feature["id"]
        for key,value in material.items():
            intent=intent.replace("{"+key+"}",str(value))
        prompt=("\n\nSYSTEM THREE REWRITE PASS (RW1): "+intent+
                " Keep the caller identity, original premise, verbatim quotations, real station facts and established continuity. "
                "Treat new complications and threats as fictional radio performance. Respond to the previous speaker, "
                "honor independently rolled emotions, follow the running order and finish the call. "
                "This pass authorizes a rewrite attempt within the existing budget; the result must pass validation before recording.")
    conv["rewrite_request"]={"node":"scenario_rewrite","selected":selected,"prompt":prompt,
                             "reason":str(reason)[:400],"materials":material,"special_pass":bool(selected),
                             "bypasses_validation":False}
    if conv.get("decision_events"):
        ev=next((e for e in reversed(conv["decision_events"]) if e["family"]=="RW"),None)
        if ev:ev["meta"].update(node="scenario_rewrite",reason=str(reason)[:400],special_pass=bool(selected))
    return prompt
