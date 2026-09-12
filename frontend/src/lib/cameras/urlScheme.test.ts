import { describe, expect, it } from 'vitest';

import {
  DATA_SCHEMES,
  STREAM_SCHEMES,
  joinScheme,
  schemeOptions,
  splitScheme,
} from './urlScheme';

describe('splitScheme', () => {
  it('splits a known scheme off the address', () => {
    expect(splitScheme('rtsp://cam.local:554/live', STREAM_SCHEMES, 'http://')).toEqual({
      scheme: 'rtsp://',
      rest: 'cam.local:554/live',
    });
    expect(splitScheme('ws://10.0.0.4:9000/feed', DATA_SCHEMES, 'http://')).toEqual({
      scheme: 'ws://',
      rest: '10.0.0.4:9000/feed',
    });
  });

  it('opens on the fallback for an empty address, with nothing typed', () => {
    expect(splitScheme('', STREAM_SCHEMES, 'rtsp://')).toEqual({ scheme: 'rtsp://', rest: '' });
    expect(splitScheme('   ', STREAM_SCHEMES, 'rtsp://')).toEqual({ scheme: 'rtsp://', rest: '' });
  });

  it('★ keeps a scheme it does not know rather than rewriting the address', () => {
    expect(splitScheme('rtmp://host/app', STREAM_SCHEMES, 'rtsp://')).toEqual({
      scheme: 'rtmp://',
      rest: 'host/app',
    });
    // ...and the picker offers it, so the operator sees what is stored.
    expect(schemeOptions(STREAM_SCHEMES, 'rtmp://')).toEqual([
      'rtsp://',
      'http://',
      'https://',
      'rtmp://',
    ]);
    expect(schemeOptions(STREAM_SCHEMES, 'rtsp://')).toEqual(['rtsp://', 'http://', 'https://']);
  });

  it('treats a schemeless address as the fallback plus what was typed', () => {
    expect(splitScheme('192.168.1.20:8080/stream', STREAM_SCHEMES, 'http://')).toEqual({
      scheme: 'http://',
      rest: '192.168.1.20:8080/stream',
    });
  });
});

describe('joinScheme', () => {
  it('puts the address back together', () => {
    expect(joinScheme('rtsp://', 'cam/live')).toBe('rtsp://cam/live');
  });

  it('★ an empty rest is an empty address, never a bare scheme', () => {
    expect(joinScheme('rtsp://', '')).toBe('');
    expect(joinScheme('tcp://', '   ')).toBe('');
  });

  it('round-trips every scheme it offers', () => {
    for (const scheme of [...STREAM_SCHEMES, ...DATA_SCHEMES]) {
      const url = `${scheme}host:1234/path`;
      const parts = splitScheme(url, [...STREAM_SCHEMES, ...DATA_SCHEMES], 'http://');
      expect(joinScheme(parts.scheme, parts.rest)).toBe(url);
    }
  });
});
