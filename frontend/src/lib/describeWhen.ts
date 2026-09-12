/**
 * `lib/describeWhen.ts` — "Today, 14:05" / "Yesterday, 09:12" / "29 Aug, 16:40".
 *
 * ★ Calendar days, not 24-hour windows: something done at 23:50 last night is
 *   "yesterday" at 00:10, which is what a person means by the word. Formatted in
 *   the app's language, so the Arabic UI reads Arabic digits and month names.
 */

import { getLanguage, t } from '../i18n';

export function describeWhen(at: number, now = Date.now()): string {
  const locale = getLanguage() === 'ar' ? 'ar' : 'en-GB';
  const time = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(at);
  const dayStart = (ms: number): number => new Date(ms).setHours(0, 0, 0, 0);
  const days = Math.round((dayStart(now) - dayStart(at)) / 86_400_000);
  if (days === 0) return `${t('Today')}, ${time}`;
  if (days === 1) return `${t('Yesterday')}, ${time}`;
  const day = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' }).format(at);
  return `${day}, ${time}`;
}
