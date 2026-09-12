/**
 * `pages/NotFoundPage.tsx` — the 404 route (router.tsx).
 *
 * ★ "404 is a route, not a redirect. A surveyor who mistypes a project id must be
 *   told the project is not there, not silently shown a different one."
 */

import type { JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import SearchOffRoundedIcon from '@mui/icons-material/SearchOffRounded';

import { EmptyState } from '../components/common/EmptyState';
import { t } from '../i18n';

export function NotFoundPage(): JSX.Element {
  const navigate = useNavigate();
  return (
    <Box sx={{ flex: 1, display: 'flex' }}>
      <EmptyState
        icon={<SearchOffRoundedIcon />}
        title={t('Page not found')}
        description="This page does not exist, or the project or image it points to is no longer here."
        primaryAction={{
          label: 'Back to the camera workspace',
          onClick: () => navigate('/cameras'),
        }}
      />
    </Box>
  );
}

export default NotFoundPage;
