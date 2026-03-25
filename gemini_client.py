"""
Minimal Gemini helper for compact Russian editorial intros and question translation.
Falls back gracefully when API fails or is not configured.
All Gemini work for one topic is done in a SINGLE API call to stay within free-tier rate limits.
"""
from __future__ import annotations

import json
import logging
import re
import time

import requests

import config

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 5.0


def _gemini_call(prompt: str, max_tokens: int = 600, temperature: float = 0.0) -> str | None:
    """Low-level Gemini call with retry on 429/5xx."""
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
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(url, json=req_body, timeout=config.GEMINI_TIMEOUT_SECONDS)
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.info("Gemini %s, retrying in %.1fs (attempt %d/%d)", resp.status_code, delay, attempt + 1, _MAX_RETRIES)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            body = resp.json()
            candidates = body.get("candidates") or []
            if not candidates:
                return None
            parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
            text = " ".join((p.get("text") or "").strip() for p in parts if isinstance(p, dict)).strip()
            return text or None
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Gemini call failed: %s", exc)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                continue
    if last_exc:
        logger.warning("Gemini exhausted all retries, last error: %s", last_exc)
    else:
        logger.warning("Gemini exhausted all retries (429/5xx).")
    return None


def generate_topic_content(
    topic_title_ru: str,
    market_data: dict,
    questions_to_translate: list[str],
) -> tuple[str | None, dict[str, str]]:
    """
    Single Gemini call per topic that returns both:
    - intro paragraph (Russian)
    - translated questions mapping

    Returns (intro_text_or_None, {original_question: translated_question}).
    On any failure, returns (None, identity_mapping).
    """
    identity = {q: q for q in questions_to_translate}
    if not config.GEMINI_API_KEY or not questions_to_translate:
        return None, identity

    q_lines = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions_to_translate)])

    prompt = (
        "Ты редактор русскоязычного Telegram-канала про рынки прогнозов Polymarket.\n"
        "Задание из двух частей.\n\n"
        "ЧАСТЬ 1 — ВВОДНЫЙ АБЗАЦ\n"
        "Напиши 2-3 предложения на русском, нейтральным тоном.\n"
        "Упомяни, где самая сильная уверенность рынка и где самое сильное движение.\n"
        "Строго по данным ниже. Не придумывай причин и не спекулируй.\n"
        f"Тема: {topic_title_ru}\n"
        f"Данные: {market_data}\n\n"
        "ЧАСТЬ 2 — ПЕРЕВОД ВОПРОСОВ\n"
        "Переведи эти вопросы рынков на русский.\n"
        "Сохрани имена собственные, даты, тикеры, числа.\n"
        f"{q_lines}\n\n"
        "ФОРМАТ ОТВЕТА (строго):\n"
        "---INTRO---\n"
        "<вводный абзац>\n"
        "---TRANSLATIONS---\n"
        "1. <перевод>\n"
        "2. <перевод>\n"
        "...\n"
    )

    text = _gemini_call(prompt, max_tokens=800, temperature=0.1)
    if not text:
        return None, identity

    intro = None
    translations = dict(identity)

    # Parse intro.
    intro_match = re.search(r"---INTRO---\s*\n(.+?)(?=---TRANSLATIONS---|$)", text, re.DOTALL)
    if intro_match:
        intro_text = intro_match.group(1).strip()
        if intro_text and not _looks_speculative_or_causal(intro_text):
            intro = intro_text

    # Parse translations.
    trans_match = re.search(r"---TRANSLATIONS---\s*\n(.+)", text, re.DOTALL)
    if trans_match:
        trans_block = trans_match.group(1).strip()
        parsed: list[str] = []
        for line in trans_block.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\d+[\.\)\:\-]\s*(.+)$", line)
            if m:
                parsed.append(m.group(1).strip())
        for i, src in enumerate(questions_to_translate):
            if i < len(parsed) and parsed[i].strip():
                translations[src] = parsed[i].strip()

    translated_count = sum(1 for src in questions_to_translate if translations.get(src) != src)
    logger.info("Gemini: intro=%s, translated %d/%d questions.", "yes" if intro else "no", translated_count, len(questions_to_translate))

    return intro, translations


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
