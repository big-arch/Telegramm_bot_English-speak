.PHONY: install setup run test lint docker clean

VENV := .venv
PY := $(VENV)/bin/python

install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	@echo
	@echo "Next: cp .env.example .env, fill in BOT_TOKEN, GEMINI_API_KEY, GROQ_API_KEY"
	@echo "Then: make setup && make run"

setup:
	$(VENV)/bin/alembic upgrade head
	$(PY) -m scripts.seed

run:
	$(PY) -m bot

test:
	$(VENV)/bin/pytest -q

docker:
	docker compose up -d --build
	docker compose logs -f

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache
