{{/*
Expand the name of the chart.
*/}}
{{- define "blender-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name.
*/}}
{{- define "blender-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "blender-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "blender-agent.labels" -}}
helm.sh/chart: {{ include "blender-agent.chart" . }}
{{ include "blender-agent.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "blender-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "blender-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "blender-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "blender-agent.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the chart-managed Secret holding the LLM and chat API keys.
*/}}
{{- define "blender-agent.secretName" -}}
{{- printf "%s-secrets" (include "blender-agent.fullname" .) }}
{{- end }}

{{/*
Whether the chart needs to create its own Secret (i.e. a key value was given
inline rather than referencing an existing Secret).
*/}}
{{- define "blender-agent.createSecret" -}}
{{- if or (and .Values.agent.llm.apiKey (not .Values.agent.llm.existingSecret)) (and .Values.agent.chatApiKey.value (not .Values.agent.chatApiKey.existingSecret)) -}}
true
{{- end -}}
{{- end }}
