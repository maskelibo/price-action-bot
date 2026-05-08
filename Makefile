# Price Action — geliştirici makefile.
.DEFAULT_GOAL := help
.PHONY: help install test lint fmt typecheck backtest up down clean validate

PY ?= python
PIP ?= pip

help:  ## Komut listesi
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install:  ## Bağımlılıkları kur (dev opsiyonu dahil)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

test:  ## Pytest çalıştır
	pytest -v

lint:  ## Ruff lint
	ruff check src tests

fmt:  ## Ruff format (autofix)
	ruff format src tests
	ruff check --fix src tests

typecheck:  ## mypy
	mypy src/price_action/analytics src/price_action/ml src/price_action/api src/price_action/cli.py

validate:  ## Ortam doğrulama
	$(PY) scripts/validate_setup.py

backtest:  ## classic_pa backtest çalıştır + HTML rapor
	$(PY) scripts/run_backtest.py --strategy classic_pa --years 3

up:  ## docker-compose up (postgres + prometheus + grafana + app)
	docker compose up -d

down:  ## docker-compose down
	docker compose down

clean:  ## Cache + build artefaktları sil
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
