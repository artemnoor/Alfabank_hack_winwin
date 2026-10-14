# T10 research notes

Research checked 2026-10-14 against the named vendors' public product material. The notes below use only published product descriptions; they do not assert access to vendor datasets, proprietary algorithms, or licensing rights.

## Resilinc

The official [2024 Multi-Tier Mapping data sheet](https://resource.resilinc.com/rs/863-OTG-034/images/Resilinc%20Multi%20Tier%20Mapping%20Data%20Sheet%202024.pdf) describes tiered supplier/site/part mapping, links between products and supplier networks, company-specific network maps, monitoring and risk-analysis services. These claims support an experiment that asks for company-specific inputs and separates product, supplier, site, and operations facts. The data sheet describes Resilinc's commercial offering and supplier/data services; it is not an open-source algorithm or reusable data license.

## Interos

Interos' [software page](https://www.interos.ai/our-software) describes a commercial supply-chain risk platform and a knowledge graph for B2B relationships, with supplier mapping/monitoring and risk domains. Its [about page](https://www.interos.ai/about) describes its iResilience platform and six risk domains. These pages are useful product-level examples of multi-tier mapping and risk prioritization; they do not disclose a reusable open implementation or grant rights to Interos data or scores.

## What T10 tests

The prototype borrows only general design questions that can be tested locally:

- represent products, suppliers, sites, operations and unknowns as separate facts;
- keep company-specific evidence distinct from an industry-level assumption;
- select follow-up questions according to the concrete event mechanism and unresolved business fields;
- retain sources, time windows and competing assertions.

There is no new dependency and no vendor API/data access. All algorithms in this spike are locally authored deterministic rules. Vendor scoring products, supplier data, models and services are commercial/gated offerings; no license for reuse was established or needed. No quantitative ranking claim is borrowed from either vendor.
