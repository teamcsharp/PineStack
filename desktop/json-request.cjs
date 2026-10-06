'use strict';

const READ_TIMEOUT_MS = 30000;
const RETRY_DELAYS_MS = [250, 750];
const TRANSPORT_CODES = new Set([
  'ECONNRESET', 'ECONNREFUSED', 'EPIPE', 'ETIMEDOUT', 'ENETRESET',
  'EHOSTUNREACH', 'ENETUNREACH', 'EAI_AGAIN', 'ERR_STREAM_PREMATURE_CLOSE',
  'UND_ERR_SOCKET', 'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT',
  'UND_ERR_BODY_TIMEOUT'
]);

function transportFailure(error) {
  if (!error || error.name === 'AbortError' || error.name === 'TimeoutError') return false;
  const cause = error.cause || {};
  if (TRANSPORT_CODES.has(error.code) || TRANSPORT_CODES.has(cause.code)) return true;
  return error.name === 'TypeError' && /^(?:fetch failed|failed to fetch|terminated|network request failed|load failed)$/i.test(String(error.message || ''));
}

function abortReason(signal) {
  return signal.reason || Object.assign(new Error('The request was aborted.'), {name: 'AbortError'});
}

function waitForRetry(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(abortReason(signal)); return; }
    let timer;
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', aborted); };
    const aborted = () => { cleanup(); reject(abortReason(signal)); };
    timer = setTimeout(() => { cleanup(); resolve(); }, ms);
    signal?.addEventListener('abort', aborted, {once: true});
    // Close the race between the first check and listener attachment.
    if (signal?.aborted) aborted();
  });
}

async function fetchJson(url, options = {}, dependencies = {}) {
  const read = String(options.method || 'GET').toUpperCase() === 'GET';
  const fetchRequest = dependencies.fetch || globalThis.fetch;
  const pause = dependencies.wait || waitForRetry;
  // The same signal covers fetching, consuming the body and every backoff.
  // A retry never grants another full deadline to an overdue request.
  const signal = options.signal || (read
    ? (dependencies.timeoutSignal || (ms => AbortSignal.timeout(ms)))(READ_TIMEOUT_MS)
    : undefined);
  const sent = signal ? {...options, signal} : options;
  for (let attempt = 0; ; attempt++) {
    if (signal?.aborted) throw abortReason(signal);
    let response;
    try {
      response = await fetchRequest(url, sent);
      const text = await response.text();
      let body = null;
      try { body = text ? JSON.parse(text) : {}; } catch { body = {text}; }
      if (!response.ok) {
        const detail = body && (body.detail || body.error || body.text);
        throw new Error(detail || `${response.status} ${response.statusText}`);
      }
      return body;
    } catch (error) {
      // Once an HTTP error arrives, even a broken error-body transfer must
      // not turn it into a repeated request. Mutations are never replayed.
      if (!read || attempt >= RETRY_DELAYS_MS.length || signal?.aborted
          || (response && !response.ok) || !transportFailure(error)) throw error;
      await pause(RETRY_DELAYS_MS[attempt], signal);
    }
  }
}

module.exports = {fetchJson, transportFailure, waitForRetry, READ_TIMEOUT_MS};
