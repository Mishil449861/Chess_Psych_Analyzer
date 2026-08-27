PYTHON ?= python
export PYTHONPATH := src

.PHONY: install test smoke app docker clean help

help:
	@echo "Targets:"
	@echo "  install   Install Python dependencies"
	@echo "  test      Run unit tests (40 tests, no network)"
	@echo "  smoke     Run end-to-end smoke test (requires Stockfish)"
	@echo "  app       Run the live-coach Streamlit app"
	@echo "  docker    Build the Docker image"
	@echo "  clean     Remove caches and the local DB"

install:
	pip install -r requirements.txt

test:
	$(PYTHON) -m pytest tests/ -v

smoke:
	$(PYTHON) scripts/smoke_test.py

app:
	streamlit run apps/live_coach_app.py

docker:
	docker build -t chess-psych .

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache
	rm -f smoke.db
	rm -rf data
	rm -rf ~/.chess_psych
