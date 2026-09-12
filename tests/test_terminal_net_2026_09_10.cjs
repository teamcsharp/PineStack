/* Finding a Pine Box terminal on the network, and talking to it.
 *
 * Nothing here opens a socket: the probe is injected, so a discovery sweep
 * is exercised in full without touching the network. That matters, because
 * the one behaviour worth guaranteeing is that a sweep stays INSIDE the
 * private subnets this machine is on and never wanders further.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {
  parseMdns, parseWireless, parseAddress, localSubnets, sweep, discover
} = require('../desktop/terminal-net.cjs');
const {Terminal} = require('../desktop/terminal.cjs');

const MDNS = [
  'List of discovered mdns services',
  'adb-HA1Y7RCV-vWmDCe\t_adb-tls-connect._tcp\t10.89.1.77:41237',
  'adb-OTHERTAB-qq11Zz\t_adb._tcp\t10.89.1.91:5555'
].join('\n');

test('mDNS output is read, and the serial pulled out of the service name', () => {
  const found = parseMdns(MDNS);
  assert.equal(found.length, 2);
  assert.equal(found[0].serial, 'HA1Y7RCV');
  assert.equal(found[0].host, '10.89.1.77');
  assert.equal(found[0].port, 41237);
  assert.equal(found[1].serial, 'OTHERTAB');
  /* The header is not a device. */
  assert.equal(parseMdns('List of discovered mdns services').length, 0);
  assert.equal(parseMdns('').length, 0);
});

test('a wireless device in adb devices is host:port, not a serial', () => {
  const rows = parseWireless([
    'List of devices attached',
    '10.89.1.77:5555\tdevice',
    '10.89.1.91:5555\toffline'
  ].join('\n'));
  assert.equal(rows.length, 2);
  assert.equal(rows[0].host, '10.89.1.77');
  assert.equal(rows[0].connected, true);
  assert.equal(rows[1].connected, false);
  /* A USB serial is not a wireless row and must not be mistaken for one. */
  assert.equal(parseWireless('HA1Y7RCV\tdevice').length, 0);
});

test('the tablet own address is read from ip addr', () => {
  const parsed = parseAddress('    inet 10.89.1.77/24 brd 10.89.1.255 scope global wlan0');
  assert.deepEqual(parsed, {address: '10.89.1.77', prefix: 24});
  assert.equal(parseAddress('no address here'), null);
  assert.equal(parseAddress(''), null);
});

test('only private subnets this machine is attached to are ever swept', () => {
  const subnets = localSubnets({
    'Wi-Fi': [{family: 'IPv4', address: '10.89.1.42', internal: false}],
    'Ethernet': [{family: 'IPv4', address: '192.168.7.5', internal: false}],
    'Loopback': [{family: 'IPv4', address: '127.0.0.1', internal: true}],
    'VPN': [{family: 'IPv4', address: '203.0.113.9', internal: false}],
    'Docker': [{family: 'IPv4', address: '172.17.0.1', internal: false}],
    'v6': [{family: 'IPv6', address: 'fe80::1', internal: false}]
  });
  assert.ok(subnets.includes('10.89.1'));
  assert.ok(subnets.includes('192.168.7'));
  assert.ok(subnets.includes('172.17.0'));
  assert.ok(!subnets.includes('127.0.0'), 'loopback is not a network to scan');
  assert.ok(!subnets.includes('203.0.113'), 'a public address must never be swept');
  assert.equal(subnets.length, 3);
});

test('a sweep covers its own /24 and stops there', async () => {
  const asked = [];
  const probe = async (host) => { asked.push(host); return host === '10.89.1.77'; };
  const hits = await sweep('10.89.1', {probe, concurrency: 8});
  assert.deepEqual(hits, ['10.89.1.77']);
  assert.equal(asked.length, 254, 'a /24 is 254 hosts');
  assert.ok(asked.every((h) => h.startsWith('10.89.1.')));
  assert.ok(!asked.includes('10.89.1.0') && !asked.includes('10.89.1.255'),
    'network and broadcast addresses are not hosts');
});

test('mDNS wins, and no sweep happens when it answers', async () => {
  let swept = false;
  const result = await discover({
    runAdb: async () => MDNS,
    probe: async () => { swept = true; return false; }
  });
  assert.equal(result.found.length, 2);
  assert.equal(result.found[0].how, 'mdns');
  assert.equal(swept, false, 'a sweep is wasted work when mDNS already answered');
});

test('with mDNS silent it falls back to a sweep of the local subnets', async () => {
  const result = await discover({
    runAdb: async () => 'List of discovered mdns services',
    subnets: ['10.89.1'],
    probe: async (host) => host === '10.89.1.77',
    interfaces: {}
  });
  assert.equal(result.found.length, 1);
  assert.equal(result.found[0].host, '10.89.1.77');
  assert.equal(result.found[0].how, 'sweep');
});

test('the sweep can be refused entirely', async () => {
  let swept = false;
  const result = await discover({
    runAdb: async () => '',
    sweepFallback: false,
    probe: async () => { swept = true; return true; }
  });
  assert.equal(result.found.length, 0);
  assert.equal(swept, false);
});

test('an adb that cannot do mDNS is a note, not a crash', async () => {
  const result = await discover({
    runAdb: async () => { throw new Error('unknown command'); },
    sweepFallback: false
  });
  assert.equal(result.found.length, 0);
  assert.match(result.notes.join(' '), /mDNS discovery is unavailable/);
});

test('enabling wireless reports where to connect, and admits it is not permanent', async () => {
  const calls = [];
  const run = async (args) => {
    calls.push(args.join(' '));
    if (args[0] === 'tcpip') return 'restarting in TCP mode port: 5555';
    if (args.includes('addr')) return 'inet 10.89.1.77/24 brd 10.89.1.255 scope global wlan0';
    return '';
  };
  const result = await new Terminal({run}).wirelessEnable(5555);
  assert.equal(result.ok, true);
  assert.equal(result.address.address, '10.89.1.77');
  assert.match(result.note, /adb connect 10\.89\.1\.77:5555/);
  /* adb tcpip does not survive a reboot unless the build persists it. */
  assert.equal(result.persists, false);
  assert.ok(calls.includes('tcpip 5555'));
});

test('a tablet with no Wi-Fi address says so instead of offering a bad target', async () => {
  const run = async (args) => args[0] === 'tcpip' ? 'restarting in TCP mode port: 5555' : '';
  const result = await new Terminal({run}).wirelessEnable();
  assert.equal(result.address, null);
  assert.match(result.note, /no Wi-Fi address yet/);
});

test('connecting reports success and failure honestly', async () => {
  const ok = await new Terminal({run: async () => 'connected to 10.89.1.77:5555'})
    .wirelessConnect('10.89.1.77');
  assert.equal(ok.ok, true);
  assert.equal(ok.target, '10.89.1.77:5555');

  const bad = await new Terminal({run: async () => 'failed to connect to 10.89.1.77:5555'})
    .wirelessConnect('10.89.1.77');
  assert.equal(bad.ok, false);

  /* A host that already carries a port is not given a second one. */
  const given = await new Terminal({run: async () => 'connected to 10.89.1.9:4444'})
    .wirelessConnect('10.89.1.9:4444');
  assert.equal(given.target, '10.89.1.9:4444');
});

/* Both real shapes of the advertisement. A tablet switched on with
 * `adb tcpip` publishes the BARE `adb-<serial>`; one paired for wireless
 * debugging adds a random suffix. The bare form is what the TB310FU
 * actually published on 2026-09-10, and a pattern that assumed the suffix
 * returned a blank serial for it. */
const MDNS_BARE = [
  'List of discovered mdns services',
  'adb-HA1Y7RCV\t_adb._tcp\t10.89.1.154:5555',
  'adb-HA1Y7RCV\t_adb._tcp\t10.89.1.154:5555'
].join('\n');

test('a bare adb-<serial> advertisement still yields the serial', () => {
  const found = parseMdns(MDNS_BARE);
  assert.equal(found.length, 2, 'adb lists the same device twice; both parse');
  assert.equal(found[0].serial, 'HA1Y7RCV',
    'the random suffix is optional - this is what the real tablet published');
  assert.equal(found[0].host, '10.89.1.154');
  assert.equal(found[0].port, 5555);
});

test('the same device advertised twice is listed once', async () => {
  const result = await discover({runAdb: async () => MDNS_BARE, sweepFallback: false});
  assert.equal(result.found.length, 1, 'deduplicated by address');
  assert.equal(result.found[0].serial, 'HA1Y7RCV');
});

test('enabling wireless waits out the daemon restart before reading the address', async () => {
  /* `adb tcpip` restarts adbd, so the next shell command lands while it is
   * gone. Reading the address once reported "no Wi-Fi address yet" for a
   * tablet that plainly had one. */
  let shellCalls = 0;
  const run = async (args) => {
    if (args[0] === 'tcpip') return 'restarting in TCP mode port: 5555';
    shellCalls += 1;
    if (shellCalls < 3) throw new Error('device offline');
    return 'inet 10.89.1.154/24 brd 10.89.1.255 scope global wlan0';
  };
  const result = await new Terminal({run}).wirelessEnable(5555);
  assert.equal(result.address.address, '10.89.1.154');
  assert.ok(shellCalls >= 3, 'it must retry rather than give up on the first failure');
  assert.match(result.note, /adb connect 10\.89\.1\.154:5555/);
});

test('a device on both USB and Wi-Fi is targeted by serial, not left ambiguous', async () => {
  /* MEASURED: with both transports up, a bare `adb tcpip 5555` answers
   * "error: more than one device/emulator" and does nothing. */
  const calls = [];
  const run = async (args) => {
    calls.push(args.join(' '));
    if (args.includes('tcpip')) {
      return args[0] === '-s' ? 'restarting in TCP mode port: 5555'
        : 'error: more than one device/emulator';
    }
    return 'inet 10.89.1.154/24 brd 10.89.1.255 scope global wlan0';
  };
  const targeted = await new Terminal({run}).wirelessEnable(5555, 'HA1Y7RCV');
  assert.equal(targeted.ok, true);
  assert.ok(calls.includes('-s HA1Y7RCV tcpip 5555'));
  assert.ok(calls.some((c) => c.startsWith('-s HA1Y7RCV shell')),
    'the address read must be targeted too');

  calls.length = 0;
  const ambiguous = await new Terminal({run}).wirelessEnable(5555);
  assert.equal(ambiguous.ok, false,
    '"more than one device" is a failure, not a success with an address');
});

test('a non-routable mDNS address is not offered as a target', () => {
  /* adb has handed back 0.0.0.0 once a TCP transport already existed. */
  const junk = parseMdns([
    'List of discovered mdns services',
    'adb-HA1Y7RCV\t_adb._tcp\t0.0.0.0:5555',
    'adb-HA1Y7RCV\t_adb._tcp\t169.254.3.4:5555',
    'adb-HA1Y7RCV\t_adb._tcp\t10.89.1.154:5555'
  ].join('\n'));
  assert.equal(junk.length, 1, 'only the reachable address survives');
  assert.equal(junk[0].host, '10.89.1.154');
});
