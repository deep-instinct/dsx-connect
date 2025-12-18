{{/*
Expand the name of the chart.
*/}}
{{- define "aws-s3-connector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "aws-s3-connector.fullname" -}}
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
{{- define "aws-s3-connector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "aws-s3-connector.labels" -}}
{{- $base := dict 
  "helm.sh/chart" (include "aws-s3-connector.chart" .) 
  "app.kubernetes.io/managed-by" .Release.Service 
-}}
{{- $sel := (include "aws-s3-connector.selectorLabels" . | fromYaml) -}}
{{- $labels := merge $base $sel -}}
{{- if .Chart.AppVersion -}}
{{- $_ := set $labels "app.kubernetes.io/version" (toString .Chart.AppVersion) -}}
{{- end -}}
{{- toYaml $labels -}}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "aws-s3-connector.selectorLabels" -}}
{{- $labels := dict 
  "app.kubernetes.io/name" (include "aws-s3-connector.name" .) 
  "app.kubernetes.io/instance" .Release.Name 
-}}
{{- toYaml $labels -}}
{{- end -}}

{{/*
HTTP route base used by the application for health/ready endpoints.
Defaults to the DSX connector's logical name, which is different from the chart name.
*/}}
{{- define "aws-s3-connector.routeBase" -}}
{{- default "aws-s3-connector" .Values.routeBase -}}
{{- end -}}

{{/*
Create the name of the service account to use (not used, but kept for parity)
*/}}
{{- define "aws-s3-connector.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "aws-s3-connector.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
