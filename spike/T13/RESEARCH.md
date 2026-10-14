# T13 research note: matching, impact and recommendations

Status: desk research from primary paper/vendor sources. Pages were reviewed on 2026-10-14. Statements below are either directly described by the cited source or explicitly marked as an inference. Vendor claims have not been independently verified. No external data or service was used by the T13 prototype.

## SHIELD

The paper describes SHIELD as an EV-battery supply-chain disruption system combining domain-informed schema induction, fine-tuned event extraction, multidimensional schema matching, and graph convolutional prediction with logical constraints. Its abstract reports evaluation on 12,070 paragraphs from 365 sources. These are author-reported results for that domain and corpus, not a general guarantee for bank credit-impact analysis. [ACL Anthology paper](https://aclanthology.org/2024.emnlp-industry.24/) · [official paper PDF](https://aclanthology.org/2024.emnlp-industry.24.pdf)

The paper's authors link a public implementation repository. GitHub marks the repository as MIT licensed and the root `LICENSE` contains the MIT grant for the software. The repository also contains a `Dataset` directory, but I found no separate dataset license or clear rights statement in the repository materials reviewed. Do not assume the source-code license grants reuse rights for every included dataset or third-party material. [MFI repository](https://github.com/F1y1113/MFI) · [repository license](https://github.com/F1y1113/MFI/blob/main/LICENSE) · [Dataset directory](https://github.com/F1y1113/MFI/tree/main/Dataset)

**T13 inference:** SHIELD supports testing an LLM-assisted mechanism proposal against a typed supply-chain graph and explicit logical constraints. Its GCN/prediction implementation is not copied or used here. Our Approach C is only a controlled-response adapter and does not reproduce SHIELD or test an LLM. The paper's positive evaluation claims are not independent evidence that this spike is accurate.

## NRAS

The EMNLP Industry Track paper describes NRAS as a deployed credit-risk news alerting system. The authors report more than 2,700 credit-relevant alerts and estimated precision of 77%. The paper describes LLM-enabled high-precision content filtering, targeted sentiment and M&A classification, and a dynamic news-volume threshold based on a rolling 90-day series with deduplication and alert-volume controls. These deployment and performance figures are author-reported. [ACL Anthology paper](https://aclanthology.org/2024.emnlp-industry.32/) · [official paper PDF](https://aclanthology.org/2024.emnlp-industry.32.pdf)

**T13 inference:** NRAS is a useful credit-news workflow reference for prioritization, deduplication, and human review. Its paper centers on targeted sentiment/M&A and news-volume alerting, not on proving a supplier-to-company causal path. It is a reference design, not an accessible implementation dependency for this spike; no NRAS code or service was used.

## Resilinc

Resilinc's official Multi-Tier Mapping product sheet describes a hybrid approach combining AI mapping and supplier-validated data, with supplier/site/part visibility across tiers. Its official EventWatchAI product sheet describes the company's event monitoring product. This is product/vendor material, not an independently audited algorithm or benchmark. Product access is offered commercially; no open-source implementation or public algorithm license was identified in the reviewed materials. [Multi-Tier Mapping product sheet](https://resource.resilinc.com/rs/863-OTG-034/images/Resilinc%20Multi%20Tier%20Mapping%20Data%20Sheet%202024.pdf) · [EventWatchAI product sheet](https://resource.resilinc.com/rs/863-OTG-034/images/Resilinc%20EventWatch%20AI%20Data%20Sheet%202024.pdf)

**T13 inference:** The useful transferable practice is to distinguish machine-discovered candidate links from supplier-validated relationships and preserve that distinction when propagating an event. T13 instead uses only explicitly supplied graph edges and makes no vendor-data claims.

## Everstream Analytics

Everstream's official product pages describe a commercial supply-chain risk platform with network mapping/digital-twin views, event monitoring and alerting, supplier risk assessment, sub-tier visibility, and insights-to-action workflows. Everstream also describes combining its proprietary data with AI/analytics and human expertise. Those are vendor descriptions and claims; no public algorithm or source-code license was found in the reviewed product materials. [Everstream platform](https://www.everstream.ai/solutions/everstream-platform/) · [Global Monitoring and Alerting](https://www.everstream.ai/platform/global-monitoring/) · [Sub-tier visibility](https://www.everstream.ai/platform/platform-sub-tier-visibility/)

**T13 inference:** Connecting detected events to an organization's own sites, materials, suppliers, and routes is a practical framing for graph-scoped matching. T13 does this only over the provided graph snapshot and exposes partial/stale graph limitations; it does not use Everstream services or data.

## What the spike tests

- **Matching:** deterministic search over the explicitly supplied, directed graph edges. `strict`, `balanced`, and `broad` select progressively less certain edge statuses, bounded by documented depth. Broad mode preserves hypothetical/inferred status as potential and never creates an absent edge.
- **Approach C:** a model-shaped response contract whose target, directed path, evidence references, and optional explicit quantity are checked against the input. The runner supplies deterministic controlled fixtures; live model quality is **NOT MEASURED**.
- **Approach D:** deterministic rules require an eligible current event, a matching graph path, present evidence with verified anchors, compatible edge status, and no stale graph. Event/edge `confirmed` status is consumed as supplied; this spike does not claim that a verified anchor proves truth or independently establish a trusted-owner policy.
- **Recommendations:** informational actions are intersected with the request catalog and a small local safety allowlist, filtered by audience, and linked to assessment evidence. They are proposed only; no action is executed.
- **Financial scenarios:** a standalone arithmetic check covers explicitly supplied assumptions. The normative `ImpactInput` has no slot for this local scenario object, so the contract-shaped assessment leaves `FinancialScenario.quantity=null`; only the offline experiment reports the gross procurement exposure scenario.

No third-party dependencies, models, vendor APIs, proprietary data, or network calls were added or invoked.
