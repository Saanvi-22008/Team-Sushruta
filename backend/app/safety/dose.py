"""Server-enforced light-dose safety decision (pure, deny-closed).

``decide(wound_id, request, grant_history, status, config, now)`` is a PURE
function: it reads the hard caps ONLY from ``config`` (never from the request
body) and returns a :class:`DoseDecision`. The HTTP layer runs it under a
per-wound lock inside a DB transaction so a racing request evaluates the caps
against the committed grant record (invariant #6).

Deny-closed order (first failing check wins; a lack of information is never a
reason to grant):

1. Config not loaded                -> deny (fail-safe, maps to 503).
2. Status escalate / active red flag -> deny, direct to care.
3. requested_dose_mj > max_dose_mj   -> deny (enforced limit; silent clamp ONLY
   if ``config.dose.clamp`` is true).
4. requested_duration_s > max_session_s -> deny (same clamp rule).
5. time since last grant < min_gap_s -> deny (return remaining gap).
6. daily / cumulative session cap exceeded -> deny.
7. otherwise                         -> grant.

Limits are read ONLY from config; the request body supplies only the two
requested parameters (DoseRequestIn is ``extra='forbid'``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a naive datetime to UTC (SQLite round-trips drop tzinfo)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

from app.core.config import DoseLimits, SafetyConfig

# Outcome values recorded on the dose_requests row.
OUTCOME_GRANTED = "granted"
OUTCOME_DENIED = "denied"

# Deny reason codes (stable, machine-readable).
REASON_CONFIG_FAILSAFE = "config_failsafe"
REASON_ESCALATE = "escalate_or_red_flag"
REASON_OVER_DOSE = "over_max_dose"
REASON_OVER_SESSION = "over_max_session"
REASON_WITHIN_GAP = "within_min_gap"
REASON_DAILY_CAP = "daily_cap_exceeded"


@dataclass(frozen=True)
class DoseDecision:
    """Immutable outcome of a dose-safety evaluation.

    ``config_failsafe`` is True only when the safety config is unavailable; the
    HTTP layer maps that to 503 (rather than a 409 denial).
    """

    outcome: str  # granted | denied
    reason_code: Optional[str]
    reason: str
    enforced_limits: dict
    granted_params: Optional[dict] = None
    next_allowed_at: Optional[datetime] = None
    config_failsafe: bool = False

    @property
    def granted(self) -> bool:
        return self.outcome == OUTCOME_GRANTED


def _resolve_dose_limits(config: Any) -> Optional[DoseLimits]:
    """Return the DoseLimits, or None when the config is in fail-safe."""
    if isinstance(config, SafetyConfig):
        if not config.loaded or config.dose is None:
            return None
        return config.dose
    return config  # already a DoseLimits


def _enforced(limits: DoseLimits) -> dict:
    return {
        "max_dose_mj": limits.max_dose_mj,
        "max_session_s": limits.max_session_s,
        "min_gap_s": limits.min_gap_s,
        "max_daily_sessions": limits.max_daily_sessions,
        "clamp": limits.clamp,
        "block_on_escalate": limits.block_on_escalate,
    }


def _latest_grant_ts(grant_history: Sequence[Any]) -> Optional[datetime]:
    """Most recent granted request timestamp, if any."""
    best: Optional[datetime] = None
    for g in grant_history:
        ts = _aware(getattr(g, "requested_at", None))
        if ts is None:
            continue
        if best is None or ts > best:
            best = ts
    return best


def _grants_in_last_day(grant_history: Sequence[Any], now: datetime) -> int:
    cutoff = now - timedelta(days=1)
    count = 0
    for g in grant_history:
        ts = _aware(getattr(g, "requested_at", None))
        if ts is not None and ts > cutoff:
            count += 1
    return count


def _status_blocks(status: Any, block_on_escalate: bool) -> bool:
    """True when the current status should block a dose (escalate / red flag).

    Accepts a StatusResult-like object, a mapping, or None. A missing status is
    NOT treated as safe when blocking is enabled: without a status we cannot
    confirm it is safe to dose, so we block (deny-closed).
    """
    if not block_on_escalate:
        return False
    if status is None:
        return True
    level = getattr(status, "level", None)
    red_flags = getattr(status, "red_flags", None)
    if level is None and isinstance(status, dict):
        level = status.get("level")
        red_flags = status.get("red_flags")
    if level == "escalate":
        return True
    if red_flags:
        return True
    return False


def decide(
    wound_id: str,
    request: Any,
    grant_history: Sequence[Any],
    status: Any,
    config: Any,
    now: datetime,
) -> DoseDecision:
    """Evaluate a dose request against the server-side caps (deny-closed).

    Parameters
    ----------
    request:
        A :class:`~app.core.schemas.DoseRequestIn` (or any object exposing
        ``requested_dose_mj`` / ``requested_duration_s``). NO cap/threshold is
        read from here.
    grant_history:
        Previously GRANTED dose requests for this wound (objects with a
        ``requested_at`` datetime), used for the gap + daily-cap checks.
    status:
        The current wound status (StatusResult-like or mapping). Escalate / an
        active red flag blocks when ``config.block_on_escalate`` is set.
    now:
        Injected clock (the only time source).
    """
    limits = _resolve_dose_limits(config)

    # 1. Config fail-safe -> deny-closed (HTTP 503).
    if limits is None:
        return DoseDecision(
            outcome=OUTCOME_DENIED,
            reason_code=REASON_CONFIG_FAILSAFE,
            reason=(
                "Safety configuration is unavailable, so no dose can be "
                "authorised. Please try again later or seek care if concerned."
            ),
            enforced_limits={},
            config_failsafe=True,
        )

    enforced = _enforced(limits)
    requested_dose = float(getattr(request, "requested_dose_mj"))
    requested_duration = float(getattr(request, "requested_duration_s"))

    # 2. Escalate / red flag -> deny, direct to care.
    if _status_blocks(status, limits.block_on_escalate):
        return DoseDecision(
            outcome=OUTCOME_DENIED,
            reason_code=REASON_ESCALATE,
            reason=(
                "The current wound status needs attention (escalation or a red "
                "flag), so light therapy is not authorised right now. Please "
                "seek care."
            ),
            enforced_limits=enforced,
        )

    # 3. Over max dose. Silent clamp ONLY when config.clamp is true.
    if requested_dose > limits.max_dose_mj:
        if not limits.clamp:
            return DoseDecision(
                outcome=OUTCOME_DENIED,
                reason_code=REASON_OVER_DOSE,
                reason=(
                    f"Requested dose {requested_dose} mJ exceeds the maximum "
                    f"allowed {limits.max_dose_mj} mJ."
                ),
                enforced_limits=enforced,
            )
        requested_dose = limits.max_dose_mj

    # 4. Over max session. Silent clamp ONLY when config.clamp is true.
    if requested_duration > limits.max_session_s:
        if not limits.clamp:
            return DoseDecision(
                outcome=OUTCOME_DENIED,
                reason_code=REASON_OVER_SESSION,
                reason=(
                    f"Requested duration {requested_duration} s exceeds the "
                    f"maximum allowed {limits.max_session_s} s."
                ),
                enforced_limits=enforced,
            )
        requested_duration = limits.max_session_s

    # 5. Minimum gap since the last granted session.
    last_grant = _latest_grant_ts(grant_history)
    if last_grant is not None:
        elapsed = (now - last_grant).total_seconds()
        if elapsed < limits.min_gap_s:
            remaining = limits.min_gap_s - elapsed
            next_allowed = last_grant + timedelta(seconds=limits.min_gap_s)
            return DoseDecision(
                outcome=OUTCOME_DENIED,
                reason_code=REASON_WITHIN_GAP,
                reason=(
                    f"Too soon since the last session; please wait "
                    f"{int(remaining)} more seconds."
                ),
                enforced_limits={**enforced, "remaining_gap_s": remaining},
                next_allowed_at=next_allowed,
            )

    # 6. Daily / cumulative cap.
    if _grants_in_last_day(grant_history, now) >= limits.max_daily_sessions:
        return DoseDecision(
            outcome=OUTCOME_DENIED,
            reason_code=REASON_DAILY_CAP,
            reason=(
                f"Daily session limit of {limits.max_daily_sessions} reached; "
                "no further sessions today."
            ),
            enforced_limits=enforced,
        )

    # 7. Grant.
    next_allowed = now + timedelta(seconds=limits.min_gap_s)
    return DoseDecision(
        outcome=OUTCOME_GRANTED,
        reason_code=None,
        reason="Dose authorised within the configured safety limits.",
        enforced_limits=enforced,
        granted_params={
            "dose_mj": requested_dose,
            "duration_s": requested_duration,
            "granted_at": now.astimezone(timezone.utc).isoformat(),
        },
        next_allowed_at=next_allowed,
    )
