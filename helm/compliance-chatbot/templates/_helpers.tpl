{{- define "chatbot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "chatbot.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "chatbot.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "chatbot.labels" -}}
app.kubernetes.io/name: {{ include "chatbot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "chatbot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "chatbot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
