# Automatizacion de Documentacion Tecnica

Esta implementacion genera documentacion tecnica desde metadatos de Azure DevOps y opcionalmente la publica en Confluence.

## Cobertura funcional

- Extraccion de datos de Azure DevOps:
  - Repositorios (metadatos, commits, PRs)
  - Pipelines y ejecuciones
  - Work items recientes
  - Estructura local del repositorio
  - Endpoints API detectados en archivos C#
- Generacion automatica:
  - Catalogo de servicios/APIs
  - Arquitectura de alto nivel (Mermaid)
  - Changelog tecnico
  - Guia de despliegue basada en pipelines
- Publicacion opcional en Confluence
- Ejecucion por evento (merge a main/master) y semanal
- Plantillas personalizables sin tocar codigo
- Trazabilidad de artefactos fuente (commit/PR/work item/pipeline)

## Archivos principales

- scripts/doc_automation/generate_docs.py
- scripts/doc_automation/config.example.json
- scripts/doc_automation/templates/*.md.tpl
- .azuredevops/build/docs-automation.yml

## Variables requeridas

- ADO_ORG_URL
- ADO_PROJECT
- ADO_PAT

Opcionales:

- ADO_REPO_ID
- PUBLISH_CONFLUENCE (true/false)
- CONFLUENCE_BASE_URL
- CONFLUENCE_SPACE_KEY
- CONFLUENCE_USER
- CONFLUENCE_API_TOKEN

## Ejecucion local (piloto)

```powershell
cd c:\Users\extjvisbal\AppConversacionalWorkspace\AppConversacional-BackEnd
$env:ADO_ORG_URL = "https://dev.azure.com/BMSC"
$env:ADO_PROJECT = "Proyecto_Genesis"
$env:ADO_REPO_ID = "BSC.genesis.conversational.backend"
$env:ADO_PAT = "<PAT>"
$env:PUBLISH_CONFLUENCE = "false"
python scripts/doc_automation/generate_docs.py --config scripts/doc_automation/config.example.json --repo-root .
```

Salida:

- docs/generated/service_catalog.md
- docs/generated/architecture_overview.md
- docs/generated/changelog.md
- docs/generated/deployment_guide.md
- docs/generated/metadata_snapshot.json

## Personalizacion de plantillas

Sin cambiar codigo:

1. Crea archivos override en docs/doc-automation/templates-overrides
2. Usa el mismo nombre de plantilla base:
   - service_catalog.md.tpl
   - architecture_overview.md.tpl
   - changelog.md.tpl
   - deployment_guide.md.tpl
3. El motor prioriza overrides y luego templates base.

Variables de plantilla disponibles:

- project_name
- generated_at
- repo_name
- repo_url
- repo_structure
- api_table_rows
- pipeline_table_rows
- run_table_rows
- traceability_commits
- traceability_prs
- traceability_workitems
- architecture_mermaid

## Publicacion en Confluence

Para habilitar:

- PUBLISH_CONFLUENCE=true
- Configura CONFLUENCE_BASE_URL, CONFLUENCE_SPACE_KEY, CONFLUENCE_USER, CONFLUENCE_API_TOKEN

El proceso hace upsert por titulo de pagina y mantiene una pagina raiz por proyecto.

## Trigger por release completado

El pipeline ya corre por merge y semanal.
Para release completed, configura un Service Hook de Azure DevOps hacia el endpoint de ejecucion del pipeline docs-automation.yml.

## Notas de seguridad

- Usa PAT con minimo scope necesario.
- No publiques secretos de variables en plantillas.
- Evita incluir valores sensibles en archivos generados.
