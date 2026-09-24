const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
const marker = 'CONTROL_PANEL_HTML = r"""';
const start = source.indexOf(marker);
const end = source.indexOf('\n"""', start + marker.length);
const panel = source.slice(start + marker.length, end);
const exportCode = panel.slice(panel.indexOf('async function exportLightbox()'),
  panel.indexOf('function closeLightbox(event)'));

test('gallery export UI sends selection and follows the device download URL', async () => {
  assert.match(panel, /id="lbExportScope"[\s\S]*value="original"[\s\S]*value="both"/);
  assert.match(panel, /id="lbExportDestination"[\s\S]*value="share"/);
  const controls = {
    lbExportButton: {disabled: false}, lbStatus: {textContent: ''},
    lbExportScope: {value: 'both'}, lbExportDestination: {value: 'device'},
    lbExportName: {value: 'My take'},
  };
  const link = {clicked: false, removed: false, click() {this.clicked = true;},
    remove() {this.removed = true;}};
  let sent;
  const context = {
    lightboxItem: {prompt_id: 'ticket', file: 'render.mp4'},
    navigator: {userAgent: 'Chrome'}, window: {},
    AbortController, setTimeout, clearTimeout,
    document: {getElementById: id => controls[id], createElement: () => link,
      body: {appendChild(node) {assert.equal(node, link);}}},
    api: async (route, options) => {
      assert.equal(route, '/api/gallery/export');
      assert.equal(options.method, 'POST');
      sent = JSON.parse(options.body);
      return {name: 'My take.zip', url: '/api/gallery/export/file?t=signed'};
    },
  };
  vm.createContext(context);
  vm.runInContext(exportCode, context);
  await vm.runInContext('exportLightbox()', context);
  assert.equal(JSON.stringify(sent), JSON.stringify({prompt_id: 'ticket',
    file: 'render.mp4', scope: 'both', destination: 'device', name: 'My take'}));
  assert.equal(link.href, '/api/gallery/export/file?t=signed');
  assert.equal(link.download, 'My take.zip');
  assert.ok(link.clicked && link.removed);
  assert.equal(controls.lbExportButton.disabled, false);
  assert.equal(controls.lbStatus.textContent, 'Downloading My take.zip');

  controls.lbExportDestination.value = 'share';
  context.api = async () => ({name: 'My take.zip', state: 'pending'});
  await vm.runInContext('exportLightbox()', context);
  assert.match(controls.lbStatus.textContent, /queued for PineBoxRecordings/);

  controls.lbExportDestination.value = 'device';
  context.navigator.userAgent = 'PineBoxKiosk/1.0.0';
  context.api = async () => ({name: 'My take.zip',
    url: '/api/gallery/export/file?t=signed'});
  let nativeRequest;
  context.window.pineDesktop = {saveGalleryExport: async request => {
    nativeRequest = request;
    return {ok: true, where: 'Download/Pine Box/My take.zip'};
  }};
  await vm.runInContext('exportLightbox()', context);
  assert.equal(JSON.stringify(nativeRequest), JSON.stringify({
    route: '/api/gallery/export/file?t=signed', name: 'My take.zip'}));
  assert.equal(controls.lbStatus.textContent,
    'Saved My take.zip to Download/Pine Box/My take.zip');
});
