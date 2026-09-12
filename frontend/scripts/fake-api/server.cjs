/**
 * `frontend/scripts/fake-api/server.cjs` — a stand-in for the API, for UI work with
 * NO backend at all. Answers just enough for the monitor pages: providers (tiles 204,
 * i.e. offline), detection availability, one LUT library entry with a pose, empty
 * drift lists, a 10 fps MJPEG re-stream of `frame.jpg`, and a 422 with a verbatim
 * message on session start (so the refused banner can be seen).
 *
 *     node frontend/scripts/fake-api/server.cjs          # port 8000
 *     cd frontend && npm run dev                           # proxies /api → 8000
 *
 * For an END-TO-END simulation against the real backend use
 * `scripts/simulate_camera.py` instead — this one fakes the server, that one fakes
 * the camera.
 */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const frame = fs.readFileSync(path.join(__dirname, 'frame.jpg'));
const json = (res, status, body) => {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
};
const envelope = (status, code, message) => ({
  error: {
    code,
    message,
    status,
    details: null,
    request_id: '01J6SCREENSHOT000000000000',
    timestamp: new Date().toISOString(),
    docs_url: null,
    feature: null,
  },
});

http
  .createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    const p = url.pathname.replace(/^\/api\/v1/, '');
    if (p === '/imagery/providers') {
      return json(res, 200, {
        items: [
          {
            name: 'esri_world_imagery',
            title: 'Esri World Imagery',
            configured: true,
            allowed: true,
            requires_key: false,
            is_default: true,
            capabilities: { kinds: ['satellite'], min_zoom: 0, max_zoom: 19, tile_size_px: 256, supports_offline: true },
            attribution: { text: 'Esri, Maxar, Earthstar Geographics', terms_url: 'https://www.esri.com' },
            coverage: { global: true },
            health: { status: 'ok', checked_at: new Date().toISOString(), latency_ms: 12 },
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
    }
    if (p.startsWith('/imagery/tiles/')) {
      res.writeHead(204, { 'x-imagery-attribution': 'Esri, Maxar, Earthstar Geographics' });
      return res.end();
    }
    if (p === '/detection/availability') {
      return json(res, 200, {
        detector: { available: true, reason: null },
        tracker: { available: true, reason: null },
        models: ['yolo26s.pt'],
        device: 'cpu',
        classes: [
          { id: 0, name: 'person' },
          { id: 2, name: 'car' },
          { id: 5, name: 'bus' },
          { id: 7, name: 'truck' },
        ],
      });
    }
    if (p === '/detection/sessions' && req.method === 'POST') {
      return json(
        res,
        422,
        envelope(
          422,
          'VALIDATION_ERROR',
          'could not open capture device /dev/video0 — it is held by another program (the live preview releases it only once the run is starting). Close the other program and try again.',
        ),
      );
    }
    if (p === '/lut/library') {
      return json(res, 200, [
        {
          site_name: 'yammone_124',
          built_utc: '2026-08-20T09:12:00Z',
          image: { width: 4032, height: 2268 },
          payload_mb: 146.3,
          validation_passed: true,
          max_error_m: 0.31,
          center: [33.833, 35.541],
          bundle_dir: '/data/lut/yammone_124_lut',
          archive_available: true,
          has_pose: true,
          imported: null,
        },
      ]);
    }
    if (p === '/drift/references') return json(res, 200, { items: [] });
    if (p === '/drift/monitors') return json(res, 200, { items: [] });
    if (p === '/capabilities') return json(res, 200, { defaults: { provider: 'esri_world_imagery' }, features: {} });
    if (p === '/health' || p === '/health/ready') return json(res, 200, { status: 'ok' });
    if (p === '/live/devices') return json(res, 200, { items: [{ id: '/dev/video0', label: 'USB Capture HDMI' }] });
    if (p === '/live/stream') {
      const boundary = 'frame';
      res.writeHead(200, {
        'content-type': `multipart/x-mixed-replace; boundary=${boundary}`,
        'cache-control': 'no-store',
        'x-live-source-codec': 'MJPEG',
      });
      const tick = setInterval(() => {
        res.write(`--${boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n`);
        res.write(frame);
        res.write('\r\n');
      }, 100);
      req.on('close', () => clearInterval(tick));
      return;
    }
    if (p === '/live/frame' && req.method === 'POST') {
      return json(res, 200, {
        filename: 'live_cam01_20260828_120000.jpg',
        width: 1280,
        height: 720,
        size_bytes: frame.length,
        file_url: '/api/v1/capture-library/live_cam01_20260828_120000.jpg',
        saved_to: null,
      });
    }
    json(res, 404, envelope(404, 'NOT_FOUND', `no fake for ${p}`));
  })
  .listen(8000, '127.0.0.1', () => console.log('fake api on 8000'));
