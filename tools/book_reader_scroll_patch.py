#!/usr/bin/env python3
"""[book-scroll] [book-fill] The book reader turns pages on a scroll or a swipe, and can fill the window. 2026-10-05.

"when reading a book, allow me to swipe or scroll the pages to change pages. I
want to be able to scroll pages endlessly. And also zoom the page to fit the
available window area."

The reader (desktop/renderer/book-preview.*, served by the station at
/books/read/<book>) showed two facing pages and turned them with two buttons,
a page box and the arrow keys. Its only "Fit" kept the whole spread visible,
which in a wide window leaves a third of the window empty either side.

[book-scroll]  The wheel, a trackpad and a finger now turn the pages. While a
               page still has more to show (a zoomed page taller than the
               window) the scroll moves down the page; at its foot the same
               scroll carries on into the next two pages, at its head into the
               two before - and on through the whole book, across an EPUB's
               chapters too. A sideways swipe turns the page at once. Home,
               End and Space do what they do in any reader.
[book-fill]    A second fit: "Fit width". The facing pages take the whole
               width of the window and the page scrolls; a reflowed EPUB
               spreads its two pages across the whole window instead. The
               choice between the two fits is remembered. A double click on
               the page swaps between them.

Everything the reader already promised is kept: exactly two facing pages, the
buttons, the page box, the chapter list, the zoom steps, and never a call that
changes what the station is doing.

The station reads these three files on every request, so the change is live
the next time a book is opened: no restart and no rebuild.

Usage:  book_reader_scroll_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        book_reader_scroll_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- book-preview.js
STATE_OLD = r'''  var current={kind:'',chapterIndex:0,pageIndex:0,pageCount:0,spreadCount:0,zoom:100};
'''
STATE_NEW = r'''  var current={kind:'',chapterIndex:0,pageIndex:0,pageCount:0,spreadCount:0,zoom:100,fit:''};
'''

DIM_OLD = r'''    var height=Math.min(availableHeight,(availableWidth-gutter)/(ratios[0]+ratios[1]))*scale;
'''
DIM_NEW = r'''    var fitted=Math.min(availableHeight,(availableWidth-gutter)/(ratios[0]+ratios[1]));
    /* [book-fill] "Fit width": the facing pages take the whole width of the window and the page scrolls. */
    if(current.fit==='width'&&current.kind==='pdf'){scale=Math.max(1,(availableWidth-gutter)/(ratios[0]+ratios[1])/fitted);current.zoom=Math.round(scale*100);}
    var height=fitted*scale;
'''

EPUB_OLD = r'''    var doc=frame.contentDocument,body=doc.body,scale=current.zoom/100,box=dimensions([.71,.71],1);
'''
EPUB_NEW = r'''    /* [book-fill] A reflowed book has no page shape of its own: at "Fit width" its two pages spread across the whole window. */
    var wide=current.fit==='width'?Math.max(.71,(Math.max(140,stage.clientWidth-28)-20)/2/Math.max(90,stage.clientHeight-28)):.71;
    var doc=frame.contentDocument,body=doc.body,scale=current.zoom/100,box=dimensions([wide,wide],1);
'''

FRAME_OLD = r'''    doc.addEventListener('keydown',keyboard);
'''
FRAME_NEW = r'''    doc.addEventListener('keydown',keyboard);
    doc.addEventListener('wheel',wheel,{passive:false});doc.addEventListener('touchstart',touchStart,{passive:true});doc.addEventListener('touchend',touchEnd,{passive:true});   /* [book-scroll] */
'''

MOVE_OLD = r'''  function goToPage(number){if(!manifest||chapterLoading)return;current.pageIndex=2*Math.floor((Math.max(1,Math.min(current.pageCount,Number(number)||1))-1)/2);if(current.kind==='pdf')layoutPdf();else layoutEpub();}
  function setZoom(number){
    var passage=current.kind==='epub'?anchor():null;
    current.zoom=Math.max(100,Math.min(200,Number(number)||100));zoomSelect.value=current.zoom;
'''
MOVE_NEW = r'''  function goToPage(number){if(!manifest||chapterLoading)return;current.pageIndex=2*Math.floor((Math.max(1,Math.min(current.pageCount,Number(number)||1))-1)/2);if(current.kind==='pdf')layoutPdf();else layoutEpub();}
  /* [book-scroll] THE WHEEL, A TRACKPAD AND A FINGER TURN THE PAGES.
   *
   * "allow me to swipe or scroll the pages to change pages. I want to be able
   *  to scroll pages endlessly."
   *
   * While the page still has more to show - a zoomed page taller than the
   * window - a scroll moves down the page, as it always did. At the foot of
   * the page the same scroll carries on into the next two pages (and starts
   * at their head); at the head, into the two before (and starts at their
   * foot). So one gesture reads the whole book, and across an EPUB's
   * chapters, without reaching for a button.
   *
   * A trackpad keeps sending movement after the fingers lift. One push is one
   * turn: after a turn nothing more is taken until the stream has paused, or
   * for a little over half a second if it never does. */
  var turnLoad=0,turnDirection=0,turnAt=0,turnHeldUntil=0,wheelAt=0,pageMovedAt=0,touch=null,turning=false;
  function canScroll(direction){return direction>0?stage.scrollTop+stage.clientHeight<stage.scrollHeight-2:stage.scrollTop>2;}
  function canPan(direction){return direction>0?stage.scrollLeft+stage.clientWidth<stage.scrollWidth-2:stage.scrollLeft>2;}
  function hasMore(direction){
    if(!manifest)return false;
    if(direction>0)return current.pageIndex+2<current.pageCount||(current.kind==='epub'&&current.chapterIndex+1<manifest.chapters.length);
    return current.pageIndex>0||(current.kind==='epub'&&current.chapterIndex>0);
  }
  function turn(direction){
    if(turning||chapterLoading||destroyed||!hasMore(direction))return Promise.resolve(false);
    turning=true;
    return move(direction).then(function(){
      /* carry on reading where the eye is: the head of the next pages, the foot of the ones before */
      stage.scrollTop=direction>0?0:stage.scrollHeight;
      spread.classList.remove('bp-turn-next','bp-turn-prev');void spread.offsetWidth;spread.classList.add(direction>0?'bp-turn-next':'bp-turn-prev');
      return true;
    }).catch(function(error){fail(error);return false;}).then(function(done){turning=false;return done;});
  }
  function wheel(event){
    if(event.ctrlKey||event.metaKey||!manifest)return;                 /* a pinch, or the browser's own zoom */
    var dx=event.deltaX,dy=event.deltaY;
    if(event.deltaMode===1){dx*=32;dy*=32;}else if(event.deltaMode===2){dx*=stage.clientWidth;dy*=stage.clientHeight;}
    if(event.shiftKey&&!dx){dx=dy;dy=0;}
    var sideways=Math.abs(dx)>Math.abs(dy)*1.2,amount=sideways?dx:dy,direction=amount>0?1:-1,time=Date.now(),flowing=time-wheelAt<140;
    wheelAt=time;
    if(!amount)return;
    var inside=event.target&&event.target.ownerDocument===document&&stage.contains(event.target);
    if(inside&&(sideways?canPan(direction):canScroll(direction))){turnLoad=0;pageMovedAt=time;return;}   /* the page itself has more to show */
    event.preventDefault();
    if(!flowing)turnHeldUntil=0;                                       /* the stream paused: the push that turned the page is over */
    if(time<turnHeldUntil)return;                                      /* the tail of the push that already turned the page */
    turnLoad=(direction===turnDirection&&time-turnAt<260?turnLoad:0)+Math.abs(amount);turnDirection=direction;turnAt=time;
    /* a scroll that has only just reached the foot of the page has not asked for the next one yet: that takes a firmer push */
    if(turnLoad<(time-pageMovedAt<450?260:Math.abs(amount)<40?90:50))return;
    turnLoad=0;turnHeldUntil=time+650;
    turn(direction);
  }
  function touchStart(event){var point=event.touches&&event.touches.length===1?event.touches[0]:null;touch=point?{x:point.clientX,y:point.clientY,at:Date.now(),up:canScroll(-1),down:canScroll(1)}:null;}
  function touchEnd(event){
    var from=touch,point=event.changedTouches&&event.changedTouches[0];touch=null;
    if(!from||!point||Date.now()-from.at>900)return;
    var dx=point.clientX-from.x,dy=point.clientY-from.y;
    if(Math.abs(dx)>=50&&Math.abs(dx)>Math.abs(dy)*1.3&&!canPan(dx<0?1:-1))turn(dx<0?1:-1);                     /* a swipe to the left is the next page */
    else if(Math.abs(dy)>=70&&Math.abs(dy)>Math.abs(dx)*1.3&&!(dy<0?from.down:from.up))turn(dy<0?1:-1);       /* a swipe up at the foot of the page, too */
  }
  /* [book-fill] TWO FITS. "Fit page" keeps both pages whole in the window; "Fit width" gives them the whole
   * width of it and lets the page scroll. The choice between the two is remembered; a zoom step is not. */
  function rememberFit(){try{root.localStorage.setItem('pineBookPreviewFit',current.fit==='width'?'width':'page');}catch(_){}}
  function savedFit(){try{return root.localStorage.getItem('pineBookPreviewFit')==='width'?'width':'';}catch(_){return '';}}
  function showFit(){stage.classList.toggle('bp-fit-width',current.fit==='width'&&current.kind==='pdf');zoomSelect.value=current.fit==='width'?'width':String(current.zoom);}
  function setZoom(number){
    var passage=current.kind==='epub'?anchor():null,width=number==='width';
    if(width||Number(number)===100)current.fit=width?'width':'';else current.fit='';
    if(width||Number(number)===100)rememberFit();
    current.zoom=width?100:Math.max(100,Math.min(200,Number(number)||100));showFit();
'''

KEYS_OLD = r'''  function keyboard(event){if((event.target.matches&&event.target.matches('input,select,textarea'))||event.altKey||event.ctrlKey||event.metaKey)return;if(event.key==='ArrowRight'||event.key==='PageDown'){event.preventDefault();move(1).catch(fail);}if(event.key==='ArrowLeft'||event.key==='PageUp'){event.preventDefault();move(-1).catch(fail);}}
'''
KEYS_NEW = r'''  function keyboard(event){if((event.target.matches&&event.target.matches('input,select,textarea'))||event.altKey||event.ctrlKey||event.metaKey)return;if(event.key==='ArrowRight'||event.key==='PageDown'){event.preventDefault();move(1).catch(fail);}if(event.key==='ArrowLeft'||event.key==='PageUp'){event.preventDefault();move(-1).catch(fail);}
    /* [book-scroll] the keys any reader has: Space reads on (Shift+Space back), Home and End are the covers */
    if((event.key===' '||event.key==='Spacebar')&&!(event.target.matches&&event.target.matches('button,a'))){event.preventDefault();var way=event.shiftKey?-1:1;if(canScroll(way))stage.scrollBy({top:way*stage.clientHeight*.85,behavior:'smooth'});else turn(way);}
    if(event.key==='Home'){event.preventDefault();if(current.kind==='epub'&&current.chapterIndex>0)loadChapter(0,false).catch(fail);else goToPage(1);}
    if(event.key==='End'){event.preventDefault();if(current.kind==='epub'&&current.chapterIndex+1<manifest.chapters.length)loadChapter(manifest.chapters.length-1,true).catch(fail);else goToPage(current.pageCount);}}
'''

WIRE_OLD = r'''  zoomSelect.onchange=function(){setZoom(zoomSelect.value);};chapterSelect.onchange=function(){selectChapter(chapterSelect.value).catch(fail);};
'''
WIRE_NEW = r'''  zoomSelect.onchange=function(){setZoom(zoomSelect.value);};chapterSelect.onchange=function(){selectChapter(chapterSelect.value).catch(fail);};
  /* [book-scroll] [book-fill] the page itself: scroll or swipe to turn, double click to swap the two fits */
  stage.addEventListener('wheel',wheel,{passive:false});stage.addEventListener('touchstart',touchStart,{passive:true});stage.addEventListener('touchend',touchEnd,{passive:true});
  stage.addEventListener('dblclick',function(event){if(event.target.closest&&event.target.closest('a,button,input,select'))return;setZoom(current.fit==='width'?100:'width');});
'''

API_OLD = r'''  root.PineBookPreview={ready:ready,next:function(){return move(1);},previous:function(){return move(-1);},setZoom:setZoom,goToPage:goToPage,selectChapter:selectChapter,state:state,destroy:destroy};
'''
API_NEW = r'''  root.PineBookPreview={ready:ready,next:function(){return move(1);},previous:function(){return move(-1);},turn:turn,setZoom:setZoom,goToPage:goToPage,selectChapter:selectChapter,state:state,destroy:destroy};
'''

BOOT_OLD = r'''    manifest=await response.json();current.kind=manifest.kind;document.title=manifest.title;document.getElementById('bp-title').textContent=manifest.title;
'''
BOOT_NEW = r'''    manifest=await response.json();current.kind=manifest.kind;document.title=manifest.title;document.getElementById('bp-title').textContent=manifest.title;
    current.fit=savedFit();showFit();   /* [book-fill] the fit that was chosen last time */
'''

JS = [
    ("the reader knows which fit it is in", STATE_OLD, STATE_NEW, "spreadCount:0,zoom:100,fit:''};", 1),
    ("fit width for page images", DIM_OLD, DIM_NEW, "    var fitted=Math.min(availableHeight,(availableWidth-gutter)/(ratios[0]+ratios[1]));", 1),
    ("fit width for a reflowed book", EPUB_OLD, EPUB_NEW, "box=dimensions([wide,wide],1);", 1),
    ("the chapter hears the wheel and the finger", FRAME_OLD, FRAME_NEW, "doc.addEventListener('wheel',wheel,{passive:false});", 1),
    ("scroll, swipe and the two fits", MOVE_OLD, MOVE_NEW, "  function wheel(event){", 1),
    ("space, home and end", KEYS_OLD, KEYS_NEW, "if(event.key==='Home'){event.preventDefault();", 1),
    ("the page hears them", WIRE_OLD, WIRE_NEW, "  stage.addEventListener('wheel',wheel,{passive:false});", 1),
    ("turn is offered to the host page", API_OLD, API_NEW, "previous:function(){return move(-1);},turn:turn,setZoom:setZoom,", 1),
    ("the last fit comes back", BOOT_OLD, BOOT_NEW, "    current.fit=savedFit();showFit();", 1),
]

# --------------------------------------------------------------------------- book-preview.css
CSS_NEW = r'''/* [book-fill] "Fit width": the facing pages take the whole width and the page scrolls; the bar's room is kept so the fit does not jump */
.bp-stage.bp-fit-width{overflow-y:scroll}
/* [book-scroll] a page turned by a scroll or a swipe arrives from the way the hand was going */
@keyframes bp-turn-next{from{opacity:.35;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes bp-turn-prev{from{opacity:.35;transform:translateY(-14px)}to{opacity:1;transform:none}}
.bp-spread.bp-turn-next{animation:bp-turn-next .16s ease-out}
.bp-spread.bp-turn-prev{animation:bp-turn-prev .16s ease-out}
@media(prefers-reduced-motion:reduce){.bp-spread.bp-turn-next,.bp-spread.bp-turn-prev{animation:none}}
'''
CSS = [("fit width, and the turn", None, CSS_NEW, ".bp-stage.bp-fit-width{overflow-y:scroll}", 1)]

# --------------------------------------------------------------------------- book-preview.html
ZOOM_OLD = r'''<option value="100">Fit</option><option value="125">125%</option>'''
ZOOM_NEW = r'''<option value="100">Fit page</option><option value="width">Fit width</option><option value="125">125%</option>'''
STAGE_OLD = r'''  <section class="bp-stage" aria-label="Book pages" tabindex="0">'''
STAGE_NEW = r'''  <section class="bp-stage" aria-label="Book pages" title="Scroll or swipe to turn the pages. Double click to fill the window." tabindex="0">'''
HTML = [
    ("the second fit is on the list", ZOOM_OLD, ZOOM_NEW, '<option value="width">Fit width</option>', 1),
    ("the page says how it turns", STAGE_OLD, STAGE_NEW, 'title="Scroll or swipe to turn the pages. Double click to fill the window."', 1),
]

EDITS = {
    "desktop/renderer/book-preview.js": JS,
    "desktop/renderer/book-preview.css": CSS,
    "desktop/renderer/book-preview.html": HTML,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in text
        if crlf:
            if text.count("\r\n") != text.count("\n"):
                raise SystemExit("%s has mixed line endings; refusing to guess" % path)
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            have = text.count(probe)
            if have == count:
                state = "applied"
            elif old is None and not have:
                text = text.rstrip("\n") + "\n" + new
                state, changed = "ready", True
            elif old is not None and not have and text.count(old) == count:
                text = text.replace(old, new)
                assert text.count(probe) == count, (name, label, "probe after the edit")
                state, changed = "ready", True
            else:
                state = "missing (anchor found %d, probe %d)" % (text.count(old) if old else 0, have)
            print("%-36s %-44s %s" % (name, label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, changed in plans:
        if changed:
            tmp = path.with_name(path.name + ".bookscroll.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%s)" % (path.name, "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
