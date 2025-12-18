{{/*
Expand the name of the chart.
*/}}
{{- define "filesystem-connector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "filesystem-connector.fullname" -}}
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

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "filesystem-connector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "filesystem-connector.labels" -}}
{{- $base := dict 
  "helm.sh/chart" (include "filesystem-connector.chart" .) 
  "app.kubernetes.io/managed-by" .Release.Service 
-}}
{{- $sel := (include "filesystem-connector.selectorLabels" . | fromYaml) -}}
{{- $labels := merge $base $sel -}}
{{- if .Chart.AppVersion -}}
{{- $_ := set $labels "app.kubernetes.io/version" (toString .Chart.AppVersion) -}}
{{- end -}}
{{- toYaml $labels -}}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "filesystem-connector.selectorLabels" -}}
{{- $labels := dict 
  "app.kubernetes.io/name" (include "filesystem-connector.name" .) 
  "app.kubernetes.io/instance" .Release.Name 
-}}
{{- toYaml $labels -}}
{{- end -}}

{{/*
HTTP route base used by the application for health/ready endpoints.
Defaults to the DSX connector's logical name, which is different from the chart name.
*/}}
{{- define "filesystem-connector.routeBase" -}}
{{- default "filesystem-connector" .Values.routeBase -}}
{{- end -}}
