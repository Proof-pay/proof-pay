# Implementation Plan: Login with Google

This plan details the step-by-step tasks required to implement the [Google Login Specification](./google-login-spec.md).

---

## Phase 1: Database Schema & Models

### 1.1 Update SQLModel User Definitions
- **File**: [`backend/app/models.py`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/backend/app/models.py#L23-L83)
- **Changes**:
  - In `User` table model:
    - Change `hashed_password: str` to `hashed_password: str | None = Field(default=None)`
    - Add `google_id: str | None = Field(default=None, unique=True, index=True, max_length=255)`
    - Add `avatar_url: str | None = Field(default=None, max_length=512)`
  - In `UserPublic`:
    - Add `avatar_url: str | None = None`
    - Add `google_linked: bool = False` and `has_password: bool = True` (or populate via validator/property on `User`)

### 1.2 Generate & Apply Alembic Migration
- **Directory**: `backend/app/alembic/versions/`
- **Commands**:
  ```bash
  uv run --directory backend alembic revision --autogenerate -m "add google oauth fields to user"
  uv run --directory backend alembic upgrade head
  ```
- **Verify migration script**:
  - `op.alter_column('user', 'hashed_password', existing_type=sa.VARCHAR(), nullable=True)`
  - `op.add_column('user', sa.Column('google_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True))`
  - `op.add_column('user', sa.Column('avatar_url', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True))`
  - `op.create_index(op.f('ix_user_google_id'), 'user', ['google_id'], unique=True)`

---

## Phase 2: Backend Configuration & CRUD Logic

### 2.1 Add Google OAuth Settings
- **File**: [`backend/app/core/config.py`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/backend/app/core/config.py)
- **Changes**:
  - Add `GOOGLE_CLIENT_ID: str | None = None`
  - Add `GOOGLE_CLIENT_SECRET: str | None = None`
  - Add `GOOGLE_REDIRECT_URI: str | None = None`
  - Add `@computed_field` property `google_oauth_enabled(self) -> bool` returning `bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)`
  - Add `@computed_field` property `effective_google_redirect_uri(self) -> str` returning `self.GOOGLE_REDIRECT_URI or f"http://localhost:8000{self.API_V1_STR}/login/google/callback"`
- **File**: [`.env`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/.env) & [`compose.yml`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/compose.yml)
  - Document `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` placeholders.

### 2.2 Update CRUD Functions for Google Auth & Nullable Passwords
- **File**: [`backend/app/crud.py`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/backend/app/crud.py#L34-L60)
- **Changes**:
  - Update `authenticate()`:
    - If `not db_user or not db_user.hashed_password`: run `verify_password(password, DUMMY_HASH)` and return `None`.
  - Add `get_user_by_google_id(*, session: Session, google_id: str) -> User | None`.
  - Add `upsert_google_user(*, session: Session, google_id: str, email: str, full_name: str | None, avatar_url: str | None) -> User`:
    1. Look up user by `google_id`. If found, update `avatar_url` (and `full_name` if empty), commit, and return.
    2. Else look up user by `email`. If found, link `user.google_id = google_id`, update `avatar_url` (and `full_name` if empty), commit, and return.
    3. Else create a new `User(email=email, full_name=full_name, google_id=google_id, avatar_url=avatar_url, hashed_password=None, is_active=True, is_superuser=False)`, commit, refresh, and return.

### 2.3 Guard Password Change Endpoint for Passwordless Users
- **File**: [`backend/app/api/routes/users.py`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/backend/app/api/routes/users.py#L103-L122)
- **Changes**:
  - In `update_password_me`: check `if not current_user.hashed_password:` before calling `verify_password`, raising `HTTPException(status_code=400, detail="User does not have a password set")`.

---

## Phase 3: Backend OAuth 2.0 Endpoints

### 3.1 State Token Helpers
- **File**: [`backend/app/utils.py`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/backend/app/utils.py)
- **Changes**:
  - Add `generate_oauth_state_token(nonce: str) -> str`: signs a JWT with `{"sub": nonce, "type": "google_oauth_state", "exp": now + 5m}`.
  - Add `verify_oauth_state_token(token: str, expected_nonce: str) -> bool`: verifies JWT signature, expiration, `"type" == "google_oauth_state"`, and `"sub" == expected_nonce`.

### 3.2 Google Login & Callback Routes
- **File**: [`backend/app/api/routes/login.py`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/backend/app/api/routes/login.py)
- **Changes**:
  - `GET /login/google`:
    - Check `settings.google_oauth_enabled`; raise `503` if not configured.
    - Generate random `nonce = secrets.token_urlsafe(32)` and `state = generate_oauth_state_token(nonce)`.
    - Build Google authorization URL (`https://accounts.google.com/o/oauth2/v2/auth`) using `urllib.parse.urlencode`.
    - Return `RedirectResponse(url=google_auth_url, status_code=302)` with `oauth_state` cookie (`httponly=True`, `samesite="lax"`, `max_age=300`, `secure=settings.FASTAPI_ENV != "development"`).
  - `GET /login/google/callback`:
    - Validate `error`, `code`, `state`, and `oauth_state` cookie.
    - Exchange `code` at `https://oauth2.googleapis.com/token` via `httpx.Client(timeout=10.0)`.
    - Fetch user info from `https://openidconnect.googleapis.com/v1/userinfo`.
    - Verify `userinfo.get("email_verified") is True` and `userinfo.get("sub")` and `userinfo.get("email")`.
    - Call `crud.upsert_google_user(...)`.
    - Verify `user.is_active`.
    - Issue ProofPay JWT via `security.create_access_token(user.id, expires_delta=...)`.
    - Redirect to `f"{settings.FRONTEND_HOST}/oauth/callback#access_token={jwt_token}&token_type=bearer"` and delete `oauth_state` cookie.

---

## Phase 4: Frontend Implementation

### 4.1 Regenerate OpenAPI Client (if applicable)
- Run `./scripts/generate-client.sh` or `bun run generate-client` in `frontend/` so updated `UserPublic` fields (`avatar_url`, `google_linked`, `has_password`) are typed in [`frontend/src/client/types.gen.ts`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/frontend/src/client/types.gen.ts).

### 4.2 Create `GoogleLoginButton` Component
- **File**: `frontend/src/components/Common/GoogleLoginButton.tsx`
- **Details**:
  - Renders an outline button with the Google SVG logo and `"Continue with Google"`.
  - Redirects browser to `${import.meta.env.VITE_API_URL || ""}/api/v1/login/google`.

### 4.3 Create `/oauth/callback` Route
- **File**: `frontend/src/routes/oauth.callback.tsx`
- **Details**:
  - Parses `access_token` from `window.location.hash` (via `new URLSearchParams(window.location.hash.substring(1))`).
  - Saves `localStorage.setItem("access_token", accessToken)`.
  - Clears URL hash and navigates to `"/"`.
  - Handles error fallback by redirecting to `"/login?error=google_auth_failed"`.

### 4.4 Update `/login`, `/signup`, and `/settings` Pages
- **Files**:
  - [`frontend/src/routes/login.tsx`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/frontend/src/routes/login.tsx)
  - [`frontend/src/routes/signup.tsx`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/frontend/src/routes/signup.tsx)
  - [`frontend/src/components/UserSettings/ChangePassword.tsx`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/frontend/src/components/UserSettings/ChangePassword.tsx)
- **Changes**:
  - Add divider (`"Or continue with"`) and `<GoogleLoginButton />` to both Login and Sign Up forms.
  - Display error toast on `/login` when redirected with `?error=...`.
  - In `ChangePassword.tsx`, if `currentUser?.has_password === false`, show a clear message explaining the account is authenticated via Google (with a link/button to trigger password recovery if they wish to set a password).

---

## Phase 5: Testing & Verification Plan

### 5.1 Backend Unit & Integration Tests
- **File**: [`backend/tests/api/routes/test_login.py`](file:///Users/nayhtet/code/BCHhackathon/proof-pay/backend/tests/api/routes/test_login.py) (or `backend/tests/api/routes/test_google_login.py`)
- **Test Cases**:
  1. `test_google_login_not_configured`: Returns `503` when `GOOGLE_CLIENT_ID` is unset.
  2. `test_google_login_redirect`: Returns `302` redirect to `accounts.google.com` and sets `oauth_state` cookie.
  3. `test_google_callback_creates_new_user`: Mock `httpx` token & userinfo responses for a new email -> creates `User` with `google_id`, `hashed_password=None`, and redirects to `/oauth/callback#access_token=...`.
  4. `test_google_callback_links_existing_email_user`: Pre-create email/password user -> callback with matching verified Google email links `google_id` and preserves existing `hashed_password`.
  5. `test_google_callback_rejects_invalid_state`: Mismatched or missing `state` redirects to `/login?error=invalid_oauth_state`.
  6. `test_google_callback_rejects_unverified_email`: `email_verified: false` redirects with error and does not create/link user.
  7. `test_google_only_user_cannot_login_with_password`: Attempting `POST /api/v1/login/access-token` on a passwordless user returns `400 Incorrect email or password` cleanly without crashing.

### 5.2 Frontend Verification
- Run `bun run build` and `bun run lint` in `frontend/` to verify TypeScript types and Biome lint rules pass.
