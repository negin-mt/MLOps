#!/bin/bash
# MLOps Platform Setup - Kind + MetalLB + Istio + Code-Server + Katib + Monitoring
# Usage: ./setup.sh [full|cluster|metallb|istio|vscode|katib|training-operator|minio|build-images|monitoring]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CLUSTER_NAME="${CLUSTER_NAME:-kind}"
METALLB_IP_START="${METALLB_IP_START:-172.20.255.200}"
METALLB_IP_END="${METALLB_IP_END:-172.20.255.250}"
STATE_DIR="${SCRIPT_DIR}/.state"

log() { echo "[$(date +%H:%M:%S)] $*"; }
err() { echo "[ERROR] $*" >&2; }

wait_for_pods() {
  local ns="$1" label="$2" timeout="${3:-300}"
  log "Waiting for pods in $ns ($label)..."
  if kubectl wait -n "$ns" pod -l "$label" --for=condition=Ready --timeout="${timeout}s" 2>/dev/null; then
    log "Pods ready."
  else
    err "Timeout waiting for pods. Check: kubectl get pods -n $ns"
    return 1
  fi
}

step_cluster() {
  log "=== 1. Creating Kind cluster ==="
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log "Cluster '$CLUSTER_NAME' already exists. Delete with: kind delete cluster --name $CLUSTER_NAME"
    return 0
  fi
  kind create cluster --config kind-config.yaml --name "$CLUSTER_NAME"
  kubectl cluster-info --context "kind-${CLUSTER_NAME}"
}

step_metallb() {
  log "=== 2. Installing MetalLB ==="
  # v0.13.7: smaller images, Kind-compatible, fewer DNS issues
  kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.7/config/manifests/metallb-native.yaml
  if ! wait_for_pods metallb-system "app=metallb" 180; then
    if kubectl get pods -n metallb-system -l component=controller --no-headers 2>/dev/null | grep -q Running; then
      log "Controller is Running; continuing (speaker may have ImagePullBackOff - check DNS if LoadBalancer IP stays Pending)"
    else
      err "MetalLB failed. Fix DNS or run: kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.7/config/manifests/metallb-native.yaml"
      return 1
    fi
  fi
  
  log "Configuring MetalLB IP pool..."
  cat <<EOF | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: first-pool
  namespace: metallb-system
spec:
  addresses:
  - ${METALLB_IP_START}-${METALLB_IP_END}
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: homelab-l2
  namespace: metallb-system
EOF
  log "MetalLB configured (${METALLB_IP_START}-${METALLB_IP_END})"
}

step_istio() {
  log "=== 3. Installing Istio ==="
  if ! istioctl version &>/dev/null; then
    err "istioctl not found. Install: curl -L https://istio.io/downloadIstio | sh -"
    return 1
  fi
  istioctl install -y --set profile=default
  kubectl label namespace default istio-injection=enabled --overwrite
  log "Istio installed. Ingress gateway will get LoadBalancer IP from MetalLB."
}

step_vscode() {
  log "=== 4. Deploying Code-Server (VS Code) ==="
  if ! docker image inspect code-server-python:latest &>/dev/null; then
    log "Building code-server-python image..."
    docker build -f Dockerfile.code-server -t code-server-python:latest .
    kind load docker-image code-server-python:latest --name "${CLUSTER_NAME}"
  else
    log "code-server-python:latest exists; loading into Kind..."
    kind load docker-image code-server-python:latest --name "${CLUSTER_NAME}"
  fi
  kubectl apply -f vscode.yaml
  kubectl apply -f istio-networking.yaml
  wait_for_pods default "app=code-server" 180
  log "Code-Server ready. Access via: http://<METALLB_IP>/vscode/"
}

step_katib() {
  log "=== 5. Installing Katib (standalone) ==="
  kubectl apply -k "github.com/kubeflow/katib.git/manifests/v1beta1/installs/katib-standalone?ref=v0.17.0"
  wait_for_pods kubeflow "app.kubernetes.io/component=katib-controller" 300
  wait_for_pods kubeflow "app.kubernetes.io/component=katib-db-manager" 120
  log "Applying RBAC for Code-Server to create Katib experiments..."
  kubectl apply -f code-server-rbac.yaml
  log "Applying multi-user namespaces, quotas, and namespace RBAC..."
  kubectl apply -f multi-user-namespaces.yaml
  log "Applying Katib trial guardrails (LimitRange + ResourceQuota)..."
  kubectl apply -f katib-guardrails.yaml
  log "Katib installed in namespace kubeflow."
}

step_training_operator() {
  log "=== 4b. Installing Kubeflow Training Operator ==="

  # Install Training Operator standalone from upstream Kubeflow manifests.
  # Installs into the 'kubeflow' namespace alongside Katib.
  # Version v1.8.0 — provides PyTorchJob, TFJob, MPIJob, XGBoostJob, PaddleJob CRDs.
  # FUTURE: When migrating to full Kubeflow stack, this step becomes redundant
  # (Training Operator is included). Guard or remove it at that point.
  kubectl apply --server-side \
    -k "github.com/kubeflow/training-operator/manifests/overlays/standalone?ref=v1.8.0" \
    >/dev/null

  # Wait for CRDs to be established before checking the controller
  kubectl wait --for=condition=established \
    crd/pytorchjobs.kubeflow.org --timeout=60s >/dev/null

  # Wait for Training Operator controller to be ready
  kubectl rollout status deployment/training-operator \
    -n kubeflow --timeout=300s >/dev/null

  # Apply RBAC granting user namespaces permission to create training jobs.
  # This is additive — does NOT modify multi-user-namespaces.yaml.
  kubectl apply -f "${SCRIPT_DIR}/training-operator-rbac.yaml" >/dev/null

  log "Training Operator ready."
  log "  CRDs available: PyTorchJob, TFJob, MPIJob, XGBoostJob, PaddleJob"
  log "  RBAC applied for: kubeflow-user-negin, kubeflow-user-yousef"
}

step_minio() {
  log "=== 5b. Installing MinIO object storage ==="

  # ── credentials (generated once, persisted locally) ─────────────────────────
  local minio_user_file="${STATE_DIR}/minio-root-user.txt"
  local minio_pass_file="${STATE_DIR}/minio-root-password.txt"
  mkdir -p "${STATE_DIR}"

  if [[ ! -f "${minio_user_file}" ]]; then
    python3 -c \
      "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(12)),end='')" \
      > "${minio_user_file}"
  fi
  if [[ ! -f "${minio_pass_file}" ]]; then
    python3 -c \
      "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(28)),end='')" \
      > "${minio_pass_file}"
  fi

  local minio_user minio_pass
  minio_user="$(<"${minio_user_file}")"
  minio_pass="$(<"${minio_pass_file}")"

  # ── namespace ────────────────────────────────────────────────────────────────
  kubectl create namespace platform --dry-run=client -o yaml | kubectl apply -f - >/dev/null

  # ── Helm install ─────────────────────────────────────────────────────────────
  if ! helm repo list 2>/dev/null | grep -q "^minio"; then
    helm repo add minio https://charts.min.io/ >/dev/null 2>&1 || true
  fi
  helm repo update >/dev/null

  log "Installing MinIO (standalone, chart 5.4.0)..."
  helm upgrade --install minio minio/minio \
    --namespace platform \
    --version 5.4.0 \
    --set mode=standalone \
    --set replicas=1 \
    --set persistence.size=10Gi \
    --set resources.requests.cpu=250m \
    --set resources.requests.memory=512Mi \
    --set resources.limits.cpu=1 \
    --set resources.limits.memory=2Gi \
    --set rootUser="${minio_user}" \
    --set rootPassword="${minio_pass}" \
    --set 'buckets[0].name=negin' \
    --set 'buckets[0].policy=none' \
    --set 'buckets[0].purge=false' \
    --set 'buckets[1].name=yousef' \
    --set 'buckets[1].policy=none' \
    --set 'buckets[1].purge=false' \
    --wait >/dev/null

  kubectl rollout status deployment/minio -n platform --timeout=300s >/dev/null

  # ── artifact-store secret in each user namespace ─────────────────────────────
  # The student_lab Python library reads these env-var-backed secrets to
  # connect to MinIO from inside Katib trial pods and training jobs.
  for ns in kubeflow-user-negin kubeflow-user-yousef; do
    kubectl -n "${ns}" create secret generic artifact-store \
      --from-literal=endpoint=http://minio.platform.svc.cluster.local:9000 \
      --from-literal=secure=false \
      --from-literal=accessKey="${minio_user}" \
      --from-literal=secretKey="${minio_pass}" \
      --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  done

  # ── root secret in platform namespace (used by setup scripts if needed) ──────
  kubectl -n platform create secret generic artifact-store-root \
    --from-literal=endpoint=http://minio.platform.svc.cluster.local:9000 \
    --from-literal=secure=false \
    --from-literal=accessKey="${minio_user}" \
    --from-literal=secretKey="${minio_pass}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null

  # ── expose MinIO console via Istio (so users can upload datasets from browser) ─
  # The MetalLB IP is read from the Istio ingress gateway service
  local lb_ip
  lb_ip=$(kubectl get svc istio-ingressgateway -n istio-system \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")

  kubectl apply -f - >/dev/null <<MINIO_VS
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: minio-console
  namespace: platform
spec:
  hosts:
    - "minio.${lb_ip}.nip.io"
  gateways:
    - istio-system/$(kubectl get gateway -A -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "istio-gateway")
  http:
    - match:
        - authority:
            prefix: "minio."
      route:
        - destination:
            host: minio.platform.svc.cluster.local
            port:
              number: 9001
MINIO_VS

  log "MinIO ready. Empty buckets created: negin, yousef"
  log "  Internal API: http://minio.platform.svc.cluster.local:9000"
  if [[ -n "${lb_ip}" ]]; then
    log "  Console UI:   http://minio.${lb_ip}.nip.io  (username: ${minio_user})"
  fi
  log "  Credentials: ${STATE_DIR}/minio-root-{user,password}.txt"
}

step_build_images() {
  log "=== Building ML runtime image ==="

  # Build the ML runtime image (for Katib trials and training jobs)
  docker build \
    -f "${SCRIPT_DIR}/Dockerfile.ml-runtime" \
    -t ml-runtime:latest \
    "${SCRIPT_DIR}" >/dev/null

  log "Loading ml-runtime:latest into Kind cluster..."
  kind load docker-image ml-runtime:latest --name "${CLUSTER_NAME}" >/dev/null

  log "ml-runtime:latest ready in cluster."
}

step_monitoring() {
  log "=== 6. Installing monitoring (Prometheus + Grafana) ==="
  bash "$SCRIPT_DIR/monitoring/install-monitoring.sh"
}

print_summary() {
  local ip
  ip=$(kubectl get svc -n istio-system istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  if [ -z "$ip" ]; then
    ip="<pending or check: kubectl get svc -n istio-system istio-ingressgateway>"
  fi
  echo ""
  echo "=============================================="
  echo "  MLOps Platform Ready"
  echo "=============================================="
  echo "  VS Code (code-server):  http://${ip}/vscode/"
  echo "  Password: 1234"
  echo ""
  echo "  Copy experiment script into Code-Server (first time):"
  echo "    POD=\$(kubectl get pod -n default -l app=code-server -o jsonpath='{.items[0].metadata.name}')"
  echo "    kubectl cp katib_experiment.py default/\$POD:/home/coder/project/katib_experiment.py"
  echo ""
  echo "  Run Katib experiment from VS Code:"
  echo "    python3 katib_experiment.py"
  if kubectl get ns monitoring &>/dev/null; then
    local gip pip
    gip=$(kubectl get svc -n monitoring kube-prometheus-grafana -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
    pip=$(kubectl get svc -n monitoring --no-headers 2>/dev/null | awk '$2=="LoadBalancer" && $5 ~ /^9090/ {print $4; exit}')
    echo ""
    echo "  Monitoring (if installed):"
    echo "    Grafana:    http://${gip:-<pending>}/"
    echo "    Prometheus: http://${pip:-<pending>}:9090/"
  fi
  echo "=============================================="
}

MODE="${1:-full}"
case "$MODE" in
  full)
    mkdir -p "$STATE_DIR"
    step_cluster
    step_metallb
    step_istio
    step_vscode
    step_katib
    step_training_operator
    step_minio
    step_build_images
    step_monitoring
    print_summary
    ;;
  cluster)  step_cluster ;;
  metallb)  step_metallb ;;
  istio)    step_istio ;;
  vscode)   step_vscode ;;
  katib)    step_katib ;;
  training-operator) step_training_operator ;;
  minio)    step_minio ;;
  build-images) step_build_images ;;
  monitoring) step_monitoring ;;
  *)
    echo "Usage: $0 {full|cluster|metallb|istio|vscode|katib|training-operator|minio|build-images|monitoring}"
    exit 1
    ;;
esac
