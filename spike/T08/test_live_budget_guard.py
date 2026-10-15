from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import run_spike
from jev_spike import DEFAULT_MODEL, SPIKE_DIR, load_verified_inputs


class LiveBudgetGuardTests(unittest.TestCase):
    def test_exhausted_ledger_prevents_classification_without_network(self) -> None:
        taxonomy, corpus, cases = load_verified_inputs()
        with tempfile.TemporaryDirectory(dir=SPIKE_DIR) as temporary:
            ledger_path = Path(temporary) / "live-attempts.json"
            attempts = [
                {
                    "case_id": f"unrelated-completed-{index}",
                    "request_sha256": hashlib.sha256(
                        f"attempt-{index}".encode()
                    ).hexdigest(),
                    "timestamp_utc": "2026-10-14T00:00:00Z",
                    "record_type": "historical_recorded_attempt",
                }
                for index in range(50)
            ]
            ledger_path.write_text(
                json.dumps({"schema_version": 1, "attempts": attempts}),
                encoding="utf-8",
            )
            client_instances = []

            class NoNetworkClient:
                def __init__(self, *_: object, **__: object) -> None:
                    self.classify_calls = 0
                    client_instances.append(self)

                def classify(self, _request: object) -> dict[str, object]:
                    self.classify_calls += 1
                    raise AssertionError("over-budget classify must never run")

            args = Namespace(
                max_calls=1,
                model=DEFAULT_MODEL,
                output=str(Path(temporary) / "pilot-report.json"),
                ledger_path=str(ledger_path),
            )
            with (
                patch.object(run_spike, "JevClient", NoNetworkClient),
                patch.dict(os.environ, {"POLZA_AI_API_KEY": "offline-test-only"}),
            ):
                report = run_spike.run_live(args, taxonomy, corpus, cases)

        self.assertEqual(len(client_instances), 1)
        self.assertEqual(client_instances[0].classify_calls, 0)
        self.assertEqual(report["attempted_calls"], 0)
        self.assertEqual(report["successful_calls"], 0)
        self.assertEqual(
            report["quality_metrics_status"], "NOT_MEASURED_INCOMPLETE_RUN"
        )
        self.assertEqual(
            report["failures"][0]["error"], "cumulative_live_call_limit_reached"
        )


if __name__ == "__main__":
    unittest.main()
