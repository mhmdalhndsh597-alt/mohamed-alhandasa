import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from monitor import Config, collect_snapshot, find_whale_transactions, update_history


class MonitorSafetyTests(unittest.TestCase):
    def config(self, **kwargs):
        values = dict(rpc_url="https://primary", chain_id=1, watch_addresses=(), contract_addresses=(),
                      discord_webhook_url=None, whale_threshold_native=Decimal("100"),
                      explorer_tx_url="https://scan/tx/{tx_hash}", rpc_urls=("https://primary",))
        values.update(kwargs)
        return Config(**values)

    def test_config_has_no_private_key_setting(self):
        self.assertFalse(hasattr(Config, "private_key"))
        self.assertNotIn("PRIVATE_KEY", " ".join(os.environ.keys()))

    @patch("monitor.rpc_call_with_fallback")
    def test_snapshot_is_read_only(self, rpc_call):
        rpc_call.side_effect = [("0x10", "https://primary"), ("0x1", "https://primary")]
        snapshot = collect_snapshot(self.config())
        self.assertFalse(snapshot["transaction_signing"])
        self.assertFalse(snapshot["transaction_submission"])

    @patch("monitor.rpc_call_with_fallback")
    def test_network_mismatch_is_visible(self, rpc_call):
        rpc_call.side_effect = [("0x10", "https://primary"), ("0x89", "https://primary")]
        snapshot = collect_snapshot(self.config())
        self.assertNotEqual(snapshot["chain_id"], snapshot["expected_chain_id"])

    def test_whale_filter_ignores_small_transfers(self):
        transactions = [{"hash": "0xsmall", "from": "0xaaa", "to": "0xbbb", "value": hex(99 * 10**18)},
                        {"hash": "0xwhale", "from": "0xaaa", "to": "0xbbb", "value": hex(101 * 10**18)}]
        alerts = find_whale_transactions(self.config(), transactions, 16)
        self.assertEqual([a["hash"] for a in alerts], ["0xwhale"])

    def test_whale_filter_respects_monitored_addresses(self):
        transactions = [{"hash": "0xother", "from": "0xother", "to": "0xelse", "value": hex(500 * 10**18)},
                        {"hash": "0xwatched", "from": "0xwatched", "to": "0xelse", "value": hex(500 * 10**18)}]
        alerts = find_whale_transactions(self.config(watch_addresses=("0xwatched",)), transactions, 16)
        self.assertEqual([a["hash"] for a in alerts], ["0xwatched"])

    def test_history_returns_24h_baseline_and_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "history.jsonl")
            observed_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"observed_at": observed_at, "block": 1, "tx_count": 1, "native_volume": "100"}) + "\n")
            baseline, change = update_history(path, {"block": 2, "tx_count": 1, "native_volume": "200"})
            self.assertEqual(baseline, Decimal("100"))
            self.assertEqual(change, Decimal("100"))


if __name__ == "__main__":
    unittest.main()
