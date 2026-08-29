UV ?= uv
CONFIG ?= configs/auckland.yml
DATA_ROOT ?=
DATA_ROOT_ARG := $(if $(strip $(DATA_ROOT)),--data-root "$(DATA_ROOT)",)

.DEFAULT_GOAL := help

.PHONY: help bootstrap sync refresh-lock test coverage lint format-check check validate-config validate-data fetch run demo export-web-demo web-install web-build build docker-build

help:
	@printf '%s\n' "Targets: sync test coverage lint format-check check validate-config validate-data fetch run demo export-web-demo web-install web-build build docker-build"

bootstrap: sync

sync:
	@command -v $(UV) >/dev/null || { echo "uv is required for locked synchronisation"; exit 2; }
	$(UV) sync --locked --all-extras

refresh-lock:
	@command -v $(UV) >/dev/null || { echo "uv is required to refresh uv.lock"; exit 2; }
	$(UV) lock

test:
	$(UV) run --frozen pytest

coverage:
	$(UV) run --frozen pytest --cov --cov-report=term-missing --cov-report=xml

lint:
	$(UV) run --frozen ruff check .

format-check:
	$(UV) run --frozen ruff format --check .

check: lint format-check coverage validate-config

validate-config:
	$(UV) run --frozen ciw validate --config "$(CONFIG)" $(DATA_ROOT_ARG) --config-only

validate-data:
	$(UV) run --frozen ciw validate --config "$(CONFIG)" $(DATA_ROOT_ARG)

fetch:
	$(UV) run --frozen ciw data fetch --config "$(CONFIG)" $(DATA_ROOT_ARG)

run:
	$(UV) run --frozen ciw run --config "$(CONFIG)" $(DATA_ROOT_ARG)

demo:
	$(UV) run --frozen ciw demo --config "$(CONFIG)" $(DATA_ROOT_ARG) --output exports/demo.json

export-web-demo:
	$(UV) run --frozen ciw export-web --config "$(CONFIG)" $(DATA_ROOT_ARG) --demo

web-install:
	npm --prefix web ci

web-build:
	npm --prefix web run build

build:
	$(UV) run --frozen python -m build

docker-build:
	docker build --tag auckland-cycling-investment-workbench:local .
