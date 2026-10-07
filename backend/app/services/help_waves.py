"""Wave advance: once an open request's current wave has waited a full timeout, the next wave goes.

Safe to run repeatedly and from several workers: the wave number moves with one conditional
UPDATE (status open AND wave_number = N). Only the worker whose UPDATE matched writes the new
recipients and notifies; every other worker matches no row and does nothing. Earlier recipients
stay on the request and are told it is still open. When no wave is left, or nobody is left to
ask, the request is exhausted: expired unfilled, and the distributor and admins are escalated.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.models import Agent, AuditLog, LiquidityRequest, LiquidityRequestRecipient
from app.models.enums import HelpResponse, HelpStatus, NotificationSeverity
from app.rules.help_request_rules import HelpPolicy
from app.rules.help_trigger_rules import TriggerPolicy
from app.services import help_notify, help_settings
from app.services import help_trigger as trig
from app.services import liquidity_requests as help_requests
from app.services.forecast import _utc

R = LiquidityRequestRecipient
log = logging.getLogger(__name__)


def advance_due(now: datetime) -> tuple[int, int]:
    """(advanced, exhausted) over open requests whose current wave has waited long enough."""
    with Session(get_engine()) as s:
        tp, hp = help_settings.trigger_current(s), help_settings.current(s)
        if not hp.enabled or hp.dry_run:  # kill switch or dry run: nothing is sent or changed
            return 0, 0
        cutoff = now - timedelta(minutes=tp.wave_timeout_min)
        ids = s.scalars(select(LiquidityRequest.id).where(
            LiquidityRequest.status == HelpStatus.open,
            func.coalesce(LiquidityRequest.wave_started_at, LiquidityRequest.created_at) <= cutoff
        ).order_by(LiquidityRequest.id)).all()
    advanced = exhausted = 0
    for request_id in ids:
        outcome = _advance_one(request_id, now)
        advanced += outcome == "advanced"
        exhausted += outcome == "exhausted"
    return advanced, exhausted


def _advance_one(request_id: int, now: datetime) -> str:
    """'advanced', 'exhausted' or 'skipped' (already moved on by someone else, or not due)."""
    with Session(get_engine()) as s, s.begin():
        req = s.get(LiquidityRequest, request_id)
        if req is None or req.status != HelpStatus.open:
            return "skipped"
        tp, hp = help_settings.trigger_current(s), help_settings.current(s)
        started = _utc(req.wave_started_at or req.created_at)
        if started > now - timedelta(minutes=tp.wave_timeout_min):
            return "skipped"
        if req.wave_number < tp.max_waves:
            members = _next_members(s, req, now, tp, hp)
            if members:
                return _send_wave(s, req, members, now, hp)
        return "exhausted" if help_requests.exhaust(s, request_id, now) else "skipped"


def _next_members(s: Session, req: LiquidityRequest, now: datetime, tp: TriggerPolicy,
                  hp: HelpPolicy) -> list[trig.Ask]:
    """Distributors not asked yet, plus the next best agents up to the wave size."""
    requester = s.get(Agent, req.requester_agent_id)
    if requester is None:
        return []
    already = set(s.scalars(select(R.recipient_user_id).where(R.request_id == req.id)))
    pool = trig.ranked_helpers(s, requester, req.float_type, float(req.amount_needed), now, tp,
                               trig.signals(s, now, tp, None), already)
    return pool.distributors + pool.wave(hp.max_recipients_per_wave)


def _send_wave(s: Session, req: LiquidityRequest, members: list[trig.Ask], now: datetime,
               hp: HelpPolicy) -> str:
    wave = req.wave_number + 1
    moved = s.execute(update(LiquidityRequest).where(
        LiquidityRequest.id == req.id, LiquidityRequest.status == HelpStatus.open,
        LiquidityRequest.wave_number == req.wave_number)
        .values(wave_number=wave, wave_started_at=now, updated_at=now)
        .execution_options(synchronize_session=False))
    if int(getattr(moved, "rowcount", 0) or 0) != 1:
        return "skipped"  # another worker sent this wave first
    earlier = help_notify.recipients_with(s, req, (HelpResponse.none, HelpResponse.superseded))
    for m in members:
        s.add(R(request_id=req.id, recipient_user_id=m.user_id, recipient_role=m.role,
                wave_number=wave, notified_at=now, response=HelpResponse.none,
                distance_km=Decimal(str(round(m.distance_km, 2)))))
    s.add(AuditLog(user_id=None, action="liquidity_request.wave", entity_type="liquidity_request",
                   entity_id=str(req.id), note=None,
                   payload={"wave": wave, "asked": len(members), "at": now.isoformat()}))
    s.flush()
    help_notify.send(s, hp, req, [m.user_id for m in members], "new", None,
                     NotificationSeverity.warning)
    help_notify.send(s, hp, req, earlier | help_notify.requester_users(s, req), "still_open")
    log.info("help request %d: wave %d sent to %d helpers", req.id, wave, len(members))
    return "advanced"
