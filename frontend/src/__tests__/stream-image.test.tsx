/**
 * `StreamImage` — the MJPEG `<img>` that must survive a change of stream.
 *
 * ★ THE BUG THIS PINS (2026-08-28): Restart, or Stop then Start, gives the mounted
 *   element a NEW session URL. React wrote the new `src` during commit and only then
 *   ran the previous effect's cleanup — which blanked the src it had just been
 *   given. The picture went dark and stayed dark until a page reload.
 */

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import { StreamImage } from '../components/live/StreamImage';

const URL_A = 'http://api.test/detection/sessions/aaa/stream';
const URL_B = 'http://api.test/detection/sessions/bbb/stream';

describe('StreamImage', () => {
  it('opens the stream it was given', () => {
    const { container } = render(<StreamImage src={URL_A} alt="run" />);
    expect(container.querySelector('img')?.src).toBe(URL_A);
  });

  it('★ shows the NEW stream after a restart, not a blank', () => {
    const { container, rerender } = render(<StreamImage src={URL_A} alt="run" />);
    rerender(<StreamImage src={URL_B} alt="run" />);
    expect(container.querySelector('img')?.src).toBe(URL_B);
  });

  it('lets go of the stream on unmount', () => {
    const { container, unmount } = render(<StreamImage src={URL_A} alt="run" />);
    const img = container.querySelector('img')!;
    unmount();
    expect(img.getAttribute('src')).toBe('');
  });
});
