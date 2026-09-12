/**
 * `monitor/DetectedSenders.tsx` — cameras found on the cable, and one click to use them.
 *
 * ★ PLUGGING IT IN IS THE INSTALLATION (2026-09-09, owner ask). A camera that
 *   detects on its own hardware already knows everything needed to talk to it and
 *   says so once a second. There is nothing for an operator to type, so this panel
 *   asks for nothing: it lists what is announcing itself and offers Connect.
 *
 * ★ CONNECT OPENS A REVIEW, IT DOES NOT ACT (2026-09-09, owner ask). Pressing it
 *   shows the packet the camera announced and the settings it would fill in; the
 *   operator corrects what they like and presses Save. Nothing touches the
 *   registry before that, and Cancel leaves no trace. See ConnectSenderDialog.
 *
 * ★ HEARD IS NOT REACHED. A sender broadcasts to the whole link as well as its own
 *   subnet, so a machine with no address on its network still hears it. That case
 *   gets its own row state and its own explanation, because "there is a camera on
 *   this cable and this machine is not on its network" is a fixable problem and an
 *   empty list is not.
 */

import { useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import { type SenderRead } from '../../api/live';
import { useSenders } from '../../hooks/useSenders';
import { t } from '../../i18n';
import { ConnectSenderDialog } from './ConnectSenderDialog';

export interface DetectedSendersProps {
  /** Called with the registered camera's id once a sender is connected. */
  onConnected?: (cameraId: string) => void;
  /** ★ Ids already registered are NOT LISTED (2026-09-09, owner ask). A camera
   *  that is in the registry has a card of its own below; offering it here again
   *  would only ever create a duplicate. It reappears in this list the moment its
   *  card is deleted, because it is still announcing itself. */
  knownSenderIds?: ReadonlySet<string>;
}

export function DetectedSenders({
  onConnected,
  knownSenderIds,
}: DetectedSendersProps): JSX.Element {
  const { items, loading, error, refresh } = useSenders(true);
  // The sender whose packet is open for review, or null. Registration happens
  // inside the dialog, on Save — this component only chooses which one to show.
  const [reviewing, setReviewing] = useState<SenderRead | null>(null);
  // What is on the wire, minus what is already registered.
  const fresh = items.filter((s) => !(knownSenderIds?.has(s.id) ?? false));
  const alreadyRegistered = items.length - fresh.length;

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="subtitle2">{t('Detected on the network')}</Typography>
        {loading && items.length === 0 && <CircularProgress size={14} />}
        <Box sx={{ flex: 1 }} />
        <Button size="small" onClick={refresh}>
          {t('Refresh')}
        </Button>
      </Stack>

      {error !== null && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {t('Could not ask the server what it can hear:')} {error}
        </Alert>
      )}

      {items.length === 0 && !loading && (
        // Not an error state: an unplugged cable is the normal reason for this.
        <Typography variant="body2" color="text.secondary">
          {t(
            'No cameras are announcing themselves. Connect one by ethernet and it ' +
              'should appear within a couple of seconds.',
          )}
        </Typography>
      )}

      {items.length > 0 && fresh.length === 0 && (
        // Everything on the wire already has a card below. Said in one quiet line
        // so the empty list is not mistaken for a cable that has gone dead.
        <Typography variant="body2" color="text.secondary">
          {alreadyRegistered === 1
            ? t('The camera on the network is already registered — see its card below.')
            : `${alreadyRegistered} ${t('cameras on the network are already registered — see their cards below.')}`}
        </Typography>
      )}

      <Stack spacing={1}>
        {fresh.map((sender) => {
          return (
            <Box
              key={sender.id}
              sx={{
                p: 1.5,
                border: '1px solid var(--hairline)',
                borderRadius: 1,
                opacity: sender.reachable ? 1 : 0.85,
              }}
            >
              <Stack direction="row" alignItems="center" spacing={1}>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography variant="body2" noWrap>
                    <strong>{sender.name}</strong>{' '}
                    <Typography component="span" variant="caption" color="text.secondary">
                      {sender.host}:{sender.port}
                    </Typography>
                  </Typography>
                  <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap' }}>
                    {sender.width !== null && sender.height !== null && (
                      <Chip size="small" label={`${sender.width}×${sender.height}`} />
                    )}
                    {sender.manual === true && (
                      <Tooltip
                        title={t(
                          'This camera detects on its own but follows nothing until ' +
                            'you click an object.',
                        )}
                      >
                        <Chip size="small" label={t('click to track')} />
                      </Tooltip>
                    )}
                    {sender.classes !== null && (
                      <Tooltip title={sender.classes.join(', ')}>
                        <Chip
                          size="small"
                          label={`${sender.classes.length} ${t('classes')}`}
                        />
                      </Tooltip>
                    )}
                    {sender.lut_placeholder && (
                      // Said on the card, not buried: this is the difference
                      // between coordinates that mean something and ones that
                      // merely look like they do.
                      <Tooltip
                        title={t(
                          'Its lookup table is a placeholder, so any coordinates it ' +
                            'sends are believable but wrong.',
                        )}
                      >
                        <Chip size="small" color="warning" label={t('placeholder table')} />
                      </Tooltip>
                    )}
                  </Stack>
                </Box>

                {sender.reachable ? (
                  <Button
                    variant="contained"
                    size="small"
                    onClick={() => setReviewing(sender)}
                  >
                    {t('Connect')}
                  </Button>
                ) : (
                  <Tooltip
                    title={t(
                      'Heard on the cable but not reachable: this machine has no ' +
                        'address on its network.',
                    )}
                  >
                    <Chip size="small" color="warning" label={t('not on its network')} />
                  </Tooltip>
                )}
              </Stack>

              {!sender.reachable && sender.needs_subnet !== null && (
                <Alert severity="info" sx={{ mt: 1 }}>
                  {t('This camera is on')} <strong>{sender.needs_subnet}</strong>{' '}
                  {t(
                    'and this machine has no address there, so it can be heard but not ' +
                      'reached. Give the wired adapter an address on that network.',
                  )}
                </Alert>
              )}

            </Box>
          );
        })}
      </Stack>

      <ConnectSenderDialog
        sender={reviewing}
        onClose={() => setReviewing(null)}
        onSaved={(cameraId) => {
          setReviewing(null);
          onConnected?.(cameraId);
        }}
      />
    </Box>
  );
}
