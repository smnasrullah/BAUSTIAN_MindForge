import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Bump when the synthetic generator changes; bootstrap regenerates data on mismatch.
DATA_VERSION = "1.0.0"

MIN_JWT_SECRET_BYTES = 32

LlmProvider = Literal["auto", "anthropic", "openai_compatible", "replay", "template"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "AgentPulse AI"
    db_mode: Literal["postgres", "sqlite"] = "postgres"
    database_url: str = "postgresql+psycopg://agentpulse:agentpulse@localhost:5432/agentpulse"
    seed: int = 42
    # Clock (app/core/clock.py). live: data and predictions follow the real time in Asia/Dhaka
    # (hourly tick, catch-up on start). fixed: the frozen SIM_NOW timeline (tests, benchmarks,
    # reproducible evaluation).
    clock_mode: Literal["live", "fixed"] = "live"
    # Live mode only: shift the clock by this many hours (verification of catch-up; keep 0).
    clock_shift_h: float = 0.0
    # Live mode: how often the data clock looks for a new hour (0 turns the loop off).
    data_tick_interval_s: int = 30
    # Catch-up writes at most this many hours per transaction; a gap above the limit
    # regenerates the whole window instead.
    data_catchup_batch_h: int = 24
    data_regen_gap_days: int = 14
    bootstrap_state_file: Path = Path("/tmp/agentpulse_bootstrap_state")
    artifacts_dir: Path = BACKEND_DIR / "ml" / "artifacts"

    # "test" skips the JWT secret length guard (pytest only).
    app_env: str = "production"
    # No usable default: run.bat / run.sh write a random value into .env.
    jwt_secret: SecretStr = SecretStr("")
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 7
    # Refresh cookie: httpOnly, SameSite=Lax, path /api/v1/auth. Set true behind HTTPS.
    refresh_cookie_secure: bool = False
    # Lockout: this many failures per email+IP inside the window blocks that pair for the window.
    login_max_failures: int = 5
    login_lockout_min: int = 15

    # Demo login passwords; values live only in .env (template: .env.example).
    # An empty value skips seeding that role's demo users.
    demo_admin_password: SecretStr = SecretStr("")
    demo_distributor_password: SecretStr = SecretStr("")
    demo_agent_password: SecretStr = SecretStr("")
    # Landing role cards + POST /auth/demo-login (one click, no password, is_demo accounts
    # only). Synthetic data only. MUST be false on any public deployment.
    demo_mode: bool = True
    demo_login_per_min: int = 10  # per client IP

    # Self-signup (POST /auth/signup): pending agent accounts an admin approves. Per client IP.
    signup_per_hour: int = 5
    # Password reset: requests per client IP and per account per hour; link lifetime.
    reset_request_per_hour: int = 5
    reset_per_account_per_hour: int = 3
    reset_token_ttl_min: int = 30
    # "dev_log" writes reset links to the server log (development only; no email is sent).
    mailer: Literal["dev_log"] = "dev_log"
    # Origin the browser uses for the app; reset links point here.
    public_base_url: str = "http://localhost:5173"

    # Browser origins allowed to call the API cross-site. Empty (default): same-origin only,
    # which is how nginx serves the app; no CORS headers are sent at all.
    cors_origins: list[str] = []
    # Per client IP, every /api request / POST /auth/login; then 429 rate_limited.
    api_rate_per_min: int = 1200
    login_rate_per_min: int = 60
    max_body_bytes: int = 1_048_576
    # uvicorn worker processes (entrypoint.sh); the in-process request cap is split across them.
    web_concurrency: int = 1
    # SQLAlchemy pool per worker process. Connections above pool_size are closed when returned,
    # so a pool smaller than the request concurrency reconnects (a Postgres fork) under load.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Server-Timing header with SQL query count/time per request (verify stack, -Perf only).
    perf_headers: bool = False

    # Optional override of app/rules/risk_rules.DEFAULT_CUTS: {"6": [amber, red], ...}.
    risk_thresholds: dict[int, list[float]] = {}
    # ML method switches (docs/DECISIONS.md, ML upgrade). forecast_conformal: serve the
    # validation-calibrated q10-q90 band. stockout_method (the DECISION input, no refill):
    # "independent" = each float alone, fixed rho 0.6 (default: at the unchanged risk cuts it
    # recalls more realised stockouts); "joint" = both floats from one set of paths with the
    # estimated copula and coupled serving (better calibrated, lower recall at the same cuts).
    # The refill-aware view is stored beside either one as an extra reading.
    forecast_conformal: bool = True
    stockout_method: Literal["joint", "independent"] = "independent"
    # app/rules/rebalance_rules.py + swap_rules.py; defaults mirror the rule dataclasses.
    rebalance_horizon_h: int = 24
    rebalance_lead_time_h: float = 3.0
    rebalance_buffer_share: float = 0.10
    rebalance_buffer_min_bdt: float = 2_000.0
    swap_radius_km: float = 5.0
    swap_min_amount_bdt: float = 5_000.0
    # Swap matching (docs/DECISIONS.md, ML upgrade S1): "assignment" = one donor per receiver,
    # distance-minimising (default); "flow" = split a shortage over several donors (MILP) with
    # travel-time windows and a per-donor fairness cap.
    swap_matching: Literal["assignment", "flow"] = "assignment"
    swap_max_receivers_per_donor: int = 2
    swap_max_donors_per_receiver: int = 3
    # app/rules/channel_rules.py (van vs top-up vs self-fetch); assumptions in docs/METHODS.md.
    van_min_batch_amount_bdt: float = 100_000.0
    van_lead_time_h: float = 4.0
    van_cluster_radius_km: float = 10.0
    van_cost_per_trip_bdt: float = 1_500.0
    topup_fee_pct: float = 0.5
    topup_eta_h: float = 0.25
    self_fetch_max_km: float = 10.0
    self_fetch_speed_kmh: float = 15.0
    travel_cost_per_km_bdt: float = 10.0
    urgent_manual_cost_bdt: float = 2_500.0
    # Van route optimizer (app/rules/van_routing, F14). All synthetic assumptions, documented in
    # docs/SYNTHETIC_ASSUMPTIONS.md. Fixed cost per van that leaves: van_cost_per_trip_bdt above.
    van_count: int = Field(default=2, ge=2, le=10)
    van_capacity_bdt: float = 1_500_000.0
    van_cash_cap_bdt: float = 1_500_000.0
    van_shift_h: float = 8.0
    van_cost_per_km_bdt: float = 25.0
    van_cost_per_hour_bdt: float = 200.0
    van_minutes_per_stop: float = 10.0
    van_speed_kmh: float = 25.0
    van_road_factor: float = 1.35
    van_horizon_h: int = 24
    van_time_limit_s: float = 10.0
    van_solution_limit: int = 300
    van_eid_time_factor: float = 1.5
    van_rain_time_factor: float = 1.3
    van_rain_mm: float = 20.0
    van_hat_bazar_time_factor: float = 1.2
    # V3 (should stage): deadline = when P(stockout) reaches the limit; a stop is flagged when
    # P(stockout before the late ETA) is above it. Fairness, safety, ETA range, freeze window.
    van_stockout_p_limit: float = Field(default=0.3, gt=0, lt=1)
    van_fair_max_wait_h: float = Field(default=8.0, gt=0)
    van_fair_min_service_rate: float = Field(default=0.5, ge=0, le=1)
    van_near_optimal_pct: float = Field(default=0.03, ge=0, le=0.2)
    van_eta_lo_factor: float = Field(default=0.85, gt=0, le=1)
    van_eta_hi_factor: float = Field(default=1.3, ge=1)
    van_freeze_min: float = Field(default=30.0, ge=0)
    # app/rules/impact_rules.py (holdout backtest, F11); assumptions in docs/METHODS.md.
    impact_alert_share: float = 0.20
    impact_decision_hours: list[int] = [8, 14, 20]
    impact_cashout_fee_pct: float = 1.85

    # Liquidity help requests: defaults only; admins override them at runtime
    # (app/services/help_settings.py, stored in system_meta).
    help_enabled: bool = True
    help_dry_run: bool = False
    help_claim_timeout_min: int = 20
    help_cooldown_min: int = 30
    help_daily_cap_per_agent: int = 3
    help_max_recipients_per_wave: int = 5
    help_late_confirm_grace_h: int = 24  # expired requests: late delivery confirmable this long
    # Automatic trigger (app/services/help_trigger.py): defaults only, admins override at runtime
    # (app/services/help_settings.py trigger_*). Interval 0 turns the background loop off.
    help_trigger_interval_s: int = 60
    help_trigger_horizon_h: int = 6
    help_trigger_buffer_pct: float = 25.0  # of the agent's own average daily demand
    help_trigger_min_shortfall_bdt: float = 5_000.0
    help_trigger_max_request_bdt: float = 200_000.0
    help_trigger_lead_margin_h: float = 1.0
    help_trigger_radius_km: float = 5.0
    help_trigger_wave_timeout_min: int = 15
    help_trigger_max_waves: int = 3
    help_trigger_recent_ask_h: float = 2.0
    help_trigger_deadline_floor_min: int = 15  # needed_by is never sooner than this
    # Urgent (stock-out sooner than twice the floor): wave 1 asks this many times more agents.
    help_trigger_urgent_wave_multiplier: float = 2.0
    help_trigger_max_new_per_tick: int = 3  # new requests per tick, most urgent first
    # Helper acceptance model (learned from SIMULATED behaviour only; docs/DECISIONS.md). It only
    # orders / sizes waves inside the helper set the rules allow. "rules": the rule score order
    # (default); "learned": highest chance of a yes first. help_wave_sizing: ask the fewest
    # helpers whose chance of at least one yes reaches help_wave_target, never more than the
    # rule's wave size.
    help_rank_model: Literal["rules", "learned"] = "rules"
    help_wave_sizing: bool = False
    help_wave_target: float = 0.9
    # DEMO_MODE: after a FRESH bootstrap (the database was just seeded) the scheduler's first
    # tick waits this long, so a new demo does not open with a burst of requests before anyone
    # is watching. A plain restart does not wait.
    help_scheduler_demo_start_delay_s: int = 120
    # DEMO_MODE: demo defaults for the wave story (small wave 1, short waves, no recent-ask
    # window; app/services/help_settings.py DEMO_*). Admin overrides still win. Off = env defaults.
    help_demo_defaults: bool = True
    # DEMO_MODE: the automatic trigger makes at most this many requests per agent and float in
    # a rolling 24 h (0 = no extra limit). The admin "simulate shortage" is not limited by it.
    help_demo_auto_per_day: int = 1

    llm_provider: LlmProvider = "auto"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_s: float = 8.0
    # Live provider calls (all users, UTC day) and per-user calls per minute; then template.
    llm_daily_call_cap: int = 500
    llm_user_calls_per_min: int = 10
    llm_cache_ttl_h: int = 168
    llm_replay_file: Path = BACKEND_DIR / "app" / "llm" / "cache" / "demo_replay.json"

    def model_post_init(self, __context: object) -> None:
        secret_bytes = len(self.jwt_secret.get_secret_value().encode())
        if self.app_env != "test" and secret_bytes < MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes; "
                "run run.bat / run.sh once to generate .env, or set a random 64-hex value."
            )
        if self.db_mode == "sqlite" and "DATABASE_URL" not in os.environ:
            self.database_url = f"sqlite:///{(BACKEND_DIR / 'agentpulse-local.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
