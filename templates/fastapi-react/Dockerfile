# Image of the generated app, used for the milestone demos (built by Cobble's preview service).
# Classic `docker build` only: no BuildKit syntax, so it also builds through the Engine API.
# Behind a TLS-inspecting proxy, pass the proxy settings as build arguments.
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS web
WORKDIR /web
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY app ./app
COPY --from=web /web/dist ./static
# The demo container has a read-only root filesystem: anything the app writes (a SQLite file,
# uploads) goes under COBBLE_DATA_DIR, a tmpfs. `app/seed.py` fills it at the first start.
ENV PORT=8000 COBBLE_DATA_DIR=/tmp COBBLE_STATIC_DIR=/srv/static
RUN useradd --system --uid 10001 --no-create-home app
USER 10001
EXPOSE 8000
CMD ["python", "-m", "app.serve"]
