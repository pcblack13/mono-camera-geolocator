/**
 * The instrument primitives — each test pins the RULE the component exists for,
 * not its markup.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { EmptyState, ErrorState, ProgressStage, StatReadout, StatusPill } from '../components/ui';

describe('StatReadout', () => {
  it('shows an em-dash for nothing — never a zero, never a blank', () => {
    // ★ Zero is a measurement; nothing is not. The whole product turns on that.
    render(<StatReadout label="CE90" value={null} unit="m" />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('0')).toBeNull();
    // and the unit does not dangle after an em-dash
    expect(screen.queryByText('m')).toBeNull();
  });

  it('renders a real value with its unit', () => {
    render(<StatReadout label="CE90" value="1.9" unit="m" />);
    expect(screen.getByText('1.9')).toBeInTheDocument();
    expect(screen.getByText('m')).toBeInTheDocument();
  });
});

describe('StatusPill', () => {
  it('carries lifecycle in border STYLE, not in colour', () => {
    // ★ Colour belongs to accuracy. A colour-blind surveyor reads these too.
    const { rerender, container } = render(<StatusPill lifecycle="draft">DRAFT</StatusPill>);
    const style = (): string => getComputedStyle(container.firstChild as Element).borderStyle;
    expect(style()).toContain('dashed');
    rerender(<StatusPill lifecycle="stale">STALE</StatusPill>);
    expect(style()).toContain('double');
    rerender(<StatusPill lifecycle="committed">COMMITTED</StatusPill>);
    expect(style()).toContain('solid');
  });
});

describe('ErrorState', () => {
  it('shows the verbatim message and its code', () => {
    render(
      <ErrorState
        message="could not open capture device '/dev/video0' — check that it is connected."
        code="LiveCaptureError · 422"
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(
      "could not open capture device '/dev/video0'",
    );
    expect(screen.getByText('LiveCaptureError · 422')).toBeInTheDocument();
  });

  it('copies message and code together', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<ErrorState message="boom" code="X · 500" />);
    fireEvent.click(screen.getByRole('button', { name: /copy/i }));
    expect(writeText).toHaveBeenCalledWith('boom\n[X · 500]');
  });
});

describe('EmptyState', () => {
  it('names what belongs here and the action that puts it there', () => {
    // ★ The established common/EmptyState — the ui barrel re-exports it so the
    //   primitive inventory and the seven pages already using it stay ONE component.
    const onClick = vi.fn();
    render(
      <EmptyState
        title="No ground control points yet"
        description="Mark a landmark in the photo, then click the matching spot on the map."
        primaryAction={{ label: 'Place first point', onClick }}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Place first point' }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe('ProgressStage', () => {
  it('keeps a failed stage’s message and leaves later stages as never-started', () => {
    // ★ A percentage bar lies on multi-stage work; stages cannot.
    render(
      <ProgressStage
        stages={[
          { label: 'Fetch tiles', state: 'done' },
          { label: 'Match', state: 'failed', message: 'provider refused: rate-limited' },
          { label: 'Score', state: 'waiting' },
        ]}
      />,
    );
    expect(screen.getByText('provider refused: rate-limited')).toBeInTheDocument();
    expect(screen.getByText('Score')).toBeInTheDocument();
  });
});
