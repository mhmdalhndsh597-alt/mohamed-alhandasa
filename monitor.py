"""Read-only blockchain monitor with whale and volume-spike alerts.

No function in this module signs, submits, routes, or transfers transactions.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
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
    rpc_urls: tuple[str, ...] = ()
    spike_threshold_percent: Decimal = Decimal("50")
    state_file: str = "data/volume_history.jsonl"
    social_webhook_urls: tuple[str, ...] = ()

    @staticmethod
    def from_env() -> "Config":
        rpc_urls = tuple(x.strip() for x in os.environ.get("RPC_URLS", "").split(",") if x.strip())
        if not rpc_urls:
            primary = os.environ.get("RPC_URL", "").strip()
            if primary:
                rpc_urls = (primary,)
        if not rpc_urls:
            raise ValueError("RPC_URL or RPC_URLS is required")
        try:
            whale = Decimal(os.environ.get("WHALE_THRESHOLD_NATIVE", "100"))
            spike = Decimal(os.environ.get("SPIKE_THRESHOLD_PERCENT", "50"))
        except InvalidOperation as exc:
            raise ValueError("threshold values must be numbers") from exc
        if whale <= 0 or spike <= 0:
            raise ValueError("threshold values must be greater than zero")
        return Config(
            rpc_url=rpc_urls[0],
            rpc_urls=rpc_urls,
            chain_id=int(os.environ.get("CHAIN_ID", "1")),
            watch_addresses=tuple(x.strip().lower() for x in os.environ.get("WATCH_ADDRESSES", "").split(",") if x.strip()),
            contract_addresses=tuple(x.strip().lower() for x in os.environ.get("CONTRACT_ADDRESSES", "").split(",") if x.strip()),
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL") or None,
            social_webhook_urls=tuple(x.strip() for x in os.environ.get("SOCIAL_WEBHOOKS", "").split(",") if x.strip()),
            whale_threshold_native=whale,
            spike_threshold_percent=spike,
            state_file=os.environ.get("STATE_FILE", "data/volume_history.jsonl"),
            explorer_tx_url=os.environ.get("EXPLORER_TX_URL", DEFAULT_EXPLORER_TX_URL).strip(),
        )


def rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with safe_urlopen(request) as response:
        result = json.loads(response.read().decode())
    if result.get("error"):
        raise RuntimeError(f"RPC error: {result['error']}")
    return result.get("result")


def rpc_call_with_fallback(config: Config, method: str, params: list[Any]) -> tuple[Any, str]:
    errors: list[str] = []
    for endpoint in config.rpc_urls or (config.rpc_url,):
        try:
            return rpc_call(endpoint, method, params), endpoint
        except Exception as exc:
            errors.append(f"{urlparse(endpoint).netloc}: {exc}")
            LOG.warning("RPC endpoint failed; trying next fallback: %s", errors[-1])
    raise RuntimeError("all RPC endpoints failed: " + " | ".join(errors))


def send_discord_embed(webhook_url: str, *, title: str, description: str, color: int,
                       fields: list[dict[str, Any]], url: str | None = None) -> None:
    embed: dict[str, Any] = {"title": title[:256], "description": description[:4000], "color": color,
                             "fields": fields[:25], "timestamp": datetime.now(timezone.utc).isoformat(),
                             "footer": {"text": "Liquidity monitor • read-only"}}
    if url:
        embed["url"] = url[:2048]
    body = {"allowed_mentions": {"parse": []}, "embeds": [embed]}
    request = urllib.request.Request(webhook_url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with safe_urlopen(request) as response:
        if response.status >= 300:
            raise RuntimeError(f"notification webhook returned HTTP {response.status}")


def _is_relevant(tx: dict[str, Any], config: Config) -> bool:
    monitored = set(config.watch_addresses) | set(config.contract_addresses)
    if not monitored:
        return True
    return (tx.get("from") or "").lower() in monitored or (tx.get("to") or "").lower() in monitored


def collect_snapshot(config: Config) -> dict[str, Any]:
    block_hex, endpoint = rpc_call_with_fallback(config, "eth_blockNumber", [])
    chain_hex, _ = rpc_call_with_fallback(config, "eth_chainId", [])
    return {"observed_at": datetime.now(timezone.utc).isoformat(), "chain_id": int(chain_hex, 16),
            "expected_chain_id": config.chain_id, "latest_block": int(block_hex, 16),
            "rpc_endpoint": urlparse(endpoint).netloc, "watch_addresses": list(config.watch_addresses),
            "contract_addresses": list(config.contract_addresses), "whale_threshold_native": str(config.whale_threshold_native),
            "spike_threshold_percent": str(config.spike_threshold_percent), "mode": "read-only",
            "transaction_signing": False, "transaction_submission": False}


def get_block_metrics(config: Config, block_number: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    block, endpoint = rpc_call_with_fallback(config, "eth_getBlockByNumber", [hex(block_number), True])
    transactions = block.get("transactions", []) if block else []
    volume = Decimal("0")
    for tx in transactions:
        try:
            volume += Decimal(int(tx.get("value", "0x0"), 16)) / WEI_PER_NATIVE
        except (TypeError, ValueError, InvalidOperation):
            LOG.warning("Skipping transaction with invalid value: %s", tx.get("hash", "unknown"))
    return {"block": block_number, "tx_count": len(transactions), "native_volume": str(volume),
            "rpc_endpoint": urlparse(endpoint).netloc}, transactions


def find_whale_transactions(config: Config, transactions: list[dict[str, Any]], block_number: int) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for tx in transactions:
        try:
            value_native = Decimal(int(tx.get("value", "0x0"), 16)) / WEI_PER_NATIVE
        except (TypeError, ValueError, InvalidOperation):
            continue
        if value_native >= config.whale_threshold_native and _is_relevant(tx, config):
            alerts.append({"hash": tx.get("hash", "unknown"), "from": tx.get("from", "unknown"),
                           "to": tx.get("to") or "contract creation", "value_native": value_native, "block": block_number})
        if len(alerts) >= config.max_alerts:
            break
    return alerts


def update_history(path: str, metrics: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    if target.exists():
        for line in target.read_text().splitlines():
            try:
                row = json.loads(line)
                if datetime.fromisoformat(row["observed_at"]) >= now - timedelta(hours=24):
                    rows.append(row)
            except (json.JSONDecodeError, KeyError, ValueError):
                LOG.warning("Ignoring malformed history row")
    baseline_values = [Decimal(row["native_volume"]) for row in rows]
    baseline = sum(baseline_values, Decimal("0")) / len(baseline_values) if baseline_values else None
    current = Decimal(metrics["native_volume"])
    change = ((current - baseline) / baseline * Decimal("100")) if baseline else None
    row = {"observed_at": now.isoformat(), "block": metrics["block"], "tx_count": metrics["tx_count"], "native_volume": str(current)}
    target.write_text("\n".join([*(json.dumps(item) for item in rows), json.dumps(row)]) + "\n")
    return baseline, change


def configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if os.environ.get("LOG_FILE", "").strip():
        handlers.append(logging.FileHandler(os.environ["LOG_FILE"]))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")


def notify_all(config: Config, **payload: Any) -> None:
    for webhook in (config.discord_webhook_url, *config.social_webhook_urls):
        if webhook:
            send_discord_embed(webhook, **payload)


def main() -> int:
    configure_logging()
    config: Config | None = None
    try:
        config = Config.from_env()
        snapshot = collect_snapshot(config)
        if snapshot["chain_id"] != config.chain_id:
            raise RuntimeError(f"network mismatch: expected {config.chain_id}, observed {snapshot['chain_id']}")
        metrics, transactions = get_block_metrics(config, snapshot["latest_block"])
        baseline, change = update_history(config.state_file, metrics)
        LOG.info("Scanned block %s via %s; volume=%s; 24h_change=%s", snapshot["latest_block"], metrics["rpc_endpoint"], metrics["native_volume"], change)
        if not config.discord_webhook_url and not config.social_webhook_urls:
            return 0
        for alert in find_whale_transactions(config, transactions, snapshot["latest_block"]):
            tx_url = config.explorer_tx_url.format(tx_hash=alert["hash"])
            notify_all(config, title="Whale alert • large native transfer", description="A transfer exceeded the configured threshold. No action was taken.", color=15158332, url=tx_url,
                       fields=[{"name": "Amount", "value": f"{alert['value_native']:,.6f} native", "inline": True}, {"name": "Block", "value": str(alert["block"]), "inline": True}, {"name": "From", "value": f"`{alert['from']}`", "inline": False}, {"name": "To", "value": f"`{alert['to']}`", "inline": False}, {"name": "Transaction", "value": f"[Open in explorer]({tx_url})", "inline": False}])
        if change is not None and abs(change) >= config.spike_threshold_percent:
            notify_all(config, title="Urgent volume spike detected", description="Current block volume moved materially versus the rolling 24-hour average.", color=16711680,
                       fields=[{"name": "Current volume", "value": f"{metrics['native_volume']} native", "inline": True}, {"name": "24h average", "value": f"{baseline} native", "inline": True}, {"name": "Change", "value": f"{change:+.2f}%", "inline": True}, {"name": "Block", "value": str(metrics["block"]), "inline": True}])
        return 0
    except Exception as exc:
        LOG.exception("Monitor failed closed")
        if config and config.discord_webhook_url:
            try:
                send_discord_embed(config.discord_webhook_url, title="Liquidity monitor stopped", description="The read-only monitor failed and requires review. No transaction was submitted.", color=15548997, fields=[{"name": "Error", "value": str(exc)[:1000], "inline": False}])
            except Exception:
                LOG.exception("Could not deliver failure notification")
        return 1


if __name__ == "__main__":
    sys.exit(main())
