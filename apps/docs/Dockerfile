# Build context: the repository root (the docs site embeds the widget built from apps/demo).
FROM node:24-slim AS build
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/demo ./apps/demo
COPY apps/docs ./apps/docs
RUN pnpm install --frozen-lockfile --filter "@voicecore/docs..." --filter "@voicecore/demo..."
RUN pnpm --filter @voicecore/docs build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY apps/docs/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/docs/build /usr/share/nginx/html
EXPOSE 8080
