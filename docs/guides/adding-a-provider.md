# Adding an imagery provider

> ## ★ STOP. Read [`docs/legal/imagery-terms.md`](../legal/imagery-terms.md) first.
>
> `gis/imagery/` is **the legal boundary**. Adding a provider is a **compliance decision** before it is
> an engineering one. **Google Earth is not addable** — see §0.

**Owner:** IU-11 · **Normative:** `CONTRACT.md` §4.16, §11.4, §11.5 ·
[ADR-002](../architecture/adr/ADR-002-abstract-the-imagery-provider.md)

---

## 0. What you may not add

**Google Earth. Ever.** Not as a provider, not as a flag, not as scaffolding, not as an enum member.
The client states it **cannot legally or technically** be searched or processed via its app or API.

★ **The `imagery_provider` PG enum has no `google_earth` member — it is unrepresentable in the type
system**, so the database itself cannot store a row claiming it as a source. **CI greps for Earth
endpoint patterns.** *Not a disabled flag: an absence.*

**Google Maps *Static* is a different product with a different licence** and is already implemented,
off by default, behind a **double opt-in**. See §2.5 of the legal doc.

---

## 1. Before you write code

- [ ] **Read the provider's current terms yourself.** Not our summary — it is dated.
- [ ] **Confirm the licence covers *deriving survey control points and supplying them to a client*** —
      not merely *"displaying a map"*. ★ **These are materially different uses**, and the second is the
      one most likely to exceed the terms.
- [ ] **Determine `allows_caching`.** If the terms cap or forbid caching, **the flag is `False`** and
      the tile cache will **refuse the write** and fall back to request-lifetime LRU with a `WARNING`.
- [ ] **Determine `allows_derivative_export`.** If the terms forbid including imagery in a derived
      deliverable, **the flag is `False`** and the **PDF omits the map figure** and says so in
      `ExportBundle.warnings`.
- [ ] **Find the attribution string** — and whether it is **dynamic** (Bing returns a vendor list from
      its metadata handshake; Esri's varies by location and zoom). ★ **A hardcoded string is a bug**
      if the provider's is dynamic.
- [ ] **Find `georef_ce90_m`.** ★ **Mandatory on `ProviderCapabilities`** — it flows into
      `CandidateWindow` → `PixelAccuracy` → `GcpAccuracy.total_ce90_m`. **If the provider does not
      publish one, say so with your best defensible estimate and document the source** — do not invent
      a flattering number. This is the term that makes `dominant_term` honest.
- [ ] **Find the rate limit.** ★ **A provider's rate limit is a contractual term, not a suggestion.**
- [ ] **Add the row to `docs/legal/imagery-terms.md`.** ★ **Not optional.**

---

## 2. The code

### 2.1 The provider

```python
# gis/src/gis/imagery/providers/acme.py
from gis.imagery.base import ImageryProvider, ProviderCapabilities, ProviderHealth, TileProviderMixin


class AcmeSatelliteProvider(TileProviderMixin, ImageryProvider):
    """Acme Satellite — keyed. Terms: https://acme.example/terms (reviewed 2026-07-17)."""

    name = "acme_satellite"          # ★ MUST be a member of gis.imagery.base.PROVIDER_NAMES

    def __init__(self, config: GisConfig) -> None:
        # ★ NEVER raise on a missing credential. Construction ALWAYS succeeds.
        #   A provider that throws in its constructor takes down the registry, the capabilities
        #   endpoint, and the UI that would have told you the key was missing.
        self._token = config.acme_token

    def is_configured(self) -> tuple[bool, str | None]:
        # ★ NEVER raises. Total. Callable with httpx absent.
        if not self._token:
            return False, "requires LE_ACME_TOKEN"
        return True, None

    def capabilities(self) -> ProviderCapabilities:
        # ★ Total. NEVER touches the network. Callable with httpx absent.
        return ProviderCapabilities(
            min_zoom=0,
            max_zoom=19,
            tile_size_px=256,
            native_crs="EPSG:3857",
            georef_ce90_m=5.0,              # ★ MANDATORY. Document your source.
            allows_caching=True,            # ★ FROM THE ToS. Not from convenience.
            allows_derivative_export=True,  # ★ FROM THE ToS.
            supports_multispectral=False,
            kinds=("satellite", "hybrid"),
        )
```

★ **`httpx` is bound at CALL time, inside the fetch function — never at module scope** (§11.3), even
though it is in `gis`'s **base** deps. The provider registry imports every provider **eagerly**, so a
module-scope `import httpx` makes `cd gis && pytest` die at **collection**, before a single test runs.
**Both facts are deliberate.**

### 2.2 Register it — explicitly

```python
# gis/src/gis/imagery/providers/__init__.py
from gis.imagery.providers.acme import AcmeSatelliteProvider

PROVIDERS = { ..., "acme_satellite": AcmeSatelliteProvider }
```

★ **No entry-point autodiscovery.** *For a product whose central legal constraint is which imagery
sources are permitted, a mechanism that lets an unreviewed provider appear **by being pip-installed**
is a liability. The set of providers is a reviewed, auditable list in version control.*

### 2.3 The four places the name must appear — ★ or a test fails

| Place | Owner | Why |
|---|---|---|
| `gis.imagery.base.PROVIDER_NAMES` | IU-11 | `gis` tests against **it** |
| `backend/app/models/enums.py::ImageryProvider` | IU-16 | ★ **`gis` may not import sqlalchemy**, so a **backend** test asserts `set(PROVIDER_NAMES) == {e.value for e in ImageryProvider}` |
| `backend/app/schemas/enums.py` | IU-17 | The wire enum |
| Migration `0002_create_enums.py` | IU-16 | The PG enum |

★ **The parametrised contract test** (`gis/tests/test_providers_contract.py`) picks it up automatically.
**A provider that is not in the contract test does not exist** (§13.4 rule 8).

### 2.4 Config

```python
# gis/src/gis/config.py — a working DEFAULT (L10). Empty = not offered, NOT a crash.
acme_token: str = ""
```

Add `LE_ACME_TOKEN` to `CONTRACT.md` §9.6 **and** `.env.example` (generated; CI byte-compares).

---

## 3. What the contract test will assert

For an **unconfigured** provider (no key — the CI state):

- `__init__` **never raises** and ★ **never touches the network** (a socket-blocking fixture proves it)
- `is_configured()` **never raises**
- `capabilities()` is **total**
- `name` ∈ `PROVIDER_NAMES`

For a **configured** provider (`fixture`, `local_ortho`):

- `get_tile` returns `(S, S, 3) uint8` ★ **RGB — not BGR, no alpha, C-contiguous**
- `get_static_bbox` returns a `SatelliteChip` whose ★ **`attribution` is non-empty**
- the chip's geotransform is **exact** for the returned pixels
- out-of-range `z` → `TileOutOfRangeError`
- ★ `allows_caching=False` **causes `DiskTileCache` to refuse the write** and fall back to LRU with a
  warning

---

## 4. Behaviour you inherit for free

| Situation | What happens |
|---|---|
| Key missing | `configured: false` **with a reason** on `GET /imagery/providers`. **Not a crash.** |
| `LE_IMAGERY_PROVIDER=auto` | Chain walk; your provider is skipped if unconfigured |
| Explicitly requested, unconfigured | ★ **`503 PROVIDER_NOT_CONFIGURED`** — *an explicit request is not a default* |
| Named, unconfigured, `LE_IMAGERY_STRICT=false` | **WARN + fall back.** ★ `chip.provider_name` is set to what was **actually** used, **so a downstream report can never misattribute imagery.** |
| Same, `LE_IMAGERY_STRICT=true` | **Raise.** *Dev is forgiving; prod is loud.* |
| Not in `LE_ALLOWED_PROVIDERS` | `403 PROVIDER_TOS_FORBIDDEN` |
| Browser tiles | ★ Proxied by default — key never leaves the server ([ADR-010](../architecture/adr/ADR-010-tile-proxy.md)) |

> ★ **The asymmetry, so you do not "fix" it:** an explicitly requested unconfigured **provider** is a
> `503`, but an explicitly requested missing **weight** is a `202` + fallback.
> **Imagery changes the answer's *provenance*; a matcher changes only its *accuracy*.**
> *Silently serving 10 m Sentinel when the operator paid for 0.3 m Mapbox is worse than a 503.*

---

## 5. Checklist

- [ ] Terms read; `docs/legal/imagery-terms.md` row added; **review date set**
- [ ] `allows_caching` / `allows_derivative_export` **from the ToS**, not from convenience
- [ ] `georef_ce90_m` **populated and its source documented**
- [ ] Attribution correct — ★ **and dynamic if the provider's is dynamic**
- [ ] `__init__` never raises; `is_configured()`/`capabilities()` never raise and never touch the network
- [ ] ★ **`httpx` bound at CALL time, not module scope**
- [ ] Registered explicitly in `providers/__init__.py`
- [ ] Name in **all four** places (§2.3)
- [ ] Env var in §9 + `.env.example`, **with a working default**
- [ ] `cd gis && pytest` green ★ **with httpx and redis blocked in `sys.modules`**
