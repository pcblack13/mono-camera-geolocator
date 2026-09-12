"""``run_match_job(ctx) -> MatchJobResult`` — ★ the engine's PRIMARY public entry point.

★ DEFERRED IN THIS BUILD. IT RAISES `NotImplementedDeferred` IMMEDIATELY AND
UNMISTAKABLY. The automatic matching engine is not implemented — see
``docs/architecture/SCOPE.md``. LandExplorer ships as a **manual GCP surveying tool**: the
surveyor marks a landmark in the photograph, clicks the same physical spot on the satellite
map, and the coordinate is recorded as a **direct observation rather than an inference**.

★ WHY THIS FUNCTION, OF ALL FUNCTIONS, MUST NOT IMPROVISE.

`run_match_job` is the one place in the system where a fabricated answer would be
indistinguishable from a real one. Its normal contract is that it *does not raise for a
business outcome* — "no match found" is a RESULT, returned as
``MatchJobResult(status="no_viable_candidate", best=None, gcp_fixes=())``, because refusing
to answer is a legitimate answer (§11.6). That contract makes it very tempting to defer this
function by *returning* that same empty result.

**That would be the worst possible choice, and it is worth being explicit about why.**
"No viable candidate" means *the engine looked and found nothing* — it is a statement about
the imagery. "Not implemented" means *the engine never looked*. Returning the former for the
latter would tell a surveyor that their photograph could not be matched against the
satellite imagery, which is a factual claim about their data, and it would be false. They
would re-shoot the site. The UI would render an honest-looking empty state. Every metric
would agree. Nothing would fail, and the product would be lying.

So: it raises, with a distinct exception class that names this module and points at the
ruling. `backend.app.api` catches exactly `NotImplementedDeferred` and answers **501** with
the uniform error envelope and a ``feature: "deferred"`` marker — not 404, because the
feature is planned rather than absent, and not a fake 200. The UI disables the control with
an honest tooltip. Nobody has to guess.

★ RE-ENABLING (SCOPE §7). Implementing the engine must require **zero changes outside
`ai_engine/`**, plus flipping the deferred endpoints from 501 to live and enabling the UI
controls. Everything this function needs already exists in typed form: `MatchContext` bundles
the injected dependencies, `steps.py` declares the nine steps with their real signatures,
`ranking.py` declares the ranking, and `MatchJobResult` declares the output. The body below
is the only thing missing.
"""

from __future__ import annotations

from ai_engine.errors import NotImplementedDeferred
from ai_engine.logging import get_logger
from ai_engine.pipeline.context import MatchContext
from ai_engine.types import MatchJobResult

__all__ = ["run_match_job"]

_log = get_logger(__name__)


def run_match_job(ctx: MatchContext) -> MatchJobResult:
    """Run the automatic matching pipeline for one job. **DEFERRED — raises.**

    When implemented, the nine steps in order (`pipeline/steps.py`), reporting progress at
    every boundary through `ctx.on_progress`:

    1. extract the query image's features (fused with describing at the landmarks);
    2. iterate the candidate windows from `ctx.windows`;
    3. extract each window's features;
    4. correspond via `ctx.source`;
    5. estimate the homography — sorting for PROSAC, then **un-permuting**;
    6. validate degeneracy;
    7. score;
    8. rank and check the ambiguity margin;
    9. finalise the best window into `GcpPixelFix`es.

    Args:
        ctx: The immutable per-job bundle. Every dependency is injected — the engine knows
            nothing about Redis, Celery or Postgres, and `ctx.on_progress` is the entire
            coupling.

    Returns:
        When implemented: a `MatchJobResult`. Never raising for a business outcome — an
        unmatchable photograph returns ``status="no_viable_candidate"`` with an empty
        `gcp_fixes`, and an under-separated winner returns ``status="ambiguous"``.

    Raises:
        NotImplementedDeferred: **Always, in this build.** See the module docstring for why
            this raises rather than returning the empty result its own contract would
            otherwise make so convenient: returning "no viable candidate" would assert that
            the engine looked and found nothing, which is a false statement about the
            surveyor's imagery rather than a true one about this build.
    """
    _log.warning(
        "run_match_job was called for job %r, but the automatic matching engine is "
        "DEFERRED in this build. Refusing rather than returning an empty result, which "
        "would falsely report that the imagery could not be matched. Place GCPs manually; "
        "see docs/architecture/SCOPE.md.",
        getattr(ctx, "job_id", "<unknown>"),
    )
    raise NotImplementedDeferred(
        __name__,
        feature="automatic geolocation pipeline (run_match_job)",
    )
