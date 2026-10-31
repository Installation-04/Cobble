export type Rgb = [number, number, number];

/** Extract the hex color tokens of the `:root` (light) or `.dark` block of the token file. */
export function parseTokens(css: string, mode: "light" | "dark"): Record<string, Rgb> {
  const selector = mode === "light" ? ":root" : ".dark";
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`block not found: ${selector}`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  const out: Record<string, Rgb> = {};
  for (const m of body.matchAll(/--([\w-]+):\s*#([0-9a-fA-F]{6})\s*;/g)) {
    const n = parseInt(m[2], 16);
    out[m[1]] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  return out;
}

function channel(v: number): number {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance([r, g, b]: Rgb): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
