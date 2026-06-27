"""Допустимые переходы статуса алерта (Шаг 5 docs/architecture.md).

Жизненный цикл:
    open ──► in_progress ──► closed
                 │      └───► false_positive
                 └──► open   (откат в работу)

closed и false_positive — терминальные: дальнейших переходов нет.
"""
from __future__ import annotations

VALID_STATUSES = {"open", "in_progress", "closed", "false_positive"}

# Из какого статуса в какие можно перейти.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress"},
    "in_progress": {"closed", "false_positive", "open"},
    "closed": set(),
    "false_positive": set(),
}

# При переходе в эти статусы проставляется resolved_at = now().
RESOLVING_STATUSES = {"closed", "false_positive"}


def validate_transition(current: str, new: str) -> str | None:
    """Вернуть текст ошибки, если переход недопустим, иначе None."""
    if new not in VALID_STATUSES:
        allowed = ", ".join(sorted(VALID_STATUSES))
        return f"Недопустимое значение статуса '{new}'. Допустимые: {allowed}."
    if new == current:
        return f"Алерт уже в статусе '{current}'."
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new not in allowed:
        if not allowed:
            return f"Из статуса '{current}' переходы запрещены (терминальный статус)."
        return (
            f"Недопустимый переход '{current}' → '{new}'. "
            f"Из '{current}' можно перейти в: {', '.join(sorted(allowed))}."
        )
    return None
