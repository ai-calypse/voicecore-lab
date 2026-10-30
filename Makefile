# All non-live tests in every language. Live tests spend money: run `make test-live` on purpose.
.PHONY: test test-go test-py test-ts test-live e2e monitoring-check monitoring-test

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
