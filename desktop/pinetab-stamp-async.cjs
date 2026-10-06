/* A slow SMB source must not freeze the desktop's windows or mirror socket. */
'use strict';
const path = require('node:path');
const {Worker} = require('node:worker_threads');
class StampSampler {
  constructor({WorkerClass=Worker, workerPath=path.join(__dirname,'pinetab-stamp-worker.cjs'),
      timeoutMs=30000, cacheMs=15000, now=Date.now} = {}) {
    Object.assign(this,{WorkerClass,workerPath,timeoutMs,cacheMs,now});
    this.worker=null; this.stopping=false; this.sequence=0;
    this.pending=new Map(); this.inFlight=new Map(); this.cache=new Map();
    this.freshFlight=new Set(); this.refreshes=new Map();
  }
  failPending(error) {
    for (const task of this.pending.values()) { clearTimeout(task.timer); task.reject(error); }
    this.pending.clear(); this.inFlight.clear(); this.freshFlight.clear();
  }
  ensureWorker() {
    if (this.stopping) throw Error('the source hash worker is still stopping');
    if (this.worker) return this.worker;
    const worker=new this.WorkerClass(this.workerPath);
    this.worker=worker;
    worker.on('message', reply => {
      if (this.worker!==worker) return;
      const task=this.pending.get(reply.id);
      if (!task) return;
      clearTimeout(task.timer); this.pending.delete(reply.id); this.inFlight.delete(task.key);
      this.freshFlight.delete(task.key);
      if (reply.error) task.reject(Error(reply.error));
      else if (!reply.value || typeof reply.value.stamp!=='string' || !Number.isFinite(reply.value.files)) {
        task.reject(Error('the source hash worker returned an invalid stamp'));
      } else {
        this.cache.set(task.key,{at:this.now(),value:reply.value});
        if (this.cache.size>32) this.cache.delete(this.cache.keys().next().value);
        task.resolve(reply.value);
      }
    });
    worker.on('error', error => { if(this.worker===worker) this.failPending(error); });
    worker.on('exit', code => {
      if (this.worker!==worker) return;
      this.worker=null; this.stopping=false;
      this.failPending(Error('the source hash worker exited ('+code+')'));
    });
    worker.unref();
    return worker;
  }
  read(root, canon, {fresh=false} = {}) {
    const key=JSON.stringify([root,canon||'']);
    if (this.inFlight.has(key)) {
      const pending=this.inFlight.get(key);
      if (!fresh || this.freshFlight.has(key)) return pending;
      // Install/build proof cannot borrow an automatic scan that began earlier.
      if (this.refreshes.has(key)) return this.refreshes.get(key);
      const refresh=pending.catch(()=>{}).then(()=>this.read(root,canon,{fresh:true}))
        .finally(()=>{if(this.refreshes.get(key)===refresh)this.refreshes.delete(key);});
      this.refreshes.set(key,refresh);
      return refresh;
    }
    const cached=this.cache.get(key);
    if (!fresh && cached && this.now()-cached.at<this.cacheMs) return Promise.resolve(cached.value);
    let worker;
    try { worker=this.ensureWorker(); } catch(error) { return Promise.reject(error); }
    const id=++this.sequence;
    let resolve,reject;
    const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const timer=setTimeout(()=>{
      if (!this.pending.has(id)) return;
      this.stopping=true;
      this.failPending(Error('the source hash did not finish within '+this.timeoutMs+'ms'));
      // Termination may await a blocked native file read. The parent never does.
      Promise.resolve(worker.terminate()).catch(()=>{});
    },this.timeoutMs);
    this.pending.set(id,{key,resolve,reject,timer}); this.inFlight.set(key,promise);
    if (fresh) this.freshFlight.add(key);
    try { worker.postMessage({id,root,canon}); }
    catch(error) {
      clearTimeout(timer); this.pending.delete(id); this.inFlight.delete(key);
      this.freshFlight.delete(key); reject(error);
    }
    return promise;
  }
  close() {
    this.failPending(Error('the source hash sampler closed'));
    if (!this.worker) return Promise.resolve();
    this.stopping=true;
    return this.worker.terminate();
  }
}
const sampler=new StampSampler();
module.exports={StampSampler,stampAsync:(root,canon,options)=>sampler.read(root,canon,options)};
