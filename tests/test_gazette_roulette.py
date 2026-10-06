import ast
import asyncio
from pathlib import Path
import unittest
import gazette_prompt

class GazetteRoulette(unittest.TestCase):
    def setUp(self):
        self.rows = gazette_prompt.articles({'id':'newest', 'articles':[
            {'file':'a.md','meta':{'section':'news','headline':'Water repair'},'body':'The neighbourhood repaired the water supply.'},
            {'file':'b.md','meta':{'section':'news','headline':'New bridge'},'body':'A new bridge opened beside the station.'},
            {'file':'c.md','meta':{'section':'music','headline':'Concert'},'body':'A band played live.'},
            {'meta':{'section':'empty'},'body':''}, {'body':'bad','error':'broken frontmatter'}]})
        self.calls=[]
    def pick(self,key,labels,weights,label):
        self.calls.append((key,list(labels),weights))
        return 0 if key.endswith('section') else 1
    def test_section_then_article_and_content(self):
        result=gazette_prompt.draw(self.rows,self.pick)
        self.assertEqual([c[0] for c in self.calls],['gazette.section','gazette.article'])
        self.assertEqual(self.calls[0][1],['news','music'])
        self.assertEqual(self.calls[1][1],['Water repair','New bridge'])
        self.assertIn('new bridge opened',result['prompt'])
        self.assertEqual(result['edition'],'newest')
    def test_empty_is_not_a_fake_roll(self):
        self.assertEqual(gazette_prompt.draw([],self.pick),{})
        self.assertFalse(self.calls)
    def test_hour_receipt_keeps_both_rolls(self):
        notes=[]
        gazette_prompt.draw(self.rows,self.pick,lambda *args:notes.append(args),'gazette2')
        self.assertEqual([n[0] for n in notes],['slot_gazette2_section','slot_gazette2'])
    def test_filters_unreadable_articles(self):
        self.assertEqual(len(self.rows),3)
    def test_prompt_request_memo_and_history(self):
        source=(Path(__file__).resolve().parents[1]/'app.py').read_text(encoding='utf-8')
        tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='gazette_prompt_messages')
        ns={'Any':object,'gazette_prompt':gazette_prompt,'asyncio':asyncio,'s3_weighted':self.pick,'h3_slot_shelf':lambda name:self.rows,'pipeline_log':lambda *a:None}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        messages=[{'role':'system','content':'Use {gazette}.'},{'role':'user','content':'Old {gazette2}'},{'role':'assistant','content':'Leave {gazette}'},{'role':'user','content':'Discuss {gazette}'}]
        result=asyncio.run(ns['gazette_prompt_messages'](messages))
        self.assertEqual(len(self.calls),2)
        self.assertIn('bridge',result[0]['content']);self.assertIn('bridge',result[-1]['content'])
        self.assertEqual(result[1],messages[1]);self.assertEqual(result[2],messages[2])
        self.assertEqual(messages[0]['content'],'Use {gazette}.')
        asyncio.run(ns['gazette_prompt_messages']([{'role':'user','content':'{gazette}'}]))
        self.assertEqual(len(self.calls),4,'a new request gets a new roll')
    def test_numbered_tokens_are_independent(self):
        self.assertEqual(gazette_prompt.TOKEN.findall('{gazette} {gazette2} {{gazette}}'),['gazette','gazette2'])

if __name__=='__main__':unittest.main()
