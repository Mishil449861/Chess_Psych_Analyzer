PYTHON ?= python
export PYTHONPATH := src

.PHONY: install test smoke demo-ui demo-real demo-tal demo-cross-era app presentation docker clean help

help:
	@echo "Targets:"
	@echo "  install   Install Python dependencies"
	@echo "  test      Run unit tests (40 tests, no network)"
	@echo "  smoke     Run end-to-end smoke test (requires Stockfish)"
	@echo "  demo-ui   Print the main static UI demo file"
	@echo "  demo-real Build the real-player same-move demo artifacts"
	@echo "  demo-tal  Build the Tal genius demo artifacts"
	@echo "  demo-cross-era Build the Tal/Carlsen cross-era demo artifacts"
	@echo "  app       Run the live-coach Streamlit app"
	@echo "  presentation Run the presentation-mode Streamlit app"
	@echo "  docker    Build the Docker image"
	@echo "  clean     Remove caches and the local DB"

install:
	pip install -r requirements.txt

test:
	$(PYTHON) -m pytest tests/ -v

smoke:
	$(PYTHON) scripts/smoke_test.py

demo-ui:
	@echo "Open demos/ui_demo.html"

demo-real:
	$(PYTHON) tests/test_real_player_same_move_demo.py

demo-tal:
	$(PYTHON) tests/test_tal_genius_demo.py

demo-cross-era:
	$(PYTHON) tests/test_cross_era_genius_demo.py

app:
	streamlit run apps/live_coach_app.py

presentation:
	streamlit run apps/presentation_demo.py

docker:
	docker build -t chess-psych .

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache
	rm -f smoke.db
	rm -rf data
	rm -rf ~/.chess_psych
