const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const THREE=require('../desktop/vendor/three.min.js');
test('shape-burst keeps animating through strong and repeated audio beats',()=>{
  const context=vm.createContext({console,THREE});
  for(const file of ['core/PineViz.js','visualizers/_shared.js','visualizers/10-ShapeBurst.js']){
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../desktop/renderer/pipviz',file),'utf8'),context);
  }
  const P=context.PineViz,definition=P.registry.find(v=>v.id==='shape-burst');
  const visual=definition.create({THREE,preset:definition.defaults,quality:{scale:.35},size:{aspect:1.675},
    palette:{bg:'#03061a',bg2:'#0a1c4d',primary:'#2b7bff',secondary:'#8a4dff',accent:'#3de1ff',glow:'#6f8cff'},
    rng:P.util.mulberry32(7)});
  visual.init();
  try{
    const state={energy:.8,rms:.6,bass:.5,mid:.4,treble:.3,beat:1,beatCount:0};
    for(let frame=0;frame<180;frame++){
      state.beatCount=Math.floor(frame/45);
      visual.update(state,1/60,frame/60);
    }
    const glyphs=visual.scene.children.find(child=>child.instanceMatrix);
    assert(glyphs.instanceMatrix.array.every(Number.isFinite));
    assert(visual.count()>=60);
  }finally{visual.dispose();}
});
