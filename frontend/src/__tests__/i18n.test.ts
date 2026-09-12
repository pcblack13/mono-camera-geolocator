/**
 * English ⇄ العربية — the three behaviours that would break the app silently.
 *
 * ★ 1. AN UNTRANSLATED STRING MUST RENDER IN ENGLISH, never as a key or a blank.
 *      This app is full of long explanatory prose and coverage grows sentence by
 *      sentence; the day a missing entry shows `map.empty.noLut` — or nothing — on
 *      a surveyor's screen is the day the feature has made the app worse.
 * ★ 2. SWITCHING TO ARABIC MIRRORS THE DOCUMENT (2026-08-31, owner decision).
 *      `dir="rtl"` flips the chrome; the geometry surfaces that this would break —
 *      the photo stage, the maps, the drag handles — are individually fenced back
 *      to LTR by `LtrIsland`, which is what makes the mirroring safe this time.
 * ★ 3. THE CHOICE MUST PERSIST. Someone who works in Arabic works in Arabic
 *      tomorrow.
 */

import { describe, expect, it, beforeEach } from 'vitest';

import { AR } from '../i18n/ar';
import { directionOf, getLanguage, setLanguage, translate } from '../i18n';

describe('translation', () => {
  beforeEach(() => setLanguage('en'));

  it('falls back to the English it was given, never to a key', () => {
    const unknown = 'A sentence nobody has translated yet.';
    expect(translate(unknown, 'ar')).toBe(unknown);
    expect(translate(unknown, 'en')).toBe(unknown);
  });

  it('returns Arabic for what it knows', () => {
    expect(translate('Live stream', 'ar')).toBe('البث المباشر');
    expect(translate('Start detection', 'ar')).toBe('ابدأ الكشف');
    // English is the source of truth and is never rewritten.
    expect(translate('Live stream', 'en')).toBe('Live stream');
  });

  it('uses surveying terms, not literal ones', () => {
    // ★ The lookup table gives every pixel its latitude and longitude; «جدول البحث»
    //   is what a programmer hears, «جدول الإحداثيات» is what it does.
    expect(AR['Lookup table']).toBe('جدول الإحداثيات');
    expect(AR['GCP tables']).toBe('جداول نقاط الضبط');
  });

  it('leaves proper nouns and formats alone', () => {
    // Translating "CSV" or "YOLO" would help nobody and break recognition.
    expect(translate('CSV', 'ar')).toBe('CSV');
    expect(translate('GeoJSON', 'ar')).toBe('GeoJSON');
  });
});

describe('switching language', () => {
  beforeEach(() => setLanguage('en'));

  it('names the language AND mirrors the document for Arabic', () => {
    // ★ RE-REVERSED (2026-08-31, owner decision). The 2026-08-21 attempt flipped
    //   the document alone and broke the geometry surfaces; those are now fenced
    //   by LtrIsland, so the document is free to say what Arabic needs it to say.
    setLanguage('ar');
    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');

    setLanguage('en');
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('states the direction each language implies', () => {
    expect(directionOf('ar')).toBe('rtl');
    expect(directionOf('en')).toBe('ltr');
  });

  it('remembers the choice', () => {
    setLanguage('ar');
    expect(localStorage.getItem('landexplorer.language')).toBe('ar');
    expect(getLanguage()).toBe('ar');
  });
});
