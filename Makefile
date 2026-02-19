.PHONY: help dev test migrate install

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

# ── Server ────────────────────────────────────────────────────────────────────

dev: ## Start Django dev server
	python manage.py runserver

test: ## Run all tests
	DB_URL="" python manage.py test core cli.tests_integration --verbosity=2

migrate: ## Run migrations
	python manage.py migrate

# ── CLI ───────────────────────────────────────────────────────────────────────

install: ## Install drp CLI (pip install -e .)
	pip install -e .
