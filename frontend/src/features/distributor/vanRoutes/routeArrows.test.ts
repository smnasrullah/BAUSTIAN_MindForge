import { describe, expect, it } from "vitest";

import { ARROW_SIZE, arrowImage } from "./routeArrows";

const alphaAt = (data: Uint8Array, x: number, y: number) => data[(y * ARROW_SIZE + x) * 4 + 3] ?? -1;

describe("arrowImage", () => {
  it("is a square RGBA image of the declared size", () => {
    const img = arrowImage();
    expect(img.width).toBe(ARROW_SIZE);
    expect(img.height).toBe(ARROW_SIZE);
    expect(img.data).toHaveLength(ARROW_SIZE * ARROW_SIZE * 4);
  });

  it("is solid on the chevron, past the SDF edge, and clear in the corners", () => {
    const { data } = arrowImage();
    // On the upper arm and at the tip: well inside the 0.75 edge.
    expect(alphaAt(data, 12, 8)).toBeGreaterThan(191);
    expect(alphaAt(data, 16, 12)).toBeGreaterThan(191);
    // Empty corners and the open side of the ">".
    expect(alphaAt(data, 0, 0)).toBe(0);
    expect(alphaAt(data, 23, 23)).toBe(0);
    expect(alphaAt(data, 2, 12)).toBe(0);
  });

  it("points along +x: the tip column is filled, the mirrored column is not", () => {
    const { data } = arrowImage();
    expect(alphaAt(data, 16, 12)).toBeGreaterThan(alphaAt(data, 7, 12));
  });
});
