"""LLM-объяснение алерта: пересказ ГОТОВОГО решения человеческим языком.

Роль языковой модели строго ограничена и это принципиально: система должна
оставаться защитимой перед регулятором.

    LLM НЕ принимает решение.
    LLM НЕ влияет на уровень риска.
    LLM НЕ добавляет фактов, которых нет во входных данных.

Уровень риска определяет Decision Engine — детерминированная объяснимая логика
(правила, метки, ML, граф). Модель получает уже принятое решение вместе с его
фактической базой и переформулирует его в связный текст для аналитика. Если
выключить эту функцию, не изменится ни одна оценка риска — только исчезнет текст.

Провайдер выбирается в .env (LLM_PROVIDER): anthropic / gemini / ollama.
Меняется ТОЛЬКО клиент — промпт, ограничения роли, кэш и обработка ошибок общие
для всех провайдеров. Ключи и адреса берутся из .env, никогда не хардкодятся.
"""
from __future__ import annotations

import hashlib
import json
import logging

import requests

from .config import LLMConfig

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Ошибка генерации с сообщением, пригодным для показа пользователю."""


class LLMNotConfigured(LLMError):
    """Ключ API не задан — функция отключена, система работает как раньше."""


LANGS = {"ru": "русском", "kk": "казахском", "en": "английском"}

# Инструкция модели. Запреты сформулированы явно: модель обязана опираться
# только на переданные факты и не может оспаривать уровень риска.
SYSTEM_PROMPT = """\
Ты — помощник аналитика в системе финансового мониторинга криптоопераций.
Твоя единственная задача — объяснить человеческим языком УЖЕ ПРИНЯТОЕ системой
решение о риске кошелька.

Что тебе дают: уровень риска, уверенность, сработавшие правила с баллами, оценки
ИИ и графового анализа с их объяснениями, метки участников, агрегаты кошелька и
сводку доказательств.

Жёсткие ограничения:
1. Опирайся ИСКЛЮЧИТЕЛЬНО на переданные факты. Не додумывай и не достраивай
   недостающее. Если чего-то в данных нет — не упоминай это.
2. Не предполагай тип преступления и не называй конкретные преступные схемы,
   если они прямо не следуют из переданных данных. «Связь с миксером» — это
   факт из данных; «отмывание доходов от наркоторговли» — домысел.
3. Не делай выводов о личности, намерениях, гражданстве или роде занятий
   владельца адреса. Кошелёк — не человек.
4. Уровень риска дан и НЕ ОБСУЖДАЕТСЯ. Не меняй его, не оспаривай, не предлагай
   другой, не пиши «на самом деле риск ниже/выше».
5. Не выдумывай числа. Используй только те, что переданы.
6. Если данных мало — так и скажи, это честный и полезный ответ.

Формат ответа — ровно три части, без markdown-заголовков и без вступлений:

РЕЗЮМЕ
2–3 предложения: что за объект и почему система присвоила ему такой уровень.

ПРИЧИНЫ
Список причин. По каждой — что она означает на практике для аналитика.

НА ЧТО ОБРАТИТЬ ВНИМАНИЕ
Что проверить при разборе. Только проверяемые шаги, опирающиеся на эти данные.

Пиши сдержанно и по делу, без канцелярита и без драматизации."""


def decision_fingerprint(context: dict) -> str:
    """Отпечаток решения: меняется — объяснение устарело и генерируется заново.

    В отпечаток входит только то, что влияет на СМЫСЛ объяснения: уровень,
    уверенность, причины и вклад источников. Время и счётчики просмотров — нет.
    """
    material = {
        "level": context.get("risk_level"),
        "confidence": context.get("confidence"),
        "reasons": context.get("reasons"),
        "scores": context.get("scores"),
        "labels": context.get("labels"),
        "evidence_count": (context.get("evidence") or {}).get("count"),
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_user_prompt(context: dict, lang: str) -> str:
    """Факты для модели — как данные, а не как инструкции."""
    lang_name = LANGS.get(lang, LANGS["ru"])
    facts = json.dumps(context, ensure_ascii=False, indent=2, default=str)
    return (
        f"Объясни решение на {lang_name} языке.\n\n"
        f"Вот все факты по алерту (других данных нет):\n\n{facts}\n\n"
        f"Уровень риска «{context.get('risk_level')}» уже определён системой — "
        f"объясни его, не переоценивая."
    )


# ---------------------------------------------------------------------------
# Клиенты провайдеров.
#
# Каждый получает готовые SYSTEM_PROMPT и user-промпт и возвращает
# (текст, имя модели). Ниже этой границы ничего не знает о том, ЧТО за факты
# передаются и какие у модели ограничения — это общая часть выше.
# ---------------------------------------------------------------------------

def _call_anthropic(system: str, user: str, cfg: LLMConfig) -> tuple[str, str]:
    """Anthropic Claude через официальный SDK."""
    try:
        import anthropic
    except ImportError as exc:
        raise LLMError(
            "Библиотека anthropic не установлена: python -m pip install -r requirements.txt"
        ) from exc

    client = anthropic.Anthropic(api_key=cfg.api_key, timeout=cfg.timeout_seconds)
    try:
        response = client.messages.create(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=system,
            output_config={"effort": cfg.effort},
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APITimeoutError as exc:
        raise LLMError(_timeout_msg(cfg)) from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Превышен лимит запросов к LLM. Подожди немного и повтори.") from exc
    except anthropic.AuthenticationError as exc:
        raise LLMError(f"Ключ LLM недействителен — проверь {cfg.credential_env} в .env.") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"Нет связи с сервисом LLM: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Сервис LLM вернул ошибку {exc.status_code}.") from exc

    # Модель может отказаться отвечать — это не ошибка сервера.
    if response.stop_reason == "refusal":
        raise LLMError("Модель отказалась формировать объяснение по этому запросу.")

    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    return text, response.model


def _call_gemini(system: str, user: str, cfg: LLMConfig) -> tuple[str, str]:
    """Google Gemini (AI Studio) через REST — без дополнительного SDK.

    Системная инструкция передаётся отдельным полем system_instruction, а не
    подмешивается в текст пользователя: так ограничения роли остаются
    инструкцией, а факты — данными.
    """
    url = f"{cfg.base_url.rstrip('/')}/models/{cfg.model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": cfg.max_tokens},
    }
    data = _post_json(url, payload, cfg, headers={"x-goog-api-key": cfg.api_key})

    # Запрос мог быть заблокирован фильтрами — это ответ, а не сбой сервера.
    blocked = (data.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise LLMError(f"Gemini отклонил запрос (причина: {blocked}).")

    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError("Gemini не вернул ответ.")
    reason = candidates[0].get("finishReason")
    if reason == "SAFETY":
        raise LLMError("Gemini отказался формировать объяснение по этому запросу.")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return text, cfg.model


def _call_ollama(system: str, user: str, cfg: LLMConfig) -> tuple[str, str]:
    """Локальная модель через OpenAI-совместимый эндпоинт Ollama."""
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": cfg.max_tokens,
        "stream": False,
    }
    data = _post_json(url, payload, cfg)

    choices = data.get("choices") or []
    if not choices:
        raise LLMError("Локальная модель не вернула ответ.")
    text = ((choices[0].get("message") or {}).get("content") or "").strip()
    return text, data.get("model") or cfg.model


def _timeout_msg(cfg: LLMConfig) -> str:
    return f"Модель не ответила за {cfg.timeout_seconds:.0f} с. Попробуй ещё раз."


def _post_json(url: str, payload: dict, cfg: LLMConfig, headers: dict | None = None) -> dict:
    """POST с общей для REST-провайдеров обработкой ошибок -> понятный LLMError."""
    try:
        resp = requests.post(url, json=payload, timeout=cfg.timeout_seconds,
                             headers={"Content-Type": "application/json", **(headers or {})})
    except requests.Timeout as exc:
        raise LLMError(_timeout_msg(cfg)) from exc
    except requests.ConnectionError as exc:
        where = cfg.base_url or "сервису LLM"
        hint = (" Проверь, что Ollama запущена (ollama serve) и модель загружена "
                f"(ollama pull {cfg.model}).") if cfg.provider == "ollama" else ""
        raise LLMError(f"Нет связи с {where}.{hint}") from exc
    except requests.RequestException as exc:
        raise LLMError(f"Ошибка обращения к LLM: {exc}") from exc

    if resp.status_code in (401, 403):
        raise LLMError(f"Ключ LLM недействителен — проверь {cfg.credential_env} в .env.")
    if resp.status_code == 429:
        raise LLMError("Превышен лимит запросов к LLM. Подожди немного и повтори.")
    if resp.status_code == 404:
        raise LLMError(f"Модель «{cfg.model}» недоступна у провайдера "
                       f"{cfg.provider} — проверь LLM_MODEL.")
    if resp.status_code >= 400:
        raise LLMError(f"Сервис LLM вернул ошибку {resp.status_code}.")

    try:
        return resp.json()
    except ValueError as exc:
        raise LLMError("Сервис LLM вернул неразборчивый ответ.") from exc


_PROVIDERS = {
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
    "ollama": _call_ollama,
}


def generate_explanation(context: dict, lang: str, cfg: LLMConfig) -> tuple[str, str]:
    """Сгенерировать объяснение. -> (текст, имя модели). Бросает LLMError.

    Промпт, ограничения роли и обработка ошибок общие; различается только клиент.
    """
    if not cfg.enabled:
        raise LLMNotConfigured(
            f"LLM не настроена: для провайдера «{cfg.provider}» не задан "
            f"{cfg.credential_env}. Функция объяснений опциональна — "
            f"остальная система работает как обычно."
        )

    call = _PROVIDERS.get(cfg.provider)
    if call is None:
        raise LLMNotConfigured(
            f"Неизвестный LLM_PROVIDER «{cfg.provider}». "
            f"Доступны: {', '.join(sorted(_PROVIDERS))}."
        )

    text, model = call(SYSTEM_PROMPT, build_user_prompt(context, lang), cfg)
    if not text:
        raise LLMError("Модель вернула пустой ответ.")
    return text, model
