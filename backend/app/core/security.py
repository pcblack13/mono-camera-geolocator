"""Principal resolution. A NO-OP when ``LE_AUTH_MODE=none`` — which is the default.

CONTRACT.md §9.2 turns auth off out of the box, and §2.4 requires this module to be
a no-op in that state.

★ **The honest consequence, stated rather than hidden** (§9.2). With auth off,
``gcps.adjusted_by = 'anonymous'`` and ``ck_gcps_adjustment_complete`` is satisfied
by a value that attributes nothing. The database can prove *that* a coordinate was
adjusted and *when*, but not *by whom*. **That is acceptable for a single-surveyor
deployment and NOT acceptable for a multi-user one producing legal survey
deliverables.** So ``PATCH /gcps/{id}`` raises ``MissingCredentials`` the moment
``LE_AUTH_MODE != none`` and no principal resolves: the audit trail is enforced
exactly when there is more than one person who could be lying. ``/health/ready``
reports ``auth_mode`` so a reviewer sees which world they are in at a glance.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping, Protocol

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, InvalidCredentials, MissingCredentials

__all__ = [
    "ANONYMOUS_PRINCIPAL",
    "ANONYMOUS_SUBJECT",
    "PrincipalKind",
    "Principal",
    "TokenVerifier",
    "authenticate",
    "hash_api_key",
]

PrincipalKind = Literal["anonymous", "api_key", "bearer", "cookie"]

#: The value written to audit columns (``gcps.adjusted_by``, ``exports.requested_by``)
#: when auth is off. A literal, not None: the columns are NOT NULL and a magic empty
#: string would be indistinguishable from a bug. 'anonymous' attributes nothing, and
#: says so in the row rather than in a comment somewhere.
ANONYMOUS_SUBJECT: Final = "anonymous"


@dataclass(frozen=True, slots=True)
class Principal:
    """Whoever is making this request. Always present; never None.

    A null-object rather than an ``Optional``: with auth off there is still a caller,
    and forcing every downstream site to branch on ``principal is None`` is how the
    branch gets forgotten at the one site that writes the audit column.
    """

    subject: str
    kind: PrincipalKind = "anonymous"
    display_name: str | None = None
    scopes: frozenset[str] = frozenset()
    claims: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_anonymous(self) -> bool:
        return self.kind == "anonymous"

    @property
    def is_authenticated(self) -> bool:
        return self.kind != "anonymous"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def __str__(self) -> str:
        return self.subject


#: The single shared anonymous principal. Frozen and immutable, so sharing is safe.
ANONYMOUS_PRINCIPAL: Final = Principal(subject=ANONYMOUS_SUBJECT, kind="anonymous")


def hash_api_key(raw_key: str) -> str:
    """Hash a raw API key for comparison against ``LE_API_KEYS``.

    §9.2 specifies ``LE_API_KEYS`` as a **CSV of hashed keys**, never plaintext: the
    variable lands in a compose file, a shell history and a process listing, and a
    leaked hash cannot be replayed against the API while a leaked key can.

    sha256, unsalted, deliberately. This is not a password hash and Argon2 would be
    cargo cult: an API key is 256 bits of CSPRNG output, so there is no dictionary to
    attack and nothing for a salt to defend. It also has to run on every request, and
    a deliberately-slow KDF on the hot path is a self-inflicted DoS.

    Generate one with::

        python -c "import secrets,hashlib;k=secrets.token_urlsafe(32);print(k, hashlib.sha256(k.encode()).hexdigest())"
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class TokenVerifier(Protocol):
    """Verifies a bearer/cookie token and returns its claims.

    The seam for ``LE_AUTH_MODE=bearer|cookie``. Kept as a Protocol so a deployment
    that needs JWKS can inject a verifier without this module growing a JWT
    dependency that the default (``none``) deployment would pay for and never use.
    """

    def verify(self, token: str) -> Mapping[str, Any]:
        """Return the token's claims, or raise ``InvalidCredentials``."""
        ...


class _UnconfiguredTokenVerifier:
    """Refuses, with an actionable message. The default for bearer/cookie mode.

    ★ L12: refuse rather than answer wrongly. This build ships no JWKS client, so
    there are exactly two honest options for ``LE_AUTH_MODE=bearer`` — refuse at the
    boundary, or accept tokens without verifying them. The second is not an option:
    an unverified bearer token is an authentication system that authenticates
    nobody while reporting that it did, which is strictly worse than having none.
    """

    def verify(self, token: str) -> Mapping[str, Any]:
        raise ConfigurationError(
            "LE_AUTH_MODE is set to a token mode, but no TokenVerifier is installed in "
            "this build, so tokens cannot be verified. Use LE_AUTH_MODE=api_key, or "
            "inject a TokenVerifier at the composition root."
        )


def authenticate(
    settings: Settings,
    *,
    api_key: str | None = None,
    bearer_token: str | None = None,
    cookie_token: str | None = None,
    token_verifier: TokenVerifier | None = None,
) -> Principal:
    """Resolve the caller to a ``Principal``, per ``LE_AUTH_MODE``.

    Framework-free by design: it takes strings, not a ``Request``, so it is callable
    from a Celery worker and testable without an ASGI app. ``api.deps.get_principal``
    (IU-21) pulls the headers off the request and calls this.

    Args:
        settings: The active settings — ``auth_mode`` and ``api_keys`` are read.
        api_key: The raw key from ``X-API-Key`` (or an ``Authorization: ApiKey`` header).
        bearer_token: The raw token from ``Authorization: Bearer``.
        cookie_token: The raw token from the session cookie.
        token_verifier: Verifier for the token modes. Defaults to one that refuses.

    Returns:
        The resolved principal. ``ANONYMOUS_PRINCIPAL`` when auth is off.

    Raises:
        MissingCredentials: auth is on and the caller presented nothing.
        InvalidCredentials: the caller presented something that did not check out.
        ConfigurationError: a token mode with no verifier installed.
    """
    # ── The default path. No hashing, no comparison, no I/O — a no-op. ──────────
    if settings.auth_mode == "none":
        return ANONYMOUS_PRINCIPAL

    if settings.auth_mode == "api_key":
        if not api_key:
            raise MissingCredentials("An API key is required. Send it in the X-API-Key header.")
        return _principal_from_api_key(api_key, settings)

    token = bearer_token if settings.auth_mode == "bearer" else cookie_token
    if not token:
        raise MissingCredentials(
            "A bearer token is required."
            if settings.auth_mode == "bearer"
            else "A session cookie is required."
        )

    verifier = token_verifier or _UnconfiguredTokenVerifier()
    claims = verifier.verify(token)
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        # A token with no subject cannot attribute an adjustment, and attributing it
        # to a blank string would put a lie in the audit column.
        raise InvalidCredentials("The token carries no subject claim.")

    scope_claim = claims.get("scope") or claims.get("scopes") or ()
    scopes = scope_claim.split() if isinstance(scope_claim, str) else tuple(scope_claim)

    return Principal(
        subject=subject,
        kind="bearer" if settings.auth_mode == "bearer" else "cookie",
        display_name=claims.get("name") or claims.get("preferred_username"),
        scopes=frozenset(scopes),
        claims=dict(claims),
    )


def _principal_from_api_key(raw_key: str, settings: Settings) -> Principal:
    """Match a raw key against the configured hashes in constant time."""
    if not settings.api_keys:
        # Auth is on and no keys are configured: nobody can ever authenticate. That
        # is a deployment mistake, not a credential problem, and a 401 would send the
        # operator hunting for a bad key that does not exist.
        raise ConfigurationError(
            "LE_AUTH_MODE=api_key but LE_API_KEYS is empty, so no request can ever "
            "authenticate. Set LE_API_KEYS to a CSV of sha256 key hashes."
        )

    presented = hash_api_key(raw_key)
    for configured in settings.api_keys:
        # compare_digest, not ==: string comparison short-circuits on the first
        # differing byte and leaks the length of the matching prefix through timing.
        # Cheap here, and the alternative is a timing oracle on a credential.
        if hmac.compare_digest(presented, configured.strip().lower()):
            # The subject is the key's fingerprint, not the key: it is stable, it is
            # safe in a log line and an audit column, and it is enough to tell two
            # surveyors apart.
            return Principal(
                subject=f"api_key:{presented[:12]}",
                kind="api_key",
                display_name=None,
                scopes=frozenset(),
                claims={},
            )

    raise InvalidCredentials("The API key presented is not recognised.")
