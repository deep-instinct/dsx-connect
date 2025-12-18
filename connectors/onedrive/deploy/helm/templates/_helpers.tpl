{{/*
Expand the name of the chart.
*/}}
{{- define "onedrive-connector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "onedrive-connector.fullname" -}}
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

{{- define "onedrive-connector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "onedrive-connector.labels" -}}
{{- $base := dict "helm.sh/chart" (include "onedrive-connector.chart" .) "app.kubernetes.io/managed-by" .Release.Service -}}
{{- $sel := (include "onedrive-connector.selectorLabels" . | fromYaml) -}}
{{- $labels := merge $base $sel -}}
{{- if .Chart.AppVersion -}}
{{- $_ := set $labels "app.kubernetes.io/version" (toString .Chart.AppVersion) -}}
{{- end -}}
{{- toYaml $labels -}}
{{- end -}}

{{- define "onedrive-connector.selectorLabels" -}}
{{- $labels := dict "app.kubernetes.io/name" (include "onedrive-connector.name" .) "app.kubernetes.io/instance" .Release.Name -}}
{{- toYaml $labels -}}
{{- end -}}

{{- define "onedrive-connector.routeBase" -}}
{{- default "onedrive-connector" .Values.routeBase -}}
{{- end -}}
