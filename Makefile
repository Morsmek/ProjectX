.PHONY: init build up down restart logs clean keys lint test \
        prod-up prod-down tunnel-create tunnel-route deploy-frontend

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

# ─── Production targets ────────────────────────────────────────────────────

prod-up:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml up -d

prod-down:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml down

# Create a Cloudflare Tunnel and print the token
# Requires: cloudflared installed and `cloudflared login` completed
tunnel-create:
	@echo "[Aegis] Creating Cloudflare Tunnel 'aegis-prod'…"
	cloudflared tunnel create aegis-prod
	@echo ""
	@echo "Copy the tunnel ID and JSON file path shown above."
	@echo "Then run: make tunnel-route DOMAIN=api.your-domain.com"

tunnel-route:
	@[ -n "$(DOMAIN)" ] || (echo "Usage: make tunnel-route DOMAIN=api.your-domain.com" && exit 1)
	cloudflared tunnel route dns aegis-prod $(DOMAIN)
	@echo "[Aegis] DNS route created: $(DOMAIN) → tunnel"
	@echo "Add CLOUDFLARE_TUNNEL_TOKEN to .env, then: make prod-up"

# Deploy frontend to Cloudflare Pages via wrangler CLI
# Requires: npm install -g wrangler && wrangler login
deploy-frontend:
	@echo "[Aegis] Deploying frontend to Cloudflare Pages…"
	cd frontend && npx wrangler pages deploy . \
	  --project-name=project-aegis \
	  --commit-dirty=true
