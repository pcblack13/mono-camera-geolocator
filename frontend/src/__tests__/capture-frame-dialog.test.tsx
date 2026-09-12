/**
 * The live capture dialog (2026-09-09, owner ask): look at the live picture, press
 * "Capture this frame" at the chosen moment, see the frozen result, then use it or
 * try again. Nothing is adopted until "Use this frame".
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/live', () => ({
  liveApi: {
    captureFrame: vi.fn(),
    captureDeviceFrame: vi.fn(),
    proxyStreamUrl: (src: string) => `/api/v1/live/stream?src=${encodeURIComponent(src)}`,
  },
}));

import { liveApi } from '../api/live';
import { CaptureFrameDialog } from '../components/cameras/CaptureFrameDialog';
import { setLanguage } from '../i18n';

const SHOT = { filename: 'gate.jpg', width: 1920, height: 1080, size_bytes: 1, file_url: '/capture-library/gate.jpg' };

describe('CaptureFrameDialog', () => {
  beforeEach(() => {
    setLanguage('en');
    vi.mocked(liveApi.captureFrame).mockReset();
    vi.mocked(liveApi.captureDeviceFrame).mockReset();
  });

  it('★ opens on the LIVE picture; the frame is captured on demand, shown frozen, then used', async () => {
    vi.mocked(liveApi.captureFrame).mockResolvedValue(SHOT as never);
    const onUse = vi.fn(async () => undefined);
    const onClose = vi.fn();
    render(
      <CaptureFrameDialog open source="http://cam/stream" device={false} name="Gate" onClose={onClose} onUse={onUse} />,
    );
    // live: the stream is shown, the capture is offered, nothing is adopted
    expect(screen.getByAltText('Live picture')).toHaveAttribute('src', 'http://cam/stream');
    expect(screen.getByTestId('capture-frame-picture')).toHaveAttribute('data-phase', 'live');
    expect(screen.queryByRole('button', { name: 'Use this frame' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Capture this frame' }));
    expect(liveApi.captureFrame).toHaveBeenCalledWith('http://cam/stream', { name: 'Gate' });
    // frozen: the captured file is the picture now, and the choice is offered
    expect(await screen.findByAltText('The captured frame')).toHaveAttribute('src', expect.stringContaining('/capture-library/gate.jpg'));
    expect(screen.getByText(/gate\.jpg · 1920 × 1080/)).toBeVisible();
    expect(onUse).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Use this frame' }));
    await waitFor(() => expect(onUse).toHaveBeenCalledWith(SHOT));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('"Try again" goes back to the live picture without using anything', async () => {
    vi.mocked(liveApi.captureDeviceFrame).mockResolvedValue(SHOT as never);
    const onUse = vi.fn(async () => undefined);
    render(
      <CaptureFrameDialog open source="/dev/video0" device onClose={() => undefined} onUse={onUse} name="Cap" />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Capture this frame' }));
    expect(liveApi.captureDeviceFrame).toHaveBeenCalledWith('/dev/video0', { name: 'Cap' });
    fireEvent.click(await screen.findByRole('button', { name: 'Try again' }));
    expect(screen.getByAltText('Live picture')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Capture this frame' })).toBeEnabled();
    expect(onUse).not.toHaveBeenCalled();
  });

  it('a refused capture is shown verbatim and the live picture stays', async () => {
    vi.mocked(liveApi.captureFrame).mockRejectedValue(new Error('the camera is busy with a detection run'));
    render(
      <CaptureFrameDialog open source="http://cam/stream" device={false} name="G" onClose={() => undefined} onUse={async () => undefined} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Capture this frame' }));
    expect(await screen.findByText('the camera is busy with a detection run')).toBeVisible();
    expect(screen.getByAltText('Live picture')).toBeInTheDocument();
  });

  it('a stream that cannot open offers Retry and disables the capture', () => {
    render(
      <CaptureFrameDialog open source="http://cam/stream" device={false} name="G" onClose={() => undefined} onUse={async () => undefined} />,
    );
    fireEvent.error(screen.getByAltText('Live picture'));
    expect(screen.getByText('The stream could not be opened.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Capture this frame' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(screen.getByAltText('Live picture')).toBeInTheDocument();
  });
});
