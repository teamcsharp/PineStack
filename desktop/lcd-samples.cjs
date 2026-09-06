const fs = require('node:fs').promises;
const path = require('node:path');
const crypto = require('node:crypto');

async function saveLcdSample({id, at, config, defaultDirectory, fetcher = fetch}) {
  const line = String(id || '').trim();
  if (!line || line.length > 160 || !/^[a-zA-Z0-9_.:-]+$/.test(line)) throw new Error('Select an available booth line first.');
  const url = String(config.baseUrl).replace(/\/+$/, '') + '/api/booth/clip?line=' + encodeURIComponent(line)
    + '&at=' + Math.max(0, Number(at) || 0);
  const response = await fetcher(url, {headers: config.apiKey ? {Authorization: 'Bearer ' + config.apiKey} : {},
    signal: AbortSignal.timeout(60000)});
  if (!response.ok) throw new Error('The station could not provide this sample (HTTP ' + response.status + ').');
  const type = response.headers.get('content-type') || '';
  if (!/^audio\//i.test(type) && !/^application\/octet-stream/i.test(type)) throw new Error('The station response was not audio.');
  const chunks = []; let size = 0;
  for await (const part of response.body) {
    size += part.length;
    if (size > 64 * 1024 * 1024) throw new Error('The sample exceeds the 64 MB download limit.');
    chunks.push(Buffer.from(part));
  }
  if (!size) throw new Error('The station returned an empty sample.');
  const ext = /wav/i.test(type) ? 'wav' : /ogg/i.test(type) ? 'ogg' : /flac/i.test(type) ? 'flac' : /mp4|m4a/i.test(type) ? 'm4a' : 'mp3';
  const directory = path.resolve(config.saveDir || defaultDirectory);
  await fs.mkdir(directory, {recursive: true});
  const file = path.join(directory, 'booth-' + line.replace(/[^a-zA-Z0-9_-]/g, '_') + '-' + crypto.randomUUID().slice(0, 8) + '.' + ext);
  const partial = file + '.partial';
  try { await fs.writeFile(partial, Buffer.concat(chunks), {flag: 'wx'}); await fs.rename(partial, file); }
  catch (error) { try { await fs.unlink(partial); } catch {} throw error; }
  return {ok: true, file, directory, bytes: size, exact: response.headers.get('x-pine-exact') === '1',
    cut: response.headers.get('x-pine-cut') || ''};
}
module.exports = {saveLcdSample};
