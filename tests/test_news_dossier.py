import asyncio
import json
import unittest

from news_dossier import fetch_service, public_url


STORY = "https://paper.example.com/news/council-vote"
TITLE = "Council votes on major downtown repair proposal"
PROSE = (
    "The council voted Tuesday to approve the downtown repair proposal. "
    "The published measure sets out a two-year schedule for work on roads and pipes. "
    "Officials said the first contracts will be considered next month. "
    "The vote and schedule appear in the council's public meeting record."
)


async def public_resolver(host):
    return ["93.184.215.14"]


async def no_results(query):
    return []


def page(body, status=200, kind="text/html", url=STORY, **headers):
    return {"url": url, "status_code": status,
            "headers": {"content-type": kind, **headers}, "text": body}


class DossierTests(unittest.IsolatedAsyncioTestCase):
    async def test_publisher_article_uses_injected_station_reader(self):
        calls = []

        async def fetch(url):
            calls.append(url)
            return page("<article>published article</article>")

        def reader(body, url):
            self.assertEqual(url, STORY)
            return {"title": TITLE, "paragraphs": [PROSE]}

        row = await fetch_service(STORY, title="Drudge headline", fetch=fetch,
                                  search=no_results, extract=reader,
                                  resolve=public_resolver)
        self.assertEqual(calls, [STORY])
        self.assertEqual(row["method"], "publisher")
        self.assertEqual(row["availability"], "full")
        self.assertEqual(row["confidence"], "high")
        self.assertEqual(row["title"], TITLE)
        self.assertEqual(row["article_text"], PROSE)
        self.assertEqual(row["evidence_links"], [STORY])
        self.assertTrue(row["fetched_at"].endswith("+00:00"))

    async def test_discovered_rss_returns_only_matching_story_excerpt(self):
        feed = "https://paper.example.com/feed.xml"
        xml = ("<rss><channel><item><title>Unrelated story</title>"
               "<link>https://paper.example.com/news/other</link>"
               "<description>Wrong detail.</description></item>"
               f"<item><title>{TITLE}</title><link>{STORY}</link>"
               "<description>Official summary of the vote.</description>"
               "</item></channel></rss>")

        async def fetch(url):
            if url == STORY:
                return page('<html><head><link rel="alternate" '
                            'type="application/rss+xml" href="/feed.xml"></head>'
                            '<body><h1>Headline</h1></body></html>')
            if url == feed:
                return page(xml, kind="application/rss+xml", url=feed)
            self.fail(f"unexpected fetch: {url}")

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  search=no_results, resolve=public_resolver)
        self.assertEqual(row["method"], "publisher_feed")
        self.assertEqual(row["availability"], "excerpt")
        self.assertEqual(row["excerpt"], "Official summary of the vote.")
        self.assertEqual(row["article_text"], "")
        self.assertIn(feed, row["evidence_links"])

    async def test_public_archive_only_after_unavailable_publisher(self):
        archive = "https://web.archive.org/web/20260924000000/" + STORY
        visited = []

        async def fetch(url):
            visited.append(url)
            if url == STORY:
                return page("not found", status=404)
            if url.startswith("https://archive.org/wayback/available?"):
                return page(json.dumps({"archived_snapshots": {"closest": {
                    "available": True, "url": archive}}}),
                    kind="application/json", url=url)
            if url == archive:
                return page("<article>archived story</article>", url=archive)
            self.fail(f"unexpected fetch: {url}")

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  extract=lambda body, url: {
                                      "title": TITLE, "paragraphs": [PROSE]},
                                  search=no_results, resolve=public_resolver)
        self.assertEqual(row["method"], "public_archive")
        self.assertEqual(row["article_text"], PROSE)
        self.assertEqual(row["source_url"], archive)
        self.assertIn(archive, row["evidence_links"])
        self.assertEqual(visited[-1], archive)

    async def test_discovered_json_publisher_api_is_an_excerpt_not_full_text(self):
        feed = "https://paper.example.com/api/stories.json"

        async def fetch(url):
            if url == STORY:
                return page('<link rel="alternate" type="application/json" '
                            'href="/api/stories.json">')
            self.assertEqual(url, feed)
            return page(json.dumps({"items": [{"url": STORY, "title": TITLE,
                "summary": "The publisher's public summary names the vote."}]}),
                kind="application/json", url=feed)

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  search=no_results, resolve=public_resolver)
        self.assertEqual(row["method"], "publisher_feed")
        self.assertEqual(row["source_url"], feed)
        self.assertEqual(row["article_text"], "")
        self.assertIn("public summary", row["excerpt"])

    async def test_archive_redirect_off_archive_host_is_not_article_evidence(self):
        archive = "https://web.archive.org/web/20260924000000/" + STORY
        other = "https://another.example.org/redirected"

        async def fetch(url):
            if url == STORY:
                return page("unavailable", status=404)
            if url.startswith("https://archive.org/wayback/available?"):
                return page(json.dumps({"archived_snapshots": {"closest": {
                    "available": True, "url": archive}}}),
                    kind="application/json", url=url)
            if url == archive:
                return page("", status=302, url=archive, location=other)
            if url == other:
                return page("<article>" + PROSE + "</article>", url=other)
            self.fail(f"unexpected fetch: {url}")

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  extract=lambda body, url: {"paragraphs": [PROSE]},
                                  search=no_results, resolve=public_resolver)
        self.assertEqual(row["availability"], "metadata")
        self.assertEqual(row["article_text"], "")

    async def test_access_denied_skips_archive_but_uses_search_excerpt(self):
        visited = []

        async def fetch(url):
            visited.append(url)
            return page("Forbidden", status=403)

        async def search(query):
            self.assertIn("site:paper.example.com", query)
            return [{"title": TITLE, "url": STORY,
                     "snippet": "The public index says the council approved repairs."}]

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  search=search, resolve=public_resolver)
        self.assertEqual(visited, [STORY])
        self.assertEqual(row["method"], "search_index")
        self.assertEqual(row["availability"], "excerpt")
        self.assertEqual(row["article_text"], "")
        self.assertEqual(row["confidence"], "low")

    async def test_paywall_marker_does_not_promote_article_or_visit_archive(self):
        visited = []

        async def fetch(url):
            visited.append(url)
            return page('<meta name="description" content="Public teaser only.">'
                        '<script type="application/ld+json">'
                        '{"isAccessibleForFree":false}</script><article>'
                        + PROSE + '</article>')

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  extract=lambda body, url: {
                                      "title": TITLE, "paragraphs": [PROSE]},
                                  search=no_results, resolve=public_resolver)
        self.assertEqual(visited, [STORY])
        self.assertEqual(row["method"], "publisher")
        self.assertEqual(row["excerpt"], "Public teaser only.")
        self.assertEqual(row["article_text"], "")

    async def test_private_url_and_private_redirect_are_never_fetched(self):
        self.assertEqual(public_url("http://127.0.0.1/secret"), "")
        self.assertEqual(public_url("http://user:pass@paper.example.com/a"), "")
        self.assertEqual(public_url("https://paper.example.com:8000/a"), "")
        visited = []

        async def fetch(url):
            visited.append(url)
            return page("", status=302, location="http://169.254.169.254/latest/meta-data/")

        invalid = await fetch_service("http://127.0.0.1/secret", fetch=fetch,
                                      search=no_results, resolve=public_resolver)
        self.assertEqual(invalid["availability"], "unavailable")
        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  search=no_results, resolve=public_resolver)
        self.assertEqual(visited, [STORY])
        self.assertEqual(row["availability"], "metadata")

    async def test_dns_private_address_prevents_callback_invocation(self):
        called = []

        async def private_resolver(host):
            return ["10.0.0.5"]

        async def fetch(url):
            called.append(url)
            return page("")

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  search=no_results, resolve=private_resolver)
        self.assertEqual(called, [])
        self.assertEqual(row["availability"], "metadata")

    async def test_unrelated_search_and_feed_cannot_supply_facts(self):
        async def fetch(url):
            if url == STORY:
                return page('<link rel="alternate" type="application/rss+xml" '
                            'href="/feed.xml">')
            if url.endswith("/feed.xml"):
                return page("<rss><channel><item><title>Other event</title>"
                            "<link>https://paper.example.com/other</link>"
                            "<description>Wrong details.</description>"
                            "</item></channel></rss>", url=url,
                            kind="application/rss+xml")
            return page("{}", kind="application/json", url=url)

        async def search(query):
            return [{"title": "Other event", "url": "https://elsewhere.example.org/other",
                     "snippet": "Wrong details."}]

        row = await fetch_service(STORY, title=TITLE, fetch=fetch,
                                  search=search, resolve=public_resolver)
        self.assertEqual(row["availability"], "metadata")
        self.assertEqual(row["article_text"], "")
        self.assertEqual(row["excerpt"], "")

    async def test_slow_publisher_falls_through_with_global_budget(self):
        async def slow_fetch(url):
            await asyncio.sleep(1)
            return page(PROSE)

        row = await fetch_service(STORY, title=TITLE, fetch=slow_fetch,
                                  search=no_results, resolve=public_resolver,
                                  budget_seconds=0.1)
        self.assertIn(row["availability"], ("metadata", "unavailable"))
        self.assertEqual(row["article_text"], "")


if __name__ == "__main__":
    unittest.main()
