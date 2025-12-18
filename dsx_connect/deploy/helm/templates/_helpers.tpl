{{/*
Shared helpers for dsx-connect components rendered from the root chart.
*/}}

{{- define "dsx.chartLabel" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "dsx.component.name" -}}
{{- $root := .root -}}
{{- $key := .component -}}
{{- $componentVals := (index $root.Values $key) | default (dict) -}}
{{- default $key $componentVals.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "dsx.component.fullname" -}}
{{- $root := .root -}}
{{- $key := .component -}}
{{- $componentVals := (index $root.Values $key) | default (dict) -}}
{{- if $componentVals.fullnameOverride }}
{{- $componentVals.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default $key $componentVals.nameOverride }}
{{- if contains $name $root.Release.Name }}
{{- $root.Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" $root.Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "dsx.component.selectorLabels" -}}
app.kubernetes.io/name: {{ include "dsx.component.name" . }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end }}

{{- define "dsx.component.labels" -}}
helm.sh/chart: {{ include "dsx.chartLabel" .root }}
{{ include "dsx.component.selectorLabels" . }}
{{- if .root.Chart.AppVersion }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{- define "dsx.component.serviceAccountName" -}}
{{- $root := .root -}}
{{- $key := .component -}}
{{- $componentVals := (index $root.Values $key) | default (dict) -}}
{{- $serviceAccount := $componentVals.serviceAccount | default (dict) -}}
{{- if $serviceAccount.create }}
{{- default (include "dsx.component.fullname" .) $serviceAccount.name }}
{{- else }}
{{- default "default" $serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "dsx-connect-api.name" -}}
{{- include "dsx.component.name" (dict "root" . "component" "dsx-connect-api") -}}
{{- end }}

{{- define "dsx-connect-api.fullname" -}}
{{- include "dsx.component.fullname" (dict "root" . "component" "dsx-connect-api") -}}
{{- end }}

{{- define "dsx-connect-api.selectorLabels" -}}
{{- include "dsx.component.selectorLabels" (dict "root" . "component" "dsx-connect-api") -}}
{{- end }}

{{- define "dsx-connect-api.labels" -}}
{{- include "dsx.component.labels" (dict "root" . "component" "dsx-connect-api") -}}
{{- end }}

{{- define "dsx-connect-api.serviceAccountName" -}}
{{- include "dsx.component.serviceAccountName" (dict "root" . "component" "dsx-connect-api") -}}
{{- end }}

{{- define "dsx-connect-scan-request-worker.name" -}}
{{- include "dsx.component.name" (dict "root" . "component" "dsx-connect-scan-request-worker") -}}
{{- end }}

{{- define "dsx-connect-scan-request-worker.fullname" -}}
{{- include "dsx.component.fullname" (dict "root" . "component" "dsx-connect-scan-request-worker") -}}
{{- end }}

{{- define "dsx-connect-scan-request-worker.selectorLabels" -}}
{{- include "dsx.component.selectorLabels" (dict "root" . "component" "dsx-connect-scan-request-worker") -}}
{{- end }}

{{- define "dsx-connect-scan-request-worker.labels" -}}
{{- include "dsx.component.labels" (dict "root" . "component" "dsx-connect-scan-request-worker") -}}
{{- end }}

{{- define "dsx-connect-verdict-action-worker.name" -}}
{{- include "dsx.component.name" (dict "root" . "component" "dsx-connect-verdict-action-worker") -}}
{{- end }}

{{- define "dsx-connect-verdict-action-worker.fullname" -}}
{{- include "dsx.component.fullname" (dict "root" . "component" "dsx-connect-verdict-action-worker") -}}
{{- end }}

{{- define "dsx-connect-verdict-action-worker.selectorLabels" -}}
{{- include "dsx.component.selectorLabels" (dict "root" . "component" "dsx-connect-verdict-action-worker") -}}
{{- end }}

{{- define "dsx-connect-verdict-action-worker.labels" -}}
{{- include "dsx.component.labels" (dict "root" . "component" "dsx-connect-verdict-action-worker") -}}
{{- end }}

{{- define "dsx-connect-results-worker.name" -}}
{{- include "dsx.component.name" (dict "root" . "component" "dsx-connect-results-worker") -}}
{{- end }}

{{- define "dsx-connect-results-worker.fullname" -}}
{{- include "dsx.component.fullname" (dict "root" . "component" "dsx-connect-results-worker") -}}
{{- end }}

{{- define "dsx-connect-results-worker.selectorLabels" -}}
{{- include "dsx.component.selectorLabels" (dict "root" . "component" "dsx-connect-results-worker") -}}
{{- end }}

{{- define "dsx-connect-results-worker.labels" -}}
{{- include "dsx.component.labels" (dict "root" . "component" "dsx-connect-results-worker") -}}
{{- end }}

{{- define "dsx-connect-notification-worker.name" -}}
{{- include "dsx.component.name" (dict "root" . "component" "dsx-connect-notification-worker") -}}
{{- end }}

{{- define "dsx-connect-notification-worker.fullname" -}}
{{- include "dsx.component.fullname" (dict "root" . "component" "dsx-connect-notification-worker") -}}
{{- end }}

{{- define "dsx-connect-notification-worker.selectorLabels" -}}
{{- include "dsx.component.selectorLabels" (dict "root" . "component" "dsx-connect-notification-worker") -}}
{{- end }}

{{- define "dsx-connect-notification-worker.labels" -}}
{{- include "dsx.component.labels" (dict "root" . "component" "dsx-connect-notification-worker") -}}
{{- end }}

{{- define "dsx-connect-dianna-worker.name" -}}
{{- include "dsx.component.name" (dict "root" . "component" "dsx-connect-dianna-worker") -}}
{{- end }}

{{- define "dsx-connect-dianna-worker.fullname" -}}
{{- include "dsx.component.fullname" (dict "root" . "component" "dsx-connect-dianna-worker") -}}
{{- end }}

{{- define "dsx-connect-dianna-worker.selectorLabels" -}}
{{- include "dsx.component.selectorLabels" (dict "root" . "component" "dsx-connect-dianna-worker") -}}
{{- end }}

{{- define "dsx-connect-dianna-worker.labels" -}}
{{- include "dsx.component.labels" (dict "root" . "component" "dsx-connect-dianna-worker") -}}
{{- end }}
