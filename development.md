# FastAPI Project - Development

## Local Development

For local development, run PostgreSQL and Mailpit with Docker Compose, and run the FastAPI and Vite development servers locally.

Start the supporting services:

```bash
docker compose up -d db mailpit
```

Then, from the `backend` directory, install the dependencies and prepare the database:

```bash
uv sync
uv run bash scripts/prestart.sh
```

Start the FastAPI development server:

```bash
uv run fastapi dev
```

In another terminal, from the project root, install the frontend dependencies and start the Vite development server:

```bash
bun install
bun run dev
```

Now you can open these URLs:

Frontend development server: <http://localhost:5173>

Backend API: <http://localhost:8000>

Automatic interactive API documentation with Swagger UI: <http://localhost:8000/docs>

Mailpit: <http://localhost:8025>

The frontend development server uses the backend at `http://localhost:8000`, as configured in `frontend/.env`.

### Frontend Served by FastAPI

Build the frontend from the `frontend` directory:

```bash
bun run build
```

The build is written to `backend/app/frontend` and served by FastAPI at <http://localhost:8000>. Rebuild the frontend after making frontend changes.

## Database Migrations

Start PostgreSQL from the project root, then run Alembic from `backend`:

```bash
docker compose up -d db
cd backend
uv sync
uv run alembic current
uv run alembic upgrade head
```

`uv run bash scripts/prestart.sh` also applies migrations and creates the initial superuser. The Compose backend runs this script when it starts. After changing SQLModel table definitions, create a revision and review its operations before applying it:

```bash
uv run alembic revision --autogenerate -m "Describe the schema change"
uv run alembic upgrade head
```

To roll back every migration, run this from the project root:

```bash
bun run migrate:reset
```

This downgrades Alembic to `base`, dropping the application tables and deleting their data. Check that `DATABASE_URL` points to the intended database before running it. To recreate the tables afterward, run `uv run alembic upgrade head` from `backend`; run `uv run bash scripts/prestart.sh` instead if you also want to recreate the initial superuser.

If Alembic reports `password authentication failed for user "postgres"`, check that `POSTGRES_PASSWORD` and the password in `DATABASE_URL` in the project root `.env` match. PostgreSQL uses `POSTGRES_PASSWORD` only when its data volume is first initialized; changing `.env` later does not change the existing database role password. To keep the data, set the role password to the value in `.env`:

```bash
# Run from the project root. Enter the POSTGRES_PASSWORD value from .env at the prompt.
docker compose exec db psql -U postgres -d app
\password postgres
\q
```

Then run `uv run alembic upgrade head` from `backend` again. Avoid deleting the database volume to resolve an authentication error, since that also deletes local data.

## Full Stack with Docker Compose and Hot Reload

From the repository root, build the development images and start the existing services:

```bash
docker compose up -d --build
```

Now you can open these URLs:

Frontend with Vite hot reload: <http://localhost:5173>

Backend API: <http://localhost:8000>

Automatic interactive API documentation with Swagger UI: <http://localhost:8000/docs>

Adminer, database web administration: <http://localhost:8080>

Traefik UI, to see how the routes are being handled by the proxy: <http://localhost:8090>

Mailpit: <http://localhost:8025>

After the first build, use `docker compose up -d` to start the same development stack. Saving files under `frontend/` updates Vite; saving Python files under `backend/app/` restarts the Uvicorn worker. The frontend calls the backend at `http://localhost:8000`, which allows the Vite origin `http://localhost:5173`. Open the Vite URL for live frontend changes. Port 8000 and the Traefik route on port 80 serve a static frontend snapshot kept for FastAPI compatibility; they do not update on source saves.

Changes to frontend dependencies (`frontend/package.json` or `bun.lock`), backend dependencies (`backend/pyproject.toml` or `uv.lock`), Dockerfiles, or backend scripts require rebuilding the affected image with `docker compose up -d --build`. Environment variable changes require recreating the affected service with `docker compose up -d --force-recreate <service>`. Source saves need neither command.

Stop a locally running FastAPI server before starting the Compose backend because both use port `8000`.

**Note**: The first time you start the stack, it might take a minute for all the services to be ready. To monitor it, use `docker compose logs`, or `docker compose logs backend` for the backend service.

## Mailpit

[Mailpit](https://mailpit.axllent.org) captures emails sent during local development instead of delivering them. The local backend connects to it at `localhost:1025`, and the Compose backend connects to the `mailpit` service. Captured emails are available at <http://localhost:8025>.

## Docker Compose Files and Environment Variables

The main `compose.yml` file contains the configuration shared by the whole stack. Docker Compose loads it automatically.

The `compose.override.yml` file adds local development settings, including bind mounts for the frontend and backend source, Vite on port 5173, and Uvicorn reload. Docker Compose loads it automatically and applies it on top of `compose.yml`. Bun dependencies remain in `/app/node_modules` outside the frontend mount; Python dependencies remain in `/app/.venv` outside the backend mount. The database uses its existing named volume.

The `compose.deploy.yml` file contains the deployment-specific settings, including HTTPS and automatic certificate handling. It is explicitly combined with `compose.yml` when deploying the application.

The backend reads local settings from the `.env` file. Docker Compose also uses it for variable interpolation and passes the settings each container needs.

After changing variables, recreate the affected service:

```bash
docker compose up -d --force-recreate <service>
```

## The `.env` File

The tracked `.env` file contains local development defaults, passwords, and other configuration. Its hostnames use `localhost` for processes running on your machine. Docker Compose overrides hostnames such as the database and SMTP server with their Compose service names.

Do not store deployment secrets in `.env`. Configure them as described in the [FastAPI Cloud deployment guide](./deployment.md) or the [Docker Compose deployment guide](./deployment-docker-compose.md).

## Pre-commit Hooks and Code Linting

The project uses [prek](https://prek.j178.dev/), a modern alternative to [pre-commit](https://pre-commit.com/), for code linting and formatting.

You can find a file `.pre-commit-config.yaml` with configurations at the root of the project.

### Install `prek` to Run Automatically

`prek` is already part of the dependencies of the project.

From the project root, install the Git hook so that `prek` runs automatically before each commit:

```bash
uv run prek install -f
```

The `-f` flag forces the installation, in case there was already a `pre-commit` hook previously installed.

Now whenever you try to commit, for example with:

```bash
git commit
```

`prek` will check and format the code you are about to commit. If it modifies any files, add those files to Git again before committing.

### Run `prek` Manually

You can also run `prek` manually on all files from the project root:

```bash
uv run prek run --all-files
```


### Signup preflight and JWT configuration

For the Vite development server, set `FRONTEND_HOST=http://localhost:5173` in
`.env`. CORS origins must exactly match the browser origin, including scheme,
host and port (`127.0.0.1` differs from `localhost`). An `OPTIONS` response of
400 can indicate that the browser origin is not allowed. Restart the backend
after changing environment values.

`SECRET_KEY` must contain at least 32 characters. Generate a local random value
with `python -c 'import secrets; print(secrets.token_urlsafe(48))'` and set it in
`.env`. Changing this key invalidates existing JWTs; sign in again. A JWT key
warning and a failed CORS preflight are separate issues. Do not reset the database
to fix either of them.
