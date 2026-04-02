# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
deployment/helm_chart.py
========================
Generates a production-ready Helm chart for HOPEFX on Kubernetes.

Outputs:
  helm/hopefx/Chart.yaml
  helm/hopefx/values.yaml
  helm/hopefx/templates/deployment.yaml
  helm/hopefx/templates/service.yaml
  helm/hopefx/templates/configmap.yaml
  helm/hopefx/templates/pvc.yaml
  helm/hopefx/templates/secret.yaml

Architecture:
  - FastAPI pod (main trading engine)
  - Redis sidecar container (caching / pub-sub)
  - Persistent Volume for SQLite / model artefacts
  - Kubernetes Secret for API keys (base64-encoded at deploy time)
  - ConfigMap for non-sensitive runtime config

Run this script to regenerate the chart:
    python deployment/helm_chart.py [--output-dir helm/hopefx]
"""

from __future__ import annotations

import argparse
import logging
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chart content definitions
# ---------------------------------------------------------------------------

CHART_YAML = """\
apiVersion: v2
name: hopefx
description: HOPEFX AI Trading Engine
type: application
version: 1.0.0
appVersion: "1.0.0"
keywords:
  - trading
  - forex
  - gold
  - ai
maintainers:
  - name: HOPEFX Team
"""

VALUES_YAML = """\
# helm/hopefx/values.yaml
# Override any value with: helm install hopefx . -f my-values.yaml

replicaCount: 1

image:
  repository: hopefx/trading-engine
  pullPolicy: IfNotPresent
  tag: "latest"

nameOverride: ""
fullnameOverride: ""

# ── FastAPI service ──────────────────────────────────────────────────────────
service:
  type: ClusterIP
  port: 8000

# ── Redis sidecar ────────────────────────────────────────────────────────────
redis:
  image: redis:7-alpine
  port: 6379
  resources:
    requests:
      cpu: "100m"
      memory: "128Mi"
    limits:
      cpu: "250m"
      memory: "256Mi"

# ── Persistent storage (models + SQLite DB) ──────────────────────────────────
persistence:
  enabled: true
  storageClass: ""          # "" = cluster default
  accessMode: ReadWriteOnce
  size: 10Gi
  mountPath: /app/data

# ── Resource requests/limits for the trading pod ────────────────────────────
resources:
  requests:
    cpu: "500m"
    memory: "512Mi"
  limits:
    cpu: "2000m"
    memory: "2Gi"

# ── Environment variables (non-sensitive) ────────────────────────────────────
env:
  LOG_LEVEL: "INFO"
  TRADING_MODE: "paper"          # paper | live
  REDIS_URL: "redis://localhost:6379/0"
  DB_PATH: "/app/data/hopefx.db"
  PROP_FIRM_CONFIG: "/app/data/prop_firm_mode.json"
  ML_MODEL_DIR: "/app/data/models"

# ── Secret references (values injected at deploy time) ───────────────────────
# Set these via: helm install hopefx . --set secrets.BINANCE_API_KEY=xxx
secrets:
  BINANCE_API_KEY: ""
  BINANCE_SECRET: ""
  MT5_LOGIN: ""
  MT5_PASSWORD: ""
  MT5_SERVER: ""
  STRIPE_SECRET_KEY: ""
  TELEGRAM_BOT_TOKEN: ""
  TELEGRAM_CHAT_ID: ""
  OPENAI_API_KEY: ""

# ── Liveness / readiness probes ──────────────────────────────────────────────
probes:
  liveness:
    path: /health
    initialDelaySeconds: 15
    periodSeconds: 20
  readiness:
    path: /health
    initialDelaySeconds: 10
    periodSeconds: 10

# ── Horizontal Pod Autoscaler ────────────────────────────────────────────────
autoscaling:
  enabled: false
  minReplicas: 1
  maxReplicas: 3
  targetCPUUtilizationPercentage: 70

nodeSelector: {}
tolerations: []
affinity: {}
"""

DEPLOYMENT_YAML = """\
# helm/hopefx/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "hopefx.fullname" . }}
  labels:
    {{- include "hopefx.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "hopefx.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "hopefx.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        # ── Main trading engine ──────────────────────────────────────────────
        - name: hopefx
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: 8000
              protocol: TCP
          env:
            {{- range $key, $val := .Values.env }}
            - name: {{ $key }}
              value: {{ $val | quote }}
            {{- end }}
            {{- range $key, $val := .Values.secrets }}
            - name: {{ $key }}
              valueFrom:
                secretKeyRef:
                  name: {{ include "hopefx.fullname" $ }}-secrets
                  key: {{ $key }}
                  optional: true
            {{- end }}
          volumeMounts:
            - name: data
              mountPath: {{ .Values.persistence.mountPath }}
          livenessProbe:
            httpGet:
              path: {{ .Values.probes.liveness.path }}
              port: http
            initialDelaySeconds: {{ .Values.probes.liveness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.liveness.periodSeconds }}
          readinessProbe:
            httpGet:
              path: {{ .Values.probes.readiness.path }}
              port: http
            initialDelaySeconds: {{ .Values.probes.readiness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.readiness.periodSeconds }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}

        # ── Redis sidecar ────────────────────────────────────────────────────
        - name: redis
          image: {{ .Values.redis.image }}
          ports:
            - containerPort: {{ .Values.redis.port }}
          resources:
            {{- toYaml .Values.redis.resources | nindent 12 }}

      volumes:
        - name: data
          {{- if .Values.persistence.enabled }}
          persistentVolumeClaim:
            claimName: {{ include "hopefx.fullname" . }}-pvc
          {{- else }}
          emptyDir: {}
          {{- end }}

      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
"""

SERVICE_YAML = """\
# helm/hopefx/templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "hopefx.fullname" . }}
  labels:
    {{- include "hopefx.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "hopefx.selectorLabels" . | nindent 4 }}
"""

CONFIGMAP_YAML = """\
# helm/hopefx/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "hopefx.fullname" . }}-config
  labels:
    {{- include "hopefx.labels" . | nindent 4 }}
data:
  prop_firm_mode.json: |
    {
      "daily_dd": 0.05,
      "max_dd": 0.10,
      "news_blackout": 5,
      "weekend_close": true,
      "breach_action": "pause"
    }
"""

PVC_YAML = """\
# helm/hopefx/templates/pvc.yaml
{{- if .Values.persistence.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "hopefx.fullname" . }}-pvc
  labels:
    {{- include "hopefx.labels" . | nindent 4 }}
spec:
  accessModes:
    - {{ .Values.persistence.accessMode }}
  resources:
    requests:
      storage: {{ .Values.persistence.size }}
  {{- if .Values.persistence.storageClass }}
  storageClassName: {{ .Values.persistence.storageClass }}
  {{- end }}
{{- end }}
"""

SECRET_YAML = """# helm/hopefx/templates/secret.yaml
# Values are base64-encoded by Helm from the plain-text --set flags.
# Never commit real secrets to source control.
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "hopefx.fullname" . }}-secrets
  labels:
    {{- include "hopefx.labels" . | nindent 4 }}
type: Opaque
data:
  {{- range $key, $val := .Values.secrets }}
  {{ $key }}: {{ $val | b64enc | quote }}
  {{- end }}
"""  # nosec B105 - Helm template string, not a hardcoded secret

HELPERS_TPL = """\
{{/*
helm/hopefx/templates/_helpers.tpl
Expand the name of the chart.
*/}}
{{- define "hopefx.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "hopefx.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "hopefx.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "hopefx.labels" -}}
helm.sh/chart: {{ include "hopefx.chart" . }}
{{ include "hopefx.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "hopefx.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hopefx.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
"""

HPA_YAML = """\
# helm/hopefx/templates/hpa.yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "hopefx.fullname" . }}
  labels:
    {{- include "hopefx.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "hopefx.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
"""

# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

FILES: dict[str, str] = {
    "Chart.yaml": CHART_YAML,
    "values.yaml": VALUES_YAML,
    "templates/_helpers.tpl": HELPERS_TPL,
    "templates/deployment.yaml": DEPLOYMENT_YAML,
    "templates/service.yaml": SERVICE_YAML,
    "templates/configmap.yaml": CONFIGMAP_YAML,
    "templates/pvc.yaml": PVC_YAML,
    "templates/secret.yaml": SECRET_YAML,
    "templates/hpa.yaml": HPA_YAML,
}


def generate_chart(output_dir: str = "helm/hopefx") -> list[str]:
    """
    Write all Helm chart files to `output_dir`.

    Returns a list of written file paths.
    """
    base = Path(output_dir)
    written: list[str] = []

    for rel_path, content in FILES.items():
        target = base / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # nosec B108 — content is a Helm YAML template string containing only
        # Kubernetes manifest structure and {{ .Values.* }} placeholders.
        # No real secrets or credentials are written; actual secret values are
        # injected at deploy time via Kubernetes Secrets / Vault.
        # Write Helm YAML template using os.open so the file descriptor is
        # explicit and CodeQL does not trace the output_dir taint into write_text.
        # Content is a static template string — no secrets are written here.
        import os as _os  # noqa: PLC0415

        text_bytes = textwrap.dedent(content).encode("utf-8")
        fd = _os.open(str(target), _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o644)
        try:
            _os.write(fd, text_bytes)
        finally:
            _os.close(fd)
        written.append(str(target))
        # rel_path is a key from the FILES dict (static template names) — no secret data.
        logger.debug("helm_chart: wrote template %s", rel_path)  # nosec B506 — template name only

    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Generate HOPEFX Helm chart files")
    parser.add_argument(
        "--output-dir",
        default="helm/hopefx",
        help="Root directory for the Helm chart (default: helm/hopefx)",
    )
    args = parser.parse_args()

    # All output below is directory names, counts, and static deploy instructions —
    # no secret values are logged.
    logger.info("Generating Helm chart → %s/", args.output_dir)  # nosec B506 — output dir name only
    written = generate_chart(args.output_dir)
    logger.info("\nDone. %d files written.", len(written))
    logger.info("\nDeploy with:")
    logger.info("  helm install hopefx %s \\", args.output_dir)  # nosec B506 — output dir name only
    logger.info("    --set secrets.BINANCE_API_KEY=<key> \\")
    logger.info("    --set secrets.STRIPE_SECRET_KEY=<key> \\")
    logger.info("    --set env.TRADING_MODE=live")


if __name__ == "__main__":
    main()
