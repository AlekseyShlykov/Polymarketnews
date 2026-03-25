"""
Minimal Gemini helper for compact Russian editorial intros and question translation.
Falls back gracefully when API fails or is not configured.
"""
from __future__ import annotations

import json
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


def _gemini_call(prompt: str, max_tokens: int = 300, temperature: float = 0.0) -> str | None:
    """Low-level Gemini call. Returns text or None."""
    if not config.GEMINI_API_KEY:
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    )
    req_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
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
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini call failed: %s", exc)
        return None


def build_topic_intro_with_gemini(topic_title_ru: str, payload: dict) -> str | None:
    """Return a short Russian intro paragraph or None on failure."""
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
    text = _gemini_call(prompt, max_tokens=180, temperature=0.1)
    if not text:
        return None
    if _looks_speculative_or_causal(text):
        logger.info("Gemini intro rejected due to causal wording.")
        return None
    return text


def _translate_single_question(question: str) -> str | None:
    """Translate one question via Gemini. Returns Russian text or None."""
    prompt = (
        "Переведи этот вопрос рынка прогнозов на русский язык.\n"
        "Сохрани имена собственные, даты, тикеры и числа.\n"
        "Ответь ТОЛЬКО переводом, без пояснений.\n\n"
        f"{question}\n"
    )
    result = _gemini_call(prompt, max_tokens=120, temperature=0.0)
    if not result:
        return None
    cleaned = result.strip().strip('"').strip("'").strip()
    if not cleaned:
        return None
    return cleaned


def translate_market_questions_to_russian(questions: list[str]) -> dict[str, str]:
    """
    Translate market questions to Russian. Strategy:
    1. Try batch Gemini translation.
    2. For any question that wasn't translated, try individual Gemini call.
    3. If Gemini is completely unavailable, keep original English
       (much better than half-Russian/half-English).
    """
    cleaned = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
    if not cleaned:
        return {}
    # Start with identity mapping (English originals as safe fallback).
    mapping: dict[str, str] = {q: q for q in cleaned}
    if not config.GEMINI_API_KEY:
        return mapping

    # Step 1: batch translation.
    batch_result = _try_batch_translate(cleaned)
    if batch_result:
        for src, tr in batch_result.items():
            if tr and tr.strip():
                mapping[src] = tr.strip()

    # Step 2: individually translate any that batch missed.
    for q in cleaned:
        if mapping[q] == q:
            single = _translate_single_question(q)
            if single:
                mapping[q] = single

    return mapping


def _try_batch_translate(questions: list[str]) -> dict[str, str] | None:
    """Try batch Gemini translation. Returns partial or full mapping, or None."""
    prompt_lines = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions)])
    prompt = (
        "Переведи эти вопросы рынков прогнозов с английского на русский.\n"
        "Сохраняй имена собственные, даты, тикеры и числа.\n"
        "Никаких пояснений. Ответ строго в формате:\n"
        "1. <перевод>\n"
        "2. <перевод>\n"
        "...\n\n"
        f"{prompt_lines}\n"
    )
    text = _gemini_call(prompt, max_tokens=600, temperature=0.0)
    if not text:
        return None

    text = text.replace("```", "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Parse flexibly: accept "1) ...", "1. ...", "1: ...", "1 - ..." etc.
    parsed: list[str] = []
    for line in lines:
        m = re.match(r"^\d+[\.\)\:\-]\s*(.+)$", line)
        if m:
            parsed.append(m.group(1).strip())

    if not parsed:
        logger.warning("Gemini batch translation: no parseable lines in response.")
        return None

    result: dict[str, str] = {}
    for i, src in enumerate(questions):
        if i < len(parsed) and parsed[i].strip():
            result[src] = parsed[i].strip()

    if result:
        logger.info("Gemini batch translated %d/%d questions.", len(result), len(questions))
    return result
