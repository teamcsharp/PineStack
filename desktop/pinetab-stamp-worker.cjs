/* Source hashing runs away from Electron's window and IPC thread. */
'use strict';
const {parentPort} = require('node:worker_threads');
const {stamp} = require('./pinetab-stamp.cjs');
parentPort.on('message', ({id, root, canon}) => {
  try { parentPort.postMessage({id, value:stamp(root, canon)}); }
  catch (error) { parentPort.postMessage({id, error:String(error.message || error)}); }
});
