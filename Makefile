.PHONY: help dev test migrate cleanup install set-domain

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

# ── Server ────────────────────────────────────────────────────────────────────

dev: ## Start Django dev server
	python manage.py runserver

test: ## Run all tests
	pytest && python manage.py test core

migrate: ## Run migrations
	python manage.py migrate

cleanup: ## Delete expired drops (DB + B2)
	python manage.py cleanup

# ── CLI ───────────────────────────────────────────────────────────────────────

install: ## Install drp CLI locally (editable)
	pip install -e .

# ── Domain migration ──────────────────────────────────────────────────────────



set-domain: ## Swap default host: make set-domain NEW=drp.fyi
	@test -n "$(NEW)" || (echo "  ✗ Usage: make set-domain NEW=drp.fyi" && exit 1)
	old=$$(grep -oP "(?<=DEFAULT_HOST = 'https://).*(?=')" cli/__init__.py); \
	sed -i "s|https://$$old|https://$(NEW)|g" cli/__init__.py pyproject.toml
	link=$$(grep -oP '(?<=\*\*\[Live →\]\().*(?=\))' README.md); \
	sed -i "s|$${link}|https://$(NEW)|g" README.md
	@echo "  ✓ Done. Railway, Resend, and README.md live link updated."