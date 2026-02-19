.PHONY: help dev test sync-setup sync sync-login sync-status

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

# ── Server ────────────────────────────────────────────────────────────────────

dev: ## Start Django dev server
	python manage.py runserver

test: ## Run all tests
	DB_URL="" python manage.py test core sync --verbosity=2

migrate: ## Run migrations
	python manage.py migrate

# ── Sync client ───────────────────────────────────────────────────────────────

sync-setup: ## Install deps & configure sync client
	@bash sync/install.sh

sync: ## Start the sync client
	@bash sync/start.sh

sync-login: ## (Re)authenticate the sync client
	@python3 sync/client.py --login

sync-status: ## Show sync config & tracked files
	@python3 sync/client.py --status
