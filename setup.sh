#!/bin/bash
# MLOps Platform Setup - Kind + MetalLB + Istio + Code-Server + Katib
# Usage: ./setup.sh [full|cluster|metallb|istio|vscode|katib]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CLUSTER_NAME="${CLUSTER_NAME:-kind}"
METALLB_IP_START="${METALLB_IP_START:-172.20.255.200}"
METALLB_IP_END="${METALLB_IP_END:-172.20.255.250}"

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
  log "Katib installed in namespace kubeflow."
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
  echo "=============================================="
}

MODE="${1:-full}"
case "$MODE" in
  full)
    step_cluster
    step_metallb
    step_istio
    step_vscode
    step_katib
    print_summary
    ;;
  cluster)  step_cluster ;;
  metallb)  step_metallb ;;
  istio)    step_istio ;;
  vscode)   step_vscode ;;
  katib)    step_katib ;;
  *)
    echo "Usage: $0 {full|cluster|metallb|istio|vscode|katib}"
    exit 1
    ;;
esac
