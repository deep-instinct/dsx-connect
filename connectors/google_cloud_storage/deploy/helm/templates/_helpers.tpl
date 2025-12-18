{{/* Name helpers for GCS connector */}}
{{- define "google-cloud-storage-connector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "google-cloud-storage-connector.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "google-cloud-storage-connector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "google-cloud-storage-connector.labels" -}}
{{- $base := dict 
  "helm.sh/chart" (include "google-cloud-storage-connector.chart" .) 
  "app.kubernetes.io/managed-by" .Release.Service 
-}}
{{- $sel := (include "google-cloud-storage-connector.selectorLabels" . | fromYaml) -}}
{{- $labels := merge $base $sel -}}
{{- if .Chart.AppVersion -}}
{{- $_ := set $labels "app.kubernetes.io/version" (toString .Chart.AppVersion) -}}
{{- end -}}
{{- toYaml $labels -}}
{{- end -}}

{{- define "google-cloud-storage-connector.selectorLabels" -}}
{{- $labels := dict 
  "app.kubernetes.io/name" (include "google-cloud-storage-connector.name" .) 
  "app.kubernetes.io/instance" .Release.Name 
-}}
{{- toYaml $labels -}}
{{- end -}}

{{/*
HTTP route base used by the application for health/ready endpoints.
Defaults to the DSX connector's logical name, which is different from the chart name.
*/}}
{{- define "google-cloud-storage-connector.routeBase" -}}
{{- default "google-cloud-storage-connector" .Values.routeBase -}}
{{- end -}}
