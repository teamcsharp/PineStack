// Keep the native display dimensions while fitting Quanta's HTTP body memory.
// CYD has no PSRAM: WebServer retains base64 plus a String copy and decoded JPEG.
(function (root) {
  function jpegBudget(device) {
    const pixels = (Number(device?.width) || 320) * (Number(device?.height) || 240);
    return /^cyd_/.test(String(device?.board || '')) || pixels <= 320 * 240
      ? 12 * 1024 : Math.min(192 * 1024, Math.max(12 * 1024, Math.round(pixels * .16)));
  }
  function encode(canvas, device) {
    const budget = jpegBudget(device);
    const sample = quality => {
      const jpeg = canvas.toDataURL('image/jpeg', quality);
      const body = jpeg.slice(jpeg.indexOf(',') + 1);
      const bytes = body.length * 3 / 4 - (body.endsWith('==') ? 2 : body.endsWith('=') ? 1 : 0);
      return {jpeg, bytes, quality, budget};
    };
    let best = sample(.66);
    if (best.bytes <= budget) return best;
    best = sample(.02);
    if (best.bytes > budget) throw new Error('LCD frame cannot fit the display memory budget.');
    let low = .02, high = .66;
    for (let i = 0; i < 6; i++) {
      const quality = (low + high) / 2, next = sample(quality);
      if (next.bytes <= budget) {best = next; low = quality;} else high = quality;
    }
    return best;
  }
  const api = {jpegBudget, encode};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PineLcdFrame = api;
})(typeof globalThis === 'undefined' ? this : globalThis);
