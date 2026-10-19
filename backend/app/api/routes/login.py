import secrets
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core import security
from app.core.config import settings
from app.models import Message, NewPassword, Token, UserPublic, UserUpdate
from app.utils import (
    generate_oauth_state_token,
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_oauth_state_token,
    verify_password_reset_token,
)

router = APIRouter(tags=["login"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
OAUTH_STATE_COOKIE = "oauth_state"


@router.post("/login/access-token")
def login_access_token(
    session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    user = crud.authenticate(
        session=session, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
    )


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    """
    Test access token
    """
    return current_user


@router.post("/password-recovery/{email}")
def recover_password(email: str, session: SessionDep) -> Message:
    """
    Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email)

    # Always return the same response to prevent email enumeration attacks
    # Only send email if user actually exists
    if user:
        password_reset_token = generate_password_reset_token(email=email)
        email_data = generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
        send_email(
            email_to=user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """
    Reset password
    """
    email = verify_password_reset_token(token=body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    user = crud.get_user_by_email(session=session, email=email)
    if not user:
        # Don't reveal that the user doesn't exist - use same error as invalid token
        raise HTTPException(status_code=400, detail="Invalid token")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    user_in_update = UserUpdate(password=body.new_password)
    crud.update_user(
        session=session,
        db_user=user,
        user_in=user_in_update,
    )
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """
    HTML Content for Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    password_reset_token = generate_password_reset_token(email=email)
    email_data = generate_reset_password_email(
        email_to=user.email, email=email, token=password_reset_token
    )

    return HTMLResponse(
        content=email_data.html_content, headers={"subject:": email_data.subject}
    )


@router.get("/login/google")
def login_google(session: SessionDep) -> RedirectResponse:
    """
    Initiate Google OAuth 2.0 authorization code flow.
    In local development when Google credentials are not set, falls back to a demo Google user.
    """
    if not settings.google_oauth_enabled or not settings.GOOGLE_CLIENT_ID:
        if settings.FASTAPI_ENV == "development":
            user = crud.upsert_google_user(
                session=session,
                google_id="google-dev-demo-user",
                email="google.demo@example.com",
                full_name="Google Demo User",
                avatar_url=None,
            )
            if not user.is_active:
                return _redirect_login_error("inactive_user")
            access_token_expires = timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
            access_token = security.create_access_token(
                user.id, expires_delta=access_token_expires
            )
            redirect_url = (
                f"{settings.FRONTEND_HOST}/oauth/callback"
                f"#access_token={access_token}&token_type=bearer"
            )
            return RedirectResponse(url=redirect_url, status_code=302)
        raise HTTPException(
            status_code=503,
            detail="Google login is not configured",
        )
    nonce = secrets.token_urlsafe(32)
    state_token = generate_oauth_state_token(nonce)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.effective_google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state_token,
        "access_type": "online",
        "prompt": "select_account",
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=nonce,
        max_age=300,
        httponly=True,
        samesite="lax",
        secure=settings.FASTAPI_ENV != "development",
    )
    return response


def _redirect_login_error(error_code: str) -> RedirectResponse:
    response = RedirectResponse(
        url=f"{settings.FRONTEND_HOST}/login?error={error_code}",
        status_code=302,
    )
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


@router.get("/login/google/callback")
def login_google_callback(
    session: SessionDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """
    Handle Google OAuth 2.0 callback, upsert/link user, and redirect to frontend with access token.
    """
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status_code=503,
            detail="Google login is not configured",
        )

    if error or not code or not state:
        return _redirect_login_error("google_auth_cancelled")

    if not oauth_state or not verify_oauth_state_token(state, oauth_state):
        return _redirect_login_error("invalid_oauth_state")

    try:
        with httpx.Client(timeout=10.0) as client:
            token_resp = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.effective_google_redirect_uri,
                },
            )
            if token_resp.status_code != 200:
                return _redirect_login_error("google_token_exchange_failed")
            token_data = token_resp.json()
            google_access_token = token_data.get("access_token")
            if not google_access_token:
                return _redirect_login_error("google_token_exchange_failed")

            userinfo_resp = client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {google_access_token}"},
            )
            if userinfo_resp.status_code != 200:
                return _redirect_login_error("google_userinfo_failed")
            userinfo = userinfo_resp.json()
    except httpx.HTTPError:
        return _redirect_login_error("google_network_error")

    google_id = userinfo.get("sub")
    email = userinfo.get("email")
    email_verified = userinfo.get("email_verified")
    full_name = userinfo.get("name")
    avatar_url = userinfo.get("picture")

    if not google_id or not email or email_verified is not True:
        return _redirect_login_error("unverified_google_email")

    user = crud.upsert_google_user(
        session=session,
        google_id=str(google_id),
        email=str(email),
        full_name=str(full_name) if full_name else None,
        avatar_url=str(avatar_url) if avatar_url else None,
    )

    if not user.is_active:
        return _redirect_login_error("inactive_user")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        user.id, expires_delta=access_token_expires
    )

    redirect_url = (
        f"{settings.FRONTEND_HOST}/oauth/callback"
        f"#access_token={access_token}&token_type=bearer"
    )
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response

