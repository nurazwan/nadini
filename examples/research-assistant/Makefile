.PHONY: deps upgrade dev run test lint fmt build up down

deps:          ## resolve latest versions of all dependencies into uv.lock
	sh scripts/deps.sh

upgrade:       ## bump every locked dependency to its latest version
	uv lock --upgrade && uv sync

dev:           ## run locally with auto-reload and the dev UI
	DEV_UI_ENABLED=true uv run uvicorn server.app:app --reload --port 8000

run:           ## run locally like production
	uv run uvicorn server.app:app --host 0.0.0.0 --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .

fmt:
	uv run ruff check --fix . && uv run ruff format .

build:         ## build the Docker image
	docker build -t research-assistant:latest .

up:            ## agent + Grafana LGTM
	docker compose up --build

down:
	docker compose down
