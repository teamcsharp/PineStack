"""Read-only deployment probe. Never print the station key."""
import json,os,urllib.request,urllib.parse,time
from pathlib import Path
key=os.environ['SPARK_AGENT_API_KEY']
def get(route):
    req=urllib.request.Request('http://127.0.0.1:8096'+route,headers={'Authorization':'Bearer '+key})
    with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)
health=get('/healthz');catalog=get('/api/books?limit=5');state=get('/api/books/state')
print(json.dumps(dict(healthy=health.get('ok',health.get('status')),books=catalog['total'],sample_titles=[b['title'] for b in catalog['books']],book_mode_active=state['active'],epub_reachable=Path('/books/Epub').is_dir(),pdf_reachable=Path('/books/PDF').is_dir(),errors=catalog['errors'],scan_seconds=state['preferences']['scan_seconds'],last_scan=state.get('last_scan'),discovery=state.get('discovery')),indent=2))
assert catalog['total']>2000
assert Path('/books/Epub').is_dir() and Path('/books/PDF').is_dir()
book=catalog['books'][0]['id'];cover=get('/api/books/'+book+'/cover');pages=get('/api/books/'+book+'/sentences?limit=3')
print(json.dumps(dict(cover_cached='<svg' in cover['svg'],sentences=pages['total'],preview_lines=len(pages['lines'])),indent=2))
query=pages['lines'][0]['text'][:60]
found=get('/api/books/'+book+'/find?q='+urllib.parse.quote(query)+'&limit=1')
assert found['total']>=1 and found['matches'][0]['line']==0
print(json.dumps(dict(passage_search=True,matches=found['total'],first_sentence=found['matches'][0]['line'])))
