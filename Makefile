.PHONY: setup up down health-check fault investigate watchdog watchdog-rules watchdog-rules-clean eval eval-all eval-replay eval-baselines compare test lint fmt demo demo-build demo-all demo-refresh demo-offline help

CLUSTER_NAME      := sre-incident-agent
KUBECONFIG_PATH   := $(HOME)/.kube/config
NAMESPACE         := otel-demo
CHAOS_NAMESPACE   := chaos-mesh
RULES_FILE        := infra/prometheus-rules/golden-signals.yaml

SCENARIO          ?= scenarios/mvp/001-checkoutservice-pod-crash.yaml
SCENARIO_DIR      ?= scenarios/mvp
RUN_ID            ?=
INCIDENT_ID       ?=
START             ?=
END               ?=

# ── Setup ──────────────────────────────────────────────────────────────────
setup:
	@echo "==> WSL2 preflight (inotify limits)"
	@bash scripts/wsl2_preflight.sh
	@echo "==> Installing Python dependencies"
	pip install -e ".[dev]"
	@echo "==> Checking kind"
	@which kind || (echo "Install kind: https://kind.sigs.k8s.io/docs/user/quick-start/#installation" && exit 1)
	@echo "==> Checking helm"
	@which helm || (echo "Install helm: https://helm.sh/docs/intro/install/" && exit 1)
	@echo "==> Checking kubectl"
	@which kubectl || (echo "Install kubectl: https://kubernetes.io/docs/tasks/tools/" && exit 1)
	@echo "==> Checking chaos-mesh CLI (optional)"
	@which chaos-mesh || true
	@echo "Setup complete."

# ── Cluster lifecycle ──────────────────────────────────────────────────────
up:
	@echo "==> WSL2 preflight (inotify limits — resets on WSL2 restart)"
	@bash scripts/wsl2_preflight.sh
	@echo "==> Creating kind cluster: $(CLUSTER_NAME)"
	kind create cluster --name $(CLUSTER_NAME) --config infra/kind-config.yaml \
		--kubeconfig $(KUBECONFIG_PATH) 2>/dev/null || \
		echo "  (cluster already exists, skipping)"
	@echo "==> Adding Helm repos"
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
	helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
	helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts 2>/dev/null || true
	helm repo add chaos-mesh https://charts.chaos-mesh.org 2>/dev/null || true
	helm repo update
	@echo "==> Installing Prometheus"
	helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
		--namespace monitoring --create-namespace \
		--values infra/helm/prometheus-values.yaml \
		--wait --timeout 5m
	@echo "==> Installing Tempo"
	helm upgrade --install tempo grafana/tempo \
		--namespace monitoring \
		--values infra/helm/tempo-values.yaml \
		--wait --timeout 3m
	@echo "==> Installing Loki"
	helm upgrade --install loki grafana/loki \
		--namespace monitoring \
		--values infra/helm/loki-values.yaml \
		--wait --timeout 3m
	@echo "==> Deploying OTel Collector"
	kubectl apply -f infra/collector/otelcol-config.yaml
	kubectl apply -f infra/collector/otelcol-daemonset.yaml
	kubectl -n monitoring rollout status daemonset/otel-collector --timeout=120s
	@echo "==> Installing OTel Astronomy Shop"
	helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
		--namespace $(NAMESPACE) --create-namespace \
		--values infra/helm/astronomy-shop-values.yaml \
		--wait --timeout 10m
	@echo "==> Installing Chaos Mesh"
	helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
		--namespace $(CHAOS_NAMESPACE) --create-namespace \
		--set chaosDaemon.runtime=containerd \
		--set chaosDaemon.socketPath=/run/containerd/containerd.sock \
		--wait --timeout 3m
	@echo ""
	@echo "Cluster ready. Run: make health-check"

down:
	kind delete cluster --name $(CLUSTER_NAME)
	@echo "Cluster deleted."

# ── Health check ───────────────────────────────────────────────────────────
health-check:
	@python3 scripts/health_check.py

# ── Fault injection ────────────────────────────────────────────────────────
fault:
	@test -f "$(SCENARIO)" || (echo "ERROR: SCENARIO not found: $(SCENARIO)" && exit 1)
	@python3 scripts/inject_and_snapshot.py --scenario $(SCENARIO)

# ── Agent (live mode) ─────────────────────────────────────────────────────
investigate:
	@test -n "$(INCIDENT_ID)" || (echo "ERROR: INCIDENT_ID required" && exit 1)
	@test -n "$(START)"       || (echo "ERROR: START required (ISO-8601)" && exit 1)
	@test -n "$(END)"         || (echo "ERROR: END required (ISO-8601)" && exit 1)
	@python3 -m src.agent.run \
		--incident-id "$(INCIDENT_ID)" \
		--start "$(START)" \
		--end "$(END)" \
		--namespace "$(NAMESPACE)"

# ── Watchdog (alert-driven on-duty agent) ─────────────────────────────────
watchdog:
	@python3 -m scripts.watchdog --interval 15

# Golden-signal PrometheusRule：apply 后内建幂等加载等待（apply 成功 ≠ 加载——
# ruleSelector 不匹配时 apply 静默不加载，P1 实测陷阱；90s 覆盖 operator 同步 ~1min）。
watchdog-rules:
	@echo "==> Applying golden-signal PrometheusRule"
	kubectl apply -f $(RULES_FILE)
	@echo "==> Waiting for Prometheus operator to load rules (up to 90s)..."
	@for i in $$(seq 1 9); do \
		COUNT=$$(curl -s http://localhost:9090/api/v1/rules | grep -o OtelDemo | wc -l || true); \
		if [ "$$COUNT" -ge 2 ]; then echo "Loaded OtelDemo rules: $$COUNT"; exit 0; fi; \
		sleep 10; \
	done; \
	echo "WARNING: rules not loaded after 90s — check ruleSelector labels (release: prometheus)"; exit 1

watchdog-rules-clean:
	@echo "==> Deleting golden-signal PrometheusRule"
	kubectl delete -f $(RULES_FILE)
	@echo "==> Golden-signal alerts removed; watchdog back to P0 (pod alerts only)"

# ── Evaluation ────────────────────────────────────────────────────────────
eval:
	@python3 -m eval.scenario_runner \
		--scenario-dir "$(SCENARIO_DIR)" \
		--mode replay

eval-replay:
	@test -n "$(RUN_ID)" || (echo "ERROR: RUN_ID required" && exit 1)
	@python3 -m eval.scenario_runner \
		--scenario-dir "$(SCENARIO_DIR)" \
		--mode replay \
		--run-id "$(RUN_ID)"

eval-baselines:
	@python3 -m eval.scenario_runner \
		--scenario-dir "$(SCENARIO_DIR)" \
		--mode baselines-only

eval-all:
	@python3 -m eval.scenario_runner \
		--scenario-dir "$(SCENARIO_DIR)" \
		--mode all

compare:
	@python3 -m eval.compare

# ── Dev ───────────────────────────────────────────────────────────────────
test:
	pytest --cov=src --cov=eval --cov-report=term-missing -q

lint:
	ruff check src/ eval/ scripts/ tests/
	mypy src/ eval/ --ignore-missing-imports

fmt:
	ruff format src/ eval/ scripts/ tests/

# ── Demo ──────────────────────────────────────────────────────────────────
demo:
	@echo "Running demo on most recent snapshot..."
	@LATEST=$$(ls -td snapshots/*/ground_truth.json 2>/dev/null | head -1 | xargs dirname); \
	test -n "$$LATEST" || (echo "No snapshots found. Run: make fault SCENARIO=..." && exit 1); \
	SCENARIO_ID=$$(basename $$LATEST); \
	python3 -m eval.scenario_runner \
		--snapshot-dir "$$LATEST" \
		--mode single \
		--print-report

# ── Local demo pack (add-local-demo-pack) ─────────────────────────────────
demo-build:
	@echo "==> Building webui/bundle.js from disk artifacts (LLM-free)"
	@python3 webui/build_bundle.py

demo-all: eval-all demo-build
	@echo "==> demo-all complete: fresh run evaluated + bundle rebuilt"
	@echo "    open webui/index.html (double-click, offline-friendly)"

demo-refresh:
	@echo "==> demo-refresh: eval-all + auto --add-run <new_run_id> + bundle rebuild"
	@echo "    (after this, click the refresh button (or F5) in webui — new run appears in the run selector)"
	@RUN_ID=$$(python3 -c "import sys; sys.path.insert(0,'.');\
		from eval.scenario_runner import run_all" 2>/dev/null; \
		newest=$$(ls -t artifacts | grep -E '^[0-9]{8}T[0-9]{6}Z$$' | head -1); \
		if [ -z "$$newest" ]; then echo ""; else echo "$$newest"; fi); \
	if [ -z "$$RUN_ID" ]; then \
		echo "ERROR: no timestamped run found under artifacts/ — run make eval-all first"; exit 1; \
	fi; \
	echo "==> New run detected: $$RUN_ID"; \
	python3 webui/build_bundle.py --add-run $$RUN_ID
	@echo "==> demo-refresh complete: $$RUN_ID added to whitelist + bundle rebuilt"

demo-offline: demo-build
	@echo "==> offline mode: bundle rebuilt from existing artifacts only (zero LLM calls)"

help:
	@echo ""
	@echo "OTel SRE-Copilot — available targets:"
	@echo ""
	@echo "  make setup          Install dependencies + check tools"
	@echo "  make up             Create kind cluster + deploy all backends"
	@echo "  make down           Destroy cluster"
	@echo "  make health-check   Verify all backends healthy"
	@echo ""
	@echo "  make fault SCENARIO=<path>     Inject fault + snapshot telemetry"
	@echo "  make investigate INCIDENT_ID=<id> START=<ts> END=<ts>"
	@echo "  make watchdog                   Alert-driven on-duty agent (poll every 15s)"
	@echo "  make watchdog-rules             Apply golden-signal PrometheusRule (+wait for load)"
	@echo "  make watchdog-rules-clean       Delete golden-signal rule (back to P0 pod alerts)"
	@echo ""
	@echo "  make demo-build                 Rebuild webui/bundle.js (offline, LLM-free)"
	@echo "  make demo-all                   eval-all + demo-build (one-shot reproduction)"
	@echo "  make demo-refresh               eval-all + auto add-run + rebuild (new run lands in UI)"
	@echo "  make demo-offline               Rebuild bundle only (no LLM, no network)"
	@echo ""
	@echo "  make eval                      Run 7 MVP scenarios (replay mode)"
	@echo "  make eval SCENARIO_DIR=...     Custom scenario dir"
	@echo "  make eval-replay RUN_ID=<id>   Replay from artifacts"
	@echo "  make eval-baselines            Run 3 baselines"
	@echo "  make eval-all                  Same-run agent + 3 baselines (the only legal comparison)"
	@echo "  make compare                   Agent vs baselines table"
	@echo ""
	@echo "  make test / make lint / make fmt"
	@echo ""
