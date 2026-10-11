"""ОПЦИОНАЛЬНАЯ, НЕКРИТИЧНАЯ функция: перефразирование советов на естественном языке.

По умолчанию выключена (ML_ENABLE_LLM=0). Ядро скоринга, прогноз, график и объяснения
от неё не зависят: при выключенном флаге, отсутствии ключа или ошибке сети возвращается None,
и сервис отдаёт шаблонные советы. В прод-контуре банка внешний вызов заменяется
локальной моделью или остаются шаблоны (см. README, раздел «Периметр данных»).
В запрос уходят только уже обезличенные шаблонные тексты советов, без транзакций и ID.
"""
from __future__ import annotations

import os

from config import ENABLE_LLM


def paraphrase_advice(texts: list[str], lang: str = "ru") -> str | None:
    if not ENABLE_LLM or not texts:
        return None
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import httpx  # импорт только при включённом флаге

        prompt = ("Перескажи эти советы предпринимателю одним коротким дружелюбным абзацем, "
                  f"на языке '{lang}', без новых фактов и цифр:\n- " + "\n- ".join(texts))
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.getenv("ML_LLM_MODEL", "claude-haiku-5-5"), "max_tokens": 400,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=8.0,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    except Exception:
        return None
