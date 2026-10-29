# All non-live tests in every language. Live tests spend money: run `make test-live` on purpose.
.PHONY: test test-py test-ts test-live

test: test-py test-ts

test-py:
	uv run pytest -m "not live"

test-ts:
	pnpm test

test-live:
	uv run pytest -m live -p no:randomly
