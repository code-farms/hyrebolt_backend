from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuthServiceDep, SettingsDep, rate_limit
from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
# Path-scoped so the browser only sends the refresh token to auth endpoints.
_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_expire_days * 86400,
        path=_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    # Same attributes as set_cookie: browsers only clear an exact match.
    response.delete_cookie(
        REFRESH_COOKIE,
        path=_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserOut,
    dependencies=[rate_limit("auth")],
)
async def register(payload: RegisterRequest, auth: AuthServiceDep) -> UserOut:
    user = await auth.register(email=payload.email, password=payload.password, name=payload.name)
    return UserOut(id=user.id, email=user.email, name=user.name, createdAt=user.createdAt)


@router.post("/login", response_model=AuthResponse, dependencies=[rate_limit("auth")])
async def login(
    payload: LoginRequest,
    auth: AuthServiceDep,
    settings: SettingsDep,
    response: Response,
) -> AuthResponse:
    access, refresh, user = await auth.login(email=payload.email, password=payload.password)
    _set_refresh_cookie(response, settings, refresh)
    return AuthResponse(
        accessToken=access,
        user=UserOut(id=user.id, email=user.email, name=user.name, createdAt=user.createdAt),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    auth: AuthServiceDep,
    settings: SettingsDep,
    response: Response,
) -> TokenResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise UnauthorizedError("No refresh token.", "invalid_token")
    access, new_refresh = await auth.refresh(token)
    _set_refresh_cookie(response, settings, new_refresh)
    return TokenResponse(accessToken=access)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, auth: AuthServiceDep, settings: SettingsDep, response: Response
) -> None:
    await auth.logout(request.cookies.get(REFRESH_COOKIE))
    _clear_refresh_cookie(response, settings)
