/**
 * `lib/cameras/connection.ts` — the connection vocabulary, in words.
 *
 * ★ ONE LIST FOR THE SERVER PAGE AND THE SETTINGS PIPELINE (2026-09-04), NARROWED
 *   TO THREE (2026-09-11, owner decision). The eight kinds before it asked for
 *   exactly three things — an address, a capture device on this machine, or a
 *   serial port — so that is what they became. A Pi and an IP camera are both an
 *   address; HDMI, BNC and USB are all a capture card; serial and UART are one
 *   line. Each kind says what it needs, so the settings page asks exactly that
 *   and nothing else. The monitor's wall keeps its own short labels.
 */

import type { CameraConnection } from '../../store/cameraRegistryStore';

export type ConnectionNeeds = 'address' | 'device' | 'serial' | 'either';

export interface ConnectionKind {
  key: CameraConnection;
  /** English — translated at render with `t()`. */
  label: string;
  /** One line, for the picker. */
  hint: string;
  needs: ConnectionNeeds;
}

export const CONNECTION_KINDS: readonly ConnectionKind[] = [
  {
    key: 'lan',
    // ★ `either`, not `address`: a board on the network may send only detections
    //   and no picture at all, which is exactly what the old `embedded` kind was
    //   for. One of the two addresses is required; the server says which.
    label: 'UTP / LAN',
    hint: 'An IP camera or a board (Pi) on the network — video at an address, detection data, or both.',
    needs: 'either',
  },
  {
    key: 'usb',
    label: 'USB / capture card',
    hint: 'A camera or capture card plugged into this machine — USB, HDMI or BNC.',
    needs: 'device',
  },
  {
    key: 'serial',
    label: 'Serial / UART',
    hint: 'A serial or UART line sending detection data — no picture.',
    needs: 'serial',
  },
];

export function connectionKind(key: CameraConnection | undefined): ConnectionKind {
  return CONNECTION_KINDS.find((k) => k.key === (key ?? 'lan')) ?? CONNECTION_KINDS[0];
}

export function connectionLabel(key: CameraConnection | undefined): string {
  return connectionKind(key).label;
}
