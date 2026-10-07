// Direction chevrons along the van routes. The image is a signed distance field built from pixels in
// code (no canvas, no sprite file), so the style stays offline and one image takes each van's colour
// through `icon-color`. It points along +x; maplibre turns it along the line in travel order.

export const ARROW_IMAGE = "van-arrow";
export const ARROW_SIZE = 24;
/** Distance in pixels from the edge to full transparency (maplibre's SDF edge sits at alpha 0.75). */
const RADIUS = 4;
const CUTOFF = 0.25;

type Pt = readonly [number, number];
// A chevron (">") drawn as two thick strokes meeting at the tip, centred in the image.
const TIP: Pt = [17, 12];
const ARMS: readonly Pt[] = [
  [8, 4],
  [8, 20],
];
const HALF_STROKE = 2.5;

function segmentDistance(p: Pt, a: Pt, b: Pt): number {
  const [px, py] = p;
  const [ax, ay] = a;
  const dx = b[0] - ax;
  const dy = b[1] - ay;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** Signed distance to the chevron outline: negative inside the stroke. */
function chevronDistance(p: Pt): number {
  return Math.min(...ARMS.map((arm) => segmentDistance(p, arm, TIP))) - HALF_STROKE;
}

/** RGBA pixels for `map.addImage(ARROW_IMAGE, arrowImage(), { sdf: true })`. */
export function arrowImage(): { width: number; height: number; data: Uint8Array } {
  const data = new Uint8Array(ARROW_SIZE * ARROW_SIZE * 4);
  for (let y = 0; y < ARROW_SIZE; y++) {
    for (let x = 0; x < ARROW_SIZE; x++) {
      const d = chevronDistance([x + 0.5, y + 0.5]);
      const alpha = Math.round(255 * Math.max(0, Math.min(1, 1 - (d / RADIUS + CUTOFF))));
      const i = (y * ARROW_SIZE + x) * 4;
      data[i] = 255;
      data[i + 1] = 255;
      data[i + 2] = 255;
      data[i + 3] = alpha;
    }
  }
  return { width: ARROW_SIZE, height: ARROW_SIZE, data };
}
