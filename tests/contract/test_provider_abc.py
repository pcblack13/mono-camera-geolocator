"""★ The `ImageryProvider` ABC conformance suite — the interchangeability proof (§13.1 IU-31).

*"`tests/contract/` — the ABC conformance suites, parametrised, importable by both
packages."* IU-11's `test_providers_contract.py` already parametrises the deep behavioural
sweep inside `gis`. This file takes the **cross-package** angle IU-11 cannot: the properties
that only mean something when more than one package is in the room.

Two of those, and the second is the one no single unit can enforce:

1. **Every provider is structurally interchangeable.** A provider is chosen by a name in a
   PG enum and constructed by the backend; the whole imagery abstraction (SCOPE.md: "swapping
   Esri for Mapbox cannot change the matching algorithm") rests on all seven satisfying one
   ABC totally — construction, identity, readiness and capabilities, with **no network and
   no credentials**.

2. **`PROVIDER_NAMES` is the join between two packages that must never diverge.** `gis` owns
   the tuple but cannot see the `imagery_provider` PG enum, because importing sqlalchemy is
   forbidden (§10.2, the `gis-purity` contract). So `gis` tests against the tuple and *this*
   suite — which may read both — pins the tuple to the PG enum's values by parsing
   `models/enums.py` with `ast`. It is the one place the constraint §5.3 states can actually
   be checked without the backend stack installed.

★ No network: `tests/conftest.py`'s autouse `_no_network` blocks IP sockets, which turns
"providers don't fetch at construction" from a claim into a proof.
"""

from __future__ import annotations

from typing import Any

import pytest

from _astsupport import REPO_ROOT, enum_members

pytest.importorskip("numpy", reason="constructing providers needs numpy")

MODELS_ENUMS = REPO_ROOT / "backend" / "app" / "models" / "enums.py"


@pytest.fixture(scope="module")
def provider_registry() -> dict[str, Any]:
    """The live `gis` provider registry: `{name: factory}` for all seven."""
    from gis.imagery.registry import PROVIDERS

    return dict(PROVIDERS)


@pytest.fixture(scope="module")
def provider_names() -> tuple[str, ...]:
    """`gis.imagery.base.PROVIDER_NAMES` — the canonical tuple."""
    from gis.imagery.base import PROVIDER_NAMES

    return PROVIDER_NAMES


def _all_names() -> tuple[str, ...]:
    """Read `PROVIDER_NAMES` once at import for parametrisation."""
    from gis.imagery.base import PROVIDER_NAMES

    return PROVIDER_NAMES


# =============================================================================
# Registry ↔ PROVIDER_NAMES ↔ PG enum — the three-way join
# =============================================================================


def test_registry_is_exactly_provider_names(
    provider_registry: dict[str, Any], provider_names: tuple[str, ...]
) -> None:
    """★ Every declared name is registered, and nothing extra is.

    §11.5: the registry is explicit and in version control — no entry-point autodiscovery, so
    a provider that appears by being pip-installed is a provider nobody reviewed. That is only
    true while the registry's keys are exactly `PROVIDER_NAMES`.
    """
    assert set(provider_registry) == set(provider_names), (
        f"registry keys {sorted(provider_registry)} != PROVIDER_NAMES {sorted(provider_names)}"
    )


def test_provider_names_equals_the_pg_enum_values(provider_names: tuple[str, ...]) -> None:
    """★★ THE CONSTRAINT `gis` CANNOT ENFORCE ON ITSELF (§5.3, §13.1 IU-15/16).

    `imagery_provider`'s PG labels ARE the registry keys — an image row stores `'mapbox_
    satellite'` and the backend must be able to construct that provider. `gis` cannot check
    this: importing `models.enums` would drag sqlalchemy into `gis` and break every offline
    test (§10.2). §5.3 explicitly relocates the check to "a **backend** test". This is the
    version that runs *here*, on a machine where sqlalchemy is not installed, by parsing the
    ORM enum instead of importing it.

    ★ There is deliberately no `google_earth` label (§5.3): out of scope by client legal
    constraint, made unrepresentable rather than merely disabled. Set equality keeps it out.
    """
    models = enum_members(MODELS_ENUMS)
    assert "ImageryProvider" in models, "models/enums.py has no ImageryProvider enum"
    pg_values = set(models["ImageryProvider"].values())

    assert set(provider_names) == pg_values, (
        "PROVIDER_NAMES and the imagery_provider PG enum have diverged — a name that exists "
        "in one and not the other is a provider the DB can store but the app cannot build, "
        "or vice versa.\n"
        f"  only in PROVIDER_NAMES: {sorted(set(provider_names) - pg_values)}\n"
        f"  only in the PG enum:    {sorted(pg_values - set(provider_names))}"
    )
    assert "google_earth" not in pg_values, "★ google_earth must remain unrepresentable (§5.3)"


def test_esri_is_the_first_name_the_keyless_default(provider_names: tuple[str, ...]) -> None:
    """★ L2: the default provider is keyless. `esri_world_imagery` leads the tuple.

    L2 is what makes `docker compose up` with an empty `.env` yield a working satellite
    search. The default has to be the one that needs no key, and the order of this tuple is
    where "default" is expressed.
    """
    assert provider_names[0] == "esri_world_imagery"


# =============================================================================
# The interchangeability proof — parametrised over every provider
# =============================================================================


@pytest.mark.parametrize("name", _all_names())
def test_provider_constructs_with_zero_config_and_no_network(
    name: str, provider_registry: dict[str, Any], clean_env: None
) -> None:
    """★ Construction never raises and never touches the network — for EVERY provider.

    L10: `Settings()` with an empty environment never raises, so a zero-config `GisConfig`
    must construct every provider, including the keyed ones (they construct unconfigured and
    *report* it; they do not refuse to exist). The `_no_network` fixture makes a DNS lookup in
    a constructor an immediate failure rather than a slow flake.
    """
    from gis.config import GisConfig

    provider = provider_registry[name](GisConfig())
    assert provider is not None


@pytest.mark.parametrize("name", _all_names())
def test_provider_identity_and_readiness_are_total(
    name: str, provider_registry: dict[str, Any], clean_env: None
) -> None:
    """★ `name` / `is_configured()` / `capabilities()` are total and honest.

    "Total" = they answer for every provider without raising, configured or not. This is the
    surface the backend calls to decide what to offer; a provider that raised from
    `is_configured()` when unconfigured would turn an honest "greyed out, needs a key" into a
    500. `name` must be a member of `PROVIDER_NAMES` — the registry key and the identity
    cannot disagree.
    """
    from gis.imagery.base import PROVIDER_NAMES, ProviderCapabilities

    provider = provider_registry[name](__import__("gis.config", fromlist=["GisConfig"]).GisConfig())

    assert provider.name == name, f"registered as {name!r} but self-identifies as {provider.name!r}"
    assert provider.name in PROVIDER_NAMES

    ready = provider.is_configured()
    assert isinstance(ready, bool)

    caps = provider.capabilities()
    assert isinstance(caps, ProviderCapabilities)
    assert caps.supports_tiles or caps.supports_static_bbox, (
        f"{name} advertises neither tiles nor static-bbox; it can serve nothing"
    )
    assert caps.georef_ce90_m >= 0.0, (
        f"{name}: georef_ce90_m is mandatory and non-negative — it is the imagery term in "
        "every GCP's accuracy budget (§4.20)"
    )
    # ``min_zoom``/``max_zoom`` are abstract properties on the PROVIDER (base.py), not on
    # ``ProviderCapabilities`` — every concrete provider therefore declares them, and the
    # serveable band must be non-empty.
    assert provider.min_zoom <= provider.max_zoom, (
        f"{name}: min_zoom {provider.min_zoom} > max_zoom {provider.max_zoom}; empty zoom band"
    )


@pytest.mark.parametrize("name", _all_names())
def test_keyless_providers_are_configured_out_of_the_box(
    name: str, provider_registry: dict[str, Any], clean_env: None
) -> None:
    """★ The three keyless providers are ready with no environment at all.

    `esri_world_imagery` (L2's default), `fixture` (offline demo) and `local_orthophoto`
    (when its dir is populated) need no credentials. With a clean env, at minimum the two
    that need no filesystem either — Esri and fixture — must report configured, or the
    out-of-the-box experience is "job failed".
    """
    from gis.config import GisConfig

    provider = provider_registry[name](GisConfig())
    keyless_always = {"esri_world_imagery", "fixture"}
    if name in keyless_always:
        assert provider.is_configured() is True, f"{name} is keyless and must be ready by default"
    if name == "fixture":
        assert provider.requires_api_key is False


@pytest.mark.parametrize("name", _all_names())
def test_keyed_providers_report_rather_than_raise_when_unconfigured(
    name: str, provider_registry: dict[str, Any], clean_env: None
) -> None:
    """★ L11: a missing key is a reported state, never a traceback.

    A keyed provider with no credentials constructs, answers `is_configured() -> False`, and
    gives a reason — it does not raise. That is what lets `GET /capabilities` grey it out
    with "requires LE_MAPBOX_ACCESS_TOKEN" instead of the app failing to start.
    """
    from gis.config import GisConfig

    provider = provider_registry[name](GisConfig())
    if provider.requires_api_key and not provider.is_configured():
        reason = provider.configuration_reason()
        assert reason, f"{name} is unconfigured but gives no reason; the UI has nothing to show"
