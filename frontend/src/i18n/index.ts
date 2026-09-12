/**
 * `i18n/index.ts` — the app in English or Arabic, chosen from the top bar.
 *
 * ★ TRANSLATION IS KEYED BY THE ENGLISH SENTENCE, not by an invented id. This app
 *   is full of long, deliberate prose — "Without one the run still detects and
 *   counts — it just cannot say where." A key like `map.empty.noLut` would put that
 *   sentence somewhere else and leave the component saying nothing readable, and
 *   every future edit would have to keep two files in step. With the English as the
 *   key, a component reads exactly as it did, an untranslated string DEGRADES TO
 *   ENGLISH rather than to a raw id, and coverage can grow sentence by sentence.
 *
 * ★ THE LAYOUT MIRRORS — WITH GUARDED ISLANDS (2026-08-31, by owner decision).
 *   Arabic reads right-to-left and the document now says so: `dir="rtl"`, an RTL
 *   MUI theme, and an emotion cache running `stylis-plugin-rtl` flip the chrome.
 *   The first attempt (2026-08-21) flipped the document ALONE and broke page after
 *   page — the Konva photo stage, the Leaflet/MapLibre maps and the drag handles
 *   all compute left-to-right geometry. The fix is not to give up on RTL but to
 *   fence those components off: each geometry surface sits inside an `LtrIsland`
 *   (`components/common/LtrIsland.tsx`) that pins `dir`, theme direction and the
 *   style cache back to LTR, so the words and the chrome mirror while the
 *   coordinate maths stays under its own feet.
 *
 * ★ The choice PERSISTS. A surveyor who works in Arabic works in Arabic tomorrow.
 */

import { useSyncExternalStore } from 'react';

import { AR } from './ar';

export type Language = 'en' | 'ar';

const STORAGE_KEY = 'landexplorer.language';

function readStored(): Language {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'ar' ? 'ar' : 'en';
  } catch {
    // Private mode / storage disabled: the app still runs, in English.
    return 'en';
  }
}

let current: Language = readStored();
const listeners = new Set<() => void>();

/** The document direction a language implies. */
export function directionOf(lang: Language): 'ltr' | 'rtl' {
  return lang === 'ar' ? 'rtl' : 'ltr';
}

/**
 * Tell the document its language AND its direction.
 *
 * ★ Arabic mirrors the document (`dir="rtl"`); the geometry surfaces that this
 *   would break are individually fenced back to LTR — see the note at the top.
 */
function applyToDocument(lang: Language): void {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = lang;
  document.documentElement.dir = directionOf(lang);
}

applyToDocument(current);

export function getLanguage(): Language {
  return current;
}

export function setLanguage(lang: Language): void {
  if (lang === current) return;
  current = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Not persisting is survivable; refusing to switch is not.
  }
  applyToDocument(lang);
  for (const l of listeners) l();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The current language, re-rendering every component that asks when it changes. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, getLanguage, () => 'en' as Language);
}

/**
 * Translate one English string.
 *
 * Called outside React (rare) — components should use `useT()` so they re-render
 * when the language changes.
 */
export function translate(text: string, lang: Language = current): string {
  if (lang === 'en') return text;
  return AR[text] ?? text;
}

/**
 * Translate — the plain function, usable anywhere.
 *
 * ★ NOT A HOOK, deliberately. Wrapping every English string in this app means
 *   touching hundreds of components, many with several inner components apiece, and
 *   a hook has to be placed inside the right function body — a mechanical edit that
 *   goes wrong silently and often. A plain call can be applied anywhere a string
 *   is written, including inside helpers and constant tables.
 *
 *   What makes it correct is that the ROOT re-mounts on a language change
 *   (`main.tsx` keys the tree by language), so every component re-renders and
 *   re-reads. Switching language is a deliberate, rare act; a remount is a fair
 *   price for making the translation impossible to get wrong.
 */
export function t(text: string): string {
  return translate(text, current);
}

/**
 * The translator, bound to the live language.
 *
 * ```tsx
 * const t = useT();
 * <Button>{t('Start detection')}</Button>
 * ```
 */
export function useT(): (text: string) => string {
  const lang = useLanguage();
  return (text: string) => translate(text, lang);
}

/**
 * The live document direction: `'rtl'` in Arabic, `'ltr'` otherwise.
 *
 * Components whose pointer maths depends on which way the page runs (the
 * splitter's drag deltas, for one) read this instead of touching the DOM.
 */
export function useDirection(): 'ltr' | 'rtl' {
  return directionOf(useLanguage());
}
