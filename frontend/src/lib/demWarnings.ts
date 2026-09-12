/**
 * `demWarnings` — split a DEM run's notes into what needs the surveyor's attention
 * and what is just narration.
 *
 * ★ WHY: every DEM run returns a `warnings` list, and the setup card used to fire
 *   EACH one as its own yellow toast. Two of them fire on almost every normal run —
 *   "No AOI given" and "reprojection was skipped, already metric" — so a routine
 *   upload produced a 15-second stream of yellow toasts that kept draining while the
 *   surveyor moved on to pick GCPs (field report). None of those two is a problem;
 *   they describe expected, correct behaviour. Classifying lets the UI toast only
 *   the ACTIONABLE ones and keep the rest quietly in the result panel.
 *
 * ★ Default is ACTIONABLE: an unrecognised warning is surfaced, never hidden. Only
 *   the explicitly-known-benign phrases are demoted to informational.
 */

export interface ClassifiedDemWarnings {
  /** Needs the surveyor to look — toast these. */
  actionable: string[];
  /** Expected narration — show in the panel, don't toast. */
  informational: string[];
}

/** Substrings that mark a warning as expected narration, not a problem. */
const INFORMATIONAL_MARKERS: readonly string[] = [
  'No AOI given', // whole-DEM processing — a deliberate choice, not a fault
  'reprojection was skipped to avoid a needless resample', // already in metres — ideal
  // ★ "Reprojection was skipped. The DEM remains in its source CRS…" — this can only
  //   fire on the "Upload DEM (preprocessed)" path, which deliberately skips reproject
  //   because the file is already projected; the "Process new DEM" page always
  //   reprojects, and a geographic DEM is auto-reprojected. So it is never a problem.
  'Reprojection was skipped. The DEM remains in its source CRS',
  'was reprojected to a metric UTM zone automatically', // the app fixed a geographic DEM for you
  'Recorded as the server-wide active DEM for reference', // adoption note, no project impact
];

function isInformational(warning: string): boolean {
  return INFORMATIONAL_MARKERS.some((marker) => warning.includes(marker));
}

export function classifyDemWarnings(warnings: readonly string[]): ClassifiedDemWarnings {
  const actionable: string[] = [];
  const informational: string[] = [];
  for (const w of warnings) {
    (isInformational(w) ? informational : actionable).push(w);
  }
  return { actionable, informational };
}
