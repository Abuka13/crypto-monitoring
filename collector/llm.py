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

Ключ и модель берутся из .env (LLMConfig), никогда не хардкодятся.
"""
from __future__ import annotations

import hashlib
import json
import logging

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


def generate_explanation(context: dict, lang: str, cfg: LLMConfig) -> tuple[str, str]:
    """Сгенерировать объяснение. -> (текст, имя модели). Бросает LLMError."""
    if not cfg.enabled:
        raise LLMNotConfigured(
            "LLM не настроена: не задан ANTHROPIC_API_KEY. "
            "Функция объяснений опциональна — остальная система работает как обычно."
        )

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
            system=SYSTEM_PROMPT,
            output_config={"effort": cfg.effort},
            messages=[{"role": "user", "content": build_user_prompt(context, lang)}],
        )
    except anthropic.APITimeoutError as exc:
        raise LLMError(
            f"Модель не ответила за {cfg.timeout_seconds:.0f} с. Попробуй ещё раз."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(
            "Превышен лимит запросов к LLM. Подожди немного и повтори."
        ) from exc
    except anthropic.AuthenticationError as exc:
        raise LLMError("Ключ LLM недействителен — проверь ANTHROPIC_API_KEY в .env.") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"Нет связи с сервисом LLM: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Сервис LLM вернул ошибку {exc.status_code}.") from exc

    # Модель может отказаться отвечать — это не ошибка сервера.
    if response.stop_reason == "refusal":
        raise LLMError("Модель отказалась формировать объяснение по этому запросу.")

    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise LLMError("Модель вернула пустой ответ.")
    return text, response.model
