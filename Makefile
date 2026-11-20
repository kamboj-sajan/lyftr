.PHONY: up down logs test smoke clean ps

BASE_URL ?= http://localhost:8000

up:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "WARNING: .env was missing, so it was copied from .env.example."; \
		echo "WARNING: put real LLM_API_KEYS (and LLM_MODEL) in .env, then run make up again."; \
	fi
	docker compose up -d --build --wait
	@echo "Backend:  http://localhost:8000/health"
	@echo "Frontend: http://localhost:3000"

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

# Runs the backend tests in the local venv if there is one, otherwise in a throwaway container.
test:
	@if [ -x backend/.venv/bin/python ]; then \
		cd backend && .venv/bin/python -m pytest; \
	else \
		docker build --target test -t lyftr-backend-test backend && docker run --rm lyftr-backend-test; \
	fi

smoke:
	BASE_URL=$(BASE_URL) ./scripts/smoke_test.sh $(BASE_URL)

# Stops everything and deletes the app_data volume (chat history and disk cache).
clean:
	docker compose down -v
