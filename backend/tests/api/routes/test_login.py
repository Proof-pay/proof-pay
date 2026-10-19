from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.crud import create_user, get_user_by_email
from app.models import User, UserCreate
from app.utils import generate_oauth_state_token, generate_password_reset_token
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
    ):
        email = "test@example.com"
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }


def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    email = "jVgQr@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/password-recovery/{email}",
        headers=normal_user_token_headers,
    )
    # Should return 200 with generic message to prevent email enumeration attacks
    assert r.status_code == 200
    assert r.json() == {
        "message": "If that email is registered, we sent a password recovery link"
    }


def test_reset_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()

    user_create = UserCreate(
        email=email,
        full_name="Test User",
        password=password,
        is_active=True,
        is_superuser=False,
    )
    user = create_user(session=db, user_create=user_create)
    token = generate_password_reset_token(email=email)
    headers = user_authentication_headers(client=client, email=email, password=password)
    data = {"new_password": new_password, "token": token}

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=headers,
        json=data,
    )

    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}

    db.refresh(user)
    assert user.hashed_password is not None
    verified, _ = verify_password(new_password, user.hashed_password)
    assert verified


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


def test_login_with_bcrypt_password_upgrades_to_argon2(
    client: TestClient, db: Session
) -> None:
    """Test that logging in with a bcrypt password hash upgrades it to argon2."""
    email = random_email()
    password = random_lower_string()

    # Create a bcrypt hash directly (simulating legacy password)
    bcrypt_hasher = BcryptHasher()
    bcrypt_hash = bcrypt_hasher.hash(password)
    assert bcrypt_hash.startswith("$2")  # bcrypt hashes start with $2

    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.hashed_password is not None
    assert user.hashed_password.startswith("$2")

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    # Verify the hash was upgraded to argon2
    assert user.hashed_password is not None
    assert user.hashed_password.startswith("$argon2")

    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    # Should not need another update since it's already argon2
    assert updated_hash is None


def test_login_with_argon2_password_keeps_hash(client: TestClient, db: Session) -> None:
    """Test that logging in with an argon2 password hash does not update it."""
    email = random_email()
    password = random_lower_string()

    # Create an argon2 hash (current default)
    argon2_hash = get_password_hash(password)
    assert argon2_hash.startswith("$argon2")

    # Create user with argon2 hash
    user = User(email=email, hashed_password=argon2_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    original_hash = user.hashed_password

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    assert user.hashed_password is not None
    assert user.hashed_password == original_hash
    assert user.hashed_password.startswith("$argon2")


def test_google_login_not_configured(client: TestClient) -> None:
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", None),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", None),
        patch.object(settings, "FASTAPI_ENV", None),
    ):
        r = client.get(
            f"{settings.API_V1_STR}/login/google",
            follow_redirects=False,
        )
        assert r.status_code == 503
        assert r.json()["detail"] == "Google login is not configured"


def test_google_login_dev_fallback(client: TestClient, db: Session) -> None:
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", None),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", None),
        patch.object(settings, "FASTAPI_ENV", "development"),
    ):
        r = client.get(
            f"{settings.API_V1_STR}/login/google",
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.headers["location"].startswith(
            f"{settings.FRONTEND_HOST}/oauth/callback#access_token="
        )
        user = get_user_by_email(session=db, email="google.demo@example.com")
        assert user is not None
        assert user.google_id == "google-dev-demo-user"


def test_google_login_redirect(client: TestClient) -> None:
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-client-id"),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret"),
    ):
        r = client.get(
            f"{settings.API_V1_STR}/login/google",
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-client-id" in location
        assert "oauth_state" in r.cookies


def test_google_callback_rejects_invalid_state(client: TestClient) -> None:
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-client-id"),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret"),
    ):
        client.cookies.set("oauth_state", "cookie-nonce")
        r = client.get(
            f"{settings.API_V1_STR}/login/google/callback",
            params={"code": "auth-code", "state": "invalid-state"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert (
            r.headers["location"]
            == f"{settings.FRONTEND_HOST}/login?error=invalid_oauth_state"
        )


def test_google_callback_creates_new_user(client: TestClient, db: Session) -> None:
    email = random_email()
    google_id = f"google-{random_lower_string()}"
    nonce = "test-nonce-123"
    state_token = generate_oauth_state_token(nonce)

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google-access-token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": google_id,
        "email": email,
        "email_verified": True,
        "name": "Google Test User",
        "picture": "https://example.com/avatar.png",
    }

    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-client-id"),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret"),
        patch("app.api.routes.login.httpx.Client") as mock_client_cls,
    ):
        mock_http = mock_client_cls.return_value.__enter__.return_value
        mock_http.post.return_value = mock_token_resp
        mock_http.get.return_value = mock_userinfo_resp

        client.cookies.set("oauth_state", nonce)
        r = client.get(
            f"{settings.API_V1_STR}/login/google/callback",
            params={"code": "valid-code", "state": state_token},
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert location.startswith(
            f"{settings.FRONTEND_HOST}/oauth/callback#access_token="
        )

        user = get_user_by_email(session=db, email=email)
        assert user is not None
        assert user.google_id == google_id
        assert user.hashed_password is None
        assert user.full_name == "Google Test User"
        assert user.avatar_url == "https://example.com/avatar.png"


def test_google_callback_links_existing_email_user(
    client: TestClient, db: Session
) -> None:
    email = random_email()
    password = random_lower_string()
    user_create = UserCreate(
        email=email,
        full_name="Existing User",
        password=password,
        is_active=True,
        is_superuser=False,
    )
    existing_user = create_user(session=db, user_create=user_create)
    original_hash = existing_user.hashed_password

    google_id = f"google-{random_lower_string()}"
    nonce = "test-nonce-link"
    state_token = generate_oauth_state_token(nonce)

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google-access-token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": google_id,
        "email": email,
        "email_verified": True,
        "name": "Google Name",
        "picture": "https://example.com/linked.png",
    }

    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-client-id"),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret"),
        patch("app.api.routes.login.httpx.Client") as mock_client_cls,
    ):
        mock_http = mock_client_cls.return_value.__enter__.return_value
        mock_http.post.return_value = mock_token_resp
        mock_http.get.return_value = mock_userinfo_resp

        client.cookies.set("oauth_state", nonce)
        r = client.get(
            f"{settings.API_V1_STR}/login/google/callback",
            params={"code": "valid-code", "state": state_token},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "#access_token=" in r.headers["location"]

        db.refresh(existing_user)
        assert existing_user.google_id == google_id
        assert existing_user.hashed_password == original_hash
        assert existing_user.avatar_url == "https://example.com/linked.png"


def test_google_callback_rejects_unverified_email(
    client: TestClient, db: Session
) -> None:
    email = random_email()
    nonce = "test-nonce-unverified"
    state_token = generate_oauth_state_token(nonce)

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google-access-token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-unverified-123",
        "email": email,
        "email_verified": False,
    }

    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-client-id"),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret"),
        patch("app.api.routes.login.httpx.Client") as mock_client_cls,
    ):
        mock_http = mock_client_cls.return_value.__enter__.return_value
        mock_http.post.return_value = mock_token_resp
        mock_http.get.return_value = mock_userinfo_resp

        client.cookies.set("oauth_state", nonce)
        r = client.get(
            f"{settings.API_V1_STR}/login/google/callback",
            params={"code": "valid-code", "state": state_token},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert (
            r.headers["location"]
            == f"{settings.FRONTEND_HOST}/login?error=unverified_google_email"
        )
        assert get_user_by_email(session=db, email=email) is None


def test_google_only_user_cannot_login_with_password(
    client: TestClient, db: Session
) -> None:
    email = random_email()
    user = User(
        email=email,
        google_id=f"google-{random_lower_string()}",
        hashed_password=None,
        is_active=True,
    )
    db.add(user)
    db.commit()

    login_data = {"username": email, "password": "somepassword123"}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400
    assert r.json()["detail"] == "Incorrect email or password"

