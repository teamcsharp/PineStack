/* Finding and talking to a Pine Box terminal over the network.
 *
 * Once a tablet is provisioned it should not need a cable again. Two ways
 * to find one, in the order they are worth trying:
 *
 *   1. mDNS. `adb mdns services` lists devices advertising themselves for
 *      wireless debugging. Free, instant, and it survives DHCP moving the
 *      tablet to a different address.
 *   2. A bounded subnet sweep. Only the private ranges this machine is
 *      actually attached to, only the ports we care about, and capped - the
 *      LCD's own discovery does the same thing for the same reason: a scan
 *      that wanders off the local network is a nuisance, not a feature.
 *
 * Everything that touches a socket is injected, so the whole of this file
 * is testable with no network at all.
 */
'use strict';

const net = require('node:net');
const os = require('node:os');

const ADB_PORT = 5555;
const PINE_PORT = 8096;

/* `adb mdns services` prints:
 *   List of discovered mdns services
 *   adb-HA1Y7RCV-abc123  _adb-tls-connect._tcp  10.89.1.77:41237
 */
function parseMdns(text) {
  const out = [];
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^List of/i.test(line)) continue;
    const match = /^(\S+)\s+(\S+)\s+([\d.]+):(\d+)$/.exec(line);
    if (!match) continue;
    /* MEASURED: this tablet advertises plain `adb-HA1Y7RCV`, while devices
     * paired for wireless debugging advertise `adb-HA1Y7RCV-vWmDCe`. A
     * pattern that demanded the random suffix matched neither reliably and
     * silently returned a blank serial, so the name is simply split and the
     * first field taken - Android serials do not contain hyphens. */
    /* MEASURED: once a TCP transport already exists, adb has handed back
     * `0.0.0.0` as the service address. That is not somewhere you can
     * connect to, so it is not a discovery - drop it rather than offer the
     * operator a target that can only fail. */
    if (/^(0\.0\.0\.0|127\.|169\.254\.)/.test(match[3])) continue;
    const rest = match[1].replace(/^adb-/, '');
    out.push({
      name: match[1],
      serial: rest ? rest.split('-')[0] : '',
      service: match[2],
      host: match[3],
      port: Number(match[4])
    });
  }
  return out;
}

/* `adb devices` lists wireless devices as host:port rather than a serial. */
function parseWireless(text) {
  const out = [];
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^List of/i.test(line) || /^\*/.test(line)) continue;
    const match = /^([\d.]+):(\d+)\s+(\S+)/.exec(line);
    if (match) {
      out.push({host: match[1], port: Number(match[2]), state: match[3],
        connected: match[3] === 'device'});
    }
  }
  return out;
}

/* The device's own address, from `ip addr`. Preferred over anything the
 * host guesses, because the tablet knows where it actually is. */
function parseAddress(text) {
  const match = /inet\s+(\d+\.\d+\.\d+\.\d+)\/(\d+)/.exec(String(text || ''));
  if (!match) return null;
  return {address: match[1], prefix: Number(match[2])};
}

/* Only private ranges, and only ones this machine is on. A terminal is a
 * thing on your own LAN; sweeping anything else would be rude and useless. */
function localSubnets(interfaces) {
  const table = interfaces || os.networkInterfaces();
  const found = new Set();
  for (const entries of Object.values(table || {})) {
    for (const entry of entries || []) {
      if (entry.internal) continue;
      if (entry.family !== 'IPv4' && entry.family !== 4) continue;
      const address = String(entry.address || '');
      const parts = address.split('.').map(Number);
      if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) continue;
      const isPrivate = parts[0] === 10
        || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)
        || (parts[0] === 192 && parts[1] === 168);
      if (!isPrivate) continue;
      /* A /24 sweep is 254 hosts. Anything wider is not a discovery, it is
       * a port scan, so a broader netmask is still swept as its /24. */
      found.add(parts.slice(0, 3).join('.'));
    }
  }
  return [...found];
}

function tcpProbe(host, port, timeout) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let settled = false;
    const done = (result) => {
      if (settled) return;
      settled = true;
      try { socket.destroy(); } catch (err) { /* already gone */ }
      resolve(result);
    };
    socket.setTimeout(timeout);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
    try { socket.connect(port, host); } catch (err) { done(false); }
  });
}

/* Sweep a /24 for one port, a bounded number of hosts at a time. */
async function sweep(base, {port = ADB_PORT, timeout = 400, concurrency = 64,
  probe = tcpProbe, from = 1, to = 254} = {}) {
  const hosts = [];
  for (let i = from; i <= to; i += 1) hosts.push(base + '.' + i);
  const hits = [];
  let cursor = 0;
  const worker = async () => {
    while (cursor < hosts.length) {
      const host = hosts[cursor++];
      /* eslint-disable-next-line no-await-in-loop */
      if (await probe(host, port, timeout)) hits.push(host);
    }
  };
  await Promise.all(Array.from({length: Math.min(concurrency, hosts.length)}, worker));
  return hits.sort();
}

/* Everything findable, mDNS first and a sweep only if asked. The sweep is
 * opt-in because it is the slow, noisy option and mDNS usually wins. */
async function discover({runAdb, subnets, sweepFallback = true, port = ADB_PORT,
  probe = tcpProbe, timeout = 400, interfaces} = {}) {
  const found = new Map();
  const notes = [];

  if (typeof runAdb === 'function') {
    try {
      for (const service of parseMdns(await runAdb(['mdns', 'services']))) {
        found.set(service.host, {host: service.host, port: service.port,
          serial: service.serial, how: 'mdns', service: service.service});
      }
    } catch (error) {
      notes.push('mDNS discovery is unavailable: ' + error.message);
    }
  }

  if (!found.size && sweepFallback) {
    const ranges = subnets && subnets.length ? subnets : localSubnets(interfaces);
    if (!ranges.length) notes.push('This machine is not on a private network.');
    for (const base of ranges) {
      /* eslint-disable-next-line no-await-in-loop */
      for (const host of await sweep(base, {port, probe, timeout})) {
        if (!found.has(host)) found.set(host, {host, port, serial: '', how: 'sweep'});
      }
    }
  }
  return {found: [...found.values()], notes};
}

module.exports = {
  parseMdns, parseWireless, parseAddress, localSubnets, sweep, discover,
  tcpProbe, ADB_PORT, PINE_PORT
};
