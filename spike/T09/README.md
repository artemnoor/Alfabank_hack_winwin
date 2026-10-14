# T09 — event resolution spike

T09 takes already materialized `EventMention` objects, an `EventSnapshot`, and
`EvidenceRecord` objects. It proposes a resolution plan in the Framework v1
`ResolutionOutput` shape. It does not extract mentions, write an event store,
or apply a proposal.

The prototype performs deterministic candidate retrieval, then chooses one of
`create`, `attach`, `correct`, `merge`, `split`, or `defer`. A near-matching name
can bring an event into the review candidate set, but cannot establish identity
or trigger a merge. Different IDs, missing dates, hypothetical statements, and
unresolved conflicts remain explicit uncertainty.

## Run it

From the repository root in the configured Python 3.12 environment:

```powershell
$env:PYTHONPATH = 'spike/T09/src;packages/contracts/src'
python -B -m pytest -q -p no:cacheprovider spike/T09/tests
python -B spike/T09/experiments/evaluate.py
```

The input suite is under `fixtures/scenarios-v1.json`. Its expected properties
are provisional and have not been approved as a gold set.

The fixture builder pins shared dataset version `1.0.1` and its canonical
hash by default. To test another immutable shared version, set all four values
before regenerating the local fixture set: `T09_SHARED_DATASET_VERSION`,
`T09_SHARED_DATASET_HASH`, `T09_SHARED_DATASET_DIR`, and
`T09_SHARED_FIXTURES_DIR`. Both paths must remain under `spike/_shared/`; the
version and hashes are checked when loading. For example, the coordinator can
point these variables at the reviewed `1.0.1` directories and hash, then run
`python -B -m t09_events.scenarios` to materialize the T09 fixture set for that
pin. The code does not silently follow a moving `latest` dataset.

## Algorithm outline

1. Validate the input with the project `ResolutionInput` model.
2. Retrieve only same-version, same-code event types. Exact participant IDs,
   same-role near names, and compatible time rank candidates. Name similarity
   is retrieval-only. Candidate ordering is deterministic.
3. Defer when identity depends on similar names, actor/object roles conflict,
   a statement is hypothetical/disputed/disproved/unknown, time scopes conflict,
   or candidates cannot be separated.
4. Attach only when the incoming structured assertion is already represented
   in the candidate record. Entity IDs define identity; display-name changes do
   not change that comparison. Certainty and provenance do not redefine the
   factual event key, but conflicting certainty/provenance blocks duplicate
   merge or is preserved as a separate assertion variant in a successor.
5. Correct only when a recognized field-specific fact resolves a matching
   missing datum. The predecessor remains linked and every unrelated missing
   datum is carried forward. An unrelated new entity cannot resolve a supplier
   or facility gap.
6. Merge only duplicate records with identical event type, entity IDs, facts,
   certainty, provenance, and compatible time scope, when an incoming mention
   independently supports them. The successor retains distinct source/status
   variants instead of collapsing them by factual signature.
7. Split only a single existing aggregate that records all source mentions
   and contains exactly their combined assertion facts, including same-type
   events with distinct facility IDs. A source article with multiple events
   and no aggregate is represented as separate creates.
8. Create a separate record when no compatible existing candidate remains.
   Source evidence does not upgrade statement certainty.

Every decision carries evidence references available in the explicitly passed
input. The proposal is immutable output; `Events.apply` remains the owner's
responsibility.

## Contracts and boundaries

The prototype reads the approved `ResolutionInput` DTO and emits
`ResolutionOutput`; it does not add or change contracts. The request's `policy`
field is an opaque `VersionedRef`; Framework v1 supplies no threshold payload or
policy resolver here. Local `ResolutionPolicy` thresholds are experimental
runtime configuration and are fingerprinted, not resolved from that reference.
See the compatibility gap in [LIMITATIONS.md](LIMITATIONS.md); this behavior is
not integration-ready until an approved owner binds the reference to policy
parameters. It follows the `Events.propose_resolution` semantics, including the target/successor counts
for each decision, one decision or unresolved entry per input mention, and
acyclic proposal lineage. Only materialized operation payloads are modeled;
there is no HTTP wrapper, database, global configuration, or network client.
The independent baseline findings and their reproductions are preserved in
[results/INDEPENDENT_REVIEW.md](results/INDEPENDENT_REVIEW.md).

See [PLAN.md](PLAN.md), [TEST_REPORT.md](TEST_REPORT.md), [RESEARCH.md](RESEARCH.md),
and [LIMITATIONS.md](LIMITATIONS.md) for scope, results, and known gaps.
