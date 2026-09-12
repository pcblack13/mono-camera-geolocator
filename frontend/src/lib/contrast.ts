/**
 * `lib/contrast.ts` — pick ink that stays readable on a colour the USER chose.
 *
 * ★ WHY THIS EXISTS. Every label the app draws on a coloured chip used to hardcode
 *   white text, which is correct only while the app owns the colour. Once a surveyor
 *   can pick their own marker colours, a pale pick (yellow, cream, light grey) leaves
 *   white-on-white: the rank number, the point code, the badge all vanish while the
 *   shape still draws — the worst kind of failure, because it looks like missing DATA
 *   rather than a bad colour choice.
 */

/** `#rgb` / `#rrggbb` → `[r, g, b]` 0–255. Null for anything else. */
function parseHex(hex: string): [number, number, number] | null {
  const m = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.exec(hex.trim());
  if (m === null) return null;
  const body = m[1];
  const full =
    body.length === 3
      ? body
          .split('')
          .map((c) => c + c)
          .join('')
      : body;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

/**
 * Relative luminance, WCAG 2.x — the sRGB channels linearised and weighted by how
 * much each contributes to perceived brightness.
 */
export function luminance(hex: string): number {
  const rgb = parseHex(hex);
  if (rgb === null) return 0.5; // unknown format: assume mid, so neither ink is claimed
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Black or white — whichever the eye can actually read on `background`.
 *
 * The 0.5 split is luminance, not lightness: it puts the flip where perception
 * puts it (pure yellow #ffff00 reads as light and gets black ink; pure blue
 * #0000ff reads as dark and gets white).
 */
export function readableOn(background: string): string {
  return luminance(background) > 0.5 ? '#000000' : '#ffffff';
}
