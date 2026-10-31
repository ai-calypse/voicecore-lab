# Build context: the repository root (the docs site embeds the widget built from apps/demo).
FROM node:24-slim AS build
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/demo ./apps/demo
COPY apps/docs ./apps/docs
COPY scripts ./scripts
RUN pnpm install --frozen-lockfile --filter "@voicecore/docs..." --filter "@voicecore/demo..."
ARG VOICECORE_GATEWAY=http://localhost:8080
ARG TURNSTILE_SITEKEY=
ARG DOCS_URL=http://localhost:3000
ENV VOICECORE_GATEWAY=$VOICECORE_GATEWAY TURNSTILE_SITEKEY=$TURNSTILE_SITEKEY DOCS_URL=$DOCS_URL
RUN pnpm --filter @voicecore/docs build && node scripts/csp.mjs apps/docs/build "$VOICECORE_GATEWAY" apps/docs/csp.conf

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY apps/docs/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/docs/csp.conf /etc/nginx/csp.conf
COPY --from=build /src/apps/docs/build /usr/share/nginx/html
EXPOSE 8080
