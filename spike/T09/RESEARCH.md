# T09 technology note

Reviewed 14 October 2026 using official project/vendor pages. No external API,
dataset, SDK, or service was called by this spike. Vendor capability and scale
figures below are vendor statements, not independently measured results.

## Existing approaches

### GDELT

GDELT publishes event and knowledge-graph data files and a distinct mentions
table; its project page says GDELT 2.0 processes articles in 65 live-translated
languages and updates every 15 minutes. That makes the event/mention split,
source breadth, time, actors, locations, and multilingual coverage useful
candidate-retrieval ideas. Its own Terms of Use state that released datasets
may be used for academic, commercial, or governmental purposes without a fee,
and that redistribution requires a GDELT citation and link. This is a data
usage grant by the project; it is not an open-source license for a reusable
event-resolution implementation. The source page does not itself settle the
copyright terms of individual publisher article contents.

GDELT should be treated as a broad source of candidate signals, not a
canonical event identity oracle. Its documented data volume, heterogeneous
normalization, and time fields need careful local validation. GDELT calls its
GKG alpha in the cited page and warns the underlying algorithms/data may change.

Official sources:

- [GDELT data and data formats](https://gdeltproject.org/data.html)
- [GDELT Terms of Use](https://gdeltproject.org/about.html)

### Event Registry / NewsAPI.ai

Event Registry defines an event as a collection of one or more articles
reporting the same world event, including coverage in different languages.
Its current API pricing page lists event search, article clustering as
“Events,” duplicate detection, and entity recognition/disambiguation. The
page shows a free account quota and paid token plans, so the API/data service
is a hosted commercial offering with a limited free tier; free access alone
does not establish a commercial-use data license.

The Event Registry Node.js SDK repository is MIT-licensed. That license applies
to this client package, not the hosted API, event clusters, or article data.
The linked vendor Terms page rendered only a JavaScript shell in this review,
so current commercial-use, retention, and redistribution conditions for API
responses remain unresolved. Do not use its service or data until the service
terms and bank egress/data policies are reviewed.

The vendor’s event-cluster concept is directly relevant to T09’s grouping
problem. However, the vendor docs do not expose its clustering internals or
guarantee a false-merge rate. Use it as a conceptual/evaluation benchmark,
not as an assumed ground-truth implementation.

Official sources:

- [Event Registry event definition](https://help.eventregistry.org/what-are-events/)
- [Event Registry / NewsAPI.ai pricing and API features](https://newsapi.ai/plans)
- [Event Registry Node.js SDK and repository license](https://github.com/EventRegistry/event-registry-node-js)
- [Event Registry Terms page](https://newsapi.ai/terms) — content could not be inspected in this review tool

### RavenPack

RavenPack describes a proprietary, commercial news-analytics product that
provides story entity/event tags, event categories, relevance, novelty, impact,
and temporal analytics. The current product page claims a proprietary taxonomy
of more than 7,000 event topics and over 12 million recognized entities. It
advertises trials and premium news content, and publishes no reusable code or
data license on the page. These are vendor-described product features; access,
price, data rights, and processing terms require a separate contract review.

The useful design reference is the separation between article-level extraction
and event-level analytics, with temporal and novelty signals available apart
from raw text similarity. T09 should still retain its own evidence refs and
uncertainty because a vendor score does not prove that a fact is true.

Official source:

- [RavenPack News Analytics](https://www.ravenpack.com/products/edge/data/news-analytics)

## What this prototype uses

The implementation is deliberately independent of those products. It uses
only Python’s standard library plus the project’s existing contract package
and pytest. Candidate retrieval keys exact event taxonomy/version and exact
participant IDs; same-role normalized name similarity only surfaces a review
candidate. A versioned 14-day event-time window is a conservative experiment
setting, not an empirically calibrated threshold. Structured assertion facts,
identity, uncertainty, and explicit lineage then determine `attach`,
`correct`, `merge`, `split`, `create`, or `defer`.

Raw article text is absent from the approved `ResolutionInput` shape used by
this operation. Therefore a title/body similarity baseline, multilingual
embedding model, and LLM candidate comparator were not implemented or
measured. No new dependencies or network access were added. The observed
metrics in `results/metrics-v1.json` are in-sample checks against synthetic,
provisional case expectations, not a comparison against Event Registry,
GDELT, or RavenPack outputs.
