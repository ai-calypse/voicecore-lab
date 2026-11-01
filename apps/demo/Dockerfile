# Build context: the repository root (the demo builds the workspace SDK packages).
FROM node:26-slim AS build
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/demo ./apps/demo
COPY scripts ./scripts
RUN pnpm install --frozen-lockfile --filter "@voicecore/demo..."
ARG VITE_GATEWAY=http://localhost:8080
ENV VITE_GATEWAY=$VITE_GATEWAY
RUN pnpm --filter @voicecore/demo build:widget && pnpm --filter @voicecore/demo build \
 && node scripts/csp.mjs apps/demo/dist "$VITE_GATEWAY" apps/demo/csp.conf

FROM nginxinc/nginx-unprivileged:1.31-alpine
COPY apps/demo/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/demo/csp.conf /etc/nginx/csp.conf
COPY --from=build /src/apps/demo/dist /usr/share/nginx/html
EXPOSE 8080
