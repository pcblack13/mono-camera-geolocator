/**
 * `map/BasemapSwitcher.tsx` (pure) — 50-frontend §2.16.
 *
 * The mandated **satellite / hybrid / terrain** switch, plus the provider selector.
 *
 * ★ L2 / ToS: the switcher offers only the `kinds` the ACTIVE provider can serve
 *   (`ProviderCapabilities.kinds`), and lists providers with `configured: false` as
 *   disabled with the reason — an explicitly requested unconfigured provider is a
 *   `503` (`useProviders` header), so offering it enabled would be a lie.
 *
 * ★ Swapping a provider changes tiles + attribution and **nothing else** — no GCP, no
 *   query key. That is the frontend's half of "swapping providers must not change the
 *   result" (§2.16). This component only reports the choice; `mapStore` holds it.
 *
 * **Pure.** All state in, callbacks out.
 */

import { useState, type MouseEvent } from 'react';
import LayersIcon from '@mui/icons-material/Layers';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import type { SelectChangeEvent } from '@mui/material/Select';
import Tooltip from '@mui/material/Tooltip';

import type { BasemapKind, ProviderId, ProviderInfo } from '../../types/geo';
import { t } from '../../i18n';

const KIND_LABEL: Record<BasemapKind, string> = {
  satellite: 'Satellite',
  hybrid: 'Hybrid',
  terrain: 'Terrain',
};

const ALL_KINDS: readonly BasemapKind[] = ['satellite', 'hybrid', 'terrain'];

export interface BasemapSwitcherProps {
  basemap: BasemapKind;
  /** The kinds the active provider can serve. Others are hidden, not disabled. */
  availableKinds: readonly BasemapKind[];
  onBasemapChange: (kind: BasemapKind) => void;

  providers: ProviderInfo[];
  /** The effective provider id (never null here — resolved to the default upstream). */
  activeProviderId: ProviderId;
  /** `null` selects "server default" (keyless Esri, L2). */
  onProviderChange: (id: ProviderId | null) => void;
}

/**
 * ★ NEVER OFFERED, whatever the server reports:
 *   - `fixture` — synthetic test tiles. Real imagery is the product; a menu entry
 *     that draws checkerboards is a support call waiting to happen.
 *   - `google_maps_static` — superseded by `google_map_tiles`, which serves the same
 *     imagery WITHOUT burning a credit strip into every tile. Both ride one key, so
 *     offering the worse one is only a way to pick it by mistake.
 *
 * ★★ `esri_world_imagery` WAS ON THIS LIST AND IS NOT ANY MORE (1.2.6). It was added
 *    when Esri was retired in favour of Mapbox, as a belt-and-braces UI ban on top of
 *    the server's `LE_ALLOWED_PROVIDERS`. When Esri was RESTORED as a first-class
 *    option, the setup panel and the store were updated and this list was not — which
 *    broke the switcher in two visible ways: choosing Esri left the dropdown BLANK
 *    (the active value had no matching item to render), and Esri never appeared in
 *    the menu to switch back to.
 *
 *    The lesson is why the entry is gone rather than made conditional: an
 *    unconditional UI ban DUPLICATES the server's allow-list, and a duplicated rule
 *    is one that can disagree with its original. `LE_ALLOWED_PROVIDERS` is the single
 *    source of truth for who may be offered — the filter below already honours it.
 */
const NEVER_OFFERED: readonly string[] = ['fixture', 'google_maps_static'];

/**
 * The providers worth showing: the ones this server can actually serve, plus the
 * active choice (so the select always has a value to display).
 *
 * ★ UNCONFIGURED PROVIDERS ARE HIDDEN, NOT DISABLED — a change from the original
 *   "show everything, grey out what needs a key". Six greyed-out lines reading
 *   "needs a key" is a menu about deployment, not about imagery: it buries the two
 *   entries that work under five that never will on this machine. Configuring one
 *   in `backend/.env` makes it appear here by itself, which is the honest signal.
 *
 * ★ DISALLOWED PROVIDERS ARE HIDDEN TOO, and even more firmly: `allowed: false`
 *   is the operator's `LE_ALLOWED_PROVIDERS` ban, and the server answers 403 for
 *   it — offering it would be offering an error. (`!== false` because servers
 *   that predate the field omit it, meaning "allowed".) The active choice still
 *   shows so the select has a value if a stored selection was banned later.
 */
export function offerableProviders(
  providers: readonly ProviderInfo[],
  activeProviderId: ProviderId,
): ProviderInfo[] {
  return providers.filter(
    (p) =>
      !NEVER_OFFERED.includes(p.name) &&
      ((p.configured && p.allowed !== false) || p.name === activeProviderId),
  );
}

export function BasemapSwitcher({
  basemap,
  availableKinds,
  onBasemapChange,
  providers,
  activeProviderId,
  onProviderChange,
}: BasemapSwitcherProps): JSX.Element {
  const kinds = ALL_KINDS.filter((k) => availableKinds.includes(k));

  const [kindMenuAnchor, setKindMenuAnchor] = useState<HTMLElement | null>(null);

  const handleProvider = (e: SelectChangeEvent<string>): void => {
    const value = e.target.value;
    onProviderChange(value === '__default__' ? null : (value as ProviderId));
  };

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        p: 0.5,
        borderRadius: 1,
        bgcolor: 'background.paper',
        boxShadow: 2,
      }}
    >
      {/* ★ The kinds live BEHIND the layers button now — three standing text
          buttons earned their chrome cost only while the choice was being made.
          The icon shows the menu; the menu shows the tick. */}
      <Tooltip title={`Basemap: ${KIND_LABEL[basemap]}`}>
        <IconButton
          size="small"
          onClick={(e: MouseEvent<HTMLElement>) => setKindMenuAnchor(e.currentTarget)}
          aria-label={`Basemap kind — currently ${KIND_LABEL[basemap]}`}
          aria-haspopup="menu"
        >
          <LayersIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu
        anchorEl={kindMenuAnchor}
        open={kindMenuAnchor !== null}
        onClose={() => setKindMenuAnchor(null)}
        disablePortal
      >
        {kinds.map((k) => (
          <MenuItem
            key={k}
            selected={k === basemap}
            onClick={() => {
              setKindMenuAnchor(null);
              if (k !== basemap) onBasemapChange(k);
            }}
          >
            {KIND_LABEL[k]}
          </MenuItem>
        ))}
      </Menu>

      <Select
        size="small"
        value={activeProviderId}
        onChange={handleProvider}
        aria-label={t('Imagery provider')}
        sx={{ minWidth: 180 }}
        MenuProps={{ disablePortal: true }}
      >
        {offerableProviders(providers, activeProviderId).map((p) => {
          const disabled = !p.configured;
          const item = (
            <MenuItem key={p.name} value={p.name} disabled={disabled}>
              {p.title}
              {p.is_default ? ' (default)' : ''}
              {disabled ? ' — needs a key' : ''}
            </MenuItem>
          );
          // ★ Tooltip explains WHY a provider is unavailable — the reason is a config
          //   action the operator can take, not a dead end.
          return disabled ? (
            <Tooltip
              key={p.name}
              title={`${p.title} is not configured on this server.`}
              placement="right"
            >
              {/* span so the tooltip fires on a disabled item */}
              <span>{item}</span>
            </Tooltip>
          ) : (
            item
          );
        })}
      </Select>
    </Box>
  );
}
