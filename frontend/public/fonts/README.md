# Self-hosted fonts

`50-frontend.md §9.4` specifies **Inter** (variable) for UI text and **JetBrains Mono** for all
numerics, **self-hosted — no CDN**, because the app must work with the NIC unplugged
(`SCOPE.md §3`, `docs/guides/offline-mode.md`). A surveyor is in a field, not on a backbone.

## Why this directory is empty

The build machine has **no network** (`CONTRACT.md §0.1`), so the `.woff2` files could not be
fetched and committed. Shipping `@font-face` rules pointing at files that do not exist would
produce a 404 per page load and a flash of invisible text — a silent failure, which `L11`
forbids. So `src/theme/typography.ts` currently declares the font **stacks** only, with Inter
and JetBrains Mono named first and a full system fallback behind them.

**The app is fully functional and correctly typeset today** — it renders in the system UI font
and the system monospace, and `font-variant-numeric: tabular-nums` (the load-bearing part of
§9.4, since it is what makes a column of latitudes scannable for anomalies) works in both.

## Activating the real fonts

1. Drop these files here:

   | File | Source | Licence |
   |---|---|---|
   | `inter-variable.woff2` | <https://github.com/rsms/inter> (`InterVariable.woff2`) | SIL OFL 1.1 |
   | `jetbrains-mono-variable.woff2` | <https://github.com/JetBrains/JetBrainsMono> | SIL OFL 1.1 |

2. Uncomment the `@font-face` block in `src/theme/typography.ts` (`FONT_FACE_CSS`). It is
   already written, already wired into `MuiCssBaseline`, and already uses `font-display: swap`
   plus the correct variable-font `font-weight` ranges.

3. Add the licence texts as `inter-OFL.txt` and `jetbrains-mono-OFL.txt` alongside the fonts.
   Both licences require the copyright notice to travel with the font files.

No other change is needed — the font stacks in `typography.ts` already name these families
first, so they take effect the moment the files resolve.
