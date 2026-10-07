// Route colours come from the design tokens (--route-1..6). WebGL paint cannot read CSS variables,
// so they are resolved with getComputedStyle, like the control-room map palette.
export const ROUTE_TOKENS = ["--route-1", "--route-2", "--route-3", "--route-4", "--route-5", "--route-6"] as const;

/** Neutral grey when a token is missing (jsdom, or a stylesheet that failed to load): never invisible. */
const MISSING = "rgb(128, 128, 128)";

export function readRoutePalette(root: HTMLElement = document.documentElement): string[] {
  const css = getComputedStyle(root);
  return ROUTE_TOKENS.map((name) => css.getPropertyValue(name).trim() || MISSING);
}

/** Van 1 gets colour 1; more vans than colours wrap around (the number on the marker still tells them apart). */
export function routeColor(palette: readonly string[], vehicleNo: number): string {
  if (palette.length === 0) return MISSING;
  return palette[(Math.max(1, vehicleNo) - 1) % palette.length] ?? MISSING;
}

/** The CSS variable for a van, for DOM elements that can use it directly (legend swatches, list dots). */
export function routeVar(vehicleNo: number): string {
  return `var(${ROUTE_TOKENS[(Math.max(1, vehicleNo) - 1) % ROUTE_TOKENS.length]})`;
}
