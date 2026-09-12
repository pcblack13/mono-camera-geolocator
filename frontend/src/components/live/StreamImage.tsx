/**
 * `live/StreamImage.tsx` — an `<img>` for an MJPEG stream that lets go on unmount.
 *
 * ★ Browsers do NOT abort an in-progress `multipart/x-mixed-replace` load when the
 *   element leaves the DOM — the connection lives until garbage collection, the
 *   server keeps encoding frames, and on the live page the capture device stays
 *   busy for the next run. Clearing `src` before unmount is the one reliable
 *   release.
 *
 * ★ THE SRC IS OWNED BY THE EFFECT, NOT BY JSX. When the stream URL CHANGES on a
 *   mounted element (Restart, or Stop then Start — a new session id), React writes
 *   the new `src` attribute during commit and only THEN runs the previous effect's
 *   cleanup — which blanked the src it had just been given. The picture went dark
 *   and the alt text showed until the page was reloaded (seen 2026-08-28). With the
 *   attribute set inside the effect, the order is the right one: old cleanup
 *   releases the old stream, new effect opens the new one.
 */

import { useEffect, useRef, type CSSProperties, type JSX } from 'react';

export interface StreamImageProps {
  src: string;
  alt: string;
  style?: CSSProperties;
  onError?: () => void;
  /** Marks the element as THE picture (`img[data-picture]`) for consumers that
   *  measure it — VideoHero's freeze-frame reads natural size through it. */
  dataPicture?: boolean;
}

export function StreamImage({ src, alt, style, onError, dataPicture }: StreamImageProps): JSX.Element {
  const ref = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const img = ref.current;
    if (!img) return undefined;
    img.src = src;
    return () => {
      img.src = '';
    };
  }, [src]);
  return (
    <img
      ref={ref}
      alt={alt}
      style={style}
      onError={onError}
      {...(dataPicture ? { 'data-picture': '' } : {})}
    />
  );
}
