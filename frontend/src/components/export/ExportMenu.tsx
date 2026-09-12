/**
 * `export/ExportMenu.tsx` — the export split button (50-frontend §2.23, SCOPE.md §3).
 *
 * ★ CSV · GeoJSON · Shapefile · KML · PDF, all fully built (SCOPE.md §3).
 *
 * ★ DISABLE, DON'T FAIL: a format the server reports unavailable
 *   (`CapabilitiesResponse.exports[].available === false` — e.g. "geopandas is not
 *   installed" for Shapefile) is listed but DISABLED with the reason as its tooltip,
 *   rather than failing after the click. This is the unit brief's explicit
 *   requirement, and it reads the server's capability report — never a hard-coded list.
 *
 * ★ The whole menu is disabled with an honest reason when there are no GCPs to export.
 */

import { useMemo, useState, type JSX } from 'react';
import Button from '@mui/material/Button';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Tooltip from '@mui/material/Tooltip';
import FileUploadOutlinedIcon from '@mui/icons-material/FileUploadOutlined';

import { useCapabilities } from '../../api/hooks/useCapabilities';
import type { Uuid } from '../../types/common';
import type { ExportFormat } from '../../types/export';
import { ExportDialog } from './ExportDialog';
import { t } from '../../i18n';

export interface ExportMenuProps {
  imageId: Uuid;
  gcpCount: number;
  disabled?: boolean;
}

/** The five mandated formats, in the order the wireframe shows them. */
const MENU_FORMATS: { format: ExportFormat; label: string }[] = [
  { format: 'csv', label: 'CSV' },
  { format: 'geojson', label: 'GeoJSON' },
  { format: 'shapefile', label: 'Shapefile' },
  { format: 'kml', label: 'KML' },
  { format: 'pdf', label: 'PDF report' },
];

export function ExportMenu({ imageId, gcpCount, disabled = false }: ExportMenuProps): JSX.Element {
  const { data: capabilities } = useCapabilities();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const [activeFormat, setActiveFormat] = useState<ExportFormat | null>(null);

  // ★ Availability + reason, keyed by format, from the server's report.
  const availability = useMemo(() => {
    const map = new Map<ExportFormat, { available: boolean; reason: string | null }>();
    for (const cap of capabilities?.exports ?? []) {
      map.set(cap.format, { available: cap.available, reason: cap.reason });
    }
    return map;
  }, [capabilities]);

  const noGcps = gcpCount === 0;
  const menuDisabled = disabled || noGcps;

  return (
    <>
      <Tooltip title={noGcps ? 'Place at least one GCP to export' : ''}>
        <span>
          <Button
            variant="outlined"
            size="small"
            startIcon={<FileUploadOutlinedIcon />}
            onClick={(e) => setAnchorEl(e.currentTarget)}
            disabled={menuDisabled}
            aria-haspopup="menu"
          >
            {t('Export')}
          </Button>
        </span>
      </Tooltip>

      <Menu anchorEl={anchorEl} open={anchorEl !== null} onClose={() => setAnchorEl(null)}>
        {MENU_FORMATS.map(({ format, label }) => {
          // ★ Absent from the report ⇒ assume available (the built default); present
          //   with available:false ⇒ disabled with its reason.
          const cap = availability.get(format);
          const available = cap?.available ?? true;
          const reason = cap?.reason ?? 'This format is not available in this build.';
          return (
            <Tooltip key={format} title={available ? '' : reason} placement="left">
              <span>
                <MenuItem
                  disabled={!available}
                  onClick={() => {
                    setActiveFormat(format);
                    setAnchorEl(null);
                  }}
                >
                  <ListItemText primary={label} secondary={available ? undefined : reason} />
                </MenuItem>
              </span>
            </Tooltip>
          );
        })}
      </Menu>

      {activeFormat !== null && (
        <ExportDialog
          open
          imageId={imageId}
          format={activeFormat}
          gcpCount={gcpCount}
          onClose={() => setActiveFormat(null)}
        />
      )}
    </>
  );
}

export default ExportMenu;
