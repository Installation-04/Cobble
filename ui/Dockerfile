# Build context: ui/
FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS build
WORKDIR /app
ENV CI=true
# pnpm comes from corepack, at the exact version pinned by "packageManager" in package.json.
COPY package.json pnpm-lock.yaml ./
# Optional build secret "ca": a CA bundle for networks with TLS inspection.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    corepack enable && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM caddy:2-alpine@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5
COPY Caddyfile.static /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
# Non-root; Caddy needs writable config/data dirs even with the admin API off.
ENV XDG_CONFIG_HOME=/tmp/caddy-config XDG_DATA_HOME=/tmp/caddy-data
USER 10001
EXPOSE 8080
