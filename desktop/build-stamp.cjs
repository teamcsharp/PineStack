'use strict';
const fs=require('node:fs'),path=require('node:path');
// Scan update metadata without holding Electron's event loop on SMB reads.
async function treeStamp(root,{io=fs.promises}={}){
 const wanted=[];
 async function walk(relative){
  let entries;try{entries=await io.readdir(path.join(root,relative),{withFileTypes:true});}catch{return false;}
  for(const entry of entries){const name=relative?relative+'/'+entry.name:entry.name;if(entry.isDirectory())await walk(name);else if(entry.isFile())wanted.push(name);}return true;
 }
 if(!await walk(''))wanted.push('main.js','preload.js','renderer/renderer.js','renderer/index.html','renderer/webview-preload.js','renderer/styles.css');
 let newest=0,bytes=0;const missing=[];
 for(const name of wanted){try{const info=await io.stat(path.join(root,name));newest=Math.max(newest,info.mtimeMs);bytes+=info.size;}catch{missing.push(name);}}
 return {newest,bytes,missing,counted:wanted.length};
}
module.exports={treeStamp};
