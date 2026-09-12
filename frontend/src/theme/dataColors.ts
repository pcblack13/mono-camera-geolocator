/**
 * `theme/dataColors.ts` — colours that ARE data, not chrome.
 *
 * ★ These are meanings, not styling: a detection class's colour identifies the
 *   class the way the accuracy ramp identifies a band. They are deliberately the
 *   same in both themes — a car must look like the same car in daylight mode —
 *   which is why they live beside the theme rather than inside it.
 *
 * ★ THE BACKEND MIRRORS TWO OF THESE. `detection_service.py` burns the box
 *   colours into the MJPEG preview as BGR constants (yellow sighting, orange
 *   tracker estimate). Change them here and the burned-in boxes will disagree
 *   with the SVG overlay on the live page — change both, or neither.
 */

/** Detection classes — the pipeline's fixed subjects, one hue each. */
export const DETECTION_CLASS_COLOURS: Record<string, string> = {
  person: '#F43F5E',
  car: '#3B82F6',
  motorcycle: '#A855F7',
  bus: '#F59E0B',
  truck: '#10B981',
};

/** A class the map has no hue for — neutral, never mistaken for a known class. */
export const DETECTION_CLASS_FALLBACK = '#E2E8F0';

/**
 * Track identities on the live map — one hue per TRACKED OBJECT, cycling.
 *
 * ★ WHY (2026-09-01, owner ask): two tracked cars are the same class, so
 *   class-colouring painted both trails identically and the map could not say
 *   which route belonged to which car. A track is an identity; identities get
 *   their own hue. Eight distinct hues, varied in lightness so neighbours in
 *   the cycle stay tellable apart on green fields and brown earth alike; nine
 *   simultaneous tracks reuse the first hue, which is honest — ninety would too.
 */
export const DETECTION_TRACK_COLOURS = [
  '#38BDF8', // sky
  '#FB7185', // rose
  '#4ADE80', // green
  '#FBBF24', // amber
  '#A78BFA', // violet
  '#2DD4BF', // teal
  '#F472B6', // pink
  '#E879F9', // fuchsia
] as const;

/** A stable hue for one track id — the same track is the same colour all run. */
export function detectionTrackColour(trackId: number): string {
  return DETECTION_TRACK_COLOURS[Math.abs(Math.trunc(trackId)) % DETECTION_TRACK_COLOURS.length];
}

/**
 * The colour one detection mark draws with: its TRACK's hue when it has an
 * identity, its class's hue when it is an untracked sighting.
 */
export function detectionMarkColour(clsName: string, trackId: number | null): string {
  if (trackId !== null) return detectionTrackColour(trackId);
  return DETECTION_CLASS_COLOURS[clsName] ?? DETECTION_CLASS_FALLBACK;
}

/** YOLO's own sighting — yellow. Mirrored in the backend's burned-in preview. */
export const DETECTION_BOX = '#FACC15';

/** The tracker's estimate — orange. Mirrored in the backend's burned-in preview. */
export const DETECTION_BOX_PREDICTED = '#FB923C';

/** A TRACKED object — cyan. Mirrored in the backend's burned-in preview (2026-09-03). */
export const DETECTION_TRACKED = '#35C8D8';

/** The LOCKED primary — green, distinct from tracked cyan. Mirrored in the burn-in. */
export const DETECTION_LOCKED = '#22C55E';

/**
 * The suggestion boxes' factory default — magenta, deliberately unlike any
 * accuracy colour or correspondence marker. The surveyor can override it
 * per-workspace; this is only where the default is DEFINED.
 */
export const SUGGESTION_DEFAULT = '#d946ef';

/**
 * The error-heat ramp — THE SERVER'S OWN. `accuracy_service._HEAT_STOPS` renders
 * the PNG overlay with exactly these stops, and the offline report embeds them.
 * A legend drawn from any other ramp is a lie told in good faith.
 */
export const HEAT_STOPS = ['#fff7ec', '#fdbb84', '#e34a33', '#7f0000'] as const;

/**
 * The nine range zones on the photograph.
 *
 * ★ THE FILLS USE `HEAT_STOPS` ABOVE — the same ramp as the satellite pane's heat
 *   map, so a zone reading 8 m on the photo is the same colour as 8 m on the map.
 *   Upstream's kit shipped its own six-stop ramp; one product, one ramp.
 * ★ A zone under the tile floor is a WASH, never a colour: a colour reads as a
 *   number, and there is no number.
 */
export const ZONE_NO_DATA = '#787878';
export const ZONE_EDGE = '#ffffff';
export const ZONE_LABEL_BG = '#0f141c';

/** Each correction stage's pin and chip — the vendored core's own `solutions.COLOUR`. */
export const STAGE_COLOUR: Record<string, string> = {
  raw: '#ec4899',
  pose: '#f59e0b',
  field: '#2563eb',
  stagef: '#15803d',
};
