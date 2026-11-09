"""Read-only liquidity and profit monitor.

This module intentionally does not sign, submit, route, or transfer transactions.
It only reads configured public-chain data and emits bounded alerts.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

LOG = logging.getLogger("liquidity-monitor")


@dataclass(frozen=True)
class Config:
    rpc_url: str
    chain_id: int
    watch_addresses: tuple[str, ...]
    contract_addresses: tuple[str, ...]
    discord_webhook_url: str | None
    max_alerts: int = 20

    @staticmethod
    def from_env() -> "Config":
        rpc_url = os.environ.get("RPC_URL", "").strip()
        if not rpc_url:
            raise ValueError("RPC_URL is required")
        chain_id = int(os.environ.get("CHAIN_ID", "1"))
        watch = tuple(x.strip() for x in os.environ.get("WATCH_ADDRESSES", "").split(",") if x.strip())
        contracts = tuple(x.strip() for x in os.environ.get("CONTRACT_ADDRESSES", "").split(",") if x.strip())
        return Config(
            rpc_url=rpc_url,
            chain_id=chain_id,
            watch_addresses=watch,
            contract_addresses=contracts,
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL") or None,
        )


def rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode())
    if result.get("error"):
        raise RuntimeError(f"RPC error: {result['error']}")
    return result.get("result")


def send_discord_alert(webhook_url: str, title: str, description: str) -> None:
    """Send an allowlisted alert; never accept arbitrary Discord commands."""
    body = {
        "allowed_mentions": {"parse": []},
        "embeds": [{"title": title[:256], "description": description[:4000], "color": 3447003}],
    }
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status >= 300:
            raise RuntimeError(f"Discord webhook returned HTTP {response.status}")


def collect_snapshot(config: Config) -> dict[str, Any]:
    block = rpc_call(config.rpc_url, "eth_blockNumber", [])
    chain = rpc_call(config.rpc_url, "eth_chainId", [])
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "chain_id": int(chain, 16),
        "expected_chain_id": config.chain_id,
        "latest_block": int(block, 16),
        "watch_addresses": list(config.watch_addresses),
        "contract_addresses": list(config.contract_addresses),
        "mode": "read-only",
        "transaction_signing": False,
        "transaction_submission": False,
    }


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    try:
        config = Config.from_env()
        snapshot = collect_snapshot(config)
        if snapshot["chain_id"] != config.chain_id:
            raise RuntimeError(
                f"network mismatch: expected {config.chain_id}, observed {snapshot['chain_id']}"
            )
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        if config.discord_webhook_url:
            send_discord_alert(
                config.discord_webhook_url,
                "Liquidity monitor: healthy read-only snapshot",
                f"Chain {snapshot['chain_id']} | block {snapshot['latest_block']} | mode read-only",
            )
        return 0
    except Exception as exc:  # fail closed: no fallback and no transaction attempt
        LOG.error("monitor failed closed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
