"""The uniform error envelope (§6.2) — including the DEFERRED surface.

**Every** non-2xx response has the :class:`ErrorEnvelope` shape: FastAPI's own
``RequestValidationError``, unhandled exceptions, and every domain error in
§6.3's hierarchy. ``ErrorEnvelope`` is registered via a shared
``COMMON_ERROR_RESPONSES`` dict on **every** route, so ``openapi.json`` documents
it everywhere rather than on a lucky few. *A missing 404 in the spec becomes an
untyped ``any`` in the generated client.*

**The single explicit exception:** ``GET /health/ready`` returns
``ReadinessResponse`` on 503, not an ``ErrorEnvelope`` — a probe wants the check
detail, and that response is not an application error.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal

from pydantic import Field

from app.core.constants import docs_url_for

from .common import ApiModel

__all__ = [
    "DEFERRED_DOCS_URL",
    "DEFERRED_FEATURE_CODE",
    "DEFERRED_HTTP_STATUS",
    "DeferredFeature",
    "ErrorBody",
    "ErrorDetail",
    "ErrorEnvelope",
    "deferred_envelope",
]


class ErrorDetail(ApiModel):
    """One field-level or sub-condition failure.

    Shaped after pydantic's own error entries so that FastAPI's
    ``RequestValidationError`` maps onto it with no translation table.
    """

    loc: list[str | int]
    msg: str
    type: str
    input: Any | None = None


# ─────────────────────────────────────────────────────────────────────────────
# The DEFERRED marker — SCOPE.md §4 rule 3
# ─────────────────────────────────────────────────────────────────────────────

#: ★ SCOPE.md §4 rule 3, verbatim: *"Endpoints for deferred features are
#: **registered and documented**, and return **``501 Not Implemented``** with
#: the uniform error envelope and a ``feature: "deferred"`` marker. They must
#: not 404 (the feature is planned, not absent) and must not fake a result."*
#:
#: **501, not 404, and not 200-with-a-guess.** The three wrong answers and why
#: each is worse:
#:   - **404** says the feature does not exist. It does — it is specified in
#:     ``CONTRACT.md §4``, its ABC is in ``ai_engine``, its tables are migrated,
#:     and its UI is built and disabled. A 404 would send a client integrator to
#:     look for a typo in a URL that is correct.
#:   - **200 + a fabricated coordinate** is the failure mode L12 exists to
#:     prevent. A GCP is a survey coordinate someone may dig, build, or file
#:     against.
#:   - **500** says we broke. We did not; we have not built this yet, on
#:     purpose, and said so in writing.
DEFERRED_HTTP_STATUS: Final[int] = 501

#: The stable, machine-readable code. Already present in
#: ``core.constants.ERROR_CODES`` (IU-15) and in IU-23's ``ApiErrorCode`` union,
#: so all three legs of the error vocabulary already agree on the spelling.
DEFERRED_FEATURE_CODE: Final[str] = "FEATURE_DEFERRED"

#: ★ Where a deferred response points. **``SCOPE.md`` and not the error-code
#: index**, deliberately: the question a caller of a 501 actually has is *"why
#: is this not built, and what do I do instead?"*, and SCOPE.md §1/§2/§5 answers
#: exactly that in three paragraphs — including the answer ("place GCPs
#: manually"). ``docs/api/errors.md#feature_deferred`` would tell them what a
#: 501 is, which they know.
#:
#: Relative, for the same reason ``core.constants.ERROR_DOCS_BASE_URL`` is: the
#: API is reachable at an arbitrary host, so an absolute URL would be wrong for
#: most deployments and a phone-home-shaped link in an air-gapped install.
DEFERRED_DOCS_URL: Final[str] = "/docs/architecture/SCOPE.md"


class DeferredFeature(ApiModel):
    """The ``feature`` marker carried by a **501** body. ★ SCOPE.md §4 rule 3.

    ★ **Why this is a typed member of ``ErrorBody`` and not a free-text
    message.** SCOPE.md §7 requires that re-enabling the engine costs *"zero
    changes outside ``ai_engine/``, plus flipping the deferred endpoints from
    501 to live and enabling the UI controls."* The UI can only be gated off a
    field a client can **switch on**. A client that has to regex a human
    sentence to decide whether to grey out a button has a UI that breaks when
    someone improves the wording — and SCOPE.md §4 rule 4 mandates a calm,
    honest explainer, not an error toast, which is a rendering decision that
    must key off structure.

    ★ ``status`` is a ``Literal["deferred"]`` and not a free string. The marker
    SCOPE.md names is literally ``feature: "deferred"``; a widened enum here
    would invite a future ``"partial"`` or ``"beta"``, which is precisely the
    hedging this whole document refuses.
    """

    status: Literal["deferred"] = "deferred"
    name: str = Field(
        description=(
            'The deferred capability, e.g. "matching", "suggest_landmarks", '
            '"segment", "camera_pose", "heatmap". Matches a member of '
            "CapabilitiesResponse.deferred_features, so a client gates controls "
            "off ONE server-provided list rather than a hard-coded constant that "
            "must be edited when the engine lands."
        )
    )
    reason: str = Field(
        description=(
            "Why, in one human sentence. Never an apology and never a promise "
            "of a date."
        )
    )
    docs_url: str = Field(
        default=DEFERRED_DOCS_URL,
        description="Points at SCOPE.md — the document that made the ruling.",
    )
    alternative: str | None = Field(
        default=None,
        description=(
            "What the caller should do instead, when there IS something. For "
            "matching: place GCPs manually. Null when there is no alternative — "
            "an invented one is worse than none."
        ),
    )


class ErrorBody(ApiModel):
    """The body of every error. ★ Also the shape of ``JobRead.error``, so the
    client renders job failures with the SAME component as HTTP errors.
    """

    code: str = Field(
        description=(
            "★ STABLE, machine-readable, SCREAMING_SNAKE. The client switches on "
            "this. Never localise. Every value is a member of "
            "core.constants.ERROR_CODES."
        )
    )
    message: str = Field(
        description=(
            "Human, English, safe to display. NEVER SQL, stack frames, file "
            "paths, or provider keys."
        )
    )
    status: int = Field(
        description=(
            "Mirrors HTTP. Duplicated in-body deliberately: it survives logging, "
            "proxies, and client libraries that discard the status line."
        )
    )
    details: list[ErrorDetail] | None = None
    request_id: str = Field(
        description=(
            "ULID. Also the X-Request-ID header. The string a user pastes into a "
            "bug report."
        )
    )
    timestamp: datetime
    docs_url: str | None = None
    feature: DeferredFeature | None = Field(
        default=None,
        description=(
            "★ SCOPE.md §4 rule 3. Non-null IFF this is a 501 for a DEFERRED "
            "feature. Null on every other error, including a genuine 501 from a "
            "proxy. Its presence is the machine-readable 'this is planned, not "
            "broken, and not absent'."
        ),
    )


class ErrorEnvelope(ApiModel):
    """``{"error": {...}}`` — the shape of **every** non-2xx response."""

    error: ErrorBody


def deferred_envelope(
    *,
    feature: str,
    reason: str,
    request_id: str,
    timestamp: datetime,
    message: str | None = None,
    alternative: str | None = None,
) -> ErrorEnvelope:
    """Build the **one** canonical 501 body for a deferred feature.

    ★ It is a function, and there is exactly one, because SCOPE.md §4 rule 3
    applies to **five** endpoints (30, 43, 47, 48, 49 — plus batch-match at 54
    and ``gcps/recompute`` at 42). Five hand-rolled 501s drift: one forgets the
    marker, one 404s, one says "coming soon". One constructor cannot.

    ★ It never fabricates. There is no default ``reason`` — the caller states
    which feature and why, or does not get an envelope.

    Args:
        feature: the capability name. Must match a member of
            ``CapabilitiesResponse.deferred_features`` so the UI gates off one
            server-provided list.
        reason: one human sentence. No date, no apology.
        request_id: the ULID from ``RequestIdMiddleware``.
        timestamp: when the response was minted. Passed in rather than defaulted
            to ``now()`` so the handler's clock is the single one, and so this is
            testable without freezing time.
        message: overrides the default human message.
        alternative: what to do instead, when there is something.

    Returns:
        A complete :class:`ErrorEnvelope` with ``status=501``,
        ``code="FEATURE_DEFERRED"`` and a populated ``feature`` marker.
    """
    return ErrorEnvelope(
        error=ErrorBody(
            code=DEFERRED_FEATURE_CODE,
            message=message or f"{feature} is not enabled in this build.",
            status=DEFERRED_HTTP_STATUS,
            details=None,
            request_id=request_id,
            timestamp=timestamp,
            # ★ Note this points at the error index (via IU-15's map) while the
            #   marker's own docs_url points at SCOPE.md. Two links, two
            #   questions: "what is this code?" and "why is this not built?".
            docs_url=docs_url_for(DEFERRED_FEATURE_CODE),
            feature=DeferredFeature(
                name=feature,
                reason=reason,
                alternative=alternative,
            ),
        )
    )
