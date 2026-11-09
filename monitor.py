"""Read-only liquidity monitor with thresholded whale alerts.

This module intentionally never signs, submits, routes, or transfers transactions.
It reads public-chain data and emits bounded Discord notifications only.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

LOG = logging.getLogger("liquidity-monitor")
WEI_PER_NATIVE = Decimal(10) ** 18
DEFAULT_EXPLORER_TX_URL = "https://etherscan.io/tx/{tx_hash}"


def safe_urlopen(request: urllib.request.Request, *, timeout: int = 15):
    scheme = urlparse(request.full_url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("only HTTP(S) URLs are allowed")
    return urllib.request.urlopen(request, timeout=timeout)  # nosec B310: scheme allowlist above


@dataclass(frozen=True)
class Config:
    rpc_url: str
    chain_id: int
    watch_addresses: tuple[str, ...]
    contract_addresses: tuple[str, ...]
    discord_webhook_url: str | None
    whale_threshold_native: Decimal
    explorer_tx_url: str
    max_alerts: int = 20

    @staticmethod
    def from_env() -> "Config":
        rpc_url = os.environ.get("RPC_URL", "").strip()
        if not rpc_url:
            raise ValueError("RPC_URL is required")
        try:
            threshold = Decimal(os.environ.get("WHALE_THRESHOLD_NATIVE", "100"))
        except InvalidOperation as exc:
            raise ValueError("WHALE_THRESHOLD_NATIVE must be a number") from exc
        if threshold <= 0:
            raise ValueError("WHALE_THRESHOLD_NATIVE must be greater than zero")
        return Config(
            rpc_url=rpc_url,
            chain_id=int(os.environ.get("CHAIN_ID", "1")),
            watch_addresses=tuple(
                x.strip().lower() for x in os.environ.get("WATCH_ADDRESSES", "").split(",") if x.strip()
            ),
            contract_addresses=tuple(
                x.strip().lower()
                for x in os.environ.get("CONTRACT_ADDRESSES", "").split(",")
                if x.strip()
            ),
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL") or None,
            whale_threshold_native=threshold,
            explorer_tx_url=os.environ.get("EXPLORER_TX_URL", DEFAULT_EXPLORER_TX_URL).strip(),
        )


def rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with safe_urlopen(request) as response:
        result = json.loads(response.read().decode())
    if result.get("error"):
        raise RuntimeError(f"RPC error: {result['error']}")
    return result.get("result")


def send_discord_embed(webhook_url: str, *, title: str, description: str, color: int,
                       fields: list[dict[str, Any]], url: str | None = None) -> None:
    """Send a bounded, notification-only embed with mentions disabled."""
    embed: dict[str, Any] = {
        "title": title[:256],
        "description": description[:4000],
        "color": color,
        "fields": fields[:25],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Liquidity monitor • read-only"},
    }
    if url:
        embed["url"] = url[:2048]
    body = {"allowed_mentions": {"parse": []}, "embeds": [embed]}
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with safe_urlopen(request) as response:
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
        "whale_threshold_native": str(config.whale_threshold_native),
        "mode": "read-only",
        "transaction_signing": False,
        "transaction_submission": False,
    }


def _is_relevant(tx: dict[str, Any], config: Config) -> bool:
    monitored = set(config.watch_addresses) | set(config.contract_addresses)
    if not monitored:
        return True
    return (tx.get("from") or "").lower() in monitored or (tx.get("to") or "").lower() in monitored


def find_whale_transactions(config: Config, block_number: int) -> list[dict[str, Any]]:
    """Find large native-asset transfers in one block; no transaction is submitted."""
    block = rpc_call(config.rpc_url, "eth_getBlockByNumber", [hex(block_number), True]) or {}
    alerts: list[dict[str, Any]] = []
    for tx in block.get("transactions", []):
        try:
            value_native = Decimal(int(tx.get("value", "0x0"), 16)) / WEI_PER_NATIVE
        except (TypeError, ValueError, InvalidOperation):
            LOG.warning("Skipping transaction with invalid value: %s", tx.get("hash", "unknown"))
            continue
        if value_native >= config.whale_threshold_native and _is_relevant(tx, config):
            alerts.append({"hash": tx.get("hash", "unknown"), "from": tx.get("from", "unknown"),
                           "to": tx.get("to") or "contract creation", "value_native": value_native,
                           "block": block_number})
        if len(alerts) >= config.max_alerts:
            break
    return alerts


def configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = os.environ.get("LOG_FILE", "").strip()
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    configure_logging()
    config: Config | None = None
    try:
        config = Config.from_env()
        snapshot = collect_snapshot(config)
        if snapshot["chain_id"] != config.chain_id:
            raise RuntimeError(f"network mismatch: expected {config.chain_id}, observed {snapshot['chain_id']}")
        whale_alerts = find_whale_transactions(config, snapshot["latest_block"])
        LOG.info("Scanned block %s; whale alerts=%s", snapshot["latest_block"], len(whale_alerts))
        if config.discord_webhook_url:
            for alert in whale_alerts:
                tx_url = config.explorer_tx_url.format(tx_hash=alert["hash"])
                send_discord_embed(
                    config.discord_webhook_url,
                    title="Whale alert • large native transfer",
                    description="A transfer exceeded the configured threshold. No action was taken.",
                    color=15158332,
                    url=tx_url,
                    fields=[
                        {"name": "Amount", "value": f"{alert['value_native']:,.6f} native", "inline": True},
                        {"name": "Block", "value": str(alert["block"]), "inline": True},
                        {"name": "From", "value": f"`{alert['from']}`", "inline": False},
                        {"name": "To", "value": f"`{alert['to']}`", "inline": False},
                        {"name": "Transaction", "value": f"[Open in explorer]({tx_url})", "inline": False},
                    ],
                )
        return 0
    except Exception as exc:  # fail closed: never fall back to a transaction attempt
        LOG.exception("Monitor failed closed")
        if config and config.discord_webhook_url:
            try:
                send_discord_embed(
                    config.discord_webhook_url,
                    title="Liquidity monitor stopped",
                    description="The read-only monitor failed and requires review. No transaction was submitted.",
                    color=15548997,
                    fields=[{"name": "Error", "value": str(exc)[:1000], "inline": False}],
                )
            except Exception:
                LOG.exception("Could not deliver failure notification")
        return 1


if __name__ == "__main__":
    sys.exit(main())
