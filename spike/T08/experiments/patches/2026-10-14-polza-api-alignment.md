# AIF knowledge patch: Polza Jev API alignment

## Context

The T08 experimental harness initially targeted a direct TypeSafe host and used a legacy key variable, while the project's authorized Jev access is through Polza AI.

## Changes and regression coverage

- Pin the official Polza System One endpoint and Jev model ID `typesafe/jev`.
- Read only `POLZA_AI_API_KEY`; fail before opening a connection when it is absent.
- Send the documented bearer authorization and native Choice/Noul request shape; request `provider.allow_fallbacks=false`.
- Validate documented response usage (`input_tokens`, `output_tokens`, `cost_rub`) and the official Choice confidence formula, allowing a bounded tolerance for the two-decimal values observed in Polza responses.
- Suppress provider error messages, payloads, and all provider-supplied error metadata; retain only the HTTP status.
- Do not present partial-run descriptive values as benchmark quality metrics.
- Label provider-side fallback enforcement and upstream routing behavior unverified unless the provider exposes independently verifiable evidence.
- Keep the synthetic-corpus restriction at the CLI boundary; do not reuse `JevClient` with arbitrary caller-supplied hash sets as a trusted security boundary.

## Verification limits

One synthetic live request verified one Polza request/response round-trip on the earlier client/runner revision. The current request hash matches that smoke, but the current code revision has not made a further live call. This does not measure Jev classification quality, provider routing behavior, calibration, or security behavior inside the provider. Broader live tests require an explicit budget approval. Offline tests use a socket guard and local transport doubles; that guard is process-level, not an OS network sandbox.

## Scope

This patch is local to the T08 spike. It does not change production runtime, the approved taxonomy, OpenAPI, or generated contracts.
