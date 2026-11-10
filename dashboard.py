"""Read-only Streamlit dashboard for the liquidity monitor.

Run with: streamlit run dashboard.py
Secrets are read from environment variables or Streamlit secrets; never hard-coded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from decimal import Decimal

import streamlit as st

from monitor import Config, collect_snapshot, get_block_metrics

st.set_page_config(page_title="محمد الهندسة | Network Monitor", page_icon="📊", layout="wide")


def load_history(path: str) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-288:]


@st.cache_data(ttl=15)
def live_snapshot() -> tuple[dict, dict]:
    config = Config.from_env()
    snapshot = collect_snapshot(config)
    metrics, _ = get_block_metrics(config, snapshot["latest_block"])
    return snapshot, metrics


st.title("محمد الهندسة — مراقبة الشبكة والسيولة")
st.caption("لوحة قراءة فقط • لا توقّع ولا ترسل معاملات")

try:
    snapshot, metrics = live_snapshot()
    columns = st.columns(4)
    columns[0].metric("آخر كتلة", f"{snapshot['latest_block']:,}")
    columns[1].metric("حجم الكتلة", f"{Decimal(metrics['native_volume']):,.4f}")
    columns[2].metric("عدد المعاملات", f"{metrics['tx_count']:,}")
    columns[3].metric("RPC", metrics["rpc_endpoint"] or "unknown")
    st.success(f"متصل — الشبكة {snapshot['chain_id']}")
except Exception as exc:
    st.error(f"تعذر قراءة الشبكة: {exc}")

history = load_history(os.environ.get("STATE_FILE", "data/volume_history.jsonl"))
if history:
    import pandas as pd

    frame = pd.DataFrame(history)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame["native_volume"] = pd.to_numeric(frame["native_volume"])
    st.subheader("حجم السيولة عبر آخر 24 ساعة")
    st.line_chart(frame.set_index("observed_at")["native_volume"])
    st.subheader("تدفق المعاملات")
    st.bar_chart(frame.set_index("observed_at")["tx_count"])
else:
    st.info("لا توجد لقطات تاريخية بعد. شغّل monitor.py أولًا.")

st.caption("التحديث الحي يعتمد على نشر Streamlit في خدمة مستمرة؛ GitHub Actions ينفذ المراقبة الدورية فقط.")
