.PHONY: backend-test backend-lint frontend-build up down logs deploy
backend-test:
	cd backend && uv run pytest -q
backend-lint:
	cd backend && uv run ruff check src tests
frontend-build:
	cd frontend && npm ci && npm run build
up:
	cd deploy && docker compose -p memora up -d --build
down:
	cd deploy && docker compose -p memora down
logs:
	cd deploy && docker compose -p memora logs -f --tail 200 backend worker
deploy:
	deploy/scripts/remote-deploy.sh
