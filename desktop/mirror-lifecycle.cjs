/* One open and one cleanup at a time, including different Mirror instances. */
'use strict';

class MirrorLifecycle {
  constructor() {
    this.opening = null;
    this.closing = Promise.resolve();
    this.current = null;
    this.cleaning = new Set();
    this.stopped = false;
    this.generation = 0;
  }

  open(create) {
    if (this.stopped) return Promise.resolve({ok:false, cancelled:true, why:'the app is closing'});
    if (this.opening) return this.opening;
    const lease = {generation: ++this.generation, closing: false, cleanup: null};
    lease.isCurrent = () => !this.stopped && !lease.closing && this.current === lease;
    this.current = lease;
    const pending = this.closing.catch(() => {}).then(() => {
      if (!lease.isCurrent()) return {ok:false, cancelled:true, why:'the mirror was closed'};
      return create(lease);
    }).finally(() => { if (this.opening === pending) this.opening = null; });
    this.opening = pending;
    return pending;
  }

  close(lease, cleanup) {
    if (!lease) return this.closing;
    if (lease.cleanup) return lease.cleanup;
    lease.closing = true;
    if (this.current === lease) this.current = null;
    // Old remote SIGINT must finish before a replacement encoder can start.
    this.cleaning.add(lease);
    const pending = this.closing.catch(() => {}).then(() => cleanup())
      .finally(() => this.cleaning.delete(lease));
    lease.cleanup = pending;
    this.closing = pending;
    return pending;
  }

  stop() {
    this.stopped = true;
    this.generation += 1;
  }
}

module.exports = {MirrorLifecycle};
