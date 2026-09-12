/**
 * The detector's lock explains itself.
 *
 * ★ The server's probe names the exact fix; the bar must show it where the surveyor
 *   is looking, not only in a tooltip on a button that cannot be pressed.
 */

import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

const probe = vi.hoisted(() => ({
  data: undefined as unknown,
  isError: false,
}));
vi.mock('../api/hooks/useDetection', () => ({
  useDetectionAvailability: () => probe,
}));
vi.mock('../api/lut', () => ({ lutApi: { library: vi.fn().mockResolvedValue([]) } }));

import { DetectionSettingsBar } from '../components/detection/DetectionSettingsBar';
import { setLanguage } from '../i18n';

function mount(): void {
  setLanguage('en');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <DetectionSettingsBar
        value={{
          model: '',
          lutSite: '',
          classes: [],
          conf: 0.25,
          imgsz: 640,
          trackerStart: 0,
          trackerType: 'csrt',
        }}
        onChange={() => undefined}
        running={false}
        starting={false}
        disabledReason="the detection runtime is not installed."
        startError={null}
        onStart={() => undefined}
        onStop={() => undefined}
        onRestart={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe('the detector lock', () => {
  it('★ shows the server’s reason and fix in the open when the detector is unavailable', () => {
    probe.data = {
      detector: {
        available: false,
        reason: 'the detection runtime is not installed. Install it: pip install ultralytics',
      },
      tracker: { available: true, reason: null },
      models: [],
      device: null,
      classes: [],
    };
    probe.isError = false;
    mount();
    expect(screen.getByText('The detector is locked on this machine')).toBeInTheDocument();
    expect(screen.getByText(/pip install ultralytics/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Start detection/ })).toBeDisabled();
  });

  it('says nothing extra when the detector is available', () => {
    probe.data = {
      detector: { available: true, reason: null },
      tracker: { available: true, reason: null },
      models: ['yolo26s.pt'],
      device: 'cpu',
      classes: [],
    };
    mount();
    expect(screen.queryByText('The detector is locked on this machine')).toBeNull();
  });

  it('names a failed probe as the API being unreachable, not as a missing detector', () => {
    probe.data = undefined;
    probe.isError = true;
    mount();
    expect(
      screen.getByText('Could not ask the server what this machine can run.'),
    ).toBeInTheDocument();
  });
});
