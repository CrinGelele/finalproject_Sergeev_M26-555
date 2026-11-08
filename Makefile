UV ?= uv
export UV_CACHE_DIR ?= $(CURDIR)/.cache/uv

.PHONY: install run lint build demo clean
install:
	$(UV) sync --locked
run:
	$(UV) run valutatrade
lint:
	$(UV) run ruff check valutatrade_hub demo main.py
build:
	$(UV) build
demo:
	$(UV) run python -m demo.record
clean:
	rm -rf dist build .ruff_cache
