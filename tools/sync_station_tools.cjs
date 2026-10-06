'use strict';
// These are bundled copies of the canonical frontend tools, kept in sync at build time.
const fs=require('node:fs/promises'),path=require('node:path');
(async()=>{const root=path.resolve(__dirname,'..'),source=path.join(root,'frontend'),target=path.join(root,'desktop/station-tools');await fs.mkdir(target,{recursive:true});for(const file of await fs.readdir(source,{withFileTypes:true}))if(file.isFile()&&/\.(js|css)$/.test(file.name))await fs.copyFile(path.join(source,file.name),path.join(target,file.name));for(const name of ['three.min.js','three.module.js','three.core.js'])await fs.copyFile(path.join(root,'app/src/main/assets/vendor',name),path.join(root,'desktop/vendor',name));})().catch(e=>{console.error(e);process.exitCode=1;});
