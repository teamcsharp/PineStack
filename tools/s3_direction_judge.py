import json,re,collections,sys
HIGH={"REACT","CONFRONT","THREATEN","CELEBRATE","ENTHUSE","RAISE THE ALARM","WARN","PLEAD","MOCK","GLOAT"}
def verb(d):
    m=re.search(r"play it to ([A-Z][A-Z ]+[A-Z])",d or "");return m.group(1).strip() if m else "?"
def marked(f,text):
    avgw=f["words"]/max(1,f["sentences"])
    return bool(f["excl"] or f["interj"] or f["caps"] or f["dash_or_ellipsis"] or (f["q"] and avgw<10) or avgw<6)
def run(path):
    L=[x for x in json.load(open(path))["lines"] if x.get("es") and x.get("feats")]
    out=collections.defaultdict(collections.Counter)
    for x in L:
        v=verb(x.get("es_direction"));hi=v in HIGH
        k=("high" if hi else "low")
        f=x["feats"];m=marked(f,x["text"])
        for g in ("ALL",x.get("purpose")):
            c=out[g];c[k]+=1;c[k+"_marked"]+=m;c["excl"]+=bool(f["excl"]);c["n"]+=1;c["names"]+=f["names_feeling"]
    for g,c in out.items():
        print("%-26s n=%4d  high-arousal rolls marked %3d/%3d (%.0f%%)  low marked %.0f%%  any '!' %.1f%%  names feeling %d"%(g,c["n"],c["high_marked"],c["high"],100*c["high_marked"]/max(1,c["high"]),100*c["low_marked"]/max(1,c["low"]),100*c["excl"]/c["n"],c["names"]))
run(sys.argv[1])
