UV ?= uv

.PHONY: install run lint build
install:
	$(UV) sync --locked
run:
	$(UV) run valutatrade
lint:
	$(UV) run ruff check .
build:
	$(UV) build
