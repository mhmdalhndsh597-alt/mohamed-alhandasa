"""Generate local Markdown and JSON performance reports from monitor history."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


def read_rows(path: str) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_report(rows: list[dict], hours: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    selected = [row for row in rows if datetime.fromisoformat(row["observed_at"]) >= cutoff]
    volumes = [Decimal(row["native_volume"]) for row in selected]
    tx_counts = [int(row["tx_count"]) for row in selected]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_hours": hours,
        "samples": len(selected),
        "total_native_volume": str(sum(volumes, Decimal("0"))),
        "average_native_volume": str(sum(volumes, Decimal("0")) / len(volumes)) if volumes else "0",
        "max_native_volume": str(max(volumes)) if volumes else "0",
        "total_transactions": sum(tx_counts),
        "max_transactions_in_sample": max(tx_counts) if tx_counts else 0,
    }


def write_report(report: dict, output_dir: str, label: str) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = directory / f"{label}-{stamp}.json"
    md_path = directory / f"{label}-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text("\n".join([
        f"# {label.title()} Network Report", "", f"Generated: {report['generated_at']}", "",
        f"- Samples: {report['samples']}", f"- Total native volume: {report['total_native_volume']}",
        f"- Average sample volume: {report['average_native_volume']}", f"- Maximum sample volume: {report['max_native_volume']}",
        f"- Total transactions: {report['total_transactions']}", f"- Maximum transactions in a sample: {report['max_transactions_in_sample']}", "",
        "This report is observational only. No transaction was signed or submitted.", ""
    ]))
    return md_path


if __name__ == "__main__":
    history = os.environ.get("STATE_FILE", "data/volume_history.jsonl")
    output = os.environ.get("REPORT_DIR", "reports")
    rows = read_rows(history)
    write_report(build_report(rows, 24), output, "daily")
    write_report(build_report(rows, 24 * 7), output, "weekly")
