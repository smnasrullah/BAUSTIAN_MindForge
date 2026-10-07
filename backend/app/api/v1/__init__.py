from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_clock,
    admin_ops,
    agents,
    anomalies,
    auth,
    copilot,
    events,
    evidence,
    explanations,
    forecast,
    impact,
    liquidity_requests,
    liquidity_trigger,
    llm,
    notifications,
    recommendation_requests,
    recommendations,
    responsible_ai,
    risk,
    risk_map,
    search,
    swaps,
    system,
    users,
    van_plans,
    whatif,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(notifications.router)
api_router.include_router(search.router)
api_router.include_router(admin.router)
api_router.include_router(admin_ops.router)
api_router.include_router(admin_clock.router)
# Before agents: the static /agents/risk must win over /agents/{agent_id}.
api_router.include_router(risk.router)
api_router.include_router(agents.router)
api_router.include_router(forecast.router)
api_router.include_router(whatif.router)
api_router.include_router(explanations.router)
api_router.include_router(events.router)
api_router.include_router(recommendations.router)
api_router.include_router(recommendation_requests.router)
api_router.include_router(swaps.router)
api_router.include_router(van_plans.router)
# Trigger routes first: GET /liquidity-requests/opt-out must not fall into GET /{request_id}.
api_router.include_router(liquidity_trigger.router)
api_router.include_router(liquidity_trigger.admin_router)
api_router.include_router(liquidity_requests.router)
api_router.include_router(liquidity_requests.admin_router)
api_router.include_router(risk_map.router)
api_router.include_router(anomalies.router)
api_router.include_router(impact.router)
api_router.include_router(evidence.router)
api_router.include_router(responsible_ai.router)
api_router.include_router(llm.router)
api_router.include_router(copilot.router)
