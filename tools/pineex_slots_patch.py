#!/usr/bin/env python3
"""[pineex] Wave C of the pineEX H3 preset: six named slots, the products list and its API, and the
protagonist's source route in the hourly door.

"a roll over the music library" {music}; "a rolling roulette of items being sold on the pine box radio
chosen at random from a dynamic list we are expanding" {product}; "roll between the {releaselog} and
{feature} or {product}" {offer}; "have the world branded with {speakerbox} billboards, branding, imagery,
books, posters, propaganda, police branded cars, spaceships, chosen via roulette" {brand}; "it can be
anyone selected from comfy UI renders or an SFX clip depending on roulette roll. Roll between using
Renders or clips then roll between folders then roll between clips for who is used as the protagonist"
{protagonist}; "Use the online research rolls as well in the roulettes" {research} (the operator, 2026-10-06).

Edits:
  h3_slots.py   CATALOGUE + NAMED know the six; BRANDED, PROTAGONIST_KINDS, RENDER_FOLDERS; the phrase
                functions music() product() offer() brand() clip_label() clip_words() protagonist() research().
  app.py        H3_SLOT_NAMES mirrors NAMED (the book slots stay book_prompt_runtime's); H3_SLOT_LABELS;
                h3_slot_shelf knows music (the library's size) and product (the merged list); h3_slot_pick
                rolls and phrases a product; the new block before h3_slots_preroll: the products store
                (data/h3_products.json, seeded on first read), h3_slot_topic (the hour's {topic}, one roll,
                shared), h3_slot_music, h3_slot_offer, h3_slot_brand, h3_slot_protagonist (three rolls, the
                pick kept on the memo), h3_slot_research (the station's research road, <= 20 s),
                h3_hourly_protagonist (the door's source route); h3_slots_preroll and h3_slot_named_sync
                dispatch them; h3_speak_fill's {topic} is h3_slot_topic's; the door asks
                h3_hourly_protagonist before it rolls gallery-or-clip; GET/POST /api/h3/products and
                POST /api/h3/products/{id}/delete beside the /api/h3/prompts routes.

Usage:  pineex_slots_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pineex_slots_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# --- h3_slots.py ------------------------------------------------------------------------------------

SLOTS_CATALOGUE_OLD = '''    ("a|b|c", "One of the options you write between the bars, rolled.", "{funny|grim|tender}"),
)
'''
SLOTS_CATALOGUE_NEW = '''    # [pineex] wave C: the library, the station's own shop window, the branded
    # world, the hour's star and what the web says (the operator, 2026-10-06).
    ("music", "A record rolled from the whole music library - not the one on air ({record} is that): "
              "title and artist. {music2} rolls a second record.", 'the record "Moonlight Drive" by The Doors'),
    ("product", "An item sold on Pine Box FM, rolled from the station's own list (data/h3_products.json, grown "
                "through /api/h3/products) merged with the DJ setting's products to place.",
     'the product "The Pine Box Gazette" - the station\\'s own newspaper, a fresh edition every day'),
    ("offer", "A roll between a feature and a product: the rolled {feature} together with its release log, or a "
              "rolled product. {offer2} rolls again.",
     'the Pine Box feature "One press builds the PineTab" [tablet-update-ask] - the release log of [tablet-update-ask] ...'),
    ("brand", "A branded surface rolled from the pool (billboards, posters, book covers, propaganda, police cars, "
              "spaceships, blimps...) carrying the hour's Speakerbox sentence in Pine Box FM livery. {brand2} is a "
              "second surface with the same words.",
     'a giant roadside billboard carrying the words "We never sleep" in Pine Box FM livery'),
    ("protagonist", "Who the piece is about: a roll between the gallery renders and the SFX clips, then a roll "
                    "between folders, then a roll between the items - and the hourly door makes the video FROM "
                    "that render or clip. Hourly door only.",
     'the protagonist is whoever appears in the clip "dog skate", which shows a dog on a skateboard'),
    ("research", "What the web says about the hour's rolled {topic} (or a Gazette headline): one result rolled "
                 "from the station's own research road under your per-site preferences. Hourly door only.",
     'what the web says about "cats on the radio": "Cats take over a local station" - a station in Ohio ...'),
    ("a|b|c", "One of the options you write between the bars, rolled.", "{funny|grim|tender}"),
)
'''

SLOTS_NAMED_OLD = '''NAMED = ("mxtape", "fordtape", "videos", "sfxclip", "convograph", "gazette", "arena", "feature", "releaselog", "book", "booktopic", "bookchapter", "booksegment", "booksentence", "booksentences")
'''
SLOTS_NAMED_NEW = '''NAMED = ("mxtape", "fordtape", "videos", "sfxclip", "convograph", "gazette", "arena", "feature", "releaselog", "book", "booktopic", "bookchapter", "booksegment", "booksentence", "booksentences",
         "music", "product", "offer", "brand", "protagonist", "research")       # [pineex] wave C
'''

SLOTS_FUNCS_OLD = '''

def catalogue() -> list[dict[str, str]]:
'''
SLOTS_FUNCS_NEW = '''

# --- [pineex] WAVE C: THE LIBRARY, THE SHOP WINDOW, THE BRANDED WORLD, THE STAR, THE WEB --------------
#
# The surfaces {brand} rolls over. app.py offers them through System 3's tabled pool
# (h3.slot_brand), so the desk can retire one; the words on them are the hour's
# {speakerbox} sentence.
BRANDED = (
    "a giant roadside billboard",
    "a wall of posters pasted down a city street",
    "the cover of a hardback book",
    "a propaganda banner hung across a public square",
    "a police car in station livery",
    "the hull of a spaceship",
    "a blimp over the stadium",
    "a neon sign over a diner",
    "a cereal box on a breakfast table",
    "a team's match jerseys",
    "a vending machine",
    "a subway car's ad panels",
    "skywriting over the beach",
    "a water tower",
    "a delivery van",
    "a bus shelter",
)
# {protagonist}: the first roll (where the star comes from), then the gallery's two "folders"
PROTAGONIST_KINDS = ("renders", "clips")
RENDER_FOLDERS = ("pictures", "videos")


def music(row: dict[str, Any]) -> str:
    """{music}: a record of the library, title by artist."""
    stem = str(row.get("path") or row.get("name") or "").replace("\\\\", "/").rsplit("/", 1)[-1]
    title = quote(row.get("title") or tidy(stem), 80)
    artist = quote(row.get("artist"), 60)
    return 'the record "%s"%s' % (title, (" by %s" % artist) if artist else "")


def product(row: dict[str, Any]) -> str:
    """{product}: an item sold on Pine Box FM, with its one-line pitch."""
    name = quote(row.get("name"), 80)
    pitch = quote(row.get("pitch"), 160).rstrip(".")
    return 'the product "%s"%s' % (name, (" - %s" % pitch) if pitch else "")


def offer(kind: str, row: dict[str, Any]) -> str:
    """{offer}: the rolled feature with its release log, or a product."""
    if kind == "feature":
        return feature(row) + " - " + releaselog(row)
    return product(row)


def brand(surface: str, sentence: str) -> str:
    """{brand}: one branded surface carrying the Speakerbox words."""
    out = str(surface or "a billboard")
    if sentence:
        out += ' carrying the words "%s"' % quote(sentence, 120)
    return out + " in Pine Box FM livery"


def clip_words(row: dict[str, Any]) -> str:
    """What a clip shows (its vision line) or, failing that, what is said in it."""
    seen = quote(row.get("seen_desc"), 160)
    said = quote(row.get("said"), 100)
    if seen:
        return ", which shows %s" % seen.rstrip(".")
    if said:
        return ', in which someone says "%s"' % said
    return ""


def clip_label(row: dict[str, Any]) -> str:
    """A clip as a line on the rolodex: its name and what it shows or says."""
    seen = quote(row.get("seen_desc") or row.get("said"), 90)
    return (tidy(row.get("name")) + ((": " + seen) if seen else ""))[:120]


def protagonist(pick: dict[str, Any]) -> str:
    """{protagonist}: who the star is, in words - the clip and what it shows, or the render."""
    name = quote(tidy(pick.get("name") or pick.get("file")))
    if pick.get("kind") == "clips":
        return 'the protagonist is whoever appears in the clip "%s"%s' % (name, clip_words(pick))
    what = "video" if pick.get("folder") == "videos" else "picture"
    return 'the protagonist is the figure in the Pine Box gallery %s "%s"' % (what, name)


def research(topic: str, row: dict[str, Any]) -> str:
    """{research}: one judged web result about the hour's topic."""
    title = quote(row.get("title"), 120)
    snippet = quote(row.get("snippet"), 220).rstrip(".")
    out = 'what the web says about "%s"' % quote(topic, 90)
    if title:
        out += ': "%s"' % title
    if snippet and snippet != title:
        out += " - " + snippet
    return out


def catalogue() -> list[dict[str, str]]:
'''

# --- app.py -------------------------------------------------------------------------------------------

NAMES_OLD = '''H3_SLOT_NAMES = r"(?:mxtape|fordtape|videos|sfxclip|convograph|gazette|arena|feature|releaselog)\\d?"   # [h3-slots] = h3_slots.NAMED
'''
NAMES_NEW = '''H3_SLOT_NAMES = r"(?:mxtape|fordtape|videos|sfxclip|convograph|gazette|arena|feature|releaselog|music|product|offer|brand|protagonist|research)\\d?"   # [h3-slots] = h3_slots.NAMED less the book slots (book_prompt_runtime fills those) [pineex]
'''

LABELS_OLD = '''    "releaselog": "the release-log entry of the feature {feature} rolled - the same roll",
}
H3_SLOT_SCREEN_LABEL = '''
LABELS_NEW = '''    "releaselog": "the release-log entry of the feature {feature} rolled - the same roll",
    # [pineex] wave C
    "music": "where in the music library an hourly H3 prompt's {music} lands (0 = first record, 1 = last)",
    "product": "which item sold on Pine Box FM an hourly H3 prompt's {product} pitches",
    "offer": "whether an hourly H3 prompt's {offer} is a feature with its release log or a product",
    "brand": "which branded surface an hourly H3 prompt's {brand} puts the Speakerbox words on",
    "protagonist_kind": "whether an hourly H3 prompt's {protagonist} comes from the gallery renders or the SFX clips",
    "protagonist_folder": "which folder (of the clip book, or pictures / videos of the gallery) the {protagonist} is drawn from",
    "protagonist_clip": "which clip or render of the rolled folder is the hour's {protagonist} - the hourly door renders from it",
    "research": "which web result about the hour's topic an hourly H3 prompt's {research} quotes",
    "research_topic": "which Gazette headline the {research} searches for when the hour has no {topic}",
}
H3_SLOT_SCREEN_LABEL = '''

SHELF_OLD = '''    if name == "sfxclip":
        con = sfx_db_reader()
        with _SFX_DB_LOCK:
            return int(con.execute("SELECT COUNT(*) FROM clips WHERE playable=1").fetchone()[0] or 0)
    return []
'''
SHELF_NEW = '''    if name == "sfxclip":
        con = sfx_db_reader()
        with _SFX_DB_LOCK:
            return int(con.execute("SELECT COUNT(*) FROM clips WHERE playable=1").fetchone()[0] or 0)
    if name == "music":                      # [pineex] the library's size: one float rolls over it, like the clip book
        return len(music_index())
    if name == "product":                    # [pineex] the station's list and the DJ setting's products to place
        return h3_products_shelf()
    return []
'''

PICK_LABELS_OLD = '''    if name == "gazette":
        labels = [str(e.get("headline") or "")[:120] for e in shelf]
    else:
        labels = [str(x) for x in shelf]
'''
PICK_LABELS_NEW = '''    if name == "gazette":
        labels = [str(e.get("headline") or "")[:120] for e in shelf]
    elif name == "product":                                              # [pineex]
        labels = [str(e.get("name") or "")[:120] for e in shelf]
    else:
        labels = [str(x) for x in shelf]
'''

PICK_PHRASE_OLD = '''    if name == "gazette":
        return h3_slots.gazette(got)
    return ""
'''
PICK_PHRASE_NEW = '''    if name == "gazette":
        return h3_slots.gazette(got)
    if name == "product":                                                # [pineex]
        return h3_slots.product(got)
    return ""
'''

BLOCK_OLD = '''

async def h3_slots_preroll(*texts: Any) -> dict[str, str]:
'''
BLOCK_NEW = '''

# --- [pineex] WAVE C: {music} {product} {offer} {brand} {protagonist} {research} --------------------
#
# "a roll over the music library"; "a rolling roulette of items being sold on
# the pine box radio chosen at random from a dynamic list we are expanding";
# "roll between the {releaselog} and {feature} or {product}"; "have the world
# branded with {speakerbox} billboards ... chosen via roulette"; "it can be
# anyone selected from comfy UI renders or an SFX clip depending on roulette
# roll. Roll between using Renders or clips then roll between folders then roll
# between clips for who is used as the protagonist"; "Use the online research
# rolls as well in the roulettes" (the operator, 2026-10-06). Every roll is
# System 3's and lands on the hour's rolodex through _h3_slot_note; the shelves
# are read off the loop; a slot with nothing to say is taken out and logged.
#
# THE PRODUCTS: data/h3_products.json {"products": [{id, name, pitch, added_at}]},
# seeded on first read with the station's own offerings, grown through
# /api/h3/products, and merged at roll time with the DJ setting's products to
# place (dj.sponsors, one per line) so the list the operator already keeps counts.
H3_PRODUCTS_FILE = "h3_products.json"
H3_PRODUCTS_MOST = 400
_H3_PRODUCTS_LOCK = RLock()
_H3_PRODUCT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
H3_PRODUCTS_SEED: tuple[tuple[str, str, str], ...] = (
    ("station", "Pine Box FM", "the station itself - two hosts, a studio guest and a music library that never sleeps"),
    ("pinelive", "PineLive recordings", "every hour of the show kept as a recording you can take home"),
    ("gazette", "The Pine Box Gazette", "the station's own newspaper, a fresh edition of real and invented news every day"),
    ("pinetab", "The PineTab kiosk", "a tablet on the wall that listens, watches and plays the station back to you"),
    ("pinecam", "Pine Cam", "the camera on the desk, filming the hosts and the room as the show goes out"),
    ("supercut", "The hourly Supercut", "an hourly video advert cut from the footage of the day"),
    ("mxtape", "MX mixtapes", "mixtapes by Ehm Eckx, the music the station's concerts and dances play to"),
    ("booktime", "Book Time", "a real book read aloud and argued over on air, chapter by chapter"),
    ("sfxlib", "The SFX clip library", "thousands of clips, seen and heard, each one findable four ways"),
    ("speakerbox", "The Speakerbox", "hundreds of hours of people talking, rolled one sentence at a time"),
    ("gallery", "Pine Box Gallery renders", "pictures and films the station paints itself and hangs on its own wall"),
)
H3_OFFER_KINDS = ("a feature", "a product")
H3_SLOT_RESEARCH_WAIT_S = 20.0


def h3_products_path() -> Path:
    return data_path(H3_PRODUCTS_FILE)


def _h3_product_row(raw: Any, pid: str = "") -> dict[str, Any] | None:
    """One product, clean: an id, a name (required), a one-line pitch, when added."""
    got = raw if isinstance(raw, dict) else {}
    name = " ".join(str(got.get("name") or "").split())[:120]
    if not name:
        return None
    want = str(pid or got.get("id") or "")
    try:
        added = round(float(got.get("added_at") or time.time()), 3)
    except (TypeError, ValueError):
        added = round(time.time(), 3)
    return {"id": want if _H3_PRODUCT_ID.fullmatch(want) else "pr-" + uuid.uuid4().hex[:10],
            "name": name, "pitch": " ".join(str(got.get("pitch") or "").split())[:300], "added_at": added}


def h3_products_seed() -> dict[str, Any]:
    now = round(time.time(), 3)
    return {"version": 1, "products": [{"id": i, "name": n, "pitch": p, "added_at": now} for i, n, p in H3_PRODUCTS_SEED]}


def _h3_products_write(store: dict[str, Any]) -> None:
    path = h3_products_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=1), encoding="utf-8")
    tmp.replace(path)


def h3_products_read() -> dict[str, Any]:
    """[pineex] The products file, seeded with the station's own offerings on
    first read (and written, so the operator can see and edit it). An
    unreadable file is left alone and the seed serves. A worker thread's."""
    path = h3_products_path()
    with _H3_PRODUCTS_LOCK:
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            got = None
        except Exception as exc:  # noqa: BLE001
            pipeline_log("ads", "hourly H3 products: %s could not be read (%s) - the seed list serves this hour"
                         % (path.name, type(exc).__name__))
            return h3_products_seed()
        if not isinstance(got, dict) or not isinstance(got.get("products"), list):
            store = h3_products_seed()
            _h3_products_write(store)
            pipeline_log("ads", "hourly H3 products: %s seeded with %d of the station's own offerings [pineex]"
                         % (path.name, len(store["products"])))
            return store
        rows: list[dict[str, Any]] = []
        ids: set[str] = set()
        for raw in got["products"][:H3_PRODUCTS_MOST]:
            row = _h3_product_row(raw)
            if row and row["id"] not in ids:
                ids.add(row["id"])
                rows.append(row)
        return {"version": 1, "products": rows}


def h3_products_shelf(store: Any = None, sponsors: Any = None) -> list[dict[str, Any]]:
    """[pineex] What {product} rolls over: the file's products, then the DJ
    setting's products to place (dj.sponsors) not already named. A worker thread's."""
    store = store if isinstance(store, dict) else h3_products_read()
    rows = [dict(r) for r in store.get("products") or [] if isinstance(r, dict) and r.get("name")]
    names = {str(r["name"]).lower() for r in rows}
    lines = sponsors if isinstance(sponsors, list) else (dj_settings().get("sponsors") or [])
    for n, line in enumerate(lines):
        name = " ".join(str(line or "").split())[:120]
        if name and name.lower() not in names:
            names.add(name.lower())
            rows.append({"id": "dj-%d" % (n + 1), "name": name, "pitch": "", "added_at": 0.0, "from": "dj.sponsors"})
    return rows[:H3_PRODUCTS_MOST]


def h3_products_view(store: Any = None) -> dict[str, Any]:
    store = store if isinstance(store, dict) else h3_products_read()
    shelf = h3_products_shelf(store)
    return {"ok": True, "file": H3_PRODUCTS_FILE, "products": list(store.get("products") or []),
            "sponsors": [r for r in shelf if r.get("from") == "dj.sponsors"], "count": len(shelf)}


def h3_products_add(name: str, pitch: str = "") -> dict[str, Any]:
    """[pineex] One more item on the list (a name, a one-line pitch); never a twin by name."""
    row = _h3_product_row({"name": name, "pitch": pitch})
    if not row:
        raise HTTPException(status_code=400, detail="A product needs a name")
    with _H3_PRODUCTS_LOCK:
        store = h3_products_read()
        if any(str(r.get("name") or "").lower() == row["name"].lower() for r in store["products"]):
            raise HTTPException(status_code=409, detail="That product is on the list already")
        if len(store["products"]) >= H3_PRODUCTS_MOST:
            raise HTTPException(status_code=409, detail="The list holds %d products already" % H3_PRODUCTS_MOST)
        store["products"].append(row)
        _h3_products_write(store)
    pipeline_log("ads", 'hourly H3 products: "%s" added (%d on the list) [pineex]' % (row["name"], len(store["products"])))
    return h3_products_view(store)


def h3_products_delete(pid: str) -> dict[str, Any]:
    """[pineex] Take an item off the list (a dj.sponsors line is the DJ settings' to edit)."""
    with _H3_PRODUCTS_LOCK:
        store = h3_products_read()
        keep = [r for r in store["products"] if str(r.get("id")) != str(pid)]
        if len(keep) == len(store["products"]):
            raise HTTPException(status_code=404, detail="No such product")
        store["products"] = keep
        _h3_products_write(store)
    pipeline_log("ads", "hourly H3 products: %s removed (%d on the list) [pineex]" % (pid, len(keep)))
    return h3_products_view(store)


def h3_slot_topic() -> str:
    """[pineex] The hour's {topic}: rolled as h3_speak_fill always rolled it
    (h3.plot_topic over the topic bank), once, and kept on the slot memo so the
    hour's text and its {research} agree."""
    vals = _H3_SLOT_MEMO["vals"]
    if isinstance(vals.get("topic"), str):
        return vals["topic"]
    choices = [str(t.get("text") or t.get("topic") or "") if isinstance(t, dict) else str(t) for t in read_bombshells()]
    choices = [x for x in choices if x.strip()]
    got = str(s3_choice("h3.plot_topic", choices, "which topic an H3 prompt uses") or "") if choices else ""
    if got:
        _h3_slot_note("slot_topic", "h3.plot_topic", choices, got)
    vals["topic"] = got
    return got


# {music}: the clip book's pattern - one float over the whole library (36,000
# records are no pool for the rolodex), the record at that point.
def h3_slot_music_row(u: float, total: int) -> dict[str, Any]:
    """The record at `u` of the library. A worker thread's (the index is cached)."""
    rows = music_index()
    if not rows:
        return {}
    at = max(0, min(len(rows) - 1, int(float(u) * len(rows))))
    r = rows[at] if isinstance(rows[at], dict) else {}
    return {"id": str(r.get("id") or ""), "title": str(r.get("title") or ""),
            "artist": str(r.get("artist") or ""), "path": str(r.get("path") or "")}


def _h3_slot_music_roll(tok: str, total: int) -> float | None:
    if not total:
        pipeline_log("ads", "hourly H3 prompts: {%s} - the music library is empty, taken out" % tok)
        return None
    u = s3_roll("h3.slot_music", H3_SLOT_LABELS["music"])
    h3_hourly_roll_note("slot_" + tok, "h3.slot_music")
    return float(u)


def _h3_slot_music_said(tok: str, row: dict[str, Any]) -> str:
    if not row:
        return ""
    got = _H3_HOURLY_ROLLS.get("slot_" + tok)
    if isinstance(got, dict):
        got["picked"] = ("%s - %s" % (row.get("title") or "", row.get("artist") or ""))[:300]
    return h3_slots.music(row)


async def h3_slot_music(tok: str) -> str:
    total = int(await asyncio.to_thread(h3_slot_shelf, "music") or 0)
    u = _h3_slot_music_roll(tok, total)
    if u is None:
        return ""
    return _h3_slot_music_said(tok, await asyncio.to_thread(h3_slot_music_row, u, total))


def h3_slot_music_sync(tok: str) -> str:
    total = int(h3_slot_shelf("music") or 0)
    u = _h3_slot_music_roll(tok, total)
    if u is None:
        return ""
    return _h3_slot_music_said(tok, h3_slot_music_row(u, total))


# {offer}: a feature (with its release log - h3_feature_take, so {feature} and
# {releaselog} elsewhere in the hour agree) or a product.
def _h3_slot_offer_kind(tok: str) -> str:
    kinds = list(H3_OFFER_KINDS)
    got = s3_choice("h3.slot_offer", kinds, H3_SLOT_LABELS["offer"])
    got = got if got in kinds else kinds[0]
    _h3_slot_note("slot_" + tok, "h3.slot_offer", kinds, got)
    return got


def _h3_slot_offer_said(tok: str, kind: str, feats: Any, products: Any) -> str:
    digit = tok[len("offer"):]
    if kind == "a feature":
        f = h3_feature_take(feats, digit)
        if f:
            return h3_slots.offer("feature", f)
        pipeline_log("ads", "hourly H3 prompts: {%s} rolled a feature but the release log has none - a product instead" % tok)
    shelf = [p for p in (products if isinstance(products, list) else h3_products_shelf()) if isinstance(p, dict)]
    if not shelf:
        pipeline_log("ads", "hourly H3 prompts: {%s} - nothing to offer, taken out" % tok)
        return ""
    labels = [str(e.get("name") or "")[:120] for e in shelf]
    k = s3_weighted("h3.slot_product", labels, [1.0] * len(labels), H3_SLOT_LABELS["product"])
    k = k if isinstance(k, int) and 0 <= k < len(labels) else 0
    _h3_slot_note("slot_" + tok + "_product", "h3.slot_product", labels, labels[k])
    return h3_slots.offer("product", shelf[k])


async def h3_slot_offer(tok: str) -> str:
    kind = _h3_slot_offer_kind(tok)
    feats: Any = None
    products: Any = None
    if kind == "a feature":
        feats = h3_feature_pool()
        if not feats:
            try:
                feats = h3_feature_pool(await asyncio.wait_for(asyncio.to_thread(_CHANGELOG.page, 300), timeout=5.0))
            except Exception:  # noqa: BLE001 - no release log: a product is offered instead
                feats = {}
    if kind != "a feature" or not feats:
        products = await asyncio.to_thread(h3_products_shelf)
    return _h3_slot_offer_said(tok, kind, feats, products)


def h3_slot_offer_sync(tok: str) -> str:
    kind = _h3_slot_offer_kind(tok)
    return _h3_slot_offer_said(tok, kind, None, h3_products_shelf() if kind != "a feature" else None)


# {brand}: a surface from the tabled pool (the desk can retire one), carrying
# the hour's {speakerbox} sentence - one roll of the sentence, shared with the
# text's own {speakerbox} through the memo; each digit is its own surface.
def h3_slot_brand(tok: str) -> str:
    pool = [s for s in (s3_pool("h3.slot_brand", h3_slots.BRANDED, H3_SLOT_LABELS["brand"]) or [])
            if s in h3_slots.BRANDED] or list(h3_slots.BRANDED)
    surface = s3_choice("h3.slot_brand", pool, H3_SLOT_LABELS["brand"], tabled=False)
    surface = surface if surface in pool else pool[0]
    _h3_slot_note("slot_" + tok, "h3.slot_brand", pool, surface)
    vals = _H3_SLOT_MEMO["vals"]
    if not isinstance(vals.get("speakerbox"), str):
        vals["speakerbox"] = _h3_slot_speakerbox()
    return h3_slots.brand(surface, vals["speakerbox"])


# {protagonist}: renders or clips, then a folder, then the one - three rolls,
# each on the rolodex; the pick is kept on the memo for the hourly door, which
# renders the hour FROM it (h3_hourly_protagonist). The door's only: the pick
# routes the hour's source.
def h3_slot_clip_folders() -> list[str]:
    """The clip book's folders holding a playable video clip, fullest first. A worker thread's."""
    con = sfx_db_reader()
    with _SFX_DB_LOCK:
        rows = con.execute("SELECT folder, COUNT(*) AS n FROM clips WHERE playable=1 AND video=1 "
                           "GROUP BY folder ORDER BY n DESC").fetchall()
    return [str(r[0]) for r in rows if r[0]][:H3_SLOT_SHELF_MOST]


def h3_slot_clip_rows(folder: str) -> list[dict[str, Any]]:
    """One folder's playable video clips, the newest indexed first: sid, name,
    seconds and what each shows or says. A worker thread's."""
    con = sfx_db_reader()
    with _SFX_DB_LOCK:
        try:
            rows = con.execute("SELECT sid, name, seconds, COALESCE(seen_desc,''), COALESCE(said,'') FROM clips "
                               "WHERE playable=1 AND video=1 AND folder=? ORDER BY seen_at DESC, name LIMIT ?",
                               (folder, H3_SLOT_SHELF_MOST)).fetchall()
        except Exception:  # noqa: BLE001 - a book without the vision and speech columns
            rows = con.execute("SELECT sid, name, seconds, '', '' FROM clips WHERE playable=1 AND video=1 AND folder=? "
                               "ORDER BY seen_at DESC, name LIMIT ?", (folder, H3_SLOT_SHELF_MOST)).fetchall()
    return [{"sid": str(r[0] or ""), "name": str(r[1] or ""), "seconds": round(float(r[2] or 0), 2),
             "seen_desc": str(r[3] or ""), "said": str(r[4] or "")} for r in rows if r[0]]


def _h3_slot_protagonist_roll(tok: str, stage: str, labels: list[str]) -> int:
    key = "h3.slot_protagonist_" + stage
    k = s3_weighted(key, [str(x)[:120] for x in labels], [1.0] * len(labels), H3_SLOT_LABELS["protagonist_" + stage])
    k = k if isinstance(k, int) and 0 <= k < len(labels) else 0
    _h3_slot_note("slot_" + tok + "_" + stage, key, [str(x) for x in labels], str(labels[k]))
    return k


async def h3_slot_protagonist(tok: str) -> str:
    kinds = list(h3_slots.PROTAGONIST_KINDS)
    kind = kinds[_h3_slot_protagonist_roll(tok, "kind", kinds)]
    pick: dict[str, Any] = {}
    if kind == "clips":
        folders = await asyncio.to_thread(h3_slot_clip_folders)
        if folders:
            folder = folders[_h3_slot_protagonist_roll(tok, "folder", folders)]
            rows = await asyncio.to_thread(h3_slot_clip_rows, folder)
            if rows:
                row = rows[_h3_slot_protagonist_roll(tok, "clip", [h3_slots.clip_label(r) for r in rows])]
                pick = {"kind": "clips", "folder": folder, "sid": row["sid"], "name": row["name"],
                        "seconds": row["seconds"], "seen_desc": row["seen_desc"], "said": row["said"]}
        if not pick:
            pipeline_log("ads", "hourly H3 prompts: {%s} rolled the clips but the book has no playable video clip - "
                                "the renders instead" % tok)
            kind = "renders"
    if kind == "renders":
        folders = list(h3_slots.RENDER_FOLDERS)
        folder = folders[_h3_slot_protagonist_roll(tok, "folder", folders)]
        items = list(await asyncio.to_thread(h3_slot_shelf, "arena" if folder == "pictures" else "videos") or [])
        if not items:
            other = "videos" if folder == "pictures" else "pictures"
            items = list(await asyncio.to_thread(h3_slot_shelf, "arena" if other == "pictures" else "videos") or [])
            if items:
                pipeline_log("ads", "hourly H3 prompts: {%s} rolled the gallery %s but there are none - the %s instead"
                             % (tok, folder, other))
                folder = other
        if items:
            file = items[_h3_slot_protagonist_roll(tok, "clip", [h3_slots.tidy(x) for x in items])]
            pick = {"kind": "renders", "folder": folder, "file": str(file), "name": str(file)}
    if not pick:
        pipeline_log("ads", "hourly H3 prompts: {%s} - no clip and no render to star, taken out" % tok)
        _H3_SLOT_MEMO.pop("protagonist", None)
        return ""
    pick["words"] = h3_slots.protagonist(pick)
    _H3_SLOT_MEMO["protagonist"] = pick
    _H3_SLOT_MEMO["protagonist_at"] = _H3_SLOT_MEMO["at"]
    return pick["words"]


async def h3_hourly_protagonist(goal: str) -> tuple[str, Any, str] | None:
    """[pineex] The hour's source when its preset rolled a {protagonist}: the
    stinger is made FROM the rolled clip or render. A clip rides the clip road
    (voice_ad_render, the clip its reference); a gallery picture the gallery
    road; a gallery video the Workshop's own "generation" reference road
    (workshop_source_path resolves a COMFY_OUTPUT video to a video reference;
    voice_ad_render takes only clip-book sids). The pick is written on the hour
    as its "source" roll. None when the hour has no protagonist: the source
    rolls as it always has."""
    star = _H3_SLOT_MEMO.get("protagonist")
    if not isinstance(star, dict) or not star or _H3_SLOT_MEMO.get("protagonist_at") != _H3_SLOT_MEMO["at"]:
        return None
    words = str(star.get("words") or "")[:200]
    rec = dict(_h3_slot_last("h3.slot_protagonist_kind"), key="h3.slot_protagonist_kind", picked=words)
    if star.get("kind") == "clips" and star.get("sid"):
        clip = {"id": str(star["sid"]), "name": str(star.get("name") or "clip")[:120],
                "seconds": round(float(star.get("seconds") or 0), 2), "video": True,
                "match": "the hour's protagonist, from the clip book folder %s" % str(star.get("folder") or "")[:80]}
        trims: dict[str, Any] = {}
        if clip["seconds"] > 0:
            trim_in, trim_out = h3_hourly_window(clip)
            h3_hourly_roll_note("marker", "h3.hourly_marker")
            trims = {"trim_in_s": trim_in, "trim_out_s": trim_out}
        h3_hourly_roll_note("source", "h3.slot_protagonist_kind", rec=rec)
        h3_hourly_rolls_bind(goal)
        message, job = await voice_ad_render(goal, reference_clip=clip, hourly=True, **trims)
        pipeline_log("ads", "hourly H3: the protagonist is the clip %s (%s) [pineex]" % (clip["name"], clip["id"]))
        return ("%s - the protagonist is the clip %s" % (message, clip["name"]), job, "clip")
    file = str(star.get("file") or "")
    if star.get("kind") == "renders" and file:
        video = file.lower().endswith((".mp4", ".webm"))
        h3_hourly_roll_note("source", "h3.slot_protagonist_kind", rec=rec)
        h3_hourly_rolls_bind(goal)
        payload = {"mode": "reference", "purpose": "parody_stinger", "source": file,
                   "source_type": "generation" if video else "gallery", "speech": voice_ad_spoken_copy(goal),
                   "prompt": ("Create a Pine Box FM stinger using the supplied %s; the figure in it is the "
                              "protagonist. Natural motion and synchronized spoken dialogue. No captions or logos. "
                              % ("video" if video else "image")) + goal,
                   "duration_mode": "at_least", "steps": 4, "air_it": False, "hourly": True}
        if video:
            payload["at_share"] = s3_roll("ad.voice_at_share",
                                          "where in its source clip a voice ad's performance is taken (a share of the clip)")
        queued = _parody_stinger_queue().add(payload)
        _parody_stinger_wake.set()
        pipeline_log("ads", "hourly H3: the protagonist is the gallery %s %s [pineex]" % ("video" if video else "picture", file))
        return ("queued a protagonist stinger from the gallery %s %s" % ("video" if video else "picture", file),
                queued, "gallery video" if video else "gallery image")
    return None


# {research}: the hour's {topic} (one roll, shared) or a rolled Gazette headline,
# through the station's own research road - one search, kept an hour, judged
# under the operator's per-site word - waited for at most
# H3_SLOT_RESEARCH_WAIT_S; one judged result rolled. The door's only: it awaits the web.
async def h3_slot_research(tok: str) -> str:
    topic = h3_slot_topic()
    if not topic:
        rows = await asyncio.to_thread(h3_slot_shelf, "gazette")
        heads = [str(r.get("headline") or "")[:120] for r in (rows or []) if isinstance(r, dict) and r.get("headline")]
        if heads:
            k = s3_weighted("h3.slot_research_topic", heads, [1.0] * len(heads), H3_SLOT_LABELS["research_topic"])
            k = k if isinstance(k, int) and 0 <= k < len(heads) else 0
            _h3_slot_note("slot_" + tok + "_topic", "h3.slot_research_topic", heads, heads[k])
            topic = heads[k]
    if not topic:
        pipeline_log("ads", "hourly H3 prompts: {%s} - no topic and no Gazette headline to search, taken out" % tok)
        return ""
    if not settings_web_search():
        pipeline_log("ads", "hourly H3 prompts: {%s} - the web search is off in settings, taken out" % tok)
        return ""
    key = _s3_research_key(topic)
    _s3_research_load()
    held = _S3_RESEARCH.get(key) or {}
    if not held or time.time() - float(held.get("at") or 0) > S3_RESEARCH_KEEP_S:
        if key not in _S3_RESEARCH_BUSY:
            _S3_RESEARCH_BUSY.add(key)
            try:
                await asyncio.wait_for(_s3_research_fetch(key, clean_search_query(topic)[:200]),
                                       timeout=H3_SLOT_RESEARCH_WAIT_S)
            except Exception as exc:  # noqa: BLE001 - a slow web is a slot taken out, never a lost hour
                pipeline_log("ads", "hourly H3 prompts: {%s} - the search did not answer in %.0f s (%s)"
                             % (tok, H3_SLOT_RESEARCH_WAIT_S, type(exc).__name__))
        else:
            waited = 0.0
            while key in _S3_RESEARCH_BUSY and waited < H3_SLOT_RESEARCH_WAIT_S:
                await asyncio.sleep(0.5)
                waited += 0.5
        held = _S3_RESEARCH.get(key) or {}
    rows = [r for r in (held.get("results") or []) if isinstance(r, dict)
            and r.get("verdict") in ("used", "spare") and (r.get("snippet") or r.get("title"))]
    if not rows:
        pipeline_log("ads", 'hourly H3 prompts: {%s} - the web had nothing usable on "%s", taken out' % (tok, topic[:60]))
        return ""
    labels = [str(r.get("title") or r.get("snippet") or "")[:120] for r in rows]
    k = s3_weighted("h3.slot_research", labels, [1.0] * len(labels), H3_SLOT_LABELS["research"])
    k = k if isinstance(k, int) and 0 <= k < len(labels) else 0
    _h3_slot_note("slot_" + tok, "h3.slot_research", labels, labels[k])
    return h3_slots.research(topic, rows[k])


async def h3_slots_preroll(*texts: Any) -> dict[str, str]:
'''

PREROLL_OLD = '''            elif name == "sfxclip":
                got = await h3_slot_sfxclip(tok)
            elif name == "convograph":
                got = await h3_slot_convograph(tok)
'''
PREROLL_NEW = '''            elif name == "sfxclip":
                got = await h3_slot_sfxclip(tok)
            elif name == "convograph":
                got = await h3_slot_convograph(tok)
            elif name == "music":                                          # [pineex] wave C
                got = await h3_slot_music(tok)
            elif name == "offer":
                got = await h3_slot_offer(tok)
            elif name == "brand":
                got = h3_slot_brand(tok)
            elif name == "protagonist":
                got = await h3_slot_protagonist(tok)
            elif name == "research":
                got = await h3_slot_research(tok)
'''

SYNC_OLD = '''    name = h3_slots.base(tok)
    if name == "convograph":
        pipeline_log("ads", "hourly H3 prompts: {%s} is rolled by the hourly door only - taken out here" % tok)
        return ""
    if name in ("feature", "releaselog"):                                 # [h3-feature]
        return h3_slot_feature(tok)
'''
SYNC_NEW = '''    name = h3_slots.base(tok)
    if name in ("convograph", "protagonist", "research"):                  # [pineex] System 3's store, the source route, the web
        pipeline_log("ads", "hourly H3 prompts: {%s} is rolled by the hourly door only - taken out here" % tok)
        return ""
    if name in ("feature", "releaselog"):                                 # [h3-feature]
        return h3_slot_feature(tok)
    if name == "music":                                                  # [pineex] wave C
        return h3_slot_music_sync(tok)
    if name == "offer":
        return h3_slot_offer_sync(tok)
    if name == "brand":
        return h3_slot_brand(tok)
'''

TOPIC_OLD = '''    if "{topic}" in str(template):
        choices = [str(t.get("text") or t.get("topic") or "") if isinstance(t, dict) else str(t) for t in read_bombshells()]
        choices = [x for x in choices if x.strip()]
        values.setdefault("topic", s3_choice("h3.plot_topic", choices, "which topic an H3 prompt uses") if choices else "")
'''
TOPIC_NEW = '''    if "{topic}" in str(template):
        values.setdefault("topic", h3_slot_topic())            # [pineex] one roll per hour, shared with {research}
'''

DOOR_OLD = '''    _h3_gallery = False
    if share:
'''
DOOR_NEW = '''    # [pineex] the hour's {protagonist}, when its preset rolled one: the stinger
    # is made FROM that clip or render, in place of the gallery-or-clip roll
    _h3_star = await h3_hourly_protagonist(goal) if globals().get("h3_hourly_protagonist") else None
    if _h3_star:
        return _h3_star
    _h3_gallery = False
    if share:
'''

ROUTES_OLD = '''    require_auth(authorization)
    return await asyncio.to_thread(h3_prompts_delete, pid[:40])
'''
ROUTES_NEW = '''    require_auth(authorization)
    return await asyncio.to_thread(h3_prompts_delete, pid[:40])


# --- [pineex] THE PRODUCTS API: the list {product} rolls over, grown from the desk -----------------
@app.get("/api/h3/products")
async def h3_products_get(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[pineex] What {product} rolls over: the station's own list (data/h3_products.json,
    seeded with its offerings) and the DJ setting's products to place."""
    require_read_auth(authorization)
    return await asyncio.to_thread(h3_products_view)


@app.post("/api/h3/products")
async def h3_products_add_api(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[pineex] {name, pitch}: one more item on the list."""
    require_auth(authorization)
    body = await _h3_prompts_body(request)
    return await asyncio.to_thread(h3_products_add, str(body.get("name") or ""), str(body.get("pitch") or ""))


@app.post("/api/h3/products/{pid}/delete")
async def h3_products_delete_api(pid: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[pineex] Take an item off the list (a dj.sponsors line is the DJ settings' to edit)."""
    require_auth(authorization)
    return await asyncio.to_thread(h3_products_delete, pid[:40])
'''

EDITS = {
    "h3_slots.py": [
        ("CATALOGUE explains the six new slots", SLOTS_CATALOGUE_OLD, SLOTS_CATALOGUE_NEW, 1),
        ("NAMED knows music, product, offer, brand, protagonist, research", SLOTS_NAMED_OLD, SLOTS_NAMED_NEW, 1),
        ("BRANDED, PROTAGONIST_KINDS, RENDER_FOLDERS and the phrase functions", SLOTS_FUNCS_OLD, SLOTS_FUNCS_NEW, 1),
    ],
    "app.py": [
        ("H3_SLOT_NAMES mirrors NAMED (less the book slots)", NAMES_OLD, NAMES_NEW, 1),
        ("H3_SLOT_LABELS: the dice of the six", LABELS_OLD, LABELS_NEW, 1),
        ("h3_slot_shelf: the library's size, the products list", SHELF_OLD, SHELF_NEW, 1),
        ("h3_slot_pick: a product's labels", PICK_LABELS_OLD, PICK_LABELS_NEW, 1),
        ("h3_slot_pick: a product's phrase", PICK_PHRASE_OLD, PICK_PHRASE_NEW, 1),
        ("the wave C block: products store, topic, music, offer, brand, protagonist, door route, research",
         BLOCK_OLD, BLOCK_NEW, 1),
        ("h3_slots_preroll dispatches the six", PREROLL_OLD, PREROLL_NEW, 1),
        ("h3_slot_named_sync: music, offer, brand sync; protagonist, research door-only", SYNC_OLD, SYNC_NEW, 1),
        ("h3_speak_fill: {topic} is h3_slot_topic's roll", TOPIC_OLD, TOPIC_NEW, 1),
        ("h3_hourly_render asks h3_hourly_protagonist before the source roll", DOOR_OLD, DOOR_NEW, 1),
        ("GET/POST /api/h3/products, POST /api/h3/products/{id}/delete", ROUTES_OLD, ROUTES_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".pineex.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
