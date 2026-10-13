"""Validate approved synthetic fixtures and their public operation bindings."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import argparse
from pathlib import Path, PurePosixPath
from typing import Any, get_type_hints

ROOT = Path(__file__).resolve().parents[1]
APPROVED = ROOT / "fixtures" / "approved"
API_SOURCE = ROOT / "apps" / "api" / "src"
CONTRACT_SOURCE = ROOT / "packages" / "contracts" / "src"
for source in (API_SOURCE, CONTRACT_SOURCE):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from alfalab_contracts.models import SCHEMA_TYPES  # noqa: E402
from alfalab_contracts.registry import load_operation_registry, validate_operation_request  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def _canonical_bytes(value: Any) -> bytes:
    """Use canonical-json-v1: UTF-8, sorted keys, compact separators, no NaN."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return _digest_bytes(_canonical_bytes(value))


def _require_non_empty_success_result(
    operation_id: str, expected_kinds_by_case: dict[str, str]
) -> None:
    if not any(
        case_id != "empty" and expected_kind == "result"
        for case_id, expected_kind in expected_kinds_by_case.items()
    ):
        raise ValueError(f"non-empty successful result fixture missing for {operation_id}")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_approved_path(relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or "\\" in relative_path:
        raise ValueError(f"fixture path must be a relative POSIX path: {relative_path!r}")
    resolved = (ROOT / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(APPROVED.resolve()):
        raise ValueError(f"fixture path escapes approved fixtures: {relative_path!r}")
    return resolved


def _operation_bindings() -> dict[str, type]:
    registry, _ = load_operation_registry()
    bindings: dict[str, type] = {}
    for owner in sorted({entry.owner for entry in registry.operations}):
        module = importlib.import_module(f"alfalab.modules.{owner}.public")
        owner_bindings = getattr(module, "OPERATION_BINDINGS", None)
        if not isinstance(owner_bindings, dict):
            raise ValueError(f"{owner}.public must export OPERATION_BINDINGS")
        overlap = bindings.keys() & owner_bindings.keys()
        if overlap:
            raise ValueError(f"operation Protocols are duplicated: {sorted(overlap)}")
        bindings.update(owner_bindings)

    expected_ids = {entry.operation_id for entry in registry.operations}
    if bindings.keys() != expected_ids:
        raise ValueError(
            "public Protocol operation IDs do not match the operation registry: "
            f"missing={sorted(expected_ids - bindings.keys())}, "
            f"extra={sorted(bindings.keys() - expected_ids)}"
        )

    contracts_by_id = {entry.operation_id: entry for entry in registry.operations}
    for operation_id, protocol in bindings.items():
        entry = contracts_by_id[operation_id]
        annotations = get_type_hints(protocol.execute)
        expected_input = SCHEMA_TYPES[entry.input_model]
        expected_output = SCHEMA_TYPES[entry.output_model]
        if annotations.get("payload") is not expected_input:
            raise ValueError(
                f"{operation_id} Protocol payload binding is {annotations.get('payload')!r}; "
                f"expected {entry.input_model}"
            )
        if annotations.get("return") is not expected_output:
            raise ValueError(
                f"{operation_id} Protocol output binding is {annotations.get('return')!r}; "
                f"expected {entry.output_model}"
            )
        if annotations.get("context", object).__name__ != "OperationContext":
            raise ValueError(f"{operation_id} Protocol must accept shared OperationContext")
    return bindings


def _validate_datasets() -> dict[str, dict[str, Any]]:
    index = _read_json(APPROVED / "index.json")
    datasets = index.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != {"radio-export-v1", "steel-buffer-v1"}:
        raise ValueError("approved index must contain radio-export-v1 and steel-buffer-v1")

    resolved: dict[str, dict[str, Any]] = {}
    for dataset_id, indexed in datasets.items():
        manifest_path = _safe_approved_path(indexed["manifest_path"])
        data_path = _safe_approved_path(indexed["data_path"])
        manifest = _read_json(manifest_path)
        data_bytes = data_path.read_bytes()
        data = _read_json(data_path)
        if manifest.get("dataset_id") != dataset_id or manifest.get("version") != "1.0.0":
            raise ValueError(f"dataset identity/version mismatch for {dataset_id}")
        if manifest.get("classification") != "synthetic" or manifest.get("synthetic_only") is not True:
            raise ValueError(f"dataset {dataset_id} is not declared synthetic-only")
        if manifest.get("retention_class") != "approved_fixture":
            raise ValueError(f"dataset {dataset_id} has an unsupported retention class")
        if manifest.get("approval_review_reference") != index.get("approval_review_reference"):
            raise ValueError(f"dataset {dataset_id} references a different content review")
        if data.get("dataset_id") != dataset_id or data.get("version") != manifest.get("version"):
            raise ValueError(f"dataset data identity/version mismatch for {dataset_id}")
        if data.get("classification") != "synthetic" or data.get("synthetic_only") is not True:
            raise ValueError(f"dataset payload {dataset_id} is not synthetic-only")
        snapshots = data.get("snapshots")
        if not isinstance(snapshots, dict) or "baseline" not in snapshots:
            raise ValueError(f"dataset {dataset_id} needs a baseline state snapshot")
        for material in data.get("records", {}).get("materials", []):
            text = material.get("text")
            expected_content_hash = material.get("content_hash")
            if not isinstance(text, str) or expected_content_hash != _digest_bytes(text.encode("utf-8")):
                raise ValueError(f"material content hash mismatch in {dataset_id}")
        for example in data.get("records", {}).get("foreign_scope_examples", []):
            if example.get("sandbox_id") != "foreign-sandbox":
                raise ValueError(f"foreign-scope example is mislabeled in {dataset_id}")
        if _digest_bytes(data_bytes) != manifest.get("hashes", {}).get("data"):
            raise ValueError(f"dataset data hash mismatch for {dataset_id}")
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != indexed.get("manifest_sha256"):
            raise ValueError(f"dataset manifest index hash mismatch for {dataset_id}")
        if hashlib.sha256(data_bytes).hexdigest() != indexed.get("data_sha256"):
            raise ValueError(f"dataset index data hash mismatch for {dataset_id}")
        resolved[dataset_id] = {
            "manifest": manifest,
            "data": data,
            "snapshots": snapshots,
            "manifest_path": indexed["manifest_path"],
            "data_path": indexed["data_path"],
            "data_hash": _digest_bytes(data_bytes),
        }
    return resolved


def validate_fixture_set() -> dict[str, int]:
    """Raise ValueError on drift; return counts for a concise CLI summary."""
    registry, contracts = load_operation_registry()
    registry_path = ROOT / "docs" / "specs" / "framework-v1" / "contracts" / "operations.json"
    registry_hash = _digest_bytes(registry_path.read_bytes())
    index = _read_json(APPROVED / "index.json")
    if index.get("schema") != "alfalab.approved-fixture-index/v1":
        raise ValueError("unsupported approved fixture index schema")
    if index.get("operation_registry_hash") != registry_hash:
        raise ValueError("fixture index is bound to a different operation registry snapshot")

    datasets = _validate_datasets()
    review_path = _safe_approved_path(index["approval_review_reference"])
    review = _read_json(review_path)
    if review.get("decision") != "approved" or review.get("quality_gold_approval") is not False:
        raise ValueError("synthetic review must approve data safety without approving quality gold")

    indexed_files = index.get("files")
    if not isinstance(indexed_files, dict):
        raise ValueError("fixture index must include a file hash map")
    actual_files = {
        path.relative_to(APPROVED).as_posix(): _digest_bytes(path.read_bytes())
        for path in APPROVED.rglob("*")
        if path.is_file() and path.name != "index.json"
    }
    if actual_files != indexed_files:
        missing = sorted(indexed_files.keys() - actual_files.keys())
        unexpected = sorted(actual_files.keys() - indexed_files.keys())
        mismatched = sorted(
            name for name in actual_files.keys() & indexed_files.keys()
            if actual_files[name] != indexed_files[name]
        )
        raise ValueError(
            f"approved fixture file index drift: missing={missing}, unexpected={unexpected}, "
            f"hash_mismatch={mismatched}"
        )

    bindings = _operation_bindings()
    manifests = sorted(
        path
        for entry in registry.operations
        for path in (APPROVED / entry.operation_id).rglob("manifest.json")
        if path.is_file()
    )
    by_operation: dict[str, int] = {}
    cases_by_operation: dict[str, set[str]] = {}
    expected_kinds_by_operation: dict[str, dict[str, str]] = {}
    for path in manifests:
        manifest = _read_json(path)
        operation_id = manifest.get("operation_id")
        if operation_id not in contracts:
            raise ValueError(f"unknown fixture operation id in {path.relative_to(ROOT)}: {operation_id!r}")
        entry = contracts[operation_id].descriptor
        relative_dir = path.relative_to(APPROVED).parts
        if not relative_dir or relative_dir[0] != operation_id:
            raise ValueError(f"fixture path does not match operation ID {operation_id}: {path}")
        if manifest.get("schema") != "alfalab.approved-operation-fixture/v1":
            raise ValueError(f"unsupported operation fixture schema in {path}")
        if manifest.get("version") != "1.0.0":
            raise ValueError(f"unsupported fixture version in {path}")
        if manifest.get("case_id") != path.parent.name:
            raise ValueError(f"case_id does not match fixture directory for {operation_id}")
        if manifest.get("contract_version") != entry.contract_version:
            raise ValueError(f"contract version mismatch for {operation_id}")
        if manifest.get("schema_hash") != entry.schema_hash:
            raise ValueError(f"operation schema hash mismatch for {operation_id}")
        if manifest.get("request_model") != entry.request_model or manifest.get("response_model") != entry.response_model:
            raise ValueError(f"request/response consumer binding mismatch for {operation_id}")

        request = manifest.get("request")
        expected = manifest.get("expected_result")
        hashes = manifest.get("hashes")
        if not isinstance(request, dict) or not isinstance(expected, dict) or not isinstance(hashes, dict):
            raise ValueError(f"fixture request/result/hash sections must be objects for {operation_id}")
        if hashes.get("request") != canonical_hash(request):
            raise ValueError(f"canonical request hash mismatch for {operation_id}/{path.parent.name}")
        if hashes.get("expected_result") != canonical_hash(expected):
            raise ValueError(f"canonical expected-result hash mismatch for {operation_id}/{path.parent.name}")
        if request.get("contract_version") != entry.contract_version:
            raise ValueError(f"request contract version mismatch for {operation_id}")
        untrusted_envelope_fields = {
            "tenant_id",
            "environment",
            "actor_id",
            "role",
            "permissions",
            "principal",
            "dsn",
            "database_url",
            "provider_url",
        }
        present_untrusted = untrusted_envelope_fields & request.keys()
        if present_untrusted:
            raise ValueError(f"client request contains server-trusted envelope fields: {sorted(present_untrusted)}")
        if request.get("implementation", {}).get("id") != "mock.baseline":
            raise ValueError(f"fixture is not bound to the required mock.baseline for {operation_id}")
        if request.get("data_declaration") != "synthetic":
            raise ValueError(f"fixture request must declare synthetic input for {operation_id}")
        if request.get("execution", {}).get("analytical_time") != manifest.get("analytical_time"):
            raise ValueError(f"fixture analytical_time is not bound to the request for {operation_id}")
        if request.get("execution", {}).get("random_seed") != manifest.get("seed"):
            raise ValueError(f"fixture seed is not bound to the request for {operation_id}")
        trusted_context = manifest.get("trusted_context")
        if not isinstance(trusted_context, dict):
            raise ValueError(f"trusted server context is missing for {operation_id}")
        if trusted_context.get("selected_sandbox") != request.get("sandbox_id"):
            raise ValueError(f"selected sandbox is not bound to the request for {operation_id}")
        allowed_sandboxes = trusted_context.get("allowed_sandboxes")
        if not isinstance(allowed_sandboxes, list) or request.get("sandbox_id") not in allowed_sandboxes:
            raise ValueError(f"request sandbox is not authorized by trusted context for {operation_id}")
        if not all(trusted_context.get(name) for name in ("actor_id", "tenant_id", "role", "source")):
            raise ValueError(f"trusted principal identity is incomplete for {operation_id}")
        if not isinstance(trusted_context.get("permissions"), list):
            raise ValueError(f"trusted principal permissions are not explicit for {operation_id}")
        deterministic_input = {
            "request": request,
            "trusted_context": trusted_context,
            "before_state": manifest.get("before_state", []),
            "analytical_time": manifest.get("analytical_time"),
            "seed": manifest.get("seed"),
        }
        if hashes.get("deterministic_input") != canonical_hash(deterministic_input):
            raise ValueError(f"deterministic input hash mismatch for {operation_id}/{manifest['case_id']}")
        if manifest.get("classification") != "synthetic":
            raise ValueError(f"fixture classification must be synthetic for {operation_id}")
        if manifest.get("cassette_refs") != []:
            raise ValueError(f"T02 fixtures must not include live external cassettes: {operation_id}")
        if manifest.get("approval_review_reference") != index["approval_review_reference"]:
            raise ValueError(f"fixture approval review reference mismatch for {operation_id}")

        for state_ref in manifest.get("before_state", []):
            dataset = datasets.get(state_ref.get("dataset_id"))
            if dataset is None or state_ref.get("version") != dataset["manifest"]["version"]:
                raise ValueError(f"unresolved before-state dataset reference for {operation_id}")
            if state_ref.get("data_path") != dataset["data_path"] or state_ref.get("data_hash") != dataset["data_hash"]:
                raise ValueError(f"before-state path/hash mismatch for {operation_id}")
            if state_ref.get("snapshot_id") not in dataset["snapshots"]:
                raise ValueError(f"unknown before-state snapshot for {operation_id}")

        expected_kind = expected.get("kind")
        if expected_kind == "schema_rejection":
            try:
                validate_operation_request(contracts[operation_id], _canonical_bytes(request))
            except ValidationError:
                pass
            else:
                raise ValueError(f"schema_rejection fixture request unexpectedly validates: {operation_id}")
        elif expected_kind == "result":
            try:
                validate_operation_request(contracts[operation_id], _canonical_bytes(request))
            except (ValidationError, ValueError) as exc:
                raise ValueError(f"result fixture request does not validate: {operation_id}: {exc}") from exc
            if expected.get("response_schema_id") != entry.response_model:
                raise ValueError(f"result rules bind to wrong response schema for {operation_id}")
        elif expected_kind == "safe_error":
            try:
                validate_operation_request(contracts[operation_id], _canonical_bytes(request))
            except (ValidationError, ValueError) as exc:
                raise ValueError(f"safe_error fixture request must be wire-valid: {operation_id}: {exc}") from exc
        else:
            raise ValueError(f"unknown expected_result.kind {expected_kind!r} for {operation_id}")
        if not expected.get("rules"):
            raise ValueError(f"expected result rules are empty for {operation_id}")
        if not expected.get("output_hash_rule"):
            raise ValueError(f"output hash rule is missing for {operation_id}")
        if expected["output_hash_rule"].get("algorithm") != "sha256" or expected["output_hash_rule"].get("canonicalization") != "canonical-json-v1":
            raise ValueError(f"unsupported output hash rule for {operation_id}")

        request_sequence = manifest.get("request_sequence")
        if request_sequence is not None:
            if not isinstance(request_sequence, list) or len(request_sequence) < 2:
                raise ValueError(f"request_sequence must contain at least two requests for {operation_id}")
            if hashes.get("request_sequence") != canonical_hash(request_sequence):
                raise ValueError(f"request sequence hash mismatch for {operation_id}/{manifest['case_id']}")
            for sequence_request in request_sequence:
                try:
                    validate_operation_request(contracts[operation_id], _canonical_bytes(sequence_request))
                except (ValidationError, ValueError) as exc:
                    raise ValueError(f"request sequence item does not validate for {operation_id}: {exc}") from exc
        if manifest["case_id"] == "duplicate":
            if not request_sequence or canonical_hash(request_sequence[0]) != canonical_hash(request_sequence[1]):
                raise ValueError(f"duplicate fixture must replay the exact same request for {operation_id}")
        if manifest["case_id"] == "conflict":
            if not request_sequence or len(request_sequence) != 2:
                raise ValueError(f"conflict fixture needs original and changed requests for {operation_id}")
            first, second = request_sequence
            if first.get("idempotency_key") != second.get("idempotency_key"):
                raise ValueError(f"conflict fixture must reuse the command key for {operation_id}")
            if canonical_hash(first) == canonical_hash(second):
                raise ValueError(f"conflict fixture requests must differ for {operation_id}")
            changed_input = {
                "request": second,
                "trusted_context": trusted_context,
                "before_state": manifest.get("before_state", []),
                "analytical_time": manifest.get("analytical_time"),
                "seed": manifest.get("seed"),
            }
            if hashes.get("deterministic_input") != canonical_hash(changed_input):
                raise ValueError(f"conflict deterministic input hash mismatch for {operation_id}")
        if manifest["case_id"] == "restored-state" and manifest.get("restore_before_each_call") is not True:
            raise ValueError(f"restored-state fixture must request state restoration for {operation_id}")
        if manifest["case_id"] == "forbidden":
            if expected_kind != "safe_error" or not any(
                ref.get("snapshot_id") == "foreign-scope" for ref in manifest.get("before_state", [])
            ):
                raise ValueError(f"forbidden read fixture must target foreign-scope state for {operation_id}")

        for state_ref in manifest.get("before_state", []):
            if state_ref.get("classification") != "synthetic":
                raise ValueError(f"before-state classification is not synthetic for {operation_id}")
        by_operation[operation_id] = by_operation.get(operation_id, 0) + 1
        cases_by_operation.setdefault(operation_id, set()).add(manifest["case_id"])
        expected_kinds_by_operation.setdefault(operation_id, {})[
            manifest["case_id"]
        ] = expected_kind

    expected_ids = set(contracts)
    if by_operation.keys() != expected_ids:
        raise ValueError(
            "every mock operation requires at least one reproducible fixture: "
            f"missing={sorted(expected_ids - by_operation.keys())}, "
            f"unexpected={sorted(by_operation.keys() - expected_ids)}"
        )
    for operation_id, entry in ((item.operation_id, item) for item in registry.operations):
        required = {"empty", "invalid-request", "controlled-failure"}
        if entry.kind == "command":
            required |= {"duplicate", "conflict", "restored-state"}
        if entry.kind == "read":
            required |= {"missing", "forbidden"}
        missing_cases = required - cases_by_operation[operation_id]
        if missing_cases:
            raise ValueError(f"required fixture cases missing for {operation_id}: {sorted(missing_cases)}")
        _require_non_empty_success_result(
            operation_id, expected_kinds_by_operation.get(operation_id, {})
        )
    return {
        "operations": len(by_operation),
        "fixtures": len(manifests),
        "datasets": len(datasets),
        "bindings": len(bindings),
    }


def rebuild_index() -> None:
    """Refresh byte fingerprints only; this does not approve fixture content."""
    old_index_path = APPROVED / "index.json"
    old_index = _read_json(old_index_path) if old_index_path.is_file() else {}
    registry_path = ROOT / "docs" / "specs" / "framework-v1" / "contracts" / "operations.json"
    datasets: dict[str, dict[str, str]] = {}
    for dataset_id in ("radio-export-v1", "steel-buffer-v1"):
        directory = APPROVED / "datasets" / dataset_id
        manifest_path = directory / "manifest.json"
        data_path = directory / "data.json"
        datasets[dataset_id] = {
            "manifest_path": f"fixtures/approved/datasets/{dataset_id}/manifest.json",
            "data_path": f"fixtures/approved/datasets/{dataset_id}/data.json",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        }
    files = {
        path.relative_to(APPROVED).as_posix(): _digest_bytes(path.read_bytes())
        for path in APPROVED.rglob("*")
        if path.is_file() and path.name != "index.json"
    }
    index = {
        "schema": "alfalab.approved-fixture-index/v1",
        "version": "1.0.0",
        "operation_registry_hash": _digest_bytes(registry_path.read_bytes()),
        "approval_review_reference": old_index.get(
            "approval_review_reference", "fixtures/approved/review/t02-synthetic-content-review.json"
        ),
        "datasets": datasets,
        "files": files,
    }
    _write_json(old_index_path, index)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="refresh byte hashes only; this does not approve changed fixture content",
    )
    args = parser.parse_args(argv)
    if args.reindex:
        rebuild_index()
        print("Refreshed fixture byte hashes only; content and quality approval still require code review.")
        return 0
    counts = validate_fixture_set()
    print(
        "Validated approved synthetic fixtures: "
        f"{counts['fixtures']} operation cases across {counts['operations']} operations, "
        f"{counts['datasets']} datasets, {counts['bindings']} typed consumer bindings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
