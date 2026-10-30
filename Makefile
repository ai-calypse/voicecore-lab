# All non-live tests in every language. Live tests spend money: run `make test-live` on purpose.
.PHONY: test test-go test-py test-ts test-live e2e monitoring-check monitoring-test redis store-test scale-test fly-image-test

test: test-go test-py test-ts

test-go:
	cd services/realtime-gateway && go test -race ./...
	cd experiments && go test -race ./...

test-py:
	uv run pytest -m "not live and not docker"

test-ts:
	pnpm test

test-live:
	uv run pytest -m live -p no:randomly

e2e:
	pnpm --filter @voicecore/demo e2e
	pnpm --filter @voicecore/docs e2e
	uv run python harness/check_docs_anchors.py

# Monitoring config with the real tools (promtool, amtool) in their images. No services needed.
monitoring-check:
	monitoring/check.sh

# The monitoring profile end to end: a stopped orchestrator pages the alert sink. Takes about 3 minutes.
monitoring-test:
	docker compose --profile monitoring up -d --build --wait --wait-timeout 300
	uv run pytest -m docker harness/tests/test_monitoring.py -p no:randomly

# A throwaway Redis for the shared-state contract tests (seam 18): make redis store-test
redis:
	docker run -d --rm --name vc-redis-test -p 127.0.0.1:16379:6379 redis:7.4-alpine

store-test:
	VOICECORE_TEST_REDIS=redis://127.0.0.1:16379/15 uv run pytest services/agent-core/tests/test_budget_store.py
	cd services/realtime-gateway && VOICECORE_TEST_REDIS=redis://127.0.0.1:16379/14 go test -race -run 'TestNonce|TestDailyQuota' ./session

# Two gateways and two orchestrators behind nginx, one Redis ledger (mock providers). About 5 minutes.
scale-test:
	docker compose --profile scale up -d --build --wait --wait-timeout 300 redis seed orch-1 orch-2 gw-1 gw-2 lb
	uv run pytest -m docker harness/tests/test_scale.py -p no:randomly

# The Fly image built and run locally (never deployed): boots, answers, drains on SIGTERM, refuses an unsafe prod start.
fly-image-test:
	uv run pytest -m docker harness/tests/test_fly_image.py -p no:randomly
