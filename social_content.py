"""Deterministic bilingual social-content generator.

This module creates drafts and API payloads only. It never publishes or contacts a social API.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

AR_HASHTAGS = ("#السيولة", "#بلوكشين", "#برمجة_الشبكات", "#بايثون", "#مراقبة_الشبكة")
EN_HASHTAGS = ("#Liquidity", "#Blockchain", "#WhaleAlert", "#Python", "#NetworkMonitoring")


@dataclass(frozen=True)
class SocialDraft:
    platform: str
    language: str
    text: str
    hashtags: tuple[str, ...]


def _fmt(value: Any, fallback: str = "غير متاح") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def build_drafts(*, chain_id: Any, block: Any, volume: Any, tx_count: Any,
                 whale_count: int = 0, largest_whale: Decimal | None = None,
                 spike_percent: Decimal | None = None) -> list[SocialDraft]:
    """Build ready-to-review drafts for Facebook, X/Twitter, and Instagram."""
    volume_text = _fmt(volume)
    block_text = _fmt(block)
    tx_text = _fmt(tx_count)
    whale_text = str(whale_count)
    largest_text = f"{largest_whale:,.4f}" if largest_whale is not None else "غير متاح"
    spike_text = f"{spike_percent:+.2f}%" if spike_percent is not None else "غير متاح"

    ar = (
        f"تحديث مراقبة الشبكة والسيولة\n\n"
        f"الشبكة: {chain_id} | الكتلة: {block_text}\n"
        f"حجم التدفق المرصود: {volume_text} من العملة الأصلية\n"
        f"عدد المعاملات: {tx_text}\n"
        f"تنبيهات الحيتان: {whale_text}\n"
        f"أكبر حركة مرصودة: {largest_text}\n"
        f"التغير مقابل خط الأساس: {spike_text}\n\n"
        "هذه قراءة تحليلية فقط؛ لا يتم توقيع أو إرسال أي معاملات."
    )
    en = (
        f"Network & liquidity monitoring update\n\n"
        f"Chain: {chain_id} | Block: {block_text}\n"
        f"Observed flow: {volume_text} native units\n"
        f"Transactions: {tx_text}\n"
        f"Whale alerts: {whale_text}\n"
        f"Largest observed move: {largest_text}\n"
        f"Change vs baseline: {spike_text}\n\n"
        "Observational analytics only; no transactions are signed or submitted."
    )
    x_text = (
        f"Network update: block {block_text} on chain {chain_id}; volume {volume_text} native; "
        f"{tx_text} txs; whale alerts {whale_text}; baseline change {spike_text}. "
        "Read-only analytics; no transactions signed.\n\n"
        + " ".join(EN_HASHTAGS)
    )
    return [
        SocialDraft("facebook", "ar", ar + "\n\n" + " ".join(AR_HASHTAGS), AR_HASHTAGS),
        SocialDraft("x", "en", x_text[:280], EN_HASHTAGS),
        SocialDraft("instagram", "ar-en", ar + "\n\n" + en + "\n\n" + " ".join(AR_HASHTAGS + EN_HASHTAGS), AR_HASHTAGS + EN_HASHTAGS),
    ]


def facebook_graph_payload(*, page_id: str, access_token_env: str = "FACEBOOK_PAGE_ACCESS_TOKEN",
                           message: str) -> dict[str, Any]:
    """Return a future Facebook Graph API request description without the token."""
    return {"method": "POST", "path": f"/{page_id}/feed", "token_env": access_token_env,
            "json": {"message": message}}


def telegram_payload(*, chat_id: str, message: str, bot_token_env: str = "TELEGRAM_BOT_TOKEN") -> dict[str, Any]:
    """Return a future Telegram Bot API request description without the token."""
    return {"method": "POST", "path": "/bot<TELEGRAM_BOT_TOKEN>/sendMessage", "token_env": bot_token_env,
            "json": {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}}
