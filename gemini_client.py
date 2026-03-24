"""
Minimal Gemini helper for compact Russian editorial intros.
Falls back gracefully when API fails or is not configured.
"""
from __future__ import annotations

import logging
import re
from typing import List

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


def translate_market_questions_to_russian(questions: list[str]) -> dict[str, str]:
    """
    Translate market questions to Russian with strict meaning preservation.
    Returns mapping original->translated (fallback to original on any failure).
    """
    cleaned = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
    if not cleaned:
        return {}
    mapping = {q: q for q in cleaned}
    if not config.GEMINI_API_KEY:
        return mapping

    prompt_lines = "\n".join([f"{i+1}) {q}" for i, q in enumerate(cleaned)])
    prompt = (
        "Переведи вопросы рынков с английского на русский.\n"
        "Сохраняй имена, даты, тикеры и числа.\n"
        "Никаких объяснений.\n"
        "Формат ответа строго построчно:\n"
        "1) <перевод>\n2) <перевод>\n...\n\n"
        f"{prompt_lines}\n"
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    )
    req_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 600},
    }
    try:
        resp = requests.post(url, json=req_body, timeout=config.GEMINI_TIMEOUT_SECONDS)
        resp.raise_for_status()
        body = resp.json()
        candidates = body.get("candidates") or []
        if not candidates:
            return mapping
        parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
        text = " ".join((p.get("text") or "").strip() for p in parts if isinstance(p, dict)).strip()
        if not text:
            return mapping
        text = text.replace("```", "").strip()
        lines: List[str] = [ln.strip() for ln in text.splitlines() if ln.strip()]
        parsed: list[str] = []
        for line in lines:
            m = re.match(r"^\d+\)\s*(.+)$", line)
            if m:
                parsed.append(m.group(1).strip())
        if len(parsed) != len(cleaned):
            return _fallback_translate_mapping(mapping)
        for src, tr in zip(cleaned, parsed):
            if isinstance(tr, str) and tr.strip():
                mapping[src] = tr.strip()
        return mapping
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini translation failed: %s", exc)
        return _fallback_translate_mapping(mapping)


def _fallback_translate_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """
    Deterministic fallback to avoid raw English questions in posts.
    """
    out = dict(mapping)
    for src in list(out.keys()):
        q = src.strip()
        low = q.lower()
        if low.startswith("will ") and q.endswith("?"):
            out[src] = f"Произойдет ли {q[5:-1].strip()}?"
        elif low.endswith(" convicted?"):
            out[src] = q[:-1].replace(" convicted", " будет признан виновным") + "?"
        else:
            out[src] = q
    return out
