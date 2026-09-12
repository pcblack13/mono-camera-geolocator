# Navigation — the two workspaces and the workchain

How the eight work pages are reached and held open, and where to add a ninth.

## What the user sees

**Two workspace tabs in the navbar — and nothing else on the sides.** Pressing a tab drops a
panel down from it with that workspace's pages, each a card with an icon, its name, one line on
what it is for, and whether it is already open. Pressing a card opens the page and closes the
panel (so does Esc or a press outside). The panel is a `menu`: `↑ ↓ ← →` walk the cards,
`Home`/`End` jump, Enter opens; opening from the keyboard focuses the first card.

| Workspace | Pages | What the surveyor is doing |
| --- | --- | --- |
| **Locator Workspace** | Projects · DEM processing · LUT generator · GCP tables | *Building* the geolocation |
| **Monitoring Workspace** | Video editor · Live stream · Video detection · Drift monitor | *Watching* cameras and clips |

**The workchain.** Every page under `/projects` — the eight above and a project's own pages
(project, editor, image setup, settings, video) — opens as a **tab** the moment it is visited,
like a file in an editor, in the strip under the navbar. Tabs stay open until closed with `×`;
closing the active one lands on its neighbour (right, else left; Home when none remain). The
strip is a WAI-ARIA `tablist`: `← →` move, `Enter` opens, `Delete` closes; middle-click closes;
right-click offers *Close · Close others · Close to the right · Close all*. It is persisted, so a
relaunch finds the same pages open. Home, the dashboard and the workflow guide are *shell*
pages: they never become tabs, and while you are on one the strip shows no active tab.

Beside the two tabs sit the shell's own links — Dashboard and the Workflow guide — as icon
buttons; the wordmark is Home. There is no side rail. Below `md` the drawer lists the same two
groups plus the shell links.

## Where it lives

| Concern | File |
| --- | --- |
| The registry — both workspaces, all eight pages, their `?tab=` and descriptions | `frontend/src/components/shell/workspaces.tsx` |
| Navbar tabs + their dropdown panels + the shell links | `frontend/src/components/shell/WorkspaceNav.tsx` (`WorkspaceTabsBar`, `ShellLinks`) |
| Open tabs — pure core (`openTab`, `closeTab`, …) + persisted store | `frontend/src/store/workchainStore.ts` |
| Which locations become tabs, and their titles/icons | `frontend/src/components/shell/workchain.ts` |
| The strip (tabs, `×`, keyboard, context menu) | `frontend/src/components/shell/WorkchainTabs.tsx` |
| The bar that holds the strip + "← Back to …" + the editor's Save; feeds the workchain from the router | `frontend/src/components/shell/PageNavBar.tsx` |
| A page naming its own tab (project name, clip filename) | `frontend/src/components/shell/useWorkchainTitle.ts` |
| Page titles by route **and query** | `frontend/src/components/shell/pageNav.ts` |
| Shell-only destinations (Home, Dashboard, Guide) | `frontend/src/components/shell/navItems.tsx` |

**The URLs did not change.** Every work page keeps its `/projects?tab=…` address (`/projects`
for the list, `?tab=drift` for the new Drift monitor). Bookmarks, the README, the workflow
guide's doors and the visit stack (`navHistoryStore`) all pin them.

## Adding a page to a workspace

1. Add one `page(...)` entry to the right workspace in `workspaces.tsx` (key, `?tab=` value,
   label, one-line description, icon). Add the `?tab=` value to `WorkspacePageTab`.
2. Render it in `ProjectsPage.tsx`'s `tab ===` chain.
3. Add its Arabic label and description to `i18n/ar.ts`.

That is all: the navbar dropdown, the drawer, the command palette, the workchain's tab title
and icon, and `resolvePageNav`'s page name all read the registry.

## Tests

`workchain.test.tsx` (core rules, which locations become tabs, the strip's gestures),
`workspace-nav.test.tsx` (registry, dropdown, shell links, palette), `page-nav.test.tsx`,
`drift-monitor-page.test.tsx` (the Drift monitor page).
