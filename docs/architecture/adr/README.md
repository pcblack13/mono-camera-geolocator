# Architecture Decision Records

**What an ADR is here:** the record of a decision that shapes the system, the reasoning that produced
it, and — the part that matters most — **the alternatives that were rejected and why**. A decision
without its rejected alternatives is not a record; it is an assertion, and the next person to have the
same idea will have it again.

**Precedence.** ADRs are **normative for reasoning**. Where an ADR's *statement of fact* differs from
`CONTRACT.md`, the contract wins. Where `CONTRACT.md` differs from
[`SCOPE.md`](../SCOPE.md), **`SCOPE.md` wins**.

```
SCOPE.md  >  CONTRACT.md  >  the six specialist docs  >  these ADRs (reasoning only)
```

`00-overview.md` §7 holds the **index and the reasoning of record** for ADR-001..014. The files here
are the fuller versions for the decisions that most shape the system, **updated where `CONTRACT.md`
v2.0 or `SCOPE.md` overruled the original text.** Where an ADR was amended, the file says so at the
top rather than quietly disagreeing with its own index entry.

---

## The records

| ADR | Decision | Status |
|---|---|---|
| **[ADR-001](ADR-001-separate-installable-packages.md)** | `ai_engine` and `gis` are separate installable packages, not backend subpackages | Accepted |
| **[ADR-002](ADR-002-abstract-the-imagery-provider.md)** | Imagery is abstracted behind `ImageryProvider`; the default is keyless Esri; **Google Earth is structurally excluded** | Accepted — **client legal constraint** |
| **[ADR-003](ADR-003-classical-cv-default.md)** | Classical CV is the default path; deep models are optional plugins that degrade gracefully | Accepted — ★ **subject DEFERRED in this build; L1 suspended** |
| **[ADR-004](ADR-004-the-georeferencing-boundary.md)** | `ai_engine` ends at pixels; `gis` is the only birthplace of lat/lon | Accepted |
| **[ADR-005](ADR-005-celery-async-api-never-does-cv.md)** | Celery + Redis for async; the API never performs CV | Accepted |
| **[ADR-006](ADR-006-confidence-gating.md)** | Refuse rather than answer wrongly; confidence is never invented | Accepted — ★ **amended by ADR-015: manual confidence is surveyor-declared** |
| **[ADR-008](ADR-008-postgis-geography-4326.md)** | PostgreSQL + PostGIS with `geography(*, 4326)`; PostGIS is a real dependency | Accepted |
| **[ADR-010](ADR-010-tile-proxy.md)** | The tile proxy lives on the backend; provider keys never reach the browser | Accepted — ★ **amended by `CONTRACT.md` §7.2: the proxy is now the default for EVERY provider** |
| **[ADR-013](ADR-013-react-query-server-zustand-ui.md)** | Server state in React Query, UI state in Zustand, and never both | Accepted |
| **[ADR-014](ADR-014-landmarks-are-user-marked.md)** | Landmarks are user-marked; automatic detection is at most a hint layer | Accepted — ★ **elevated by ADR-015** |
| **★ [ADR-015](ADR-015-defer-the-automatic-matching-engine.md)** | **Defer the automatic matching engine; ship manual GCP surveying** | **Accepted — the ruling that defines this build** |

**Indexed in `00-overview.md` §7, not expanded here:** ADR-007 (object storage behind `ObjectStorage`,
local default) · ADR-009 (GDAL/rasterio behind an adapter — `gis/rasterio_shim.py` in the contract) ·
ADR-011 (migrations are explicit; auto-migrate is dev-only) · ADR-012 (a search prior is required;
global blind search is not offered — **moot in this build, since matching is deferred**).

---

## Where to start

**If you read one, read [ADR-015](ADR-015-defer-the-automatic-matching-engine.md).** It is why this
repository contains an elaborate, fully-specified matching engine that raises `NotImplementedDeferred`,
and why the product you can actually run is a manual surveying tool. Everything in
[`TRACEABILITY.md`](../TRACEABILITY.md) follows from it.

**If you are about to enable a keyed imagery provider**, read
[ADR-002](ADR-002-abstract-the-imagery-provider.md) and then
[`docs/legal/imagery-terms.md`](../../legal/imagery-terms.md). That is a compliance obligation, not a
formality.

**If you are about to touch a coordinate**, read [ADR-004](ADR-004-the-georeferencing-boundary.md).
Most bugs in this system will be a frame confusion.

---

## Writing a new one

1. Number it next in sequence (ADR-016…). **Never renumber an existing ADR** — `00-overview.md`,
   `CONTRACT.md` and these files cross-reference by number.
2. Filename: `ADR-0NN-kebab-case-decision.md`. The title is the *decision*, in the imperative or as a
   statement of fact — not the topic. "Defer the automatic matching engine", not "Matching".
3. Sections: **Status · Context · Decision · Rationale · Consequences (positive AND negative, honestly)
   · Alternatives considered (each with *why rejected*) · Related.**
4. **Supersede rather than edit.** If a decision is reversed, the old ADR gets a status banner pointing
   at the new one and keeps its text. The record of what we believed and why is the point; a rewritten
   ADR is a lost lesson.
5. If it amends a contract or scope ruling, say so **at the top**, and say **which document wins**.
6. Add the row to the table above **and** to `TRACEABILITY.md` if it changes what is delivered.
