import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import crystal_prompts
from rhyme_assistance import RhymeAssistance, lexical_vector


class RhymeAssistanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='rhyme-assistance-test-')
        cls.path=Path(cls.temp.name)/'words.sqlite3'
        cls.store=RhymeAssistance(cls.path)
        cls.built=cls.store.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.store.close();cls.temp.cleanup()

    def setUp(self):
        with self.store.lock,self.store.db:
            self.store.db.execute('DELETE FROM embeddings')
            self.store.db.execute('DELETE FROM query_vectors')

    def test_real_full_corpora_are_indexed_and_restart_is_not_a_reimport(self):
        self.assertGreater(self.built['counts']['phones'],130000)
        self.assertEqual(self.built['counts']['senses'],117659)
        self.assertGreater(self.built['counts']['lemmas'],200000)
        other=RhymeAssistance(self.path)
        try:
            with patch.object(Path,'read_bytes',side_effect=AssertionError('no corpus reread')):
                self.assertEqual(other.initialize()['revision'],self.built['revision'])
        finally:other.close()

    def test_read_only_retrieval_has_exact_pronunciation_and_sense_provenance(self):
        before=self.store.db.total_changes
        result=self.store.assist('Please explain the rest.',style_words={'plain','best'})
        self.assertEqual(self.store.db.total_changes,before)
        self.assertFalse(result['search']['neural_used'])
        row=next(r for r in result['endings'] if r['anchor']=='rest')
        self.assertEqual(row['rhyme_phones'],['EH','S','T'])
        self.assertIn('best',[r['word'] for r in row['options']])
        for option in row['options']:
            self.assertNotEqual(option['word'],'rest')
            self.assertTrue(option['phones'])
        sense=next(r for r in result['related'] if r['source_word']=='rest')
        self.assertIn('remainder',sense['alternatives'])
        self.assertEqual(sense['relationship'],'same_synset_options')
        self.assertIn('left after other parts',sense['definition'])
        self.assertEqual(sense['provenance']['offset'],sense['sense'].split(':')[1])

    def test_names_tags_and_suffix_only_pairs_do_not_become_endpoints(self):
        result=self.store.assist('Dale, get to the point, man. We have records to spin.',
            exclude_words=['dale'],normalize=lambda w:w.rstrip('s'),
            required_depth=lambda w:2 if w.endswith('tion') else 1)
        self.assertNotIn('dale',[r['anchor'] for r in result['endings']])
        self.assertNotIn('man',[r['anchor'] for r in result['endings']])
        self.assertEqual(result['endings'][0]['anchor'],'spin')
        pairs=[]
        for r in result['endings']:
            for v in r['options']:
                pair=tuple(sorted((r['anchor'].rstrip('s'),v['word'].rstrip('s'))))
                self.assertNotEqual(*pair);pairs.append(pair)
        self.assertEqual(len(pairs),len(set(pairs)))

    def test_empty_unbuilt_or_unknown_source_does_not_guess(self):
        empty=RhymeAssistance(Path(self.temp.name)/'empty.sqlite3')
        try:
            self.assertFalse(empty.assist('A known source')['ready'])
        finally:empty.close()
        self.assertEqual(self.store.assist('qxzvvkjzqq')['endings'],[])
        self.assertEqual(self.store.assist('')['related'],[])

    def test_cached_neural_vectors_are_used_only_for_exact_source_and_model(self):
        source='Explain the remaining material.'
        rows=self.store.embedding_batch('test-local',source=source,limit=8)
        self.assertTrue(rows)
        vectors=[[1.0]+[0.0]*7 for _ in rows]
        self.store.put_embeddings('test-local',rows,vectors)
        self.store.put_query_embedding(source,'test-local',[1.0]+[0.0]*7)
        result=self.store.assist(source,model='test-local')
        self.assertTrue(result['search']['neural_used'])
        self.assertTrue(any('neural_cosine' in r for r in result['related']))
        self.assertFalse(self.store.assist(source+' Elsewhere.',model='test-local')['search']['neural_used'])
        self.assertFalse(self.store.assist(source,model='another-model')['search']['neural_used'])
        other=RhymeAssistance(self.path)
        try:self.assertTrue(other.assist(source,model='test-local')['search']['neural_used'])
        finally:other.close()

    def test_vector_source_revision_dimensions_and_nonfinite_values_are_fenced_atomically(self):
        rows=self.store.embedding_batch('test-local',limit=2)
        good=[[1.0]+[0.0]*7 for _ in rows]
        altered=copy.deepcopy(rows);altered[-1]['sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'changed sense'):self.store.put_embeddings('test-local',altered,good)
        self.assertEqual(self.store.status()['vectors'],[])
        altered=copy.deepcopy(rows);altered[-1]['revision']='wrong'
        with self.assertRaisesRegex(ValueError,'stale corpus'):self.store.put_embeddings('test-local',altered,good)
        bad=copy.deepcopy(good);bad[-1][0]=float('nan')
        with self.assertRaises(ValueError):self.store.put_embeddings('test-local',rows,bad)
        self.store.put_embeddings('test-local',rows,good)
        with self.assertRaisesRegex(ValueError,'dimensions'):
            self.store.put_embeddings('test-local',rows,[[1.0]+[0.0]*8 for _ in rows])
        self.assertEqual(self.store.status()['vectors'][0]['rows'],2)

    def test_modified_corpus_does_not_replace_working_index(self):
        old=self.store.vendor
        fake=Path(self.temp.name)/'fake-vendor';(fake/'wordnet').mkdir(parents=True,exist_ok=True)
        manifest=json.loads((old/'wordnet'/'provenance.json').read_text())
        manifest['files']=[{'path':'LICENSE','bytes':3,'sha256':'wrong'}]
        (fake/'wordnet'/'provenance.json').write_text(json.dumps(manifest))
        (fake/'wordnet'/'LICENSE').write_text('bad')
        self.store.vendor=fake
        try:
            with self.assertRaisesRegex(ValueError,'hash mismatch'):self.store.initialize()
            self.assertEqual(self.store.status()['revision'],self.built['revision'])
            self.assertTrue(self.store.assist('Explain the rest')['endings'])
        finally:self.store.vendor=old

    def test_concurrent_reads_keep_separate_source_receipts(self):
        sources=['Ask about the rest.','Please explain that point.','Music moving through.']*3
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(self.store.assist,sources))
        self.assertEqual([r['source_sha256'] for r in results],
                         [hashlib.sha256(s.encode()).hexdigest() for s in sources])

    def test_long_source_ngrams_do_not_crowd_out_source_word_senses(self):
        source='metaphors '+('explain the remaining records as music continues through the evening. '*18)
        rows=self.store._senses(source,limit=60)
        self.assertTrue(any(r['source_word']=='metaphors' for r in rows))

    def test_prompt_evidence_is_optional_pinned_compact_and_no_accepted_neighbor_retrieval(self):
        source='Ask for metaphors to explain the rest.'
        evidence=self.store.assist(source)
        plain=crystal_prompts.turn_prompt(source,'world',[],.88,'banter')
        with_options=crystal_prompts.turn_prompt(source,'world',[],.88,'banter',rhyme_assistance=evidence)
        self.assertIn('WORD OPTIONS RETRIEVED BEFORE WRITING',with_options)
        self.assertLess(len(with_options)-len(plain),3500)
        self.assertIn('Sound similarity is not semantic evidence',with_options)
        wrong=crystal_prompts.turn_prompt('Another source.','world',[],.88,'banter',rhyme_assistance=evidence)
        self.assertNotIn('WORD OPTIONS RETRIEVED BEFORE WRITING',wrong)
        combined=crystal_prompts.round_prompt([('A',source),('B','Keep my accepted line.')],
            'world',[],.88,'banter',selected_indices=[0],
            candidates=['failed','Keep my accepted line.'],evaluations=[{'ok':False},{'ok':True}],
            rhyme_assistance=[evidence,evidence])
        self.assertEqual(combined.count('"word_options"'),1)
        self.assertIn('"immutable":true',combined)


if __name__=='__main__':unittest.main()
