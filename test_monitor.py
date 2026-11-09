import os
import unittest
from unittest.mock import patch

from monitor import Config, collect_snapshot


class MonitorSafetyTests(unittest.TestCase):
    def test_config_has_no_private_key_setting(self):
        self.assertFalse(hasattr(Config, "private_key"))
        self.assertNotIn("PRIVATE_KEY", " ".join(os.environ.keys()))

    @patch("monitor.rpc_call")
    def test_snapshot_is_read_only(self, rpc_call):
        rpc_call.side_effect = ["0x10", "0x1"]
        with patch.dict(os.environ, {"RPC_URL": "https://example.invalid", "CHAIN_ID": "1"}, clear=False):
            snapshot = collect_snapshot(Config.from_env())
        self.assertFalse(snapshot["transaction_signing"])
        self.assertFalse(snapshot["transaction_submission"])

    @patch("monitor.rpc_call")
    def test_network_mismatch_is_visible(self, rpc_call):
        rpc_call.side_effect = ["0x10", "0x89"]
        with patch.dict(os.environ, {"RPC_URL": "https://example.invalid", "CHAIN_ID": "1"}, clear=False):
            snapshot = collect_snapshot(Config.from_env())
        self.assertNotEqual(snapshot["chain_id"], snapshot["expected_chain_id"])


if __name__ == "__main__":
    unittest.main()
