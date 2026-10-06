"""[book-title] A book's title is said the way a person says it (#1588, 2026-10-05).

The titles and the spoken lines are the station's own, from openings written on 10-05.

Run from the repo root:  python3 -m unittest tests.test_book_time_title_2026_10_05
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the repo root, however this file is run

from segment_contract import book_time_bookends, book_title_said  # noqa: E402

STATION = 'Chicken Tendo Little Pine Box FM Station'
MCCARTHY = ('McCarthy and His Enemies - Record and Its Meaning -- William F Buckley Jr, L Brent Bozell, '
            'William Schlamm -- 1954')
PLAGUE = "A Plague Upon Humanity - The Hidden Story of Japan's Biological Warfare Program"


def said(script: str, title: str) -> bool:
    return book_time_bookends(script, title=title, station=STATION)['intro']['written']


class BookTitleTest(unittest.TestCase):
    def test_the_openings_the_station_wrote_name_their_books(self):
        mccarthy = ("A: Welcome to Book Time on %s. I am Dill.\nB: And I'm Skip.\n"
                    "A: We are diving into McCarthy and His Enemies - Record and Its Meaning, looking at chapter Blank Page today." % STATION)
        plague = ("A: Welcome to Book Time on %s. I'm Dill.\nB: And I'm Skip.\n"
                  "A: We are diving into A Plague Upon Humanity, Fortress of Fear." % STATION)
        self.assertTrue(said(mccarthy, MCCARTHY))
        self.assertTrue(said(plague, PLAGUE))

    def test_the_whole_catalogue_title_still_counts(self):
        self.assertTrue(said("A: Welcome to Book Time on %s. Tonight: %s." % (STATION, MCCARTHY), MCCARTHY))
        self.assertTrue(said("A: Welcome to Book Time on %s. The Actual Book." % STATION, 'The Actual Book'))

    def test_another_book_is_still_another_book(self):
        other = "A: Welcome to Book Time on %s. I'm Dill.\nB: Tonight, The Road to Serfdom." % STATION
        self.assertFalse(said(other, MCCARTHY))
        self.assertFalse(said(other, PLAGUE))
        self.assertFalse(said("A: Welcome to Book Time on %s. The Wrong Book." % STATION, 'The Actual Book'))
        near = "A: Welcome to Book Time on %s. McCarthyism and its enemies were everywhere." % STATION
        self.assertFalse(said(near, MCCARTHY), 'a word that merely starts the same is not the title')

    def test_a_leading_title_too_short_to_mean_a_book_does_not_count(self):
        script = "A: Welcome to Book Time on %s. It is late, and it is raining." % STATION
        self.assertFalse(said(script, 'It - A Novel -- Stephen King -- 1986'))
        self.assertTrue(said("A: Welcome to Book Time on %s. Tonight: It - A Novel -- Stephen King -- 1986." % STATION,
                             'It - A Novel -- Stephen King -- 1986'), 'the whole title is still an answer')
        self.assertTrue(said("A: Welcome to Book Time on %s. Tonight we open Walden." % STATION, 'Walden - Or, Life in the Woods'),
                        'one word, long enough to be a name')

    def test_the_other_ways_a_catalogue_title_trails_off(self):
        for title in ('The Jungle: A Novel of Chicago', 'The Jungle (1906 edition)', 'The Jungle [annotated]', 'The Jungle; with notes'):
            self.assertTrue(book_title_said(title, 'tonight we read the jungle, by upton sinclair'), title)
        self.assertTrue(book_title_said('', 'anything at all'), 'no title to check is not a failure')
        self.assertFalse(book_title_said('The Jungle: A Novel of Chicago', 'tonight we read the jungles of borneo'))

    def test_the_station_and_the_welcome_are_asked_for_as_before(self):
        self.assertFalse(said("A: Welcome to Book Time. McCarthy and His Enemies.", MCCARTHY), 'the station must be named')
        self.assertFalse(said("A: This is %s. McCarthy and His Enemies." % STATION, MCCARTHY), 'and there must be a welcome')


if __name__ == '__main__':
    unittest.main()
