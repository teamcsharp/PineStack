// Preserve native pixels and learn a fitting quality instead of binary-searching
// up to eight synchronous encodes on every scrolling frame.
(function (root) {
  const history = new WeakMap();
  function jpegBudget(device) {
    const negotiated = Number(device?.maxJpeg);
    if (Number(device?.pineProtocol) >= 2 && Number(device?.streamPort) > 0
        && Number.isInteger(negotiated) && negotiated >= 12288) return Math.min(24576, negotiated);
    const pixels = (Number(device?.width) || 320) * (Number(device?.height) || 240);
    return /^cyd_/.test(String(device?.board || '')) || pixels <= 320 * 240
      ? 12 * 1024 : Math.min(192 * 1024, Math.max(12 * 1024, Math.round(pixels * .16)));
  }
  function encode(canvas, device) {
    const budget = jpegBudget(device);
    const previous = history.get(canvas);
    let encodes = 0;
    const sample = quality => {
      encodes++;
      const jpeg = canvas.toDataURL('image/jpeg', quality);
      const body = jpeg.slice(jpeg.indexOf(',') + 1);
      const bytes = body.length * 3 / 4 - (body.endsWith('==') ? 2 : body.endsWith('=') ? 1 : 0);
      return {jpeg, bytes, quality, budget, encodes};
    };
    let quality = previous?.budget === budget ? previous.quality : .66;
    // Recover quality gradually after switching from a dense page to simple UI.
    if (previous?.bytes < budget * .72) quality = Math.min(.66, quality + .035);
    let best = sample(quality);
    for (let i = 0; best.bytes > budget && i < 3 && quality > .02; i++) {
      quality = Math.max(.02, quality * Math.min(.78, budget / best.bytes * .82));
      best = sample(quality);
    }
    if (best.bytes > budget) best = sample(.02);
    if (best.bytes > budget) throw new Error('LCD frame cannot fit the display memory budget.');
    history.set(canvas, {quality: best.quality, bytes: best.bytes, budget});
    return best;
  }
  const api = {jpegBudget, encode};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PineLcdFrame = api;
})(typeof globalThis === 'undefined' ? this : globalThis);
