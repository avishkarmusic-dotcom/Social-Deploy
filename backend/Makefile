.PHONY: up down migrate seed test lint fresh

up:            ## Boot the whole stack
	docker compose up --build -d
	@echo "  API   http://localhost:8000/docs"
	@echo "  Web   http://localhost:3000"

migrate:       ## Apply migrations (pre-deploy job, never at app start)
	docker compose exec api alembic upgrade head

seed:          ## Load demo data
	docker compose exec api python -m app.seed

fresh: up migrate seed  ## Zero to running with data

test:
	docker compose exec api pytest -q

lint:
	docker compose exec api ruff check app tests
	docker compose exec api mypy app

down:
	docker compose down -v
