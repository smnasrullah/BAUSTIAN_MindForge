"""Python enums mirrored as PostgreSQL enum types (names in PG_ENUM_NAMES)."""

from enum import StrEnum


class UserRole(StrEnum):
    agent = "agent"
    distributor = "distributor"
    admin = "admin"


class UrbanRural(StrEnum):
    urban = "urban"
    peri_urban = "peri_urban"
    rural = "rural"


class FloatType(StrEnum):
    cash = "cash"
    emoney = "emoney"


class TxnType(StrEnum):
    cash_in = "cash_in"
    cash_out = "cash_out"


# Demand that draws each float down: cash <- cash_out, e-money <- cash_in.
FLOAT_DEMAND: dict[FloatType, TxnType] = {FloatType.cash: TxnType.cash_out,
                                          FloatType.emoney: TxnType.cash_in}


class EventType(StrEnum):
    salary = "salary"
    eid = "eid"
    hat_bazar = "hat_bazar"
    weather = "weather"
    holiday = "holiday"


class RiskLevelCode(StrEnum):
    green = "green"
    amber = "amber"
    red = "red"


class RecommendationKind(StrEnum):
    add_cash = "add_cash"
    add_emoney = "add_emoney"
    swap = "swap"
    van = "van"


class RecommendationStatus(StrEnum):
    open = "open"
    requested = "requested"
    done = "done"
    expired = "expired"


class RecommendationChannel(StrEnum):
    """How the money would reach the agent (app/rules/channel_rules.py)."""

    swap = "swap"
    top_up = "top_up"
    van = "van"
    self_fetch = "self_fetch"
    urgent_manual = "urgent_manual"


class RequestStatus(StrEnum):
    requested = "requested"
    approved = "approved"
    declined = "declined"
    fulfilled = "fulfilled"
    cancelled = "cancelled"


class SwapStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class SwapResponse(StrEnum):
    accepted = "accepted"
    declined = "declined"


class HelpStatus(StrEnum):
    """Liquidity help request; transitions live in app/rules/help_request_rules.py."""

    open = "open"
    claimed = "claimed"
    fulfilled = "fulfilled"
    expired = "expired"
    cancelled = "cancelled"


class HelpResponse(StrEnum):
    """One recipient's answer to a help request."""

    none = "none"
    accepted = "accepted"
    declined = "declined"
    expired = "expired"
    superseded = "superseded"


class HelpOrigin(StrEnum):
    system = "system"
    user = "user"


class HelpReasonCategory(StrEnum):
    """The only part of a help request's reason a helper sees (no numbers, no balances)."""

    salary_day = "salary_day"
    eid = "eid"
    holiday = "holiday"
    market_day = "market_day"
    weather = "weather"
    high_demand = "high_demand"
    unknown = "unknown"


class AnomalyStatus(StrEnum):
    open = "open"
    confirmed = "confirmed"
    dismissed = "dismissed"


class ImpactScenario(StrEnum):
    model = "model"
    baseline = "baseline"


class LlmIntent(StrEnum):
    copilot = "copilot"
    narrate = "narrate"
    agent_briefing = "agent_briefing"
    distributor_briefing = "distributor_briefing"
    anomaly_narrative = "anomaly_narrative"
    van_narrative = "van_narrative"


class GeneratedBy(StrEnum):
    llm = "llm"
    template = "template"
    replay = "replay"


class GuardResult(StrEnum):
    passed = "pass"
    numbers_fail = "numbers_fail"
    injection = "injection"
    schema_fail = "schema_fail"
    timeout = "timeout"
    error = "error"


class Lang(StrEnum):
    bn = "bn"
    en = "en"


class Theme(StrEnum):
    light = "light"
    dark = "dark"
    system = "system"


class ChatRole(StrEnum):
    user = "user"
    assistant = "assistant"


class NotificationType(StrEnum):
    risk_change = "risk_change"
    swap_offer = "swap_offer"
    swap_decision = "swap_decision"
    anomaly = "anomaly"
    system = "system"
    help_request = "help_request"


class NotificationSeverity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


PG_ENUM_NAMES: dict[type[StrEnum], str] = {
    UserRole: "user_role",
    UrbanRural: "urban_rural",
    FloatType: "float_type",
    TxnType: "txn_type",
    EventType: "event_type",
    RiskLevelCode: "risk_level",
    RecommendationKind: "recommendation_kind",
    RecommendationStatus: "recommendation_status",
    RecommendationChannel: "recommendation_channel",
    RequestStatus: "request_status",
    SwapStatus: "swap_status",
    SwapResponse: "swap_response",
    HelpStatus: "help_status",
    HelpResponse: "help_response",
    HelpOrigin: "help_origin",
    HelpReasonCategory: "help_reason_category",
    AnomalyStatus: "anomaly_status",
    ImpactScenario: "impact_scenario",
    LlmIntent: "llm_intent",
    GeneratedBy: "generated_by",
    GuardResult: "guard_result",
    Lang: "lang_code",
    ChatRole: "chat_role",
    Theme: "theme_pref",
    NotificationType: "notification_type",
    NotificationSeverity: "notification_severity",
}
