"""Live narration probe; does not mark an unheard sentence completed."""
import json,os,urllib.request
key=os.environ['SPARK_AGENT_API_KEY']
def call(route,body=None):
    data=None if body is None else json.dumps(body).encode()
    request=urllib.request.Request('http://127.0.0.1:8096'+route,data=data,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=180) as response:return json.load(response)
state=call('/api/books/state')
if state['active']:
    print('Skipped narration probe: a live Book Mode session already owns playback.')
else:
    prefs=state['preferences'];old_book=state['book'];old_position=state['position']
    try:
        call('/api/books/preferences',{'show':'read','readers':['host'],'sfx':False})
        book=old_book or call('/api/books?limit=1')['books'][0]['id']
        selected=call('/api/books/'+book+'/select',{'confirm':True})
        if selected.get('confirm_resume'):raise RuntimeError('Unexpected confirmation response')
        selected=call('/api/books/mode',{'active':True})
        rendered=call('/api/books/next',{'session':selected['session'],'line':selected['position']})
        clip=rendered['clip'];path=clip['path'];url=path if path.startswith('http') else 'http://127.0.0.1:8096'+path
        if clip.get('sig'):url+=('&' if '?' in url else '?')+'t='+clip['sig']
        req=urllib.request.Request(url,headers={'Authorization':'Bearer '+key,'Range':'bytes=0-63'})
        with urllib.request.urlopen(req,timeout=30) as response:
            sample=response.read(64)
            print(json.dumps(dict(narration_rendered=True,audio_bytes_verified=len(sample),reader=rendered['reader'],sentence=rendered['line'],bookmark_advanced=False)))
        assert sample
    finally:
        call('/api/books/preferences',prefs)
        if old_book:call('/api/books/'+old_book+'/select',{'confirm':True});call('/api/books/seek',{'line':old_position})
        call('/api/books/mode',{'active':False})
