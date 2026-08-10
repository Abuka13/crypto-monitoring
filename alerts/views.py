"""Вьюхи REST API интерфейса аналитика: алерты, кошельки, транзакции, правила,
статистика, аутентификация. Маршруты — в alerts/urls.py."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema,
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .graph_query import DEFAULT_LIMIT, MAX_DEPTH, build_ego_network, resolve_center
from .models import Alert, Rule, Tx, Wallet
from .serializers import (
    AlertDetailSerializer, AlertListSerializer, RuleSerializer,
    RuleToggleSerializer, StatusUpdateSerializer, TransactionSerializer,
    WalletDetailSerializer, WalletSerializer, _related_risk,
)
from .transitions import RESOLVING_STATUSES, validate_transition


@extend_schema(tags=["alerts"])
class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """Список и детали алертов (только чтение); смена статуса — отдельным action."""

    queryset = (
        Alert.objects.select_related(  # против N+1 при final_score/контексте
            "transaction_risk__transaction__sender_wallet",
            "transaction_risk__transaction__receiver_wallet",
            "wallet_risk__wallet",
            "wallet_risk__wallet__graph_features",  # объяснение графового риска
            "wallet",                                # сущность алерта
        )
        .all()
        .order_by("-created_at")
    )
    # Серверные фильтры/поиск (?status=&level=&target_type=&search=).
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "level", "target_type"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "level", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AlertDetailSerializer
        return AlertListSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("limit", int, description="Сколько транзакций вернуть (по умолчанию 50)"),
            OpenApiParameter("offset", int, description="Смещение для постраничного просмотра"),
        ],
        responses=OpenApiResponse(description="Транзакции-доказательства алерта"),
        description="Полный список транзакций-доказательств алерта, постранично.",
    )
    @action(detail=True, methods=["get"], url_path="evidence")
    def evidence(self, request, pk=None):
        """Доказательства алерта: все связанные транзакции (limit/offset)."""
        alert = self.get_object()

        def _int(name, default, cap):
            try:
                return max(0, min(int(request.query_params.get(name, default)), cap))
            except (TypeError, ValueError):
                return default

        limit, offset = _int("limit", 50, 200), _int("offset", 0, 10 ** 9)
        qs = (
            Tx.objects.filter(evidence_for__alert_id=alert.id)
            .select_related("sender_wallet", "receiver_wallet")
            .order_by("-transaction_timestamp", "-id")
        )
        return Response({
            "count": alert.evidence_count,
            "results": TransactionSerializer(qs[offset:offset + limit], many=True).data,
        })

    @extend_schema(
        request=StatusUpdateSerializer,
        responses={200: AlertDetailSerializer},
        examples=[OpenApiExample("Взять в работу", value={"status": "in_progress"})],
        description=(
            "Сменить статус алерта. Разрешены переходы "
            "open → in_progress → closed/false_positive и откат in_progress → open. "
            "Недопустимый переход или значение — 400. При переходе в closed/"
            "false_positive проставляется resolved_at = now()."
        ),
    )
    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        alert = self.get_object()

        body = StatusUpdateSerializer(data=request.data)
        if not body.is_valid():
            return Response(
                {"detail": "Не передан корректный статус.", "errors": body.errors},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        new_status = body.validated_data["status"]

        error = validate_transition(alert.status, new_status)
        if error:
            return Response(
                {"detail": error},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        alert.status = new_status
        update_fields = ["status"]
        if new_status in RESOLVING_STATUSES:
            alert.resolved_at = timezone.now()
            update_fields.append("resolved_at")
        alert.save(update_fields=update_fields)

        return Response(AlertDetailSerializer(alert).data)


@extend_schema(
    tags=["auth"],
    responses=OpenApiResponse(
        description="Текущий пользователь",
        examples=[OpenApiExample("Пример", value={
            "username": "analyst1", "first_name": "Иван", "last_name": "Петров",
            "is_staff": False, "is_superuser": False,
        })],
    ),
)
@api_view(["GET"])
def me_view(request):
    """Данные текущего пользователя (по access-токену) — для шапки интерфейса."""
    u = request.user
    return Response({
        "username": u.username,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "is_staff": u.is_staff,
        "is_superuser": u.is_superuser,
    })


@extend_schema(tags=["auth"], request=None, responses={205: None})
@api_view(["POST"])
def logout_view(request):
    """Выход: отзывает (blacklist) переданный refresh-токен. Тело: {"refresh": "..."}."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import RefreshToken
    token_str = request.data.get("refresh")
    if token_str:
        try:
            RefreshToken(token_str).blacklist()
        except TokenError:
            pass  # уже невалиден/отозван — выход всё равно успешен
    return Response(status=http_status.HTTP_205_RESET_CONTENT)


@extend_schema(
    tags=["wallets"],
    parameters=[OpenApiParameter(
        "risk", str, description="Уровень риска: low (<40) / medium (40–70) / high (>=70)")],
)
class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    """Кошельки (только чтение). Фильтры: is_flagged, label, risk (уровень)."""

    queryset = Wallet.objects.all().order_by("-risk_score", "id")
    serializer_class = WalletSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_flagged", "label"]
    search_fields = ["address"]           # ?search= по адресу кошелька
    ordering_fields = ["risk_score", "transaction_count"]
    # Пагинация (limit/offset) — чтобы сервер не отдавал десятки тысяч строк разом.

    def get_serializer_class(self):
        # В деталях кошелька отдаём ещё и признаки (wallet_features).
        return WalletDetailSerializer if self.action == "retrieve" else WalletSerializer

    def get_queryset(self):
        # Серверный фильтр по уровню риска (>=70 high, >=40 medium, иначе low).
        qs = super().get_queryset()
        risk = self.request.query_params.get("risk")
        if risk == "high":
            qs = qs.filter(risk_score__gte=70)
        elif risk == "medium":
            qs = qs.filter(risk_score__gte=40, risk_score__lt=70)
        elif risk == "low":
            qs = qs.filter(risk_score__lt=40)
        return qs


@extend_schema(tags=["transactions"])
class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """Транзакции (только чтение)."""

    queryset = (
        Tx.objects.select_related("sender_wallet", "receiver_wallet")
        .all()
        .order_by("-transaction_timestamp", "-id")
    )
    serializer_class = TransactionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status"]
    # ?search= по хешу транзакции и адресам отправителя/получателя
    search_fields = ["tx_hash", "sender_wallet__address", "receiver_wallet__address"]
    # Пагинация (limit/offset) — транзакций может быть очень много.


@extend_schema(tags=["rules"])
class RuleViewSet(viewsets.ReadOnlyModelViewSet):
    """Правила Rule Engine: список + включение/выключение (PATCH is_active)."""

    queryset = Rule.objects.all().order_by("id")
    serializer_class = RuleSerializer
    pagination_class = None

    @extend_schema(request=RuleToggleSerializer, responses={200: RuleSerializer})
    def partial_update(self, request, pk=None):
        rule = self.get_object()
        body = RuleToggleSerializer(data=request.data)
        if not body.is_valid():
            return Response(
                {"detail": "Передай поле is_active (true/false).", "errors": body.errors},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        rule.is_active = body.validated_data["is_active"]
        rule.save(update_fields=["is_active"])
        return Response(RuleSerializer(rule).data)


@extend_schema(
    tags=["graph"],
    parameters=[
        OpenApiParameter("address", str, description="Адрес центрального кошелька"),
        OpenApiParameter("wallet_id", int, description="ID центрального кошелька (альтернатива address)"),
        OpenApiParameter("depth", int, description=f"Глубина обхода 1..{MAX_DEPTH} (по умолчанию 1)"),
        OpenApiParameter("limit", int, description=f"Максимум узлов (по умолчанию {DEFAULT_LIMIT}, максимум 200)"),
    ],
    responses=OpenApiResponse(
        description="Эго-сеть кошелька: узлы и рёбра",
        examples=[OpenApiExample("Пример", value={
            "center_id": 25867, "depth": 1, "limit": 60,
            "truncated": False, "total_neighbors": 2, "shown_neighbors": 2,
            "nodes": [{
                "id": 25867, "address": "0xeb55…", "label": None, "label_source": None,
                "risk_level": "MEDIUM", "final_score": 0.0, "graph_score": 76.24,
                "tx_count": 5, "is_center": True, "depth": 0,
            }],
            "edges": [{"source": 25867, "target": 991,
                       "tx_count": 3, "total_amount": "1500000000000000000"}],
        })],
    ),
)
@api_view(["GET"])
def graph_view(request):
    """Эго-сеть кошелька для страницы «Граф потоков».

    Весь граф не отдаётся: центр + соседи на глубину depth, не более limit узлов.
    Если соседей больше лимита — возвращаются самые значимые по объёму потока,
    а в ответе стоит truncated=true с общим числом связей.
    """
    center = resolve_center(request.query_params.get("address"),
                            request.query_params.get("wallet_id"))
    if center is None:
        return Response(
            {"detail": "Кошелёк не найден. Передай address или wallet_id."},
            status=http_status.HTTP_404_NOT_FOUND,
        )

    def _int(name, default):
        try:
            return int(request.query_params.get(name, default))
        except (TypeError, ValueError):
            return default

    center_id, center_address = center
    data = build_ego_network(center_id, _int("depth", 1), _int("limit", DEFAULT_LIMIT))
    data["center_id"] = center_id
    data["center_address"] = center_address
    return Response(data)


def _explain_context(alert: Alert) -> dict:
    """Факты для LLM — снимок готового решения, без права его менять."""
    risk = _related_risk(alert)
    decision = getattr(risk, "decision", None) or {}
    sources = decision.get("sources", {}) or {}
    wallet = alert.wallet

    ctx = {
        "risk_level": decision.get("level") or alert.level.upper(),
        "confidence": decision.get("confidence"),
        "reasons": decision.get("reasons", []),
        "scores": {
            "rule": float(risk.rule_score) if risk else None,
            "ml": float(getattr(risk, "ml_score", 0) or 0) if risk else None,
            "graph": (float(risk.graph_score)
                      if risk and getattr(risk, "graph_score", None) is not None else None),
        },
        "fired_rules": (sources.get("rule", {}) or {}).get("fired", []),
        "ml_explanation": getattr(risk, "ml_explanation", None),
        "graph_explanation": (sources.get("graph", {}) or {}).get("explanation"),
        "hard_signals": (sources.get("hard_signal", {}) or {}).get("items", []),
        "trusted_entity": sources.get("trusted_entity"),
        "labels": {},
        "wallet": {},
        "evidence": {
            "count": alert.evidence_count,
            "first_event_at": str(alert.first_event_at) if alert.first_event_at else None,
            "last_event_at": str(alert.last_event_at) if alert.last_event_at else None,
            "total_amount_eth": round(float(alert.total_amount) / 1e18, 4),
        },
    }
    if wallet:
        ctx["labels"] = {"label": wallet.label, "label_source": wallet.label_source}
        ctx["wallet"] = {
            "address": wallet.address,
            "transaction_count": wallet.transaction_count,
            "total_received_eth": round(float(wallet.total_received) / 1e18, 4),
            "total_sent_eth": round(float(wallet.total_sent) / 1e18, 4),
            "first_seen_at": str(wallet.first_seen_at) if wallet.first_seen_at else None,
            "last_seen_at": str(wallet.last_seen_at) if wallet.last_seen_at else None,
        }
    return ctx


@extend_schema(
    tags=["alerts"],
    request=None,
    responses=OpenApiResponse(
        description="Объяснение решения человеческим языком",
        examples=[OpenApiExample("Пример", value={
            "text": "РЕЗЮМЕ\n…", "lang": "ru", "cached": False,
            "model": "claude-opus-5", "generated_at": "2026-08-10T12:00:00Z",
            "risk_level": "CRITICAL", "disclaimer": "llm_generated",
        })],
    ),
    description=(
        "Объяснение алерта языковой моделью. LLM НЕ участвует в принятии решения "
        "и не влияет на уровень риска — она переформулирует готовое решение "
        "Decision Engine. Результат кэшируется по связке (алерт, язык, версия "
        "решения); при изменении решения генерируется заново. "
        "Тело: {\"lang\": \"ru|kk|en\", \"force\": false}."
    ),
)
@api_view(["POST"])
def explain_alert_view(request, pk: int):
    """Объяснить решение по алерту человеческим языком (LLM)."""
    from collector import db as cdb
    from collector.config import Config as CollectorConfig
    from collector.llm import (
        LLMError, LLMNotConfigured, decision_fingerprint, generate_explanation,
    )

    alert = (
        Alert.objects.select_related(
            "transaction_risk", "wallet_risk", "wallet"
        ).filter(pk=pk).first()
    )
    if alert is None:
        return Response({"detail": "Алерт не найден."},
                        status=http_status.HTTP_404_NOT_FOUND)

    lang = (request.data.get("lang") or "ru").lower()
    if lang not in ("ru", "kk", "en"):
        lang = "ru"
    force = bool(request.data.get("force"))

    try:
        config = CollectorConfig.load()
    except Exception as exc:
        return Response({"detail": f"Ошибка конфигурации: {exc}"},
                        status=http_status.HTTP_503_SERVICE_UNAVAILABLE)

    if not config.llm.enabled:
        return Response(
            {"detail": "LLM не настроена: не задан ANTHROPIC_API_KEY. "
                       "Функция объяснений опциональна — остальная система работает "
                       "как обычно.", "configured": False},
            status=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    context = _explain_context(alert)
    fingerprint = decision_fingerprint(context)

    conn = cdb.connect(config.database_url)
    try:
        if not force:
            cached = cdb.get_alert_explanation(conn, alert.id, lang, fingerprint)
            if cached is not None:
                text, model, generated_at = cached
                return Response({
                    "text": text, "lang": lang, "cached": True, "model": model,
                    "generated_at": generated_at.isoformat(),
                    "risk_level": context["risk_level"], "disclaimer": "llm_generated",
                })

        try:
            text, model = generate_explanation(context, lang, config.llm)
        except LLMNotConfigured as exc:
            return Response({"detail": str(exc), "configured": False},
                            status=http_status.HTTP_503_SERVICE_UNAVAILABLE)
        except LLMError as exc:
            return Response({"detail": str(exc)},
                            status=http_status.HTTP_503_SERVICE_UNAVAILABLE)

        cdb.save_alert_explanation(conn, alert_id=alert.id, lang=lang,
                                   decision_hash=fingerprint, text=text, model=model)
    finally:
        conn.close()

    return Response({
        "text": text, "lang": lang, "cached": False, "model": model,
        "generated_at": timezone.now().isoformat(),
        # Уровень риска возвращается как есть — LLM его не меняла и не могла.
        "risk_level": context["risk_level"], "disclaimer": "llm_generated",
    })


@extend_schema(
    tags=["screening"],
    request=None,
    responses=OpenApiResponse(
        description="Вердикт по адресу",
        examples=[OpenApiExample("Пример", value={
            "address": "0x8589427373d6d84e98730d7795d8f6f8731fdb79",
            "found": True, "no_activity": False,
            "label": "mixer", "label_source": "public_known",
            "risk_level": "MEDIUM", "confidence": 0.6,
            "reasons": ["Правило: Связь с миксером (+40) [сильное правило]"],
            "scores": {"rule": 40.0, "ml": 61.0, "graph": 20.5, "final": 48.4},
            "summary": {"tx_count": 94, "total_received": "1000000000000000000"},
            "tx_fetched": 94, "truncated": False, "cached": False, "elapsed_ms": 4200,
        })],
    ),
    description=(
        "Проверка произвольного Ethereum-адреса. Если адреса нет в базе или у него "
        "мало транзакций — история подтягивается из Etherscan на лету (до SCREEN_MAX_TX), "
        "затем считаются признаки, ML, граф и вердикт Decision Engine. Результат "
        "кэшируется на SCREEN_CACHE_MINUTES; force=true игнорирует кэш. "
        "Тело запроса: {\"address\": \"0x…\", \"force\": false}."
    ),
)
@api_view(["POST"])
def screen_view(request):
    """Скрининг адреса по запросу: сбор данных на лету -> оценка -> вердикт."""
    from collector.config import Config as CollectorConfig
    from collector.screening import ScreeningError, is_valid_address, screen_address

    address = (request.data.get("address") or "").strip()
    if not is_valid_address(address):
        return Response(
            {"detail": "Неверный формат адреса. Ожидается 0x и 40 hex-символов "
                       "(например 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045)."},
            status=http_status.HTTP_400_BAD_REQUEST,
        )

    try:
        config = CollectorConfig.load()
    except Exception as exc:
        return Response({"detail": f"Ошибка конфигурации сборщика: {exc}"},
                        status=http_status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        result = screen_address(address, config, force=bool(request.data.get("force")))
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
    except ScreeningError as exc:
        # Лимит/недоступность Etherscan — это не 500, а понятный ответ пользователю.
        return Response({"detail": str(exc)},
                        status=http_status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(result)


@extend_schema(
    tags=["screening"],
    responses=OpenApiResponse(description="Последние проверенные адреса"),
)
@api_view(["GET"])
def screen_history_view(request):
    """История последних проверок (для панели «Недавние» на странице скрининга)."""
    from collector import db as cdb
    from collector.config import Config as CollectorConfig

    try:
        config = CollectorConfig.load()
        conn = cdb.connect(config.database_url)
    except Exception as exc:
        return Response({"detail": f"Нет доступа к базе: {exc}"},
                        status=http_status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        rows = cdb.get_recent_screenings(conn, limit=10)
    finally:
        conn.close()

    return Response({"results": [
        {
            "address": address,
            "risk_level": (result or {}).get("risk_level", "LOW"),
            "label": (result or {}).get("label"),
            "last_screened_at": last_at.isoformat(),
        }
        for address, result, last_at in rows
    ]})


@extend_schema(
    tags=["stats"],
    responses=OpenApiResponse(
        description="Сводка для дашборда",
        examples=[
            OpenApiExample(
                "Пример",
                value={
                    "total_alerts": 40,
                    "alerts_last_24h": 6,
                    "by_status": {
                        "open": 30, "in_progress": 4,
                        "closed": 4, "false_positive": 2,
                    },
                    "by_level": {"low": 0, "medium": 0, "high": 40},
                    "flagged_wallets": 3,
                },
            )
        ],
    ),
)
@api_view(["GET"])
def stats_view(request):
    """Агрегаты для дашборда аналитика."""
    by_status = {"open": 0, "in_progress": 0, "closed": 0, "false_positive": 0}
    for row in Alert.objects.values("status").annotate(n=Count("id")):
        by_status[row["status"]] = row["n"]

    by_level = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for row in Alert.objects.values("level").annotate(n=Count("id")):
        by_level[row["level"]] = row["n"]

    since = timezone.now() - timedelta(hours=24)

    # Тренд за 14 дней (алертов по дням) — считается на сервере.
    days = 14
    start = timezone.now() - timedelta(days=days - 1)
    trend = [0] * days
    rows = (
        Alert.objects.filter(created_at__gte=start.replace(hour=0, minute=0, second=0, microsecond=0))
        .annotate(day=TruncDate("created_at"))
        .values("day").annotate(n=Count("id"))
    )
    today = timezone.now().date()
    for row in rows:
        idx = days - 1 - (today - row["day"]).days
        if 0 <= idx < days:
            trend[idx] = row["n"]

    return Response(
        {
            "total_alerts": Alert.objects.count(),
            "alerts_last_24h": Alert.objects.filter(created_at__gte=since).count(),
            "by_status": by_status,
            "by_level": by_level,
            "flagged_wallets": Wallet.objects.filter(is_flagged=True).count(),
            "trend": trend,
        }
    )
