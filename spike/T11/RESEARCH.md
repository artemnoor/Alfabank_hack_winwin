# T11 research: provenance and source trust

Research checked against official sources on 2026-10-14. Vendor descriptions below are vendor claims; they are not independent measurements.

## W3C PROV-O

The [PROV-O Recommendation](https://www.w3.org/TR/prov-o/) is a W3C Recommendation that expresses the PROV Data Model in OWL 2 and provides classes and properties for interoperable provenance descriptions. Its core vocabulary distinguishes `Entity`, `Activity`, and `Agent`; relations include `wasGeneratedBy`, `wasDerivedFrom`, `wasAttributedTo`, `used`, `hadPrimarySource`, `wasQuotedFrom`, and `wasRevisionOf`, along with temporal and invalidation properties. The spec also links to a machine-readable OWL encoding.

**Useful for T11:** represent a source artifact, an extraction/annotation activity, its responsible agent, and the evidence/claim derived from that activity. The vocabulary can make provenance chains explicit and leave room for application-specific terms.

**Limit:** PROV-O describes provenance relations; it does not decide whether a publisher's assertion is true. This is an inference from the standard's stated scope and vocabulary.

**License/access:** the Recommendation and ontology are publicly accessible. W3C's [document license](https://www.w3.org/copyright/document-license-2023/) governs copying document material with attribution and a link; W3C distinguishes this from its [software licenses](https://www.w3.org/copyright/). The ontology is a vocabulary, not a drop-in factual verification engine. This spike uses no copied ontology file and adds no PROV dependency.

## Diffbot

Diffbot's official [Origin documentation](https://www.diffbot.com/docs/dql/concepts/origin) defines an origin as a public web location where entity data was extracted or an information source used to infer a fact; it says a fact can be compiled from one or more unique origins. The [Knowledge Graph product page](https://www.diffbot.com/products/knowledge-graph) describes querying and enhancing data against its Knowledge Graph.

**Useful for T11:** keep per-fact origin references rather than one source list attached to a whole entity. Distinguish an extracted fact from one inferred using a source. An origin count alone does not prove independent corroboration; that limitation is an inference from the origin documentation, which does not define independence or truth criteria.

**License/access:** the Knowledge Graph is an API/data service requiring an account token; the official [API authentication](https://www.diffbot.com/docs/authentication) and [plans/pricing page](https://www.diffbot.com/pricing) describe account plans and credits. The public docs do not make the graph itself an open dataset. Diffbot does publish API client software: its current [Python client repository](https://github.com/diffbot/diffbot-python) and [TypeScript client repository](https://github.com/diffbot/diffbot-typescript) identify MIT licenses. Those licenses cover the client code, not the hosted graph, its data, or API usage terms. The Python README notes the old `diffbot-python` package is legacy and the package name is now `diffbot`. The spike uses neither SDK nor service.

## Everstream Analytics

Everstream's official [FAQ](https://www.everstream.ai/company/everstream-analytics-frequently-asked-questions-faqs/) describes AI-assisted network mapping and event monitoring combined with human analyst validation. It also says its platform uses proprietary data sources and filters duplicated/irrelevant alerts against a company's supply-chain model. Its [product overview](https://www.everstream.ai/why-everstream-analytics/) describes connecting events to suppliers, sites, materials, and shipments.

These are **vendor claims**. They suggest two useful process ideas to test: deduplicate at the underlying origin, then check event relevance against explicit company dependencies; retain human review where the source assertion or exposure path is uncertain. The public pages do not expose a reproducible trust rubric, source-independence rule, calibration data, or confidence threshold. No such rule is inferred or copied into T11.

**License/access:** the public [Terms and Conditions](https://www.everstream.ai/terms-and-conditions/) limits website material to informational/non-commercial use, while stating that services may be subject to local terms and directing visitors to obtain those terms from Everstream. The reviewed sources do not publish an open-source implementation or a software license for the platform. This is a bounded finding about the reviewed public official pages, not a claim that no private or customer-specific terms exist. No Everstream service or data was used.

## T11 design choices derived from the research

- Preserve source artifact, exact version, locator, assertion annotation provenance, and publisher-root identity as separate references.
- Recompute quote/source integrity from a pinned snapshot; hashes verify content identity only.
- Treat assertion relations as explicit inputs to this prototype. Do not mistake extraction or source reliability for truth.
- Count distinct roots only in a specifically named owner policy; never assign a generic numeric reliability score.
- Keep `unknown`, `unverified`, `historical`, and `disputed` distinct and auditable.
