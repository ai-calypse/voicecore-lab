# All non-live tests in every language. Live tests spend money: run `make test-live` on purpose.
.PHONY: test test-go test-py test-ts test-live e2e

test: test-go test-py test-ts

test-go:
	cd services/realtime-gateway && go test -race ./...
	cd experiments && go test -race ./...

test-py:
	uv run pytest -m "not live"

test-ts:
	pnpm test

test-live:
	uv run pytest -m live -p no:randomly

e2e:
	pnpm --filter @voicecore/demo e2e
	pnpm --filter @voicecore/docs e2e
	uv run python harness/check_docs_anchors.py
