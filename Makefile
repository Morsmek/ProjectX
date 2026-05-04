.PHONY: init build up down restart logs clean keys lint test

COMPOSE := docker compose
PYTHON   := python3

init: keys
	@cp -n .env.example .env || true
	@echo "[Aegis] Run: make build && make up"

keys:
	@$(PYTHON) scripts/gen-keys.py

build:
	$(COMPOSE) build --parallel

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f --tail=100

clean:
	$(COMPOSE) down -v --remove-orphans
	docker image prune -f

lint:
	@for svc in gateway blockchain hermes sdba oracle payment mesh vdi; do \
		echo "── $$svc"; \
		cd services/$$svc && python -m ruff check . 2>/dev/null || true; cd ../..; \
	done

test:
	@$(PYTHON) -m pytest tests/ -v

status:
	$(COMPOSE) ps
	@echo ""
	@echo "─── Blockchain ───────────────────────────────────────────"
	@curl -s http://localhost:8080/chain/status | python -m json.tool 2>/dev/null || echo "Gateway not reachable"

blackout:
	@echo "[Aegis] Activating Blackout Protocol..."
	@curl -s -X POST http://localhost:8086/blackout/activate \
	     -H "X-Kill-Switch-Key: $$KILL_SWITCH_KEY" | python -m json.tool

freeze-status:
	@curl -s http://localhost:8084/freeze/status | python -m json.tool
