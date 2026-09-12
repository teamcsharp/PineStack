import unittest

from newspaper_city import clean_description, subject_role, subject_label, seed_theme, fallback_story, accept_story, sentences


class CityCopyTests(unittest.TestCase):
    def test_live_awkward_topics_and_object_labels_are_not_printed(self):
        for text, topic in (
            ('too aggressive when mixing individual tracks across the frequency spectrum', 'sound'),
            ('I felt so happy when I went to the club', 'nightlife'),
            ('I can take him straight to hell with me because he was furious', 'disagreement'),
            ('the judge gave an instruction and everyone made notes', 'records'),
            ('rubber washers with the metal pot', 'repairs'),
            ('a signal from the underwater station disables the jammer', 'reception'),
        ):
            self.assertEqual(seed_theme({'text': text})[0], topic)
        self.assertEqual(seed_theme({'text': 'straight happy interested thank right'})[0], 'neighbourhood life')
        cube = clean_description("It's dominated by a vibrant, glossy red cube resting on wood.")
        self.assertEqual(subject_label(cube, subject_role(cube)), 'cube')
        self.assertNotIn("It's dominated", cube)
        self.assertEqual(subject_role('Huge plastic glasses are pressed against a mass of faces.'), 'resident')
        self.assertEqual(subject_label('The black surface rests on a table. White lettering says Hello world.', 'goods or service'), 'lettered panel')
        self.assertEqual(subject_label('A magnificent bird, a heron, stands by the water.', 'neighbourhood animal'), 'heron')
        self.assertEqual(subject_label('Two ducks stand together. One duck rests.', 'neighbourhood animal'), 'ducks')
        for description in ('Two ducks stand by the water.', 'In the lower corners, more cats sit quietly.'):
            story = fallback_story({'subject': description, 'role': 'neighbourhood animal'}, {'text': 'Water repairs.'}, 8, 'Pine Box FM')
            self.assertIn(description, story['body'])
            self.assertNotIn('pointed out', story['body'])

    def test_actual_spoken_descriptions_lose_repeated_delivery_and_keep_animals_alive(self):
        cases = [
            ("Listen to this! I'm holding up a photograph of a fiery scene in a church. In the center, a magnificent deer is engulfed in flames.", "neighbourhood animal", "deer"),
            ("Listen up folks, I've got a picture here, and it's doing things to me. The central figure is a woman with fiery red hair and metallic armor.", "resident", "red hair"),
            ("Listen to this, folks, I'm holding up a photograph bathed in sunset. In the foreground sits a thick-furred orangutan, its eyes dark. He rests upon a metal trunk.", "neighbourhood animal", "orangutan"),
            ("A photograph of a red bicycle with a wicker basket", "goods or service", "red bicycle"),
            ("Two figures of what look like deer stand alert in the grass.", "neighbourhood animal", "deer"),
        ]
        for raw, role, detail in cases:
            with self.subTest(detail=detail):
                cleaned = clean_description(raw)
                self.assertEqual(subject_role(cleaned), role)
                self.assertIn(detail, cleaned)
                self.assertNotRegex(cleaned.lower(), r"listen|holding|photograph|picture here")

    def test_fallback_changes_with_source_and_retains_exact_provenance(self):
        subject = {"name": "bike.png", "role": "goods or service", "subject": "A red bicycle with a wicker basket."}
        water = {"file": "water.md", "text": "The water supply failed beside the community faucet."}
        song = {"file": "music.md", "text": "The band will rehearse a new song for the neighbourhood."}
        first = fallback_story(subject, water, 0, "Pine Box FM")
        second = fallback_story(subject, song, 0, "Pine Box FM")
        self.assertNotEqual(first["body"], second["body"])
        self.assertEqual(first["source"], water)
        self.assertIn("water arrangements", first["body"])
        self.assertIn("rehearsal", second["body"])
        self.assertIn("red bicycle", first["body"])

    def test_writer_repeating_patter_or_existing_sentences_uses_grounded_fallback(self):
        subject = {"name": "bike.png", "role": "goods or service", "subject": "A red bicycle with a wicker basket."}
        fallback = fallback_story(subject, {"text": "The band rehearsed a song."}, 0, "Pine Box FM")
        body = "The red bicycle reached the courtyard during the music rehearsal. Neighbours left their questions beside the station gate before supper. The rider helped carry the instruments back to the workshop."
        candidate = {"headline": "A bicycle joins the evening rehearsal", "body": body}
        accepted = accept_story(candidate, fallback, subject, set())
        self.assertEqual(accepted["copy_origin"], "writer")
        self.assertEqual(accept_story(candidate, fallback, subject, sentences(body)), fallback)
        self.assertEqual(accept_story({**candidate, "body": "Listen up folks, I'm holding up this image. " + body}, fallback, subject, set()), fallback)


if __name__ == "__main__":
    unittest.main()
