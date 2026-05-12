.PHONY: install test smoke lint docker clean help

help:
	@echo "Targets:"
	@echo "  install   Install Python dependencies"
	@echo "  test      Run unit tests (40 tests, no network)"
	@echo "  smoke     Run end-to-end smoke test (requires Stockfish)"
	@echo "  docker    Build the Docker image"
	@echo "  clean     Remove caches and the local DB"

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v

smoke:
	python smoke_test.py

docker:
	docker build -t chess-psych .

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache
	rm -f chess_psych.db smoke.db
	rm -rf ~/.chess_psych
