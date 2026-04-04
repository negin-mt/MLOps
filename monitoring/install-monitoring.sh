#!/bin/bash
# Install Prometheus + Grafana (kube-prometheus-stack) for cluster monitoring.
# Usage: ./monitoring/install-monitoring.sh
# Requires: kubectl, curl; Helm 3 (downloads to ../.tools/helm if missing)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

CHART_REPO="prometheus-community"
CHART_NAME="kube-prometheus-stack"
# Pin for reproducible installs; bump when upgrading
CHART_VERSION="${KUBE_PROMETHEUS_CHART_VERSION:-82.17.0}"
RELEASE_NAME="${MONITORING_RELEASE_NAME:-kube-prometheus}"
NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"

HELM="${HELM:-helm}"
if ! command -v helm &>/dev/null; then
  TOOLS_DIR="$ROOT/.tools"
  mkdir -p "$TOOLS_DIR"
  HELM="$TOOLS_DIR/helm"
  if [[ ! -x "$HELM" ]]; then
    echo "[install-monitoring] Helm not found; downloading Helm 3 to $HELM ..."
    curl -fsSL https://get.helm.sh/helm-v3.14.4-linux-amd64.tar.gz -o /tmp/helm-linux-amd64.tar.gz
    tar -xzf /tmp/helm-linux-amd64.tar.gz -C /tmp
    mv /tmp/linux-amd64/helm "$HELM"
    chmod +x "$HELM"
  fi
fi

echo "[install-monitoring] Using Helm: $($HELM version --short)"

$HELM repo add "$CHART_REPO" https://prometheus-community.github.io/helm-charts 2>/dev/null || true
$HELM repo update

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "[install-monitoring] Installing $CHART_NAME $CHART_VERSION (release=$RELEASE_NAME, ns=$NAMESPACE) ..."
$HELM upgrade --install "$RELEASE_NAME" "$CHART_REPO/$CHART_NAME" \
  --namespace "$NAMESPACE" \
  --version "$CHART_VERSION" \
  -f "$SCRIPT_DIR/values-kind.yaml" \
  --wait \
  --timeout 15m

echo ""
echo "=============================================="
echo "  Monitoring stack installed"
echo "=============================================="
echo "  Namespace: $NAMESPACE"
echo ""

GRAF_SVC="${RELEASE_NAME}-grafana"
GRAF_IP=$(kubectl get svc -n "$NAMESPACE" "$GRAF_SVC" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
# Prometheus Service name may be truncated (e.g. kube-prome-prometheus); discover LoadBalancer on port 9090
PROM_IP=$(kubectl get svc -n "$NAMESPACE" --no-headers 2>/dev/null | awk '$2=="LoadBalancer" && $5 ~ /^9090/ {print $4; exit}')

echo "  Grafana (user: admin; password set in monitoring/values-kind.yaml):"
echo "    http://${GRAF_IP:-<pending>}/"
echo "  Prometheus UI:"
echo "    http://${PROM_IP:-<pending>}:9090/"
echo ""
echo "  If the password was auto-generated, read it with:"
echo "    kubectl get secret -n $NAMESPACE ${RELEASE_NAME}-grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo"
echo "=============================================="
