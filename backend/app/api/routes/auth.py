"""Google OAuth and session auth routes."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import get_optional_user
from app.config import Settings, get_settings
from app.db.mongo import get_db
from app.schemas.auth import AuthMeResponse, UserPublic
from app.services.auth_service import upsert_google_user
from app.services.session_service import (
    clear_session_cookie,
    consume_oauth_state,
    create_oauth_state,
    create_session,
    delete_session,
    set_session_cookie,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _require_google_oauth(settings: Settings) -> None:
    if not settings.google_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "oauth_not_configured",
                "message": "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET in the backend .env file.",
            },
        )


@router.get("/google/login")
async def google_login(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    _require_google_oauth(settings)
    db = get_db()
    state = await create_oauth_state(db)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_google_oauth(settings)
    frontend = settings.frontend_url.rstrip("/")

    if error:
        logger.warning("Google OAuth error: %s", error)
        return RedirectResponse(url=f"{frontend}/login?error=oauth_denied", status_code=302)

    db = get_db()
    if not code or not await consume_oauth_state(db, state):
        return RedirectResponse(url=f"{frontend}/login?error=invalid_state", status_code=302)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            if token_response.status_code >= 400:
                logger.error("Google token exchange failed: %s", token_response.text)
                return RedirectResponse(url=f"{frontend}/login?error=token_exchange", status_code=302)

            tokens = token_response.json()
            access_token = tokens.get("access_token")
            if not access_token:
                return RedirectResponse(url=f"{frontend}/login?error=token_exchange", status_code=302)

            userinfo_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_response.status_code >= 400:
                logger.error("Google userinfo failed: %s", userinfo_response.text)
                return RedirectResponse(url=f"{frontend}/login?error=userinfo", status_code=302)

            profile = userinfo_response.json()
    except httpx.HTTPError:
        logger.exception("Google OAuth HTTP failure")
        return RedirectResponse(url=f"{frontend}/login?error=oauth_network", status_code=302)

    google_sub = profile.get("sub")
    email = profile.get("email")
    name = profile.get("name") or email or "Google User"
    picture = profile.get("picture")

    if not google_sub or not email:
        return RedirectResponse(url=f"{frontend}/login?error=incomplete_profile", status_code=302)

    user = await upsert_google_user(
        db,
        google_sub=str(google_sub),
        email=str(email),
        name=str(name),
        picture=str(picture) if picture else None,
    )
    session_id = await create_session(db, user["id"], settings)

    response = RedirectResponse(url=f"{frontend}/dashboard", status_code=302)
    set_session_cookie(response, session_id, settings)
    return response


@router.get("/me", response_model=AuthMeResponse)
async def auth_me(user: dict | None = Depends(get_optional_user)) -> AuthMeResponse:
    if user is None:
        return AuthMeResponse(authenticated=False, user=None)
    return AuthMeResponse(
        authenticated=True,
        user=UserPublic(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            picture=user.get("picture"),
            created_at=user["created_at"],
        ),
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    db = get_db()
    session_id = request.cookies.get(settings.session_cookie_name)
    await delete_session(db, session_id)
    payload = JSONResponse({"ok": True})
    clear_session_cookie(payload, settings)
    return payload
