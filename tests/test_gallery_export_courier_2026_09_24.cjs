const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'main.js'),
  'utf8');
const start = source.indexOf('let courierBusy = false;');
const end = source.indexOf('\n}\n', source.indexOf('async function courierRound()', start)) + 2;
assert.ok(start >= 0 && end > start);
const courierCode = source.slice(start, end);

test('gallery courier replaces an existing file with the same byte count', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'gallery-courier-'));
  const target = path.join(folder, 'custom.mp4');
  fs.writeFileSync(target, Buffer.from('old-data'));
  const bytes = Buffer.from('new-data');
  const job = {id: 'gallery-job', name: 'custom.mp4', dest: folder,
    bytes: bytes.length, force: true, url: '/api/export/courier/gallery-job/file'};
  let reported;
  let fetched = false;
  const context = {
    fs, path, Buffer,
    readConfig: () => ({baseUrl: 'http://station'}),
    fetchJson: async (url, options) => {
      if (url.endsWith('/done')) {
        reported = JSON.parse(options.body);
        return {ok: true};
      }
      return {pending: [job]};
    },
    fetch: async () => {
      fetched = true;
      return {ok: true, arrayBuffer: async () => bytes};
    },
    authHeaders: () => ({}),
    rememberLog: () => {},
  };
  vm.createContext(context);
  vm.runInContext(courierCode, context);
  try {
    await vm.runInContext('courierRound()', context);
    assert.ok(fetched);
    assert.deepEqual(fs.readFileSync(target), bytes);
    assert.equal(reported.ok, true);
    assert.equal(reported.path, target);
  } finally {
    fs.rmSync(folder, {recursive: true, force: true});
  }
});
