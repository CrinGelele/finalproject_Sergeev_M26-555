UV ?= uv
export UV_CACHE_DIR := $(CURDIR)/.cache/uv

.PHONY: install run lint test build demo clean
install:
	$(UV) sync --locked
run:
	$(UV) run valutatrade
lint:
	$(UV) run ruff check valutatrade_hub tests demo main.py
test:
	$(UV) run python -m unittest discover -s tests -v
build:
	$(UV) build
demo:
	$(UV) run python -m demo.record
clean:
	rm -rf dist build .ruff_cache
