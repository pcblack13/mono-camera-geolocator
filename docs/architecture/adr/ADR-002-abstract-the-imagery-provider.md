# ADR-002 — Imagery is abstracted behind `ImageryProvider`; the default is keyless Esri; Google Earth is structurally excluded

**Status:** Accepted — **client legal constraint**
**Deciders:** Technical Lead
**Normative record:** `CONTRACT.md` §11.4, §11.5, §7.2 · [`docs/legal/imagery-terms.md`](../../legal/imagery-terms.md)
**Amends:** the `00-overview.md` §7 statement of ADR-002, where it differs. `CONTRACT.md` wins.

---

## Context

**The client states plainly that Google Earth imagery cannot legally or technically be searched or
processed via its app or API.** This is not a preference, a performance concern, or a matter of taste.
It is the constraint the imagery layer is designed around.

The UX must nonetheless be a familiar 2D satellite view — the thing every user means when they say
"Google Earth". The brief additionally requires that the system work **out of the box with no API
keys**, on a machine with **no network guarantee**.

Those three requirements pull in three directions:

- "Looks like Google Earth" pulls toward the one provider we may not use.
- "Zero config" pulls toward a keyless provider.
- "No network guarantee" pulls toward no web provider at all.

A design that hardcodes any single imagery source fails at least one of them, and — worse — makes
the legal constraint a matter of **developer discipline** rather than of **structure**. Someone would
eventually add a Google Earth call because it was the easy way to get the tile they wanted, and
nothing in the codebase would stop them.

## Decision

**1. Every imagery source sits behind one ABC: `gis.imagery.base.ImageryProvider`.** It is
synchronous by design (Celery calls it from a worker pool) and total: `name`, `is_configured()`,
`capabilities()`, `health()`, `get_tile()`, `get_static_bbox()`. **`__init__` never raises on a
missing credential** — construction always succeeds and `is_configured()` reports readiness. A
provider that throws in its constructor takes down the registry, the capabilities endpoint, and the
UI that would have told you the key was missing.

**2. Seven providers, registered explicitly** in `gis/imagery/providers/__init__.py`:

| Provider | Key | Note |
|---|---|---|
| `esri_world_imagery` | **none** | ★★ **DEFAULT — keyless (L2)** |
| `local_orthophoto` | none | ★★ **OFFLINE · highest accuracy · the only path where total error is knowable** |
| `fixture` | none | ★★ **TEST + OFFLINE DEMO** · deterministic · no network |
| `mapbox` | `LE_MAPBOX_ACCESS_TOKEN` | |
| `bing` | `LE_BING_MAPS_KEY` | metadata handshake |
| `sentinel` | OAuth2 client credentials | refuses `zoom > 15` |
| `google_static` | key **AND** `LE_GOOGLE_TOS_ACKNOWLEDGED=true` | **double opt-in** |

**3. Google Earth is not a provider, and is not representable.** Not a disabled flag. Not a
commented-out class. Not an enum member set to `false`. **An absence:**

- no provider module, no registry entry, no scaffolding;
- the `imagery_provider` PG enum has **no `google_earth` member** — it is unrepresentable in the type
  system, so the database itself cannot store a row claiming Google Earth as a source;
- CI greps for Earth endpoint patterns.

**4. The default is keyless Esri, resolved through `LE_IMAGERY_PROVIDER=auto`**, which walks
`LE_IMAGERY_FALLBACK_CHAIN` (`local_orthophoto,esri_world_imagery`) and takes the first
`is_configured()` provider. An empty ortho dir self-skips → Esri (zero-config, L2). A populated one
wins → `local_orthophoto`, because if the operator mounted orthophotos they are definitionally better
than any web tile source.

**5. Legal constraints are enforced mechanically, not by documentation** (`CONTRACT.md` §11.5):

| Constraint | Mechanism — **not a doc paragraph** |
|---|---|
| Google Earth is out of scope | No provider, no enum label. Unrepresentable. |
| Google Maps Static needs an affirmative act | Double opt-in: key **and** `LE_GOOGLE_TOS_ACKNOWLEDGED=true` |
| Some providers forbid caching | `capabilities().allows_caching = False` ⇒ `DiskTileCache`/`RedisTileCache` **refuse the write** and fall back to in-process LRU with a `WARNING` |
| Some providers forbid derivative export | `capabilities().allows_derivative_export = False` ⇒ `ExportContext.chip = None` ⇒ **the PDF omits the map figure** and records it in `ExportBundle.warnings` |
| Attribution is a licence condition | `SatelliteChip.attribution`, `CandidateWindow.attribution` and `match_results.attribution` are **required fields**. **Pixels cannot travel without their credit.** |
| The operator's allow-list | `LE_ALLOWED_PROVIDERS` — a hard list; outside it ⇒ `403 PROVIDER_TOS_FORBIDDEN` |
| Provider registration | **Explicit. No entry-point autodiscovery.** |

## Rationale

**The abstraction is what makes the legal constraint structural.** Once every source is an
`ImageryProvider` and the set of providers is an explicit, reviewed, version-controlled list, "we do
not use Google Earth" stops being a rule someone must remember and becomes a property of the type
system. §11.5's first row is the point of the whole ADR: **not a disabled flag — an absence.**

**Explicit registration over plugin autodiscovery, deliberately.** Entry-point autodiscovery is
idiomatic Python and is the wrong choice here: for a product whose central legal constraint is *which
imagery sources are permitted*, a mechanism that lets an unreviewed provider appear **by being
pip-installed** is a liability. The set of providers is a list a reviewer can read.

**`allows_caching` and `allows_derivative_export` are capability flags rather than documentation**
because a ToS obligation that lives only in a Markdown file is an obligation nobody enforces at 2 a.m.
A provider with restrictive terms **cannot accidentally accumulate a permanent on-disk copy** via a
background job, because the cache asks the capability object first.

**Keyless Esri is a bootstrapping decision, not a licensing one — and the contract refuses to let
that read as a recommendation.** Reachable ≠ licensed. "Derived survey deliverable" is the use most
likely to exceed the terms of any web basemap. The default satisfies the zero-config mandate and
nothing more; the caveat is repeated in the README, the first-run log line, the UI provider picker and
every PDF. **Whether it is a defensible product default for paid deliverables is a question for the
client and their counsel** — `CONTRACT.md` §12.5 escalates it rather than deciding it, and
`TRACEABILITY.md` §5 keeps it visible.

## Consequences

**Positive.**
- The legal constraint is enforced by structure. It survives a new developer who has not read this ADR.
- Providers are interchangeable. `local_orthophoto` — fully offline, highest accuracy, error knowable
  — is a config change, not a port.
- `docker compose up` with an empty `.env` yields a working satellite view (L2).
- `LE_IMAGERY_OFFLINE=true` restricts resolution to `local_orthophoto` + `fixture`: **air-gapped mode
  is a first-class supported mode**, not a test flag.
- The provider-contract test (`gis/tests/test_providers_contract.py`) is **parametrised over every
  provider** — the interchangeability proof. A provider that is not in it does not exist (§13.4 rule 8).

**Negative, stated honestly.**
- Seven providers is seven ToS surfaces to track. `docs/legal/imagery-terms.md` is the record, and
  it is a **standing obligation**, not a one-time write-up. Terms change; the doc has a review date.
- The ABC is the lowest common denominator of seven quite different APIs (XYZ pyramids, a metadata
  handshake, an OAuth2 scene API, a local GeoTIFF). `get_static_bbox` and the explicit
  `sat_geotransform` + `sat_geotransform_srid` exist because tile addressing does **not** generalise —
  `local_orthophoto` produces UTM geotransforms that a 3857-only design could not store.
- Attribution as a required field means it cannot be forgotten, and also means every synthetic
  provider and fixture must supply one. Accepted: that is the constraint working.

## Alternatives considered

**Rejected — use Google Earth.** The client states it cannot legally or technically be used. There is
no engineering answer to this and no amount of cleverness makes it available.

**Rejected — a `google_earth` provider that raises / a disabled feature flag.** This is the seductive
one: it looks tidy, it documents the constraint in code, and it is exactly wrong. A flag can be
flipped; an enum member can be selected; a raising stub invites a `# TODO: implement`. Worse, the
`imagery_provider` enum would carry a value the database could store, so a row could **claim** Google
Earth provenance. Absence is the only implementation of "never".

**Rejected — hardcode one provider (Esri) with no abstraction.** Cheaper by a day. It forecloses
`local_orthophoto` (the offline, highest-accuracy path and the only one where total error is
knowable), forecloses `fixture` (and therefore the entire no-network test and demo story), and puts
the ToS chokepoint nowhere. The abstraction is not speculative generality — **three of the seven
providers are load-bearing today.**

**Rejected — a Mapbox token in `VITE_MAPBOX_TOKEN`.** It is public the moment the bundle ships. URL
restrictions mitigate and do not solve, and it forecloses server-side caching. See ADR-010.

**Rejected — leave ToS compliance to documentation.** "Several providers cap caching" in a Markdown
file does not stop a 30-day disk cache from accumulating a permanent copy. `allows_caching` does.

## Related

- [`docs/legal/imagery-terms.md`](../../legal/imagery-terms.md) — per-provider ToS posture, the
  operator's pre-flight checklist, and why Google Earth cannot be a provider. **Read before enabling
  any keyed provider.**
- [ADR-010](ADR-010-tile-proxy.md) — the tile proxy; keys never reach the browser.
- `CONTRACT.md` §11.4 (`auto` resolution), §11.5 (mechanical enforcement), §7.2 (proxy rationale).
- `TRACEABILITY.md` R-07 · R-07g.
