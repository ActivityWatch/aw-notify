.PHONY: build test package clean

build:
	poetry install

test:
	poetry run aw-notify --help  # Ensures that it at least starts
	make typecheck

typecheck:
	poetry run mypy aw_notify --ignore-missing-imports

PYFILES=$(shell find . -type f -name '*.py')

format:
	black ${PYFILES}

package:
	pyinstaller aw-notify.spec --clean --noconfirm

clean:
	rm -rf build dist
	rm -rf aw_notify/__pycache__
