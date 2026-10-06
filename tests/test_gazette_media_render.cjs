/* Run with Electron: electron tests/test_gazette_media_render.cjs
 * Real Gazette scene markup at newspaper and tabloid column widths.
 * Local fixtures only; no station or GPU work is started. */
const {app, BrowserWindow} = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = process.env.PINE_GAZETTE_ROOT || path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-gazette-scenes-'));
app.setPath('userData', temp);
app.disableHardwareAcceleration();
let win, server;
const timeout = setTimeout(() => app.exit(1), 45000);
const fixtureCode = [
'import json,sys',
'from pathlib import Path',
'namespace = {"__name__": "gazette_fixture"}',
'file = Path(sys.argv[1]) / "gazette_media.py"',
'exec(compile(file.read_text(encoding="utf-8"),str(file),"exec"),namespace)',
'rows=[]',
'for kind in ("image", "video"):',
'    media={"image":{"status":"ready","url":"/api/generations/image/mayor.png?t=fixture",',
'                    "caption":\'Fictional city scene: <Mayor "Ada"> responds at City Hall.\'}}',
'    if kind=="video":',
'        media["video"]={"status":"ready","url":"/api/generations/media/mayor.mp4?t=fixture",',
'                        "caption":\'Fictional reaction scene: <Mayor "Ada"> defends the contract.\'}',
'    for width in (180,196,270,380):',
'        rows.append({"kind":kind,"width":width,"html":namespace["render"](media),',
'                     "estimate":namespace["estimate"](media,width)})',
'print(json.dumps(rows))',
].join('\n');
const rows = JSON.parse(execFileSync(process.env.PYTHON || 'python',
  ['-c', fixtureCode, root], {encoding:'utf8', timeout:20000}));
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII=', 'base64');
const markup = '<!doctype html><html lang="en"><head><meta charset="utf-8">'
  + '<style>body{margin:0;padding:12px;font:13.5px/1.4 Georgia,serif;background:#f7f4e9}'
  + '.column{display:inline-block;vertical-align:top;margin:0 12px 18px 0;max-width:100%}'
  + 'figure{padding:0}figcaption{overflow-wrap:normal}</style></head><body>'
  + rows.map((row,index)=>'<section class="column" data-index="'+index+'" style="width:'+row.width+'px">'+row.html+'</section>').join('')
  + '</body></html>';
function measure(){
  return Promise.all([...document.querySelectorAll('img')].map(image=>image.complete?Promise.resolve():new Promise(resolve=>{
    image.onload=image.onerror=resolve;
  }))).then(()=>[...document.querySelectorAll('.column')].map(column=>{
    const figure=column.querySelector('figure'),asset=figure.querySelector('img,video'),box=asset.getBoundingClientRect(),style=getComputedStyle(figure);
    return {index:Number(column.dataset.index),width:box.width,height:box.height,
      outer:figure.getBoundingClientRect().height+parseFloat(style.marginTop)+parseFloat(style.marginBottom),
      overflow:column.scrollWidth>column.clientWidth,caption:figure.querySelector('figcaption').textContent,
      video:asset.tagName==='VIDEO',controls:asset.controls,preload:asset.preload,
      source:asset.querySelector('source')?.getAttribute('src'),poster:asset.getAttribute('poster'),
      imageCount:figure.querySelectorAll('img').length};
  }));
}
app.whenReady().then(async()=>{
  server = http.createServer((request,response)=>{
    const pathname = new URL(request.url,'http://127.0.0.1').pathname;
    if(pathname==='/'){response.writeHead(200,{'Content-Type':'text/html'});response.end(markup);}
    else if(pathname==='/api/generations/image/mayor.png'){response.writeHead(200,{'Content-Type':'image/png'});response.end(png);}
    else {response.writeHead(404);response.end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:1200,height:900,webPreferences:{offscreen:true,sandbox:false}});
  await win.loadURL('http://127.0.0.1:'+server.address().port+'/');
  const measurements=await win.webContents.executeJavaScript('('+measure.toString()+')()');
  for(const measured of measurements){
    const row=rows[measured.index];
    assert(Math.abs(measured.width-row.width)<1, row.kind+' scene fits '+row.width+'px column');
    assert(Math.abs(measured.height-row.width*9/16)<1, 'scene keeps the same 16:9 space while video loads');
    assert(!measured.overflow, 'scene does not leave the column');
    assert(measured.outer<=row.estimate+1, 'estimator reserves visible scene plus caption: '+measured.outer+' <= '+row.estimate);
    assert(measured.caption.includes('<Mayor "Ada">'), 'escaped caption remains readable');
    assert(measured.caption.startsWith('Fictional'), 'fictional scene is labelled');
    if(row.kind==='video'){
      assert(measured.controls);
      assert.equal(measured.preload,'none');
      assert.equal(measured.source,'/api/generations/media/mayor.mp4?t=fixture');
      assert.equal(measured.poster,'/api/generations/image/mayor.png?t=fixture');
      assert.equal(measured.imageCount,0, 'video poster does not repeat a still image');
    }
  }
  console.log('8 Gazette media browser layouts passed: column fit, stable video dimensions, escaped fiction captions, signed sources and estimator containment.');
  fs.writeFileSync(process.env.PINE_GAZETTE_MEDIA_REPORT || path.join(temp, 'report.json'), JSON.stringify({ok:true, checks:8, measurements}));
  win.destroy();
  await new Promise(resolve=>server.close(resolve));
  clearTimeout(timeout);
  app.exit(0);
}).catch(error=>{fs.writeFileSync(process.env.PINE_GAZETTE_MEDIA_REPORT || path.join(temp, 'report.json'), JSON.stringify({ok:false,error:String(error.stack||error)}));console.error(error);if(win)win.destroy();if(server)server.close();clearTimeout(timeout);app.exit(1);});
