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
    OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH_NAME="$(uname -m)"
    case "$ARCH_NAME" in
      x86_64|amd64) ARCH_NAME="amd64" ;;
      arm64|aarch64) ARCH_NAME="arm64" ;;
      *)
        echo "[install-monitoring] Unsupported architecture for Helm bootstrap: $ARCH_NAME" >&2
        exit 1
        ;;
    esac
    ARCHIVE_NAME="helm-v3.14.4-${OS_NAME}-${ARCH_NAME}.tar.gz"
    TMP_DIR="$(mktemp -d)"
    curl -fsSL "https://get.helm.sh/${ARCHIVE_NAME}" -o "${TMP_DIR}/helm.tgz"
    tar -xzf "${TMP_DIR}/helm.tgz" -C "${TMP_DIR}"
    mv "${TMP_DIR}/${OS_NAME}-${ARCH_NAME}/helm" "$HELM"
    chmod +x "$HELM"
    rm -rf "$TMP_DIR"
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
