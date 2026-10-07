from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from app.core.config import Settings, get_settings
from app.core.deps import CurrentUser, SessionDep
from app.core.rate_limit import client_ip
from app.core.shared_limit import SharedRateLimiter
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    DemoLoginRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserOut,
)
from app.services import auth as auth_service
from app.services import mailer, password_reset, signup
from app.services.auth import AuthError, IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])
# Mounted by create_app only when DEMO_MODE=true: with it off the route does not exist.
demo_router = APIRouter(prefix="/auth", tags=["auth"])
demo_limiter = SharedRateLimiter("demo_login")
# Hourly windows, per client IP.
signup_limiter = SharedRateLimiter("signup", window_s=3600)
reset_limiter = SharedRateLimiter("reset", window_s=3600)

REFRESH_COOKIE = "ap_refresh"
# Scoped so the browser only sends the refresh token to the auth endpoints.
REFRESH_COOKIE_PATH = "/api/v1/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE, max_length=512)]


def _set_refresh_cookie(response: Response, tokens: IssuedTokens, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=tokens.refresh_max_age,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.refresh_cookie_secure,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.refresh_cookie_secure,
    )


def _token_response(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=UserOut.model_validate(tokens.user),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    settings = get_settings()
    try:
        tokens = auth_service.login(
            session,
            body.email,
            body.password,
            client_ip(request),
            request.headers.get("user-agent"),
            settings,
        )
    except AuthError as exc:
        if exc.code == "too_many_attempts":
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=exc.code,
                headers={"Retry-After": str(settings.login_lockout_min * 60)},
            ) from exc
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=exc.code) from exc
    _set_refresh_cookie(response, tokens, settings)
    return _token_response(tokens)


DEMO_ERRORS = {"demo_mode_off": status.HTTP_404_NOT_FOUND,
               "demo_login_denied": status.HTTP_403_FORBIDDEN}


@demo_router.post("/demo-login", response_model=TokenResponse)
def demo_login(
    body: DemoLoginRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    """One-click sign-in as a seeded is_demo account (DEMO_MODE only, rate-limited per IP,
    audited). Never enable DEMO_MODE on a public deployment."""
    settings = get_settings()
    ip = client_ip(request)
    if not demo_limiter.allow(ip, settings.demo_login_per_min):
        auth_service.record_demo_attempt(session, body.role, ip, "rate_limited")
        session.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_attempts",
                            headers={"Retry-After": "60"})
    try:
        tokens = auth_service.demo_login(
            session, body.role, ip, request.headers.get("user-agent"), settings
        )
    except AuthError as exc:
        code = DEMO_ERRORS.get(exc.code, status.HTTP_403_FORBIDDEN)
        raise HTTPException(code, detail=exc.code) from exc
    _set_refresh_cookie(response, tokens, settings)
    return _token_response(tokens)


def _too_many() -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_attempts",
                         headers={"Retry-After": "3600"})


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_202_ACCEPTED)
def create_signup(body: SignupRequest, request: Request, session: SessionDep) -> SignupResponse:
    """Self-signup. Always a pending agent account with no agent link (the role is not taken
    from the client); it cannot sign in until an admin approves it. Rate-limited per IP,
    audited (auth.signup). A taken e-mail gets the generic 400 `signup_rejected`."""
    ip = client_ip(request)
    if not signup_limiter.allow(ip, get_settings().signup_per_hour):
        raise _too_many()
    try:
        signup.signup(session, body.full_name, body.email, body.password, ip)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc
    return SignupResponse()


@router.post("/forgot-password", response_model=ForgotPasswordResponse,
             status_code=status.HTTP_202_ACCEPTED)
def forgot_password(body: ForgotPasswordRequest, request: Request,
                    session: SessionDep) -> ForgotPasswordResponse:
    """Same 202 whether or not the e-mail has an account. A single-use link (30 min) goes out
    through the mailer; the development mailer writes it to the server log. Audited."""
    settings = get_settings()
    ip = client_ip(request)
    if not reset_limiter.allow(ip, settings.reset_request_per_hour):
        raise _too_many()
    password_reset.request_reset(session, body.email, ip, settings,
                                 mailer.get_mailer(settings))
    return ForgotPasswordResponse()


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password(body: ResetPasswordRequest, request: Request,
                   session: SessionDep) -> ResetPasswordResponse:
    """Spend a reset token: new password, every session of the user signed out. Unknown, used
    and expired tokens all get 400 `invalid_reset_token`. Audited."""
    ip = client_ip(request)
    if not reset_limiter.allow(("reset", ip), get_settings().reset_request_per_hour * 2):
        raise _too_many()
    try:
        password_reset.reset_password(session, body.token, body.new_password, ip)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc
    return ResetPasswordResponse()


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request, response: Response, session: SessionDep, ap_refresh: RefreshCookie = None
) -> TokenResponse:
    settings = get_settings()
    try:
        tokens = auth_service.refresh(
            session, ap_refresh, request.headers.get("user-agent"), settings
        )
    except AuthError as exc:
        # A JSONResponse is built from the exception, so clear the cookie via headers.
        cleared = Response()
        _clear_refresh_cookie(cleared, settings)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=exc.code,
            headers={"set-cookie": cleared.headers["set-cookie"]},
        ) from exc
    _set_refresh_cookie(response, tokens, settings)
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: SessionDep, ap_refresh: RefreshCookie = None) -> Response:
    """Works with an expired access token: the cookie alone identifies the session."""
    auth_service.logout(session, ap_refresh)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, get_settings())
    return response


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    body: ChangePasswordRequest,
    user: CurrentUser,
    session: SessionDep,
    ap_refresh: RefreshCookie = None,
) -> ChangePasswordResponse:
    try:
        revoked = auth_service.change_password(
            session, user, body.old_password, body.new_password, ap_refresh
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc
    return ChangePasswordResponse(other_sessions_revoked=revoked)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
