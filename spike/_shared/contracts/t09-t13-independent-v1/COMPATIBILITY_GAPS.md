# Compatibility gaps (recorded, not patched)

This version keeps all source grouping and test owner policy local to `spike/_shared`. No normative DTO or OpenAPI file was changed.

- `#/components/schemas/RawMaterial/properties` and `#/components/schemas/Provenance/properties` have no `publisher_root_id` or `syndication_group_id` fields. The corpus stores `publisher_root_id` and `syndication_group_id` in local synthetic source metadata.
- `#/components/schemas/Provenance/properties` has no trusted-owner-policy reference. The fixture corpus stores a local named test policy and authorized statement IDs; this is not a production authorization or threshold.
- `#/components/schemas/EvidenceRecord/properties` stores anchor verification and a source-reliability label, but does not express independent-source grouping or a claim-truth decision. T11 must not treat `verified_anchor` as confirmation of the claim.
- `#/components/schemas/GraphEdge/properties` has no explicit negative-polarity field. The T12 negative declaration is preserved as a sourced experimental Statement input and must not be encoded as a positive edge or inferred from a missing edge.
- `#/components/schemas/Statement/properties/predicate` accepts a versioned code reference, but the frozen schema checks only the code-reference shape and contains no owner-approved semantic mapping for experimental predicate codes `sources_from_country`, `does_not_source_from_country`, or `depends_on_country`. Their graph interpretation requires ontology/contract-owner review.

These are explicit constraints for the spike; resolving them would require a separately approved contract decision.
