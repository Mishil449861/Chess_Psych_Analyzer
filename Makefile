PYTHON ?= python
export PYTHONPATH := src

.PHONY: install test smoke demo-ui demo-build-ui demo-refresh demo-real demo-tal demo-cross-era experiment-models app presentation presentation-data docker clean help

help:
	@echo "Targets:"
	@echo "  install   Install Python dependencies"
	@echo "  test      Run unit tests (40 tests, no network)"
	@echo "  smoke     Run end-to-end smoke test (requires Stockfish)"
	@echo "  demo-ui   Print the main static UI demo file"
	@echo "  demo-build-ui Rebuild the static UI content from current evidence"
	@echo "  demo-refresh Refresh the 3/5-minute comparison datasets, then rebuild UI"
	@echo "  demo-real Build the real-player same-move demo artifacts"
	@echo "  demo-tal  Build the Tal genius demo artifacts"
	@echo "  demo-cross-era Build the Tal/Carlsen cross-era demo artifacts"
	@echo "  experiment-models Run cached coaching-model experiments"
	@echo "  app       Run the live-coach Streamlit app"
	@echo "  presentation Run the presentation-mode Streamlit app"
	@echo "  presentation-data Precompute the three presentation profiles with the real model"
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

demo-build-ui:
	$(PYTHON) scripts/build_same_mistake_cohort.py
	$(PYTHON) scripts/build_demo_ui_content.py

demo-refresh:
	$(PYTHON) scripts/build_personal_pattern_demo.py erolmcc --max-games 120 --output demos/erolmcc_blitz_evidence.json --skip-ai-labels
	$(PYTHON) scripts/build_personal_pattern_demo.py MishilT --max-games 120 --output demos/mishilt_blitz_evidence.json --skip-ai-labels
	$(PYTHON) scripts/build_personal_pattern_demo.py hikaru --max-games 120 --output demos/hikaru_blitz_evidence.json --skip-ai-labels
	$(MAKE) demo-build-ui

demo-real:
	$(PYTHON) tests/test_real_player_same_move_demo.py

demo-tal:
	$(PYTHON) tests/test_tal_genius_demo.py

demo-cross-era:
	$(PYTHON) tests/test_cross_era_genius_demo.py

experiment-models:
	$(PYTHON) scripts/experiment_coaching_models.py
	$(PYTHON) scripts/experiment_personalization.py

app:
	streamlit run apps/live_coach_app.py

presentation:
	streamlit run apps/presentation_demo.py

presentation-data:
	$(PYTHON) scripts/precompute_presentation_profiles.py

docker:
	docker build -t chess-psych .

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache
	rm -f smoke.db
	rm -rf data
	rm -rf ~/.chess_psych
