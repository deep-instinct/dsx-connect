{{- define "dsx-connect.name" -}}
{{- default (.Chart.Name | trimSuffix "-chart") .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dsx-connect.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "dsx-connect.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "dsx-connect.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "dsx-connect.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
When an embedded service uses auth.existingSecret, the chart owns its connection URL:
the password is read from the Secret and substituted with $(VAR) expansion, which
requires the password variable to be defined before the URL. A matching URL in
.Values.env is skipped so it cannot override the generated one.
*/}}
{{- define "dsx-connect.postgresSecretManaged" -}}
{{- if and .Values.postgresql.enabled .Values.postgresql.auth.existingSecret }}true{{ end -}}
{{- end -}}

{{- define "dsx-connect.rabbitmqSecretManaged" -}}
{{- if and .Values.rabbitmq.enabled .Values.rabbitmq.auth.existingSecret }}true{{ end -}}
{{- end -}}

{{- define "dsx-connect.env" -}}
{{- $fullname := include "dsx-connect.fullname" . -}}
{{- $pgManaged := include "dsx-connect.postgresSecretManaged" . -}}
{{- $mqManaged := include "dsx-connect.rabbitmqSecretManaged" . -}}
- name: PYTHONUNBUFFERED
  value: "1"
- name: DSX_CONNECT_V2_RUNTIME__SCAN_WORKER_REPLICAS
  value: {{ .Values.workers.scan.replicaCount | quote }}
{{- if $pgManaged }}
{{- $pg := .Values.postgresql }}
- name: DSX_CONNECT_CHART_POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $pg.auth.existingSecret | quote }}
      key: {{ $pg.auth.existingSecretPasswordKey | default "password" | quote }}
- name: DSX_CONNECT_V2_POSTGRES__URL
  value: {{ printf "postgresql://%s:$(DSX_CONNECT_CHART_POSTGRES_PASSWORD)@%s-postgres:%v/%s" $pg.auth.username $fullname $pg.service.port $pg.auth.database | quote }}
{{- end }}
{{- if $mqManaged }}
{{- $mq := .Values.rabbitmq }}
- name: DSX_CONNECT_CHART_RABBITMQ_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $mq.auth.existingSecret | quote }}
      key: {{ $mq.auth.existingSecretPasswordKey | default "password" | quote }}
- name: DSX_CONNECT_V2_RABBITMQ__URL
  value: {{ printf "amqp://%s:$(DSX_CONNECT_CHART_RABBITMQ_PASSWORD)@%s-rabbitmq:%v/%%2F" $mq.auth.username $fullname $mq.service.amqpPort | quote }}
{{- end }}
{{- range $key, $val := .Values.env }}
{{- if not (or (and $pgManaged (eq $key "DSX_CONNECT_V2_POSTGRES__URL")) (and $mqManaged (eq $key "DSX_CONNECT_V2_RABBITMQ__URL"))) }}
- name: {{ $key }}
  value: {{ $val | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "dsx-connect.serviceSecretPassword" -}}
{{- if .auth.existingSecret }}
valueFrom:
  secretKeyRef:
    name: {{ .auth.existingSecret | quote }}
    key: {{ .auth.existingSecretPasswordKey | default "password" | quote }}
{{- else }}
value: {{ .auth.password | quote }}
{{- end }}
{{- end -}}
