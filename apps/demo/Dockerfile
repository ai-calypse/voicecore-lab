# Build context: the repository root (the demo builds the workspace SDK packages).
FROM node:24-slim AS build
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/demo ./apps/demo
RUN pnpm install --frozen-lockfile --filter "@voicecore/demo..."
RUN pnpm --filter @voicecore/demo build:widget && pnpm --filter @voicecore/demo build

FROM nginx:1.27-alpine
COPY --from=build /src/apps/demo/dist /usr/share/nginx/html
EXPOSE 80
