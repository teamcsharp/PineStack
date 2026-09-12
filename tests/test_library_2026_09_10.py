"""The Library (#1158): "I want the LLM locally internalizing it and making
it able to be used in the documentation system and used in (non radio) query."

The measured facts these tests hold in place, all found on the real shelf at
//10.89.1.125/QuickSwap/Manuals while this was built:

  * A 44-chapter EPUB read as ONE BLANK PAGE because `<script src="..."/>` is
    self-closing: routing it through handle_starttag raised the skip counter
    with nothing to lower it again, and every word after it was dropped.
  * The zip on that shelf is not a website bundle, it is the two PDFs that
    already sit beside it loose - so a zip whose members are all on the shelf
    already must be refused, not indexed a second time.
  * "play some music" scored 0.63 against a book about music production and
    "what time is it" 0.55, because a manual really is about music and really
    does discuss time. Similarity cannot separate those from a real question;
    SPECIFICITY can - does the question use a word only part of the shelf
    knows?
"""
import asyncio
import json
import math
import re
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import library
import library_extract as extract


# --------------------------------------------------------------- fixtures

CHAPTER_ONE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head>
<title>Chopping</title>
<link rel="stylesheet" href="css/book.css" type="text/css"/>
<script src="js/book.js"/>
<meta charset="UTF-8"/>
</head><body onload="Body_onLoad()">
<h1>C02: Chopping Techniques</h1>
<p><img src="images/pad.png" alt="the pads"/></p>
<p>Hold the sixteen levels button and press a pad to slice the loop into
even chops across the pad bank. Each chop keeps its own start point.</p>
<p>Chop mode divides the whole sample at once, where trim mode only crops
the start and the end of it. Once the slices are made, convert them to a
new program and every pad plays one slice, so the loop can be rebuilt in a
different order without ever leaving the pads.</p>
<p><a href="ch2.xhtml" onclick="alert(1)">Next</a></p>
</body></html>
"""

CHAPTER_TWO = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Keygroups</title>
</head><body>
<h1>D01: Keygroup Programs</h1>
<p>A keygroup program spreads one sample across a range of notes. Set the
low and high note for each keygroup, then tune the root.</p>
</body></html>
"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="i">
 <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>The Test Bible</dc:title>
 </metadata>
 <manifest>
  <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
        properties="nav"/>
  <item id="p1" href="images/pad.png" media-type="image/png"/>
 </manifest>
 <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>
"""

NAV = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><nav>
<ol><li><a href="ch1.xhtml">Chopping Techniques</a></li>
<li><a href="ch2.xhtml">Keygroup Programs</a></li></ol>
</nav></body></html>
"""

CONTAINER = ("""<?xml version="1.0"?><container version="1.0" """
             """xmlns="urn:oasis:names:tc:opendocument:xmlns:container">"""
             """<rootfiles><rootfile full-path="OPS/book.opf" """
             """media-type="application/oebps-package+xml"/></rootfiles>"""
             """</container>""")

# a one-pixel png, so the figure road has something real to carry
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


def build_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OPS/book.opf", OPF)
        zf.writestr("OPS/ch1.xhtml", CHAPTER_ONE)
        zf.writestr("OPS/ch2.xhtml", CHAPTER_TWO)
        zf.writestr("OPS/nav.xhtml", NAV)
        zf.writestr("OPS/images/pad.png", PNG)


def bag_embed(dims: int = 96):
    """A deterministic stand-in for nomic-embed-text: a bag of words folded
    into a fixed number of buckets, normalised. Cosine then reflects word
    overlap, which is all these tests need to reason about."""
    async def embed(texts):
        out = []
        for text in texts:
            vec = [0.0] * dims
            for word in re.findall(r"[a-z0-9]+", str(text).lower()):
                vec[hash(word) % dims] += 1.0
            mag = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / mag for x in vec])
        return out
    return embed


def page_score(page, words):
    """The shape of app.py's _te_page_score, which the app injects for real."""
    text = str(page.get("text") or "").lower()
    head = str(page.get("heading") or "").lower()
    score = 0.0
    for word in words:
        hits = text.count(word)
        if hits:
            score += 1.0 + min(hits, 6) * 0.35
        if word in head:
            score += 3.0
    return score


# ------------------------------------------------------------- extraction


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_epub_reads_every_chapter_past_a_self_closing_script(self):
        """The regression that made a 44-chapter book read as one blank page."""
        book = self.root / "bible.epub"
        build_epub(book)
        out = self.root / "out"
        got = extract.read_document(book, out)

        self.assertEqual(got["kind"], "epub")
        self.assertEqual(got["title"], "The Test Bible")
        self.assertEqual(len(got["pages"]), 2)
        self.assertFalse(got["thin"])
        # Chapter one's words survive the <script src="..."/> that precedes
        # them. This is the whole point of the test.
        self.assertIn("sixteen levels", got["pages"][0]["text"])
        self.assertIn("chops across the pad bank", got["pages"][0]["text"])
        self.assertIn("keygroup", got["pages"][1]["text"].lower())
        # The nav document is a table of contents, not a chapter.
        self.assertNotIn("nav.xhtml",
                         [p["source_url"] for p in got["pages"]])
        self.assertEqual(got["pages"][0]["heading"], "chopping techniques")

    def test_epub_chapters_are_written_out_sanitised_for_the_reader(self):
        book = self.root / "bible.epub"
        build_epub(book)
        out = self.root / "out"
        got = extract.read_document(book, out)

        self.assertEqual(got["figures"], 1)
        self.assertTrue((out / "pages" / "img" / "OPS_images_pad.png").is_file())
        html = (out / "pages" / "0001.html").read_text(encoding="utf-8")
        # Nothing executable, nothing that reaches off the box.
        for forbidden in ("<script", "onload", "onclick", "<link", "href="):
            self.assertNotIn(forbidden, html, forbidden)
        # ...and the figure still points at the file we extracted.
        self.assertIn('src="img/OPS_images_pad.png"', html)
        self.assertIn("sixteen levels", html)

    def test_a_zip_that_only_repackages_the_shelf_is_refused(self):
        loose = self.root / "guide.txt"
        loose.write_text("Hold shift and press step to set a component.\n"
                         "The value is chosen with the black keys.\n",
                         encoding="utf-8")
        bundle = self.root / "bundle.zip"
        with zipfile.ZipFile(bundle, "w") as zf:
            zf.write(loose, "guide.txt")

        # Nothing else on the shelf yet: the bundle is worth reading.
        first = extract.read_document(bundle, None)
        self.assertTrue(first["pages"])

        # Once the loose file is on the shelf, the bundle adds nothing.
        with self.assertRaises(extract.ExtractError) as caught:
            extract.read_document(bundle, None,
                                  skip_shas={extract.file_sha(loose)})
        self.assertIn("already on the shelf", str(caught.exception))

    def test_the_scanner_leaves_windows_litter_and_strangers_alone(self):
        shelf = self.root / "Manuals"
        (shelf / "deep" / "deeper").mkdir(parents=True)
        (shelf / "Thumbs.db").write_bytes(b"not a document")
        (shelf / ".hidden.pdf").write_bytes(b"%PDF-")
        (shelf / "notes.md").write_text("# real", encoding="utf-8")
        (shelf / "cover.png").write_bytes(PNG)
        (shelf / "deep" / "manual.txt").write_text("real", encoding="utf-8")
        (shelf / "deep" / "deeper" / "buried.txt").write_text("x",
                                                              encoding="utf-8")

        found = {p.name for p in extract.scan_folder(shelf)}
        self.assertEqual(found, {"notes.md", "manual.txt"})
        self.assertEqual(extract.doc_kind(shelf / "Thumbs.db"), "")
        self.assertEqual(extract.doc_kind(shelf / "cover.png"), "")

    def test_plain_text_is_cut_into_citable_pages_at_its_headings(self):
        path = self.root / "notes.md"
        path.write_text("# First\n\nabcd efgh ijkl mnop qrst uvwx yzab.\n\n"
                        "# Second\n\nmore words that carry a second idea.\n",
                        encoding="utf-8")
        got = extract.read_document(path, None)
        self.assertEqual(len(got["pages"]), 2)
        self.assertEqual(got["pages"][0]["n"], 1)
        self.assertEqual(got["pages"][1]["n"], 2)
        self.assertIn("second idea", got["pages"][1]["text"])


# ---------------------------------------------------------------- chunking


class ChunkTests(unittest.TestCase):
    def test_chunks_overlap_so_a_straddled_fact_stays_findable(self):
        text = " ".join(f"word{i}" for i in range(600))
        chunks = library.page_chunks(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), library.CHUNK_CHARS)
            self.assertGreaterEqual(len(chunk), library.CHUNK_MIN)
        # every neighbour shares its tail with the next one's head
        for first, second in zip(chunks, chunks[1:]):
            tail = first[-40:].split()
            self.assertTrue(any(word in second for word in tail),
                            "no overlap between neighbouring chunks")

    def test_a_chunk_never_crosses_a_page_and_carries_where_it_came_from(self):
        doc = {"title": "Guide", "pages": [
            {"n": 4, "heading": "sampling", "text": "alpha " * 200},
            {"n": 5, "heading": "mixer", "text": "beta " * 200},
        ]}
        rows = library.doc_chunks(doc, "guide-1")
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["slug"], "guide-1")
            self.assertIn(row["page"], (4, 5))
            if row["page"] == 4:
                self.assertNotIn("beta", row["text"])
                self.assertEqual(row["heading"], "sampling")
            else:
                self.assertNotIn("alpha", row["text"])
        # the heading rides along in what is embedded, not in what is shown
        self.assertTrue(rows[0]["embed"].startswith("Guide — sampling: ")
                        or rows[0]["embed"].startswith("Guide - sampling: "))


# ------------------------------------------------------- the shelf, end to end


class ShelfTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.shelf = self.root / "Manuals"
        self.shelf.mkdir()
        library._INDEX = None
        library._SHARDS.clear()
        self.addCleanup(library._SHARDS.clear)
        library.configure(data_dir=self.root / "library", embed=bag_embed(),
                          page_score=page_score)

    def write(self, name: str, body: str) -> Path:
        path = self.shelf / name
        path.write_text(body, encoding="utf-8")
        return path

    async def test_a_new_file_is_assimilated_and_then_findable(self):
        self.write("opxy.md",
                   "# Step components\n\n"
                   + "Hold shift and tap a step to open the step component "
                     "picker on the OPXY keyboard. " * 6)
        got = await library.ingest_pass([self.shelf])

        self.assertEqual(got["read"], 1)
        self.assertGreater(got["chunks"], 0)
        rows = library.docs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "ready")
        self.assertTrue(rows[0]["sha"])
        # both halves of the memory landed, and they agree
        npy, jsl = library.shard_paths(rows[0]["slug"])
        self.assertTrue(npy.is_file() and jsl.is_file())
        held = library.shard_load(rows[0]["slug"])
        self.assertIsNotNone(held)
        self.assertEqual(held[0].shape[0], len(held[1]))

        hits = await library.search("step component picker OPXY keyboard", k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["slug"], rows[0]["slug"])
        self.assertIn("step component", hits[0]["text"])

    async def test_a_changed_file_is_re_read_and_a_deleted_one_forgotten(self):
        path = self.write("guide.md", "# Tape\n\n" + "the tape speed dial. " * 30)
        await library.ingest_pass([self.shelf])
        slug = library.docs()[0]["slug"]

        # unchanged: the second pass does no work at all
        again = await library.ingest_pass([self.shelf])
        self.assertEqual(again["read"], 0)

        # changed on disk: read again
        path.write_text("# Tape\n\n" + "the reverse tape brake. " * 30,
                        encoding="utf-8")
        import os
        os.utime(path, (0, 0))          # anything but the recorded mtime
        third = await library.ingest_pass([self.shelf])
        self.assertEqual(third["read"], 1)

        # gone from the shelf: gone from the memory, files and all
        path.unlink()
        fourth = await library.ingest_pass([self.shelf])
        self.assertEqual(fourth["forgotten"], 1)
        self.assertEqual(library.docs(), [])
        npy, jsl = library.shard_paths(slug)
        self.assertFalse(npy.exists())
        self.assertFalse(jsl.exists())
        self.assertFalse(library.vocab_path(slug).exists())
        self.assertEqual(await library.search("tape brake"), [])

    async def test_the_shelf_stays_shut_for_words_every_document_knows(self):
        for name in ("one.md", "two.md", "three.md", "four.md"):
            self.write(name, "# Music\n\n"
                       + "play the music and watch the time go by. " * 20
                       + "\n\n# Special\n\n"
                       + f"the {name[:3]}gizmo control does its own thing. " * 8)
        await library.ingest_pass([self.shelf])

        counts, ready = library._document_frequency()
        self.assertEqual(ready, 4)
        self.assertEqual(counts.get("music"), 4)     # every document
        self.assertEqual(counts.get("onegizmo"), 1)  # only one

        # A question made only of words the whole shelf uses is not a
        # question the shelf can answer.
        self.assertFalse(library.shelf_question("play the music"))
        self.assertFalse(library.shelf_question("the time"))
        # ...but one rare word is enough to open it.
        self.assertTrue(library.shelf_question("onegizmo control"))
        self.assertEqual(await library.search("play the music"), [])

    async def test_the_console_search_is_not_gated_the_chat_road_is(self):
        self.write("a.md", "# Music\n\n" + "play the music loudly. " * 30)
        self.write("b.md", "# Music\n\n" + "play the music quietly. " * 30)
        await library.ingest_pass([self.shelf])

        self.assertEqual(await library.search("play the music"), [])
        opened = await library.search("play the music", gate=False)
        self.assertTrue(opened, "somebody typing into the shelf's own search "
                                "box means it")

    async def test_one_thick_manual_cannot_fill_the_whole_answer(self):
        big = "# Chopping\n\n" + "chop the sample into slices. " * 400
        self.write("thick.md", big)
        self.write("thin.md", "# Chopping\n\n" + "chop the sample here. " * 20)
        await library.ingest_pass([self.shelf])

        hits = await library.search("chop the sample into slices", k=6,
                                    per_doc=2)
        by_doc = {}
        for hit in hits:
            by_doc[hit["slug"]] = by_doc.get(hit["slug"], 0) + 1
        self.assertTrue(by_doc)
        for count in by_doc.values():
            self.assertLessEqual(count, 2)

    async def test_an_unreadable_file_is_recorded_not_fatal(self):
        (self.shelf / "broken.pdf").write_bytes(b"this is not a pdf at all")
        self.write("fine.md", "# Fine\n\n" + "the gizmo control works. " * 20)
        got = await library.ingest_pass([self.shelf])

        states = {r["name"]: r["state"] for r in library.docs()}
        self.assertEqual(states["fine.md"], "ready")
        self.assertIn(states["broken.pdf"], ("skipped", "failed"))
        self.assertTrue(next(r["note"] for r in library.docs()
                             if r["name"] == "broken.pdf"))
        self.assertGreaterEqual(got["read"], 1)

    async def test_the_section_road_gives_the_run_up_not_one_orphan_page(self):
        self.write("m.md", "\n\n".join(
            f"# Part {i}\n\nthe part{i} control is set with the encoder. " * 4
            for i in range(1, 6)))
        await library.ingest_pass([self.shelf])
        slug = library.docs()[0]["slug"]

        text = library.section(slug, 3, "part3 control")
        self.assertIn("part3", text)
        self.assertIn("[page 3", text)
        self.assertGreater(text.count("[page"), 1,
                           "the neighbours should come with it")

    async def test_a_book_asked_for_by_name_outranks_the_gear_corpus(self):
        """Measured: "what does the MPC Bible say about chopping a sample"
        was answered out of the GEAR manuals, because "MPC" is a device alias
        there - so the book the operator named never got a look. Two
        distinctive words of a title have to line up, which is why "chop it
        on the MPC" is still the gear manuals' question, not the shelf's."""
        self.write("MPC Bible 3.md",
                   "# Chopping\n\n" + "chop the sample into slices. " * 30)
        self.write("CyDrums manual.md",
                   "# Stutter\n\n"
                   + "stutter the playback across tracks. " * 30)
        await library.ingest_pass([self.shelf])
        by_name = {r["name"]: r["slug"] for r in library.docs()}

        self.assertEqual(library.named_document("what does the MPC Bible say"),
                         by_name["MPC Bible 3.md"])
        self.assertEqual(library.named_document("the cydrums manual"),
                         by_name["CyDrums manual.md"])
        # one word of a title is not naming it - that stays the gear corpus'
        self.assertEqual(library.named_document("how do I chop on the MPC"), "")
        self.assertEqual(library.named_document("bible"), "")

    async def test_a_transcript_supports_an_answer_but_never_triggers_one(self):
        """Measured on the real shelf once 321 speakbox transcripts joined
        the eight manuals: "write me a poem about rain" (words 3.1, cosine
        0.65) and "sing me a song about the sea" (4.4, 0.62) both beat "what
        are keygroup programs" (3.1, 0.63). No floor separates those, because
        every false positive came from a TRANSCRIPT and every true one from a
        MANUAL. So documentation opens the shelf and a record of speech does
        not - though it still rides along once the shelf is open."""
        talk = self.root / "speakbox"
        talk.mkdir()
        (talk / "show.md").write_text(
            "# Rain\n\n" + "we talked about the rain and the poem of it. " * 40,
            encoding="utf-8")
        self.write("gizmo.md",
                   "# Gizmo\n\n" + "the gizmo encoder sets the rain delay. " * 40)
        library.configure(data_dir=self.root / "library", embed=bag_embed(),
                          page_score=page_score, reference=[str(self.shelf)])
        await library.ingest_pass([self.shelf, talk])

        by_name = {r["name"]: r["slug"] for r in library.docs()}
        self.assertTrue(library.is_reference(by_name["gizmo.md"]))
        self.assertFalse(library.is_reference(by_name["show.md"]))

        # the transcript alone cannot open the shelf...
        self.assertEqual(await library.search("the poem of it"), [])
        # ...but a documentation question opens it, and then the transcript
        # is allowed to ride along on the same subject.
        hits = await library.search("the gizmo encoder rain delay", k=6)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["slug"], by_name["gizmo.md"])

    def test_an_epub_is_cited_by_chapter_and_a_pdf_by_page(self):
        self.assertEqual(library.page_word("epub"), "chapter")
        self.assertEqual(library.page_word("zip"), "chapter")
        self.assertEqual(library.page_word("pdf"), "page")
        self.assertEqual(library.page_word("epub", plural=True), "chapters")

    def test_a_document_keeps_its_folder_across_restarts(self):
        """PYTHONHASHSEED is random per process; builtin hash() would hand
        the same document a new folder on every restart."""
        first = library.slug_for("/samples/Manuals/OP1 Field Notebook.pdf")
        self.assertEqual(
            first, library.slug_for("/samples/Manuals/OP1 Field Notebook.pdf"))
        self.assertNotEqual(
            first, library.slug_for("/other/OP1 Field Notebook.pdf"))
        self.assertTrue(re.fullmatch(r"[a-z0-9-]+", first))


if __name__ == "__main__":
    unittest.main()
