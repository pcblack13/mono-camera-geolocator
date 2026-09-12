/** The rail column between the photo and the map exists only while there is a rail (2026-09-10). */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { WorkspaceGrid } from '../components/workspace/WorkspaceGrid';

const sizes = { imageFr: 1, mapFr: 1, inspectorPx: 320, dockPx: 200 };

describe('WorkspaceGrid', () => {
  it('★ no rail → a 0 px column; a rail → 56 px; one seam only', () => {
    const { rerender } = render(
      <WorkspaceGrid paneSizes={sizes} inspectorOpen={false} dockOpen={false} dockHeight={200}
        onResizeColumns={() => undefined} onResizeDock={() => undefined}
        imagePane={<div>photo</div>} toolRail={null} inspector={null} mapPane={<div>map</div>} dock={null} />,
    );
    expect(screen.getByTestId('workspace-columns').style.gridTemplateColumns).toBe('minmax(0, 1fr) 6px 0px 0px minmax(0, 1fr)');
    rerender(
      <WorkspaceGrid paneSizes={sizes} inspectorOpen={false} dockOpen={false} dockHeight={200}
        onResizeColumns={() => undefined} onResizeDock={() => undefined}
        imagePane={<div>photo</div>} toolRail={<div>rail</div>} inspector={null} mapPane={<div>map</div>} dock={null} />,
    );
    expect(screen.getByTestId('workspace-columns').style.gridTemplateColumns).toBe('minmax(0, 1fr) 6px 56px 0px minmax(0, 1fr)');
    expect(screen.getAllByRole('separator')).toHaveLength(1);
  });
});
