"""Bilingual, read-only Streamlit dashboard for the liquidity monitor.
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
lang = st.sidebar.radio("Language / اللغة", ["العربية", "English"], index=0)
ar = lang == "العربية"
T = {
    "title": "محمد الهندسة — مراقبة الشبكة والسيولة" if ar else "Mohamed Al-Handasa — Network & Liquidity Monitor",
    "caption": "لوحة قراءة فقط • لا توقّع ولا ترسل معاملات" if ar else "Read-only dashboard • no transaction signing or sending",
    "block": "آخر كتلة" if ar else "Latest block",
    "volume": "حجم الكتلة" if ar else "Block volume",
    "tx": "عدد المعاملات" if ar else "Transaction count",
    "rpc": "نقطة RPC" if ar else "RPC endpoint",
    "connected": "متصل — الشبكة" if ar else "Connected — network",
    "error": "تعذر قراءة الشبكة" if ar else "Unable to read the network",
    "history": "حجم السيولة خلال آخر 24 ساعة" if ar else "Liquidity volume over the last 24 hours",
    "flow": "تدفق المعاملات" if ar else "Transaction flow",
    "empty": "لا توجد لقطات تاريخية بعد. شغّل monitor.py أولًا." if ar else "No historical snapshots yet. Run monitor.py first.",
    "footer": "التحديث الحي يعتمد على نشر Streamlit في خدمة مستمرة؛ GitHub Actions ينفذ المراقبة الدورية فقط." if ar else "Live updates require Streamlit on a persistent service; GitHub Actions only runs periodic monitoring.",
}
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

st.title(T["title"])
st.caption(T["caption"])
try:
    snapshot, metrics = live_snapshot()
    columns = st.columns(4)
    columns[0].metric(T["block"], f"{snapshot['latest_block']:,}")
    columns[1].metric(T["volume"], f"{Decimal(metrics['native_volume']):,.4f}")
    columns[2].metric(T["tx"], f"{metrics['tx_count']:,}")
    columns[3].metric(T["rpc"], metrics["rpc_endpoint"] or "unknown")
    st.success(f"{T['connected']} {snapshot['chain_id']}")
except Exception as exc:
    st.error(f"{T['error']}: {exc}")
history = load_history(os.environ.get("STATE_FILE", "data/volume_history.jsonl"))
if history:
    import pandas as pd
    frame = pd.DataFrame(history)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame["native_volume"] = pd.to_numeric(frame["native_volume"])
    st.subheader(T["history"])
    st.line_chart(frame.set_index("observed_at")["native_volume"])
    st.subheader(T["flow"])
    st.bar_chart(frame.set_index("observed_at")["tx_count"])
else:
    st.info(T["empty"])
st.caption(T["footer"])
