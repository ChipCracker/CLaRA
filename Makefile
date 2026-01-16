SHELL := /bin/bash

PROJECT ?= .
MODEL ?= mistral
LT_URL ?= http://localhost:8010
OLLAMA_URL ?= http://localhost:11434

.PHONY: pull up down review review-auto check debug-check review-fix debug-review-fix fix debug-fix fix-content debug-fix-content annotate debug-annotate build pdf report

pull:
	@docker compose pull || true
	@docker compose up -d ollama
	@docker compose exec -T ollama ollama pull $(MODEL)
	@docker compose down

up:
	docker compose up -d

down:
	docker compose down

debug-check:
	@docker compose run --rm core python -m clara.cli check --fast --json out/check.json || (echo "" && cat out/check.json && exit 1)

check: debug-check

review:
	@$(MAKE) review-auto

debug-review-fix:
	docker compose run --rm core python -m clara.cli review-fix --json out/review.json || (echo "" && cat out/review.json && exit 1)

review-fix: debug-review-fix

review-auto:
	docker compose run --rm core python -m clara.cli review-auto --json out/review.json || (echo "" && cat out/review.json && exit 1)
	@$(MAKE) pdf

debug-fix:
	docker compose run --rm core python -m clara.cli fix

fix: debug-fix

debug-fix-content:
	docker compose run --rm core python -m clara.cli check --fast --json out/check.json || true
	docker compose run --rm core python -m clara.cli fix-content --issues out/check.json

fix-content: debug-fix-content

debug-annotate:
	docker compose run --rm core python -m clara.cli annotate --issues out/review.json

annotate: debug-annotate

clean:
	rm -rf out/
	find . -name "*.bak*" -delete

build:
	docker compose run --rm core tectonic -X compile tex/main.tex --outdir out

pdf: build

report:
	jq '.' out/review.json
