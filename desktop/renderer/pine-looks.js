/* LOOK TRANSFORMS, THE SAME SHAPE BLENDER'S ARE.
 *
 * "I want to have look filters. The exact same look filters that are
 *  available in Blender. I want to have filmic."
 *
 * Blender's Filmic is a view transform plus a contrast LOOK: the transform
 * maps a wide scene range into the display, and the look is a contrast curve
 * applied in that space. What arrives here is already display-referred JPEG -
 * the sensor's own tone mapping has happened - so this cannot be Filmic in
 * the colour-managed sense, and saying otherwise would be a lie told in a
 * tooltip.
 *
 * What it CAN do, and does: put the picture back into a roughly linear space,
 * apply the same family of curves Blender's looks describe, and map it out
 * again. On a camera feed that is the difference the operator is actually
 * after - highlights that roll instead of clipping, and shadows that open.
 *
 * EVERY LOOK IS A PURE FUNCTION OF ONE CHANNEL VALUE, so a 256-entry table is
 * exact rather than an approximation, and applying it to a 12-megapixel frame
 * is a lookup rather than a pow() per pixel.
 */
(function (root) {
  'use strict';

  function clamp(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

  /* sRGB <-> linear, so the curves below act on light rather than on code
     values. Doing contrast in sRGB is what makes a "contrast" slider crush
     the shadows and nothing else. */
  function toLinear(v) {
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  }
  function toSRGB(v) {
    return v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  }

  /* The filmic shoulder: a Reinhard-style roll with a toe, which is the
     characteristic Blender's Filmic has and a plain gamma does not - the
     highlights bend instead of arriving at white and stopping. */
  function filmic(x, contrast) {
    const a = 2.51 * contrast;
    const b = 0.03;
    const c = 2.43 * contrast;
    const d = 0.59;
    const e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e));
  }

  const LOOKS = [
    { id: 'none', name: 'Standard', note: 'The picture as the camera gave it.' },
    { id: 'filmic-vlow', name: 'Filmic — Very Low Contrast', contrast: 0.6 },
    { id: 'filmic-low', name: 'Filmic — Low Contrast', contrast: 0.8 },
    { id: 'filmic', name: 'Filmic — Base Contrast', contrast: 1.0 },
    { id: 'filmic-med', name: 'Filmic — Medium High Contrast', contrast: 1.2 },
    { id: 'filmic-high', name: 'Filmic — High Contrast', contrast: 1.45 },
    { id: 'filmic-vhigh', name: 'Filmic — Very High Contrast', contrast: 1.7 },
    { id: 'flat', name: 'Flat (grade later)',
      note: 'Lifts the shadows and holds the highlights, so nothing is lost '
        + 'before it reaches a grade.' },
    { id: 'raw', name: 'Raw (linear)',
      note: 'No display curve at all. Dark on screen, and correct if '
        + 'something downstream is going to do the transform.' }
  ];

  /**
   * A 256-entry table for one look at one gamma and one exposure.
   *
   * exposure is in STOPS, the unit a camera uses, so +1 is twice the light.
   */
  function table(id, gamma, stops) {
    const out = new Uint8ClampedArray(256);
    const look = LOOKS.find((l) => l.id === id) || LOOKS[0];
    const gain = Math.pow(2, Number(stops) || 0);
    const g = Number(gamma) > 0 ? Number(gamma) : 1;

    for (let i = 0; i < 256; i += 1) {
      let v = toLinear(i / 255) * gain;

      if (look.id.indexOf('filmic') === 0) {
        v = filmic(v, look.contrast);
        /* filmic() answers in display space already, so it is not taken back
           through toSRGB - doing both is the double-gamma that makes a
           "filmic" look washed out and grey. */
        v = Math.pow(clamp(v), 1 / g);
        out[i] = Math.round(clamp(v) * 255);
        continue;
      }

      if (look.id === 'flat') {
        /* A shallow S with a lifted toe: nothing clipped, nothing crushed. */
        v = clamp(v);
        v = 0.06 + v * 0.84;
        v = toSRGB(v);
      } else if (look.id === 'raw') {
        v = clamp(v);              /* left linear on purpose */
      } else {
        v = toSRGB(clamp(v));
      }

      v = Math.pow(clamp(v), 1 / g);
      out[i] = Math.round(clamp(v) * 255);
    }
    return out;
  }

  /** Apply a look to an ImageData in place. */
  function apply(image, id, gamma, stops) {
    if ((!id || id === 'none') && Number(gamma || 1) === 1 && !Number(stops)) {
      return image;
    }
    const map = table(id, gamma, stops);
    const px = image.data;
    for (let i = 0; i < px.length; i += 4) {
      px[i] = map[px[i]];
      px[i + 1] = map[px[i + 1]];
      px[i + 2] = map[px[i + 2]];
    }
    return image;
  }

  root.pineLooks = { LOOKS, table, apply };
})(window);
