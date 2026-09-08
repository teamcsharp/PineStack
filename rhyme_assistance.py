"""Persistent, offline word retrieval before a Crystal rewrite.

CMUdict supplies pronunciation, WordNet supplies *sense-specific* relations.
Neither a shared sound nor vector proximity licenses a new factual statement.
All corpus rows retain original identifiers and hashes. No model/network calls
occur here; an optional background caller can persist real local embeddings.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import threading
import time
from collections import Counter
from pathlib import Path

VERSION = 1
LEXICAL_VECTOR_MODEL = "wordnet-lexical-sha256-512-v1"
_ROOT = Path(__file__).resolve().parent
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_STOP = set("a an and are as at be been being but by can could did do does for from had has have he her here him his how i if in into is it its just me my no not of on or our out she so some than that the their them then there these they this those to too up us was we were what when where which who why will with would you your".split())
_STOP.add('please')
_PHONE = re.compile(r"(?:AA|AE|AH|AO|AW|AY|EH|ER|EY|IH|IY|OW|OY|UH|UW)[012]|(?:B|CH|D|DH|F|G|HH|JH|K|L|M|N|NG|P|R|S|SH|T|TH|V|W|Y|Z|ZH)")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _tokens(text):
    return [w for w in _WORD.findall(str(text).lower().replace("\u2019", "'")) if w not in _STOP]


def lexical_vector(text):
    """Deterministic sparse lexical vector, explicitly not a neural embedding."""
    values = Counter(int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % 512
                     for word in _tokens(text))
    length = math.sqrt(sum(n*n for n in values.values())) or 1.0
    return {str(i): n / length for i, n in values.items()}


def _dot(left, right):
    return sum(v * right.get(k, 0.0) for k, v in left.items())


def _normalized_vector(vector):
    if not isinstance(vector, (list, tuple)) or not 8 <= len(vector) <= 4096:
        raise ValueError("embedding dimensions must be between 8 and 4096")
    out = [float(v) for v in vector]
    if not all(math.isfinite(v) for v in out):
        raise ValueError("embedding values must be finite")
    length = math.sqrt(sum(v*v for v in out))
    if not length:
        raise ValueError("zero embedding")
    return [v/length for v in out]


class RhymeAssistance:
    def __init__(self, path, *, vendor=None):
        self.path = Path(path)
        self.vendor = Path(vendor) if vendor is not None else _ROOT / "vendor"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), timeout=15, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS phones(word TEXT NOT NULL,variant INTEGER NOT NULL,
              phones TEXT NOT NULL,tail TEXT NOT NULL,syllables INTEGER NOT NULL,
              PRIMARY KEY(word,variant));
            CREATE INDEX IF NOT EXISTS phone_tail ON phones(tail,word);
            CREATE TABLE IF NOT EXISTS senses(id TEXT PRIMARY KEY,pos TEXT NOT NULL,
              gloss TEXT NOT NULL,words TEXT NOT NULL,pointers TEXT NOT NULL,
              lexical TEXT NOT NULL,source_file TEXT NOT NULL,source_offset TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lemmas(word TEXT NOT NULL,sense TEXT NOT NULL,
              rank INTEGER NOT NULL,proper INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(word,sense));
            CREATE INDEX IF NOT EXISTS lemma_sense ON lemmas(sense,word);
            CREATE TABLE IF NOT EXISTS usage(word TEXT PRIMARY KEY,count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS forms(word TEXT NOT NULL,base TEXT NOT NULL,
              PRIMARY KEY(word,base));
            CREATE TABLE IF NOT EXISTS embeddings(sense TEXT NOT NULL,model TEXT NOT NULL,
              dimensions INTEGER NOT NULL,text_sha256 TEXT NOT NULL,vector BLOB NOT NULL,
              at REAL NOT NULL,PRIMARY KEY(sense,model));
            CREATE TABLE IF NOT EXISTS query_vectors(source_sha256 TEXT NOT NULL,model TEXT NOT NULL,
              dimensions INTEGER NOT NULL,vector BLOB NOT NULL,at REAL NOT NULL,
              PRIMARY KEY(source_sha256,model));
            CREATE VIRTUAL TABLE IF NOT EXISTS sense_search USING fts5(id UNINDEXED,words,gloss);
        """)
        self.db.commit()
        self._status = self._read_status()

    def close(self):
        with self.lock:
            self.db.close()

    def _read_status(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key='corpus'").fetchone()
        return json.loads(row[0]) if row else {"ready": False, "revision": "", "version": VERSION}

    def status(self):
        with self.lock:
            result = dict(self._status)
            result["vectors"] = [dict(r) for r in self.db.execute(
                "SELECT model,dimensions,COUNT(*) AS rows FROM embeddings GROUP BY model,dimensions")]
            result["lexical_vector_model"] = LEXICAL_VECTOR_MODEL
            result["cached_queries"] = self.db.execute("SELECT COUNT(*) FROM query_vectors").fetchone()[0]
            return result

    def initialize(self):
        """Build every pinned entry in one transaction, retaining old data on failure.

        Run in a background thread. Already-built matching indexes only read the
        small provenance manifest; no corpus walk occurs during prompt retrieval.
        """
        from crystal_rhyme import DICTIONARY_SHA256, DICTIONARY_VERSION
        manifest = json.loads((self.vendor / "wordnet" / "provenance.json").read_text())
        fingerprint = hashlib.sha256(_json({"schema": VERSION, "cmu": DICTIONARY_SHA256,
                                            "wordnet": manifest}).encode()).hexdigest()
        with self.lock:
            if self._status.get("ready") and self._status.get("revision") == fingerprint:
                self._compact()
                return self.status()
        started = time.monotonic()
        paths = {row["path"]: row for row in manifest["files"]}
        for name, row in paths.items():
            path = self.vendor / "wordnet" / name
            if path.parent != self.vendor / "wordnet" or path.stat().st_size != row["bytes"]:
                raise ValueError("invalid WordNet corpus size/path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("WordNet corpus hash mismatch: " + name)
        cmu = (self.vendor / "cmudict" / "cmudict.dict").read_bytes()
        if len(cmu) > 4_000_000 or hashlib.sha256(cmu).hexdigest() != DICTIONARY_SHA256:
            raise ValueError("CMUdict corpus hash mismatch")
        counts = Counter()
        with self.lock, self.db:
            for table in ("phones", "senses", "lemmas", "forms", "usage", "sense_search", "embeddings"):
                self.db.execute("DELETE FROM " + table)
            usage=Counter()
            for line in (self.vendor / 'wordnet' / 'cntlist.rev').read_text().splitlines():
                fields=line.split()
                if len(fields)==3:usage[fields[0].split('%',1)[0]]+=int(fields[2])
            self.db.executemany('INSERT INTO usage VALUES(?,?)',usage.items())
            pronunciations = []
            for raw in cmu.splitlines():
                fields = raw.split(b"#", 1)[0].decode("ascii").split()
                if len(fields) < 2 or any(_PHONE.fullmatch(p) is None for p in fields[1:]):
                    continue
                word = re.sub(r"\(\d+\)$", "", fields[0])
                if not re.fullmatch(r"[a-z]+(?:'[a-z]+)?", word):
                    continue
                stress = [i for i, p in enumerate(fields[1:]) if p[-1:] in ("1", "2")]
                if not stress:
                    continue
                variant = int(re.search(r"\((\d+)\)$", fields[0]).group(1)) if "(" in fields[0] else 1
                tail = " ".join(re.sub(r"[012]$", "", p) for p in fields[1:][stress[-1]:])
                pronunciations.append((word, variant, _json(fields[1:]), tail,
                                       sum(p[-1:].isdigit() for p in fields[1:])))
            self.db.executemany("INSERT OR IGNORE INTO phones VALUES(?,?,?,?,?)", pronunciations)
            for pos in ("noun", "verb", "adj", "adv"):
                filename = "data." + pos
                ranks = {}
                for line in (self.vendor / "wordnet" / ("index." + pos)).read_text().splitlines():
                    if not line or line.startswith(" "):
                        continue
                    fields = line.split(); ptrs = int(fields[3])
                    for rank, offset in enumerate(fields[6+ptrs:]):
                        ranks[(fields[0], offset)] = rank + 1
                senses, lemmas, searches = [], [], []
                for line in (self.vendor / "wordnet" / filename).read_text().splitlines():
                    if not line or line.startswith(" "):
                        continue
                    left, _, gloss = line.partition("|"); fields = left.split()
                    offset, actual_pos, size = fields[0], fields[2], int(fields[3], 16)
                    words = [re.sub(r"\((?:a|p|ip)\)$", "", fields[4+2*i]) for i in range(size)]
                    sense_id = pos + ":" + offset
                    pointer_start = 4 + size*2; n = int(fields[pointer_start]); pointers = []
                    for i in range(n):
                        q = fields[pointer_start+1+i*4:pointer_start+5+i*4]
                        pointers.append({"relation":q[0], "offset":q[1], "pos":q[2], "word_scope":q[3]})
                    text = " ".join(words).replace("_", " ") + ". " + gloss.strip()
                    senses.append((sense_id, actual_pos, gloss.strip(), _json(words), _json(pointers),
                                   _json(lexical_vector(text)), filename, offset))
                    searches.append((sense_id, " ".join(words).replace("_", " "), gloss.strip()))
                    for word in words:
                        lemmas.append((word.lower(), sense_id, ranks.get((word.lower(),offset),999),
                                       int(word[:1].isupper())))
                self.db.executemany("INSERT INTO senses VALUES(?,?,?,?,?,?,?,?)", senses)
                self.db.executemany("INSERT OR IGNORE INTO lemmas VALUES(?,?,?,?)", lemmas)
                self.db.executemany("INSERT INTO sense_search VALUES(?,?,?)", searches)
                forms=[]
                for line in (self.vendor / "wordnet" / (pos + ".exc")).read_text().splitlines():
                    values=line.split()
                    forms.extend((values[0], base) for base in values[1:])
                self.db.executemany("INSERT OR IGNORE INTO forms VALUES(?,?)",forms)
            for table in ("phones", "senses", "lemmas", "forms"):
                counts[table]=self.db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
            result={"ready":True,"version":VERSION,"revision":fingerprint,
                    "counts":dict(counts),"built_seconds":round(time.monotonic()-started,3),
                    "cmudict":{"version":DICTIONARY_VERSION,"sha256":DICTIONARY_SHA256},
                    "wordnet":{"version":manifest["version"],"archive_sha256":manifest["archive_sha256"],
                               "license":"vendor/wordnet/LICENSE","source":manifest["url"]}}
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('corpus',?)",(_json(result),))
        self._status=result
        with self.lock:
            self._compact()
        return self.status()

    def _compact(self):
        """Fold the import's write-ahead log back into the index.

        The one-transaction corpus import leaves a WAL as large as the
        database itself (143 MB observed) and SQLite never shrinks it on its
        own; every later reader then walks that log. Called under the lock,
        in the worker thread, never on the event loop."""
        try:
            self.db.execute("PRAGMA journal_size_limit=67108864")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass  # a busy reader keeps the log for now; retried on the next open

    def _forms(self, word):
        forms=[word]
        forms.extend(r[0] for r in self.db.execute("SELECT base FROM forms WHERE word=? LIMIT 8",(word,)))
        for ending, replacement in (("ies","y"),("es",""),("s",""),("ing",""),("ing","e"),("ed",""),("ed","e")):
            if word.endswith(ending) and len(word)>len(ending)+2:
                base=word[:-len(ending)]+replacement
                if self.db.execute("SELECT 1 FROM lemmas WHERE word=? LIMIT 1",(base,)).fetchone():
                    forms.append(base)
        return list(dict.fromkeys(forms))

    def _senses(self, source, limit=12, model=""):
        tokens=[w for w in _tokens(source) if w not in {'get','got','man','bro','dude'}]
        unique=list(dict.fromkeys(tokens))[:32]
        # Long turns must still query their actual words; an unbounded prefix
        # of n-grams previously crowded every unigram out of the request cap.
        words=unique + ["_".join(tokens[i:i+n]) for n in (3,2)
                        for i in range(min(16,len(tokens)-n+1))]
        qv=lexical_vector(source); found={}
        for word in words[:96]:
            forms=self._forms(word)
            context=' '.join(t for t in tokens if t not in forms)
            context_words=set(_tokens(context));context_vector=lexical_vector(context)
            for lemma in forms:
                for r in self.db.execute("SELECT s.*,l.rank FROM lemmas l JOIN senses s ON s.id=l.sense WHERE l.word=? AND l.proper=0 ORDER BY l.rank LIMIT 24",(lemma,)):
                    row=dict(r); row["source_word"]=word.replace("_"," ")
                    overlap=context_words & set(_tokens(row['gloss']))
                    extra=_dot(context_vector,json.loads(row['lexical'])) if overlap else 0
                    # A gloss repeating its headword is not contextual proof.
                    # Other source words and exact usage examples outrank it.
                    examples=re.findall(r'"([^"]+)"',row['gloss'].lower())
                    source_flat=' '.join(_WORD.findall(str(source).lower()))
                    phrase=max((len(_tokens(e)) for e in examples if len(_tokens(e))>=2
                                and ' '.join(_WORD.findall(e)) in source_flat),default=0)
                    row["score"]=extra+0.12/max(1,row["rank"])+min(0.7,phrase*0.15)
                    if row["id"] not in found or found[row["id"]]["score"]<row["score"]:
                        found[row["id"]]=row
        # Definition search complements exact lemmas; the relationship remains
        # explicitly 'related sense', never a certified synonym of the source.
        if unique:
            query=" OR ".join('"'+w.replace('"','')+'"' for w in unique[:16])
            for r in self.db.execute("SELECT s.* FROM sense_search f JOIN senses s ON s.id=f.id WHERE sense_search MATCH ? ORDER BY bm25(sense_search) LIMIT 24",(query,)):
                if r["id"] in found: continue
                row=dict(r);row["source_word"]="";row["rank"]=999
                if len(set(_tokens(row['gloss'])) & set(unique))<2:continue
                row["score"]=_dot(qv,json.loads(row["lexical"]))*0.35
                found[row["id"]]=row
        if model:
            query = self.db.execute("SELECT * FROM query_vectors WHERE source_sha256=? AND model=?",
                (hashlib.sha256(source.encode()).hexdigest(),str(model))).fetchone()
            if query:
                q = struct.unpack('<'+'f'*query['dimensions'],query['vector'])
                for row in found.values():
                    saved=self.db.execute("SELECT dimensions,vector FROM embeddings WHERE sense=? AND model=?",
                        (row['id'],str(model))).fetchone()
                    if saved and saved['dimensions']==len(q):
                        vector=struct.unpack('<'+'f'*len(q),saved['vector'])
                        cosine=sum(a*b for a,b in zip(q,vector))
                        row['lexical_score']=row['score'];row['neural_cosine']=cosine
                        # A source lemma remains an option of its cited sense;
                        # proximity never changes the relationship label.
                        row['score']=row['score']*0.35+max(0,cosine)*0.65
        return sorted(found.values(),key=lambda r:(-r["score"],r["id"]))[:limit]

    def assist(self, source, *, style_words=(), limit=6, model="nomic-embed-text",
               normalize=None, required_depth=None, exclude_words=()):
        """Bounded read-only retrieval; no embeddings or corpus import on a miss."""
        source=str(source or "");limit=max(1,min(8,int(limit)))
        started=time.monotonic()
        with self.lock:
            info={"version":VERSION,"revision":self._status.get("revision",""),
                  "source_sha256":hashlib.sha256(source.encode()).hexdigest(),
                  "ready":bool(self._status.get("ready")),"endings":[],"related":[],
                  "search":{"lexical_vector_model":LEXICAL_VECTOR_MODEL,"neural_used":False},
                  "limitations":"Sound matches are not meaning matches. WordNet alternatives are sense-specific options, not interchangeable facts. Keep source roles, uncertainty and intent; use imagery only when it adds no factual claim."}
            if not info["ready"] or not source.strip(): return info
            senses=self._senses(source[:12000],limit=max(12,limit*2),model=model)
            info['search']['neural_used']=any('neural_cosine' in r for r in senses)
            info['search']['neural_model']=str(model)
            info['search']['neural_basis']='cached exact-source query and cited-sense embeddings; lexical shortlist'
            related=[]
            # Prefer the last topic-bearing source words to weak lead-ins and
            # repeated vocative tags. Never use an inferred proper name as a
            # invitation to rename the source speaker.
            excluded=set(str(w).lower() for w in exclude_words)
            tags=set(re.findall(r',\s*([a-z]+)[.!?;]',source.lower())) & {'man','bro','dude','buddy','pal'}
            seed_words=[w for w in reversed(list(dict.fromkeys(_tokens(source))))
                        if w not in tags|excluded|{'get','got'}][:24]
            covered=Counter()
            for row in senses:
                if row['source_word'] in excluded or covered[row['source_word']]>=1:continue
                alternatives=[w.replace("_"," ") for w in json.loads(row["words"])
                              if w.lower().replace("_"," ")!=row["source_word"] and not w[:1].isupper()][:4]
                relation=("same_synset_options" if alternatives else "source_sense") if row["source_word"] else "related_sense"
                related.append({"source_word":row["source_word"],"alternatives":alternatives,
                    "relationship":relation,"sense":row["id"],"definition":row["gloss"],
                    "pos":row["pos"],"score":round(row["score"],4),
                    "provenance":{"corpus":"Princeton WordNet 3.0","file":row["source_file"],"offset":row["source_offset"]}})
                if 'neural_cosine' in row:
                    related[-1]['neural_cosine']=round(row['neural_cosine'],4)
                covered[row['source_word']]+=1
                if row["source_word"]:
                    seed_words.extend(w for w in alternatives if " " not in w)
                if len(related)>=limit:break
            info["related"]=related
            source_bound={word for row in related if row['source_word']
                          for word in row['alternatives'] if ' ' not in word}
            style=style_words if isinstance(style_words,(set,frozenset)) else set(str(w).lower() for w in style_words)
            source_words=set(_tokens(source));endings=[];seen=set()
            normalize=normalize or (lambda w:w)
            required_depth=required_depth or (lambda w:1)
            for word in list(dict.fromkeys(seed_words))[:40]:
                if word in _STOP|excluded or len(word)<2:continue
                for p in self.db.execute("SELECT * FROM phones WHERE word=? ORDER BY variant LIMIT 3",(word,)):
                    depth=sum(x in {'AA','AE','AH','AO','AW','AY','EH','ER','EY','IH','IY','OW','OY','UH','UW'} for x in p['tail'].split())
                    if depth<max(1,int(required_depth(word))):continue
                    matches=self.db.execute("SELECT p.*,MIN(l.rank) AS frequency_rank,COALESCE(u.count,0) AS uses FROM phones p JOIN lemmas l ON l.word=p.word LEFT JOIN usage u ON u.word=p.word WHERE p.tail=? AND p.word!=? AND l.proper=0 GROUP BY p.word,p.variant ORDER BY uses DESC,frequency_rank,length(p.word),p.word LIMIT 64",(p["tail"],word)).fetchall()
                    matches=sorted(matches,key=lambda r:(r["word"] not in source_words,
                        r['word'] not in source_bound,-r['uses'],r["word"] not in style,
                        abs(r["syllables"]-p["syllables"]),len(r["word"]),r["word"]))
                    chosen=[]
                    for m in matches:
                        pair=tuple(sorted((normalize(word),normalize(m["word"]))))
                        if (pair in seen or pair[0]==pair[1] or m["word"] in _STOP|excluded
                                or depth<max(1,int(required_depth(m['word'])))):continue
                        # A small prompt shortlist should not inject an obscure
                        # subject merely because its sound matches (e.g.
                        # area/malaria). Full dictionary rows remain searchable.
                        # Keep rare words when already supplied by the source
                        # or its cited sense; otherwise use concordance-backed
                        # common options. This never changes an acceptance gate.
                        if m['word'] not in source_words|source_bound and (
                                m['uses']<5 or abs(m['syllables']-p['syllables'])>1):continue
                        seen.add(pair)
                        chosen.append({"word":m["word"],"phones":json.loads(m["phones"]),"syllables":m["syllables"],"in_source":m["word"] in source_words,"in_style":m["word"] in style,"wordnet_tagged_uses":m['uses']})
                        if len(chosen)>=4:break
                    if chosen:
                        endings.append({"anchor":word,"anchor_in_source":word in source_words,
                          "phones":json.loads(p["phones"]),"rhyme_phones":p["tail"].split(),
                          "options":chosen,"provenance":{"corpus":"CMUdict","version":self._status["cmudict"]["version"],"sha256":self._status["cmudict"]["sha256"]}})
                    if len(endings)>=limit:break
                    if chosen:break  # One useful pronunciation per source anchor.
                if len(endings)>=limit:break
            info["endings"]=endings;info["milliseconds"]=round((time.monotonic()-started)*1000,3)
            return info

    def embedding_batch(self, model, *, limit=16, source=""):
        """Return missing persistent sense vectors; caller chooses idle-time budget."""
        model=str(model);limit=max(1,min(32,int(limit)))
        with self.lock:
            if not self._status.get("ready"):return []
            if source:
                ids=[r['id'] for r in self._senses(str(source)[:12000],limit=32)]
                rows=[]
                for sid in ids:
                    r=self.db.execute("SELECT s.id,s.words,s.gloss FROM senses s LEFT JOIN embeddings e ON e.sense=s.id AND e.model=? WHERE s.id=? AND e.sense IS NULL",(model,sid)).fetchone()
                    if r:rows.append(r)
                    if len(rows)>=limit:break
            else:
                rows=self.db.execute("SELECT s.id,s.words,s.gloss FROM senses s LEFT JOIN embeddings e ON e.sense=s.id AND e.model=? WHERE e.sense IS NULL ORDER BY s.id LIMIT ?",(model,limit)).fetchall()
            out=[]
            for r in rows:
                text=" ".join(json.loads(r["words"])).replace("_"," ")+". "+r["gloss"]
                out.append({"id":r["id"],"text":text,"sha256":hashlib.sha256(text.encode()).hexdigest(),"revision":self._status["revision"]})
            return out

    def put_embeddings(self, model, rows, vectors):
        """Fence source/revision/model/dimensions; atomically retain actual vectors."""
        if len(rows)!=len(vectors) or len(rows)>32:raise ValueError("embedding batch mismatch")
        prepared=[];dims=None
        with self.lock, self.db:
            for row, raw in zip(rows,vectors):
                if row.get("revision")!=self._status.get("revision"):raise ValueError("stale corpus revision")
                actual=self.db.execute("SELECT words,gloss FROM senses WHERE id=?",(row["id"],)).fetchone()
                if not actual:raise ValueError("unknown sense")
                text=" ".join(json.loads(actual["words"])).replace("_"," ")+". "+actual["gloss"]
                if hashlib.sha256(text.encode()).hexdigest()!=row["sha256"]:raise ValueError("changed sense text")
                vector=_normalized_vector(raw)
                if dims is not None and dims!=len(vector):raise ValueError("mixed embedding dimensions")
                dims=len(vector)
                prepared.append((row["id"],str(model),dims,row["sha256"],struct.pack('<'+'f'*dims,*vector),time.time()))
            existing=self.db.execute("SELECT dimensions FROM embeddings WHERE model=? LIMIT 1",(str(model),)).fetchone()
            if existing and dims is not None and existing[0]!=dims:raise ValueError("model dimensions changed")
            self.db.executemany("INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?,?)",prepared)
        return len(prepared)

    def query_cached(self, source, model):
        with self.lock:
            return bool(self.db.execute("SELECT 1 FROM query_vectors WHERE source_sha256=? AND model=?",
                (hashlib.sha256(str(source)[:12000].encode()).hexdigest(),str(model))).fetchone())

    def put_query_embedding(self, source, model, vector):
        """Background-only exact source cache; no stored private query text."""
        vector=_normalized_vector(vector);dimensions=len(vector)
        with self.lock,self.db:
            existing=self.db.execute("SELECT dimensions FROM embeddings WHERE model=? LIMIT 1",(str(model),)).fetchone()
            if existing and existing[0]!=dimensions:raise ValueError('model dimensions changed')
            self.db.execute("INSERT OR REPLACE INTO query_vectors VALUES(?,?,?,?,?)",
                (hashlib.sha256(str(source)[:12000].encode()).hexdigest(),str(model),dimensions,
                 struct.pack('<'+'f'*dimensions,*vector),time.time()))
            self.db.execute("DELETE FROM query_vectors WHERE rowid IN (SELECT rowid FROM query_vectors ORDER BY at DESC LIMIT -1 OFFSET 2048)")
