"""
Minimal Gemini helper for compact Russian editorial intros.
Falls back gracefully when API fails or is not configured.
"""
from __future__ import annotations

import logging
import re

import requests

import config

logger = logging.getLogger(__name__)

_RISKY_CAUSE_PATTERNS = (
    r"\bпотому что\b",
    r"\bиз-за\b",
    r"\bна фоне\b",
    r"\bтак как\b",
    r"\bпо причине\b",
)


def _looks_speculative_or_causal(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in _RISKY_CAUSE_PATTERNS)


def build_topic_intro_with_gemini(topic_title_ru: str, payload: dict) -> str | None:
    """Return a short Russian intro paragraph or None on failure."""
    if not config.GEMINI_API_KEY:
        return None

    prompt = (
        "Ты редактор Telegram-канала про рынки прогнозов.\n"
        "Пиши строго на русском и только по данным ниже.\n"
        "Нельзя придумывать внешние причины, новости или инсайды.\n"
        "Нельзя спекулировать и объяснять движение внешними причинами.\n"
        "Нужен 1 короткий абзац (2-3 предложения), нейтральный тон.\n"
        "Упомяни, где сейчас самая сильная уверенность рынка и где было самое сильное движение.\n"
        f"Тема: {topic_title_ru}\n\n"
        f"Данные: {payload}\n"
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    )
    req_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 180},
    }
    try:
        resp = requests.post(url, json=req_body, timeout=config.GEMINI_TIMEOUT_SECONDS)
        resp.raise_for_status()
        body = resp.json()
        candidates = body.get("candidates") or []
        if not candidates:
            return None
        parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
        text = " ".join((p.get("text") or "").strip() for p in parts if isinstance(p, dict)).strip()
        if not text:
            return None
        # Safety net: if model starts explaining "why", use deterministic fallback.
        if _looks_speculative_or_causal(text):
            logger.info("Gemini intro rejected due to causal wording.")
            return None
        return text
    except Exception as exc:  # noqa: BLE001 - do not break the bot on LLM failures.
        logger.warning("Gemini intro generation failed: %s", exc)
        return None
