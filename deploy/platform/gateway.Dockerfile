# The voicecore-gateway image (Step 10): the Go gateway plus the widget it serves at /widget.js.
# Published as ghcr.io/ai-calypse/voicecore-gateway. Build context: the repository root.
FROM node:24-slim AS widget
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/demo ./apps/demo
RUN pnpm install --frozen-lockfile --filter "@voicecore/demo..."
RUN pnpm --filter @voicecore/demo build:widget

FROM golang:1.27 AS build
WORKDIR /src
COPY services/realtime-gateway/go.mod services/realtime-gateway/go.sum ./
RUN go mod download
COPY services/realtime-gateway/ ./
ARG VERSION=dev
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=${VERSION}" -o /gateway ./cmd/gateway

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /gateway /app/gateway
COPY --from=widget /src/apps/demo/public/embed/voicecore.js /app/widget.js
EXPOSE 8080
ENTRYPOINT ["/app/gateway"]
