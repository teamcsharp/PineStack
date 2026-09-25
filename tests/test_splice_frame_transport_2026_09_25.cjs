const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const file=fs.readFileSync(path.join(__dirname,'../desktop/renderer/video-editor.js'),'utf8');
const source=file.slice(file.indexOf('  function startParodyEditor()'));

function functionText(name,next){return source.slice(source.indexOf('    function '+name+'('),source.indexOf('    function '+next+'('));}

test('buffer callbacks retain their actual element across player promotions',()=>{
 const prepare=functionText('preloadAdjacent','queuePreviewLayers');
 assert.match(prepare,/var buffer = preloadPreview/);
 assert.match(prepare,/buffer === preloadPreview/);
 assert.match(prepare,/removeEventListener\('seeked', warmed\)/);
 assert.ok(prepare.indexOf("addEventListener('loadedmetadata'")<prepare.indexOf('buffer.load()'));
});

test('decoded frames drive handoff and trimming never advances to the next clip',()=>{
 assert.match(functionText('frameClock','applyJoinSeek'),/updateFromVideo\(metadata.mediaTime\)/);
 const update=source.slice(source.indexOf('    function updateFromVideo('),source.indexOf('    programPlayers.forEach'));
 assert.match(update,/if \(trimActive\).*return/);
 assert.match(update,/if \(playing && sourceTime >= clip.out_s/);
 assert.doesNotMatch(update,/clips\[nextBase\]\.source_id === activeId/);
});

test('trim seeks coalesce while decoding and the committed boundary retains its inset',()=>{
 assert.match(functionText('applySeek','playFailed'),/preview.seeking\) return/);
 assert.match(source,/if \(pointer.type !== 'pointercancel'\) move\(pointer\)/);
 assert.match(source,/setTrimMode\(false, true\); render\(\); seekSequence\(boundary\); showJoin\(index, edge\)/);
 const join=functionText('showJoin','setTrimMode');
 assert.match(join,/edge === 'out' \? other.in_s/);
 assert.match(join,/other.out_s - 1 \/ fps/);
});
