/**
 * "Has the camera moved?" (2026-09-09): the one question asked before a frame
 * with control points is replaced. Same aim carries the points; moved detaches
 * the table. Both are stated on the buttons themselves.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { FrameChangeDialog } from '../components/cameras/FrameChangeDialog';
import { setLanguage } from '../i18n';

describe('FrameChangeDialog', () => {
  beforeEach(() => setLanguage('en'));

  it('★ names the points at stake and what each answer does — with a table', () => {
    const onDecide = vi.fn();
    render(<FrameChangeDialog open pointCount={6} hasTable onDecide={onDecide} onCancel={() => undefined} />);
    expect(screen.getByText(/The current frame has 6 control points/)).toBeVisible();
    expect(screen.getByTestId('frame-change-same-aim')).toHaveTextContent('the lookup table stays');
    expect(screen.getByTestId('frame-change-moved')).toHaveTextContent('lookup table is detached');
    fireEvent.click(screen.getByTestId('frame-change-same-aim'));
    expect(onDecide).toHaveBeenCalledWith('same-aim');
    fireEvent.click(screen.getByTestId('frame-change-moved'));
    expect(onDecide).toHaveBeenCalledWith('moved');
  });

  it('without a table it only speaks of the points', () => {
    render(<FrameChangeDialog open pointCount={4} hasTable={false} onDecide={() => undefined} onCancel={() => undefined} />);
    expect(screen.getByTestId('frame-change-same-aim')).not.toHaveTextContent('lookup table');
    expect(screen.getByTestId('frame-change-moved')).not.toHaveTextContent('lookup table');
  });

  it('Cancel leaves everything as it was', () => {
    const onCancel = vi.fn();
    render(<FrameChangeDialog open pointCount={4} hasTable onDecide={() => undefined} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
