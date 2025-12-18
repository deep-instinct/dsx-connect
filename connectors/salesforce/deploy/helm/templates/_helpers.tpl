{{/*
Expand the chart name.
*/}}
{{- define "salesforce-connector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "salesforce-connector.fullname" -}}
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
{{- define "salesforce-connector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "salesforce-connector.labels" -}}
{{- $base := dict
  "helm.sh/chart" (include "salesforce-connector.chart" .)
  "app.kubernetes.io/managed-by" .Release.Service
-}}
{{- $sel := (include "salesforce-connector.selectorLabels" . | fromYaml) -}}
{{- $labels := merge $base $sel -}}
{{- if .Chart.AppVersion -}}
{{- $_ := set $labels "app.kubernetes.io/version" (toString .Chart.AppVersion) -}}
{{- end -}}
{{- toYaml $labels -}}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "salesforce-connector.selectorLabels" -}}
{{- $labels := dict
  "app.kubernetes.io/name" (include "salesforce-connector.name" .)
  "app.kubernetes.io/instance" .Release.Name
-}}
{{- toYaml $labels -}}
{{- end -}}

{{/*
HTTP route base (health/ready/webhook).
*/}}
{{- define "salesforce-connector.routeBase" -}}
{{- default "salesforce-connector" .Values.routeBase -}}
{{- end -}}
