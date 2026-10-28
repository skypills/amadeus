PYTHON ?= python3

.PHONY: install test cov lint format check build run gui diagnose clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	QT_QPA_PLATFORM=offscreen pytest

cov:
	QT_QPA_PLATFORM=offscreen pytest --cov=amadeus --cov-report=term-missing

lint:
	ruff check src tests

format:
	ruff format src tests

check: lint test

build:
	$(PYTHON) -m build

run:
	amadeus

gui:
	amadeus-gui

diagnose:
	amadeus --diagnose

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .coverage
