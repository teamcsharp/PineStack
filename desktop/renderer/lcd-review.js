// Canvas-only review of one immutable cut occurrence. No playback commands.
(function (root) {
  const BASE = '/api/orchestrator/rejections';
  const text = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);
  const inside = (x, y, box) => x >= box.x && x < box.x + box.w && y >= box.y && y < box.y + box.h;
  function geometry(width = 320, height = 240) {
    const sx = width / 320, sy = height / 240;
    const boxes = {panel:[6,64,308,172],body:[12,88,296,84],previous:[12,174,142,24],
      next:[166,174,142,24],accept:[12,201,142,33],reject:[166,201,142,33],close:[266,9,48,44],
      words:[76,34,58,24],why:[138,34,58,24],system:[200,34,60,24]};
    return Object.fromEntries(Object.entries(boxes).map(([key,[x,y,w,h]]) => [key,{x:x*sx,y:y*sy,w:w*sx,h:h*sy}]));
  }
  function create(options = {}) {
    const now = options.now || Date.now;
    let visible = false, ref = null, detail = null, generation = 0, loading = false, pending = null;
    let error = '', message = '', stale = false, offset = 0, lines = [], layoutText = '', shownAt = null, section = 'words';
    const pageSize = 6;
    const same = item => ref && item && ref.review_id === item.review_id && Number(ref.review_seq) === Number(item.review_seq);
    const armed = () => shownAt != null && now() - shownAt >= 350;
    const valid = () => !!(detail && ref?.review_id && Number(ref.review_seq) > 0
      && detail.revision != null && Number.isInteger(Number(detail.revision)) && Number(detail.revision) >= 0
      && (detail.candidate || detail.source));
    const actionable = () => visible && valid() && !loading && !pending && !error && !stale && armed();
    function snapshot() {
      return {open:visible,busy:!!pending,loading,detail,error,message,stale,section,offset,totalLines:lines.length,
        selectedId:ref?.review_id || '',eventSeq:Number(ref?.review_seq) || 0,revision:detail?.revision,
        page:Math.floor(offset/pageSize)+1,pages:Math.max(1,Math.ceil(lines.length/pageSize)),armed:armed(),
        canAccept:actionable() && !detail?.technical && detail?.review_status !== 'allowed',
        canReject:actionable() && detail?.review_status !== 'kept'};
    }
    const changed = () => options.onChange?.(snapshot());
    function resetLayout() { lines = []; layoutText = ''; offset = 0; shownAt = null; }
    function close() {
      if (!visible) return false;
      visible = false; ++generation; loading = false;
      changed(); options.onClose?.(); return true;
    }
    function applyRecord(result, target) {
      const row = result?.row || result;
      if (!row || String(row.id || '') !== String(target.review_id)) throw new Error('The response belongs to another cut.');
      const sequence = row.event_seq ?? row.review_seq;
      if (sequence == null) throw new Error('The station did not confirm this cut occurrence. Refresh after its review service is updated.');
      if (Number(sequence) !== Number(target.review_seq)) throw new Error('This cut changed. Close and reopen its updated row.');
      if (row.revision == null || !Number.isInteger(Number(row.revision))) throw new Error('This cut has no current review revision.');
      if (detail && String(detail.id) === String(row.id) && Number(row.revision) < Number(detail.revision)) return false;
      detail = row;
      if (row.occurrence_current === false || row.read_only) {
        stale = true; message = 'A newer occurrence exists. Close and reopen its updated cut row before deciding.';
      }
      resetLayout(); return true;
    }
    async function load() {
      const target = {...ref}, token = ++generation;
      loading = true; error = ''; message = ''; stale = false; detail = null; resetLayout(); changed();
      try {
        const result = await options.get(BASE + '/' + encodeURIComponent(target.review_id)
          + '?event_seq=' + encodeURIComponent(target.review_seq));
        if (!visible || token !== generation || !same(target)) return;
        if (result?.ok === false) throw new Error(result.error || result.detail || 'The review is unavailable.');
        applyRecord(result,target);
      } catch (reason) {
        if (!visible || token !== generation || !same(target)) return;
        error = String(reason.message || reason); stale = /409|changed|stale|another cut/i.test(error);
      } finally { if (token === generation) { loading = false; changed(); } }
    }
    async function open(value) {
      ++generation; visible = true; ref = {...(value || {})}; detail = null; error = ''; message = ''; stale = false; section = 'words'; resetLayout();
      if (!ref.review_id || !(Number(ref.review_seq) > 0) || ref.review_state === 'unavailable') {
        loading = false;
        error = 'No stored review is linked to this cut. Its wording remains held; no decision was sent.';
        changed(); return;
      }
      return load();
    }
    async function vote(action) {
      if (!actionable() || action === 'allow' && (detail.technical || detail.review_status === 'allowed')
          || action === 'keep' && detail.review_status === 'kept') return;
      const target = {...ref}, record = detail;
      pending = {review_id:target.review_id,review_seq:target.review_seq,action};
      message = action === 'allow' ? 'Saving acceptance...' : 'Keeping this wording rejected...'; changed();
      try {
        const result = await options.post(BASE + '/' + encodeURIComponent(target.review_id), {
          action,expected_revision:Number(record.revision),expected_event_seq:Number(target.review_seq),note:'LCD review',
        });
        if (result?.ok === false) throw new Error(result.error || result.detail || 'The decision was not confirmed.');
        if (visible && same(target)) {
          const updated = result?.row || await options.get(BASE + '/' + encodeURIComponent(target.review_id)
            + '?event_seq=' + encodeURIComponent(target.review_seq));
          if (!visible || !same(target)) return;
          const applied = applyRecord(updated,target);
          message = applied === false ? 'Review changed elsewhere. The current saved decision is shown.' : result?.effect?.say || result?.row?.effect?.say
            || (action === 'allow' ? 'Wording accepted. Scheduled recovery will check its recording.' : 'Wording stays rejected.');
          error = ''; resetLayout();
        }
      } catch (reason) {
        if (visible && same(target)) {
          error = String(reason.message || reason);
          stale = /409|changed|stale|revision|another cut/i.test(error);
          message = stale ? 'This cut changed. Close and reopen its updated row.'
            : 'Decision not confirmed. Retry record checks its saved state; it never repeats a vote.';
          detail = null; resetLayout();
        }
      } finally { pending = null; changed(); }
    }
    function scroll(delta) {
      if (!visible) return false;
      offset = Math.max(0,Math.min(Math.max(0,Math.floor((lines.length-1)/pageSize)*pageSize),offset+Number(delta || 0)*pageSize));
      changed(); return true;
    }
    function swipe(direction) { if (!visible) return false; return scroll(direction === 'up' ? 1 : -1); }
    function tap(x,y,width=320,height=240) {
      if (!visible) return false;
      const g=geometry(width,height);
      for(const name of ['words','why','system'])if(inside(x,y,g[name])){
        section=name;offset=0;layoutText='';lines=[];changed();return true;
      }
      if (inside(x,y,g.close) || !inside(x,y,g.panel)) { close(); return true; }
      if (inside(x,y,g.previous)) return scroll(-1);
      if (inside(x,y,g.next)) return scroll(1);
      if (inside(x,y,g.accept)) {
        if (error && !stale && ref.review_id && !pending && !loading) void load();
        else void vote('allow');
      } else if (inside(x,y,g.reject)) void vote('keep');
      return true;
    }
    function content() {
      const row = detail || ref || {}, context = row.context || {};
      const parts = [];
      if (loading) parts.push('Loading the complete cut...');
      if (message) parts.push(message);
      if (error) parts.push('REVIEW UNAVAILABLE\n' + error);
      const candidate = row.candidate || row.rejected_candidate || row.text || '';
      if (section === 'words') {
        if (candidate) parts.push('CUT WORDING\n' + text(candidate));
        if (row.source && row.source !== candidate) parts.push('ORIGINAL WORDING\n' + text(row.source));
      }
      const reasons = row.reasons || ref?.reasons;
      if (section === 'why') {
        if (row.gate || ref?.gate) parts.push('RESPONSIBLE GATE\n' + text(row.gate || ref.gate));
        if (reasons) parts.push('FULL REASONS\n' + (Array.isArray(reasons) ? reasons.map(text).join('\n') : text(reasons)));
        if (row.evaluation) parts.push('MACHINE EVALUATION\n'+text(row.evaluation));
        if (row.technical) parts.push('TECHNICAL CHECK\nAcceptance cannot repair missing or invalid audio. Keep rejected remains available.');
      }
      if (section === 'system') {
        const path = row.system_path || context.system_path || context.pipeline_path || context.route;
        parts.push('SYSTEM PATH\n' + (path ? text(path) : 'Gate: '+text(row.gate || ref?.gate || 'editorial gate')+'\nNo additional system path was stored.'));
        const where = ['kind','stage','speaker','who','marker','turn','entry_id','trace_id']
          .filter(key=>context[key] != null && context[key] !== '').map(key=>key+': '+text(context[key]));
        if (where.length) parts.push('WRITING / RECORDING CONTEXT\n'+where.join('\n'));
        parts.push('REVIEW STATE\n'+text(row.review_status || 'pending'));
        if (row.effect?.say || row.effect?.status) parts.push('SAVED EFFECT\n'+text(row.effect.say || row.effect.status));
        const preference = row.preference || row.effect?.preference;
        if (preference) parts.push('FUTURE FEEDBACK\n'+[preference.say,preference.mode,
          preference.count != null ? 'Saved examples: '+preference.count : ''].filter(Boolean).map(text).join('\n'));
      }
      return parts.join('\n\n') || 'No full wording was supplied for this cut.';
    }
    function wrap(ctx,value,width) {
      const output=[];
      for (const paragraph of String(value).replace(/\r/g,'').split('\n')) {
        if (!paragraph) { output.push(''); continue; }
        let rest=Array.from(paragraph);
        while(rest.length) {
          let low=1,high=rest.length,fit=1;
          while(low<=high) { const mid=(low+high)>>1;
            if(ctx.measureText(rest.slice(0,mid).join('')).width<=width){fit=mid;low=mid+1;}else high=mid-1;
          }
          let end=fit;
          if(fit<rest.length)for(let i=fit-1;i>0;i--)if(/\s/.test(rest[i])){end=i;break;}
          output.push(rest.slice(0,end).join('')); rest=rest.slice(end);
          if(rest[0]===' ')rest.shift();
        }
      }
      return output;
    }
    function draw(ctx,width=320,height=240) {
      if (!visible) return false;
      ctx.save();ctx.scale(width/320,height/240);ctx.textBaseline='alphabetic';ctx.textAlign='left';
      // The native AV/PB button owns x<64,y<60. Never paint that region.
      ctx.fillStyle='#07121b';ctx.fillRect(64,0,256,60);ctx.fillRect(0,60,320,180);
      ctx.fillStyle='#edf8f2';ctx.font='bold 15px sans-serif';ctx.fillText('Review cut wording',76,24,184);
      const g=geometry(), paint=(box,label,enabled,tone='#244137')=>{
        ctx.fillStyle=enabled?tone:'#203039';ctx.fillRect(box.x,box.y,box.w,box.h);
        ctx.fillStyle=enabled?'#f0fff4':'#80969e';ctx.font='bold 12px sans-serif';ctx.textAlign='center';
        ctx.fillText(label,box.x+box.w/2,box.y+box.h/2+4,box.w-6);ctx.textAlign='left';
      };
      paint(g.close,'Close',true);
      for(const name of ['words','why','system'])paint(g[name],name[0].toUpperCase()+name.slice(1),true,section===name?'#38604e':'#243c46');
      ctx.fillStyle='#142733';ctx.fillRect(g.panel.x,g.panel.y,g.panel.w,g.panel.h);
      ctx.font='12px sans-serif';
      const body=content();
      if(body!==layoutText){layoutText=body;lines=wrap(ctx,body,g.body.w);offset=Math.min(offset,Math.max(0,Math.floor((lines.length-1)/pageSize)*pageSize));}
      if(detail && !loading && shownAt==null)shownAt=now();
      ctx.fillStyle='#9edfc2';ctx.font='bold 11px sans-serif';
      ctx.fillText((pending?'Saving...':loading?'Loading...':'Cut '+(ref?.review_seq || '?'))+'  /  page '+(Math.floor(offset/pageSize)+1)+' of '+Math.max(1,Math.ceil(lines.length/pageSize)),12,79,296);
      ctx.save();ctx.beginPath();ctx.rect(g.body.x,g.body.y,g.body.w,g.body.h);ctx.clip();
      ctx.font='12px sans-serif';ctx.fillStyle='#f1f5f8';
      lines.slice(offset,offset+pageSize).forEach((line,i)=>ctx.fillText(line,g.body.x,g.body.y+12+i*14));ctx.restore();
      paint(g.previous,'Previous page',offset>0,'#293f4c');
      paint(g.next,'Next page',offset+pageSize<lines.length,'#293f4c');
      const can=actionable();
      const retry=!!(error&&!stale&&ref?.review_id&&Number(ref.review_seq)>0);
      paint(g.accept,retry?'Retry record':'Accept wording',retry?!pending&&!loading:can&&!detail?.technical&&detail?.review_status!=='allowed');
      paint(g.reject,'Reject wording',can&&detail?.review_status!=='kept','#663c3a');
      ctx.restore();return true;
    }
    return {open,close,tap,swipe,scroll,draw,snapshot};
  }
  const api={create,geometry};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.PineLcdReview=api;
})(typeof window==='undefined'?globalThis:window);
