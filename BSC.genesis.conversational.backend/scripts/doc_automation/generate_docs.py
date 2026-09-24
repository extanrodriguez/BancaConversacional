#!/usr/bin/env python3
"""
Generador de documentacion tecnica desde Azure DevOps.
- Extrae datos de repositorio, PRs, commits, pipelines y work items.
- Genera documentos Markdown con plantillas personalizables.
- Publica opcionalmente en Confluence (upsert por titulo).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, parse, request


DEFAULT_FILES = {
    "service_catalog": "service_catalog.md",
    "architecture_overview": "architecture_overview.md",
    "changelog": "changelog.md",
    "deployment_guide": "deployment_guide.md",
}

TEMPLATE_FILES = {
    "service_catalog": "service_catalog.md.tpl",
    "architecture_overview": "architecture_overview.md.tpl",
    "changelog": "changelog.md.tpl",
    "deployment_guide": "deployment_guide.md.tpl",
}


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def bool_from_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def is_unresolved_pipeline_var(value: str) -> bool:
    v = value.strip()
    return v.startswith("$(") and v.endswith(")")


def load_config(config_path: Path, repo_root: Path) -> Dict[str, Any]:
    cfg = read_json(config_path)

    env_map = {
        "ado_org_url": "ADO_ORG_URL",
        "ado_project": "ADO_PROJECT",
        "ado_repo_id": "ADO_REPO_ID",
        "ado_pat": "ADO_PAT",
        "ado_bearer_token": "ADO_BEARER_TOKEN",
        "publish_confluence": "PUBLISH_CONFLUENCE",
        "confluence_base_url": "CONFLUENCE_BASE_URL",
        "confluence_space_key": "CONFLUENCE_SPACE_KEY",
        "confluence_user": "CONFLUENCE_USER",
        "confluence_api_token": "CONFLUENCE_API_TOKEN",
        "confluence_parent_title": "CONFLUENCE_PARENT_TITLE",
    }

    for key, env_name in env_map.items():
        env_val = os.getenv(env_name)
        if env_val is None or env_val == "":
            continue
        if is_unresolved_pipeline_var(env_val):
            continue
        cfg[key] = env_val

    cfg.setdefault("output_dir", "docs/generated")
    cfg.setdefault("templates_dir", "scripts/doc_automation/templates")
    cfg.setdefault("templates_override_dir", "docs/doc-automation/templates-overrides")
    cfg.setdefault("since_days", 30)
    cfg.setdefault("max_items", 50)
    cfg.setdefault("publish_confluence", False)
    cfg.setdefault("confluence_parent_title", "Technical Documentation")
    cfg.setdefault("ado_bearer_token", "")

    cfg["publish_confluence"] = bool_from_value(cfg.get("publish_confluence"), False)
    cfg["since_days"] = int(cfg.get("since_days", 30))
    cfg["max_items"] = int(cfg.get("max_items", 50))

    cfg["repo_root"] = str(repo_root)
    cfg["config_path"] = str(config_path)
    cfg["output_dir_abs"] = str((repo_root / cfg["output_dir"]).resolve())
    cfg["templates_dir_abs"] = str((repo_root / cfg["templates_dir"]).resolve())
    cfg["templates_override_dir_abs"] = str((repo_root / cfg["templates_override_dir"]).resolve())

    required = ["ado_org_url", "ado_project"]
    missing = [
        k
        for k in required
        if not str(cfg.get(k, "")).strip() or is_unresolved_pipeline_var(str(cfg.get(k, "")))
    ]
    auth_bearer = str(cfg.get("ado_bearer_token", "")).strip()
    auth_pat = str(cfg.get("ado_pat", "")).strip()
    if is_unresolved_pipeline_var(auth_bearer):
        auth_bearer = ""
    if is_unresolved_pipeline_var(auth_pat):
        auth_pat = ""
    if not auth_bearer and not auth_pat:
        missing.append("ado_bearer_token|ado_pat")
    if missing:
        raise ValueError(f"Faltan configuraciones requeridas: {', '.join(missing)}")

    return cfg


class AzureDevOpsClient:
    def __init__(self, org_url: str, project: str, pat: str = "", bearer_token: str = ""):
        self.org_url = org_url.rstrip("/")
        self.project = project
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if bearer_token:
            self.headers["Authorization"] = f"Bearer {bearer_token}"
        else:
            auth = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
            self.headers["Authorization"] = f"Basic {auth}"

    def _request(
        self,
        method: str,
        url: str,
        query: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if query:
            q = parse.urlencode(query, doseq=True)
            url = f"{url}?{q}"

        payload = None
        if data is not None:
            payload = json.dumps(data).encode("utf-8")

        req = request.Request(url=url, data=payload, method=method, headers=self.headers)
        try:
            with request.urlopen(req, timeout=60) as res:
                raw = res.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as ex:
            body = ex.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Azure DevOps API error {ex.code}: {body}") from ex

    def _api(self, path: str) -> str:
        return f"{self.org_url}/{self.project}/_apis/{path.lstrip('/')}"

    def list_repositories(self) -> List[Dict[str, Any]]:
        data = self._request("GET", self._api("git/repositories"), {"api-version": "7.1-preview.1"})
        return data.get("value", [])

    def get_repository(self, repo_id_or_name: str) -> Dict[str, Any]:
        data = self._request(
            "GET",
            self._api(f"git/repositories/{parse.quote(repo_id_or_name, safe='') }"),
            {"api-version": "7.1-preview.1"},
        )
        return data

    def get_commits(self, repo_id: str, from_date_iso: str, top: int) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            self._api(f"git/repositories/{repo_id}/commits"),
            {
                "api-version": "7.1-preview.1",
                "searchCriteria.fromDate": from_date_iso,
                "searchCriteria.$top": top,
            },
        )
        return data.get("value", [])

    def get_pull_requests(self, repo_id: str, top: int) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            self._api(f"git/repositories/{repo_id}/pullrequests"),
            {
                "api-version": "7.1-preview.1",
                "searchCriteria.status": "completed",
                "$top": top,
            },
        )
        return data.get("value", [])

    def list_pipelines(self) -> List[Dict[str, Any]]:
        data = self._request("GET", self._api("pipelines"), {"api-version": "7.1-preview.1"})
        return data.get("value", [])

    def get_pipeline_runs(self, pipeline_id: int, top: int) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            self._api(f"pipelines/{pipeline_id}/runs"),
            {"api-version": "7.1-preview.1", "$top": top},
        )
        return data.get("value", [])

    def query_recent_work_item_ids(self, top: int) -> List[int]:
        wiql = {
            "query": (
                "Select [System.Id] "
                "From WorkItems "
                "Where [System.TeamProject] = @project "
                "Order By [System.ChangedDate] Desc"
            )
        }
        data = self._request("POST", self._api("wit/wiql"), {"api-version": "7.1-preview.2"}, wiql)
        ids = [w.get("id") for w in data.get("workItems", []) if w.get("id")]
        return ids[:top]

    def get_work_items(self, ids: List[int]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        data = self._request(
            "POST",
            self._api("wit/workitemsbatch"),
            {"api-version": "7.1-preview.1"},
            {
                "ids": ids,
                "fields": [
                    "System.Id",
                    "System.WorkItemType",
                    "System.Title",
                    "System.State",
                    "System.ChangedDate",
                ],
            },
        )
        return data.get("value", [])


class ConfluenceClient:
    def __init__(self, base_url: str, user: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        auth = base64.b64encode(f"{user}:{api_token}".encode("utf-8")).decode("ascii")
        self.headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        query: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{parse.urlencode(query)}"

        payload = json.dumps(data).encode("utf-8") if data is not None else None
        req = request.Request(url=url, data=payload, method=method, headers=self.headers)

        try:
            with request.urlopen(req, timeout=60) as res:
                raw = res.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as ex:
            body = ex.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Confluence API error {ex.code}: {body}") from ex

    def find_page(self, space_key: str, title: str) -> Optional[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/rest/api/content",
            {
                "spaceKey": space_key,
                "title": title,
                "expand": "version",
            },
        )
        results = data.get("results", [])
        return results[0] if results else None

    def create_page(self, space_key: str, title: str, body_storage: str, parent_id: Optional[str]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": body_storage, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        return self._request("POST", "/rest/api/content", data=payload)

    def update_page(self, page_id: str, title: str, version_number: int, body_storage: str) -> Dict[str, Any]:
        payload = {
            "id": str(page_id),
            "type": "page",
            "title": title,
            "version": {"number": int(version_number) + 1},
            "body": {"storage": {"value": body_storage, "representation": "storage"}},
        }
        return self._request("PUT", f"/rest/api/content/{page_id}", data=payload)


def to_confluence_storage(markdown_text: str) -> str:
    escaped = html.escape(markdown_text)
    return f"<h1>Technical Documentation</h1><pre>{escaped}</pre>"


def flatten_relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def build_repo_structure(repo_root: Path, max_depth: int = 4, max_entries: int = 250) -> str:
    ignore_dirs = {
        ".git",
        "node_modules",
        "bin",
        "obj",
        "build",
        "dist",
        ".gradle",
        ".idea",
        ".vscode",
    }
    lines: List[str] = []
    count = 0

    for current, dirs, files in os.walk(repo_root):
        rel = Path(current).resolve().relative_to(repo_root.resolve())
        depth = 0 if str(rel) == "." else len(rel.parts)
        if depth > max_depth:
            dirs[:] = []
            continue

        dirs[:] = [d for d in sorted(dirs) if d not in ignore_dirs]
        files = sorted(files)

        if str(rel) != ".":
            indent = "  " * (depth - 1)
            lines.append(f"{indent}- {rel.parts[-1]}/")
            count += 1

        for file_name in files:
            if file_name.startswith("."):
                continue
            if count >= max_entries:
                lines.append("- ... (truncado)")
                return "\n".join(lines)
            if depth == max_depth:
                continue
            indent = "  " * depth
            lines.append(f"{indent}- {file_name}")
            count += 1

    return "\n".join(lines) if lines else "- (sin estructura detectada)"


def discover_catalog_items(repo_root: Path, max_items: int) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []

    patterns = [
        ("API Controller", re.compile(r"Controller\\.cs$", re.IGNORECASE)),
        ("API Contract", re.compile(r"Contracts?/.*\\.cs$", re.IGNORECASE)),
        ("React Screen", re.compile(r"src/screens/.+\\.(tsx|ts)$", re.IGNORECASE)),
        ("React Component", re.compile(r"src/components/.+\\.(tsx|ts)$", re.IGNORECASE)),
        ("Service", re.compile(r"(Services?|hooks)/.+\\.(cs|tsx|ts)$", re.IGNORECASE)),
        ("Pipeline", re.compile(r"\\.azuredevops/.+\\.ya?ml$", re.IGNORECASE)),
    ]

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = flatten_relative(path, repo_root)
        if any(part in {".git", "node_modules", "bin", "obj", "build", "dist"} for part in Path(rel).parts):
            continue

        item_type = None
        for t_name, rx in patterns:
            if rx.search(rel):
                item_type = t_name
                break

        if item_type is None:
            continue

        display_name = path.stem
        rows.append((display_name, item_type, rel))
        if len(rows) >= max_items:
            break

    return rows


def discover_endpoints(repo_root: Path, max_items: int) -> List[Tuple[str, str, str]]:
    endpoint_rows: List[Tuple[str, str, str]] = []
    endpoint_pattern = re.compile(r"\b(MapGet|MapPost|MapPut|MapDelete|HttpGet|HttpPost|HttpPut|HttpDelete)\s*\(?\s*\"([^\"]+)\"?", re.IGNORECASE)

    for path in sorted(repo_root.rglob("*.cs")):
        rel = flatten_relative(path, repo_root)
        if any(part in {"bin", "obj"} for part in Path(rel).parts):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for match in endpoint_pattern.finditer(content):
            verb = match.group(1)
            route = match.group(2) if match.group(2) else "(ruta no extraida)"
            endpoint_rows.append((route, f"Endpoint {verb}", rel))
            if len(endpoint_rows) >= max_items:
                return endpoint_rows

    return endpoint_rows


def markdown_table_rows_catalog(items: List[Tuple[str, str, str]]) -> str:
    if not items:
        return "| - | - | - | Repositorio local |"
    lines = []
    for name, t, path in items:
        lines.append(f"| {name} | {t} | {path} | Repositorio ({path}) |")
    return "\n".join(lines)


def markdown_list_from_refs(refs: List[Dict[str, Any]], kind: str) -> str:
    if not refs:
        return "- Sin elementos detectados"
    lines = []
    for r in refs:
        if kind == "commit":
            cid = r.get("commitId", "")[:8]
            author = ((r.get("author") or {}).get("name") or "N/A").strip()
            comment = (r.get("comment") or "").splitlines()[0][:120]
            url = (r.get("url") or "").replace("_apis/git/repositories", "_git").replace("/commits/", "/commit/")
            lines.append(f"- {cid} | {author} | {comment} | {url}")
        elif kind == "pr":
            pr_id = r.get("pullRequestId", "")
            title = (r.get("title") or "").strip()[:150]
            status = r.get("status", "")
            url = r.get("url") or ""
            lines.append(f"- PR {pr_id} | {status} | {title} | {url}")
        elif kind == "workitem":
            fields = r.get("fields", {})
            wid = fields.get("System.Id", r.get("id", ""))
            wtype = fields.get("System.WorkItemType", "")
            state = fields.get("System.State", "")
            title = fields.get("System.Title", "")
            org_url = r.get("_webUrl", "")
            lines.append(f"- WI {wid} | {wtype} | {state} | {title} | {org_url}")
        elif kind == "pipeline":
            lines.append(f"- {r}")
    return "\n".join(lines)


def markdown_pipeline_rows(pipelines: List[Dict[str, Any]]) -> str:
    if not pipelines:
        return "| - | - | - |"
    lines = []
    for p in pipelines:
        pid = p.get("id", "")
        name = p.get("name", "")
        url = ((p.get("_links") or {}).get("web") or {}).get("href", "")
        lines.append(f"| {pid} | {name} | {url} |")
    return "\n".join(lines)


def markdown_run_rows(run_rows: List[Dict[str, Any]]) -> str:
    if not run_rows:
        return "| - | - | - | - | - | - |"
    lines = []
    for r in run_rows:
        pipeline_name = ((r.get("pipeline") or {}).get("name") or "")
        run_id = r.get("id", "")
        state = r.get("state", "")
        result = r.get("result", "")
        created = r.get("createdDate", "")
        url = ((r.get("_links") or {}).get("web") or {}).get("href", "")
        lines.append(f"| {pipeline_name} | {run_id} | {state} | {result} | {created} | {url} |")
    return "\n".join(lines)


def load_template(templates_dir: Path, overrides_dir: Path, template_name: str) -> str:
    override_path = overrides_dir / template_name
    default_path = templates_dir / template_name

    if override_path.exists():
        return override_path.read_text(encoding="utf-8")
    if default_path.exists():
        return default_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"No existe plantilla: {template_name}")


def render_template(template: str, context: Dict[str, str]) -> str:
    output = template
    for k, v in context.items():
        output = output.replace(f"{{{{{k}}}}}", v)
    return output


def infer_architecture_mermaid(repo_root: Path) -> str:
    has_dotnet = any(repo_root.rglob("*.csproj"))
    has_react_native = (repo_root / "app.json").exists() and (repo_root / "src").exists()

    if has_dotnet:
        return "\n".join(
            [
                "flowchart LR",
                "  C[Canales Cliente] --> API[API .NET]",
                "  API --> APP[Application Layer]",
                "  APP --> DOM[Domain Layer]",
                "  APP --> INF[Infrastructure Layer]",
                "  INF --> EXT[Servicios Externos]",
                "  API --> CI[CI/CD Azure Pipelines]",
            ]
        )

    if has_react_native:
        return "\n".join(
            [
                "flowchart LR",
                "  U[Usuario Mobile] --> UI[React Native UI]",
                "  UI --> HK[Hooks/State]",
                "  HK --> SV[Servicios API/WebSocket]",
                "  SV --> BE[Backend Conversacional]",
                "  UI --> CI[CI/CD Azure Pipelines]",
            ]
        )

    return "\n".join(
        [
            "flowchart LR",
            "  SRC[Repositorio] --> BUILD[Pipeline Build]",
            "  BUILD --> DEPLOY[Pipeline Deploy]",
            "  DEPLOY --> RUNTIME[Entorno Ejecucion]",
        ]
    )


def collect_all_data(cfg: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    client = AzureDevOpsClient(
        cfg["ado_org_url"],
        cfg["ado_project"],
        cfg.get("ado_pat", ""),
        cfg.get("ado_bearer_token", ""),
    )

    repo_id_or_name = str(cfg.get("ado_repo_id", "")).strip()
    if not repo_id_or_name:
        repositories = client.list_repositories()
        if not repositories:
            raise RuntimeError("No se encontraron repositorios en Azure DevOps")
        repo = repositories[0]
    else:
        repo = client.get_repository(repo_id_or_name)

    repo_id = repo.get("id")
    if not repo_id:
        raise RuntimeError("No fue posible determinar el id del repositorio")

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cfg["since_days"])
    since_iso = since.replace(microsecond=0).isoformat()

    commits = client.get_commits(repo_id, since_iso, cfg["max_items"])
    prs = client.get_pull_requests(repo_id, cfg["max_items"])
    pipelines = client.list_pipelines()

    run_rows: List[Dict[str, Any]] = []
    for p in pipelines[: min(len(pipelines), 10)]:
        try:
            runs = client.get_pipeline_runs(int(p.get("id", 0)), top=5)
            for r in runs:
                r["pipeline"] = {"name": p.get("name", "")}
            run_rows.extend(runs)
        except Exception:
            continue

    wi_ids = client.query_recent_work_item_ids(cfg["max_items"])
    work_items = client.get_work_items(wi_ids)
    for wi in work_items:
        wi_id = wi.get("id")
        wi["_webUrl"] = f"{cfg['ado_org_url'].rstrip('/')}/{cfg['ado_project']}/_workitems/edit/{wi_id}"

    repo_structure = build_repo_structure(repo_root)
    catalog_items = discover_catalog_items(repo_root, cfg["max_items"])
    endpoint_items = discover_endpoints(repo_root, max(10, min(100, cfg["max_items"])))
    if endpoint_items:
        catalog_items.extend(endpoint_items[: max(0, cfg["max_items"] - len(catalog_items))])

    return {
        "repo": repo,
        "commits": commits,
        "prs": prs,
        "pipelines": pipelines,
        "runs": run_rows[: cfg["max_items"]],
        "work_items": work_items,
        "repo_structure": repo_structure,
        "catalog_items": catalog_items[: cfg["max_items"]],
    }


def build_context(cfg: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, str]:
    repo = data["repo"]
    context = {
        "project_name": cfg["ado_project"],
        "generated_at": utc_now_iso(),
        "repo_name": repo.get("name", ""),
        "repo_url": repo.get("webUrl", ""),
        "repo_structure": data["repo_structure"],
        "api_table_rows": markdown_table_rows_catalog(data["catalog_items"]),
        "architecture_mermaid": infer_architecture_mermaid(Path(cfg["repo_root"])),
        "traceability_commits": markdown_list_from_refs(data["commits"], "commit"),
        "traceability_prs": markdown_list_from_refs(data["prs"], "pr"),
        "traceability_workitems": markdown_list_from_refs(data["work_items"], "workitem"),
        "pipeline_table_rows": markdown_pipeline_rows(data["pipelines"]),
        "run_table_rows": markdown_run_rows(data["runs"]),
    }
    return context


def write_docs(cfg: Dict[str, Any], context: Dict[str, str]) -> Dict[str, str]:
    output_dir = Path(cfg["output_dir_abs"])
    templates_dir = Path(cfg["templates_dir_abs"])
    override_dir = Path(cfg["templates_override_dir_abs"])
    ensure_dir(output_dir)

    written: Dict[str, str] = {}
    for doc_key, out_name in DEFAULT_FILES.items():
        template_name = TEMPLATE_FILES[doc_key]
        template = load_template(templates_dir, override_dir, template_name)
        rendered = render_template(template, context)
        out_path = output_dir / out_name
        out_path.write_text(rendered, encoding="utf-8")
        written[doc_key] = str(out_path)

    return written


def write_metadata_snapshot(cfg: Dict[str, Any], data: Dict[str, Any], written_docs: Dict[str, str]) -> str:
    output_dir = Path(cfg["output_dir_abs"])
    ensure_dir(output_dir)

    snapshot = {
        "generated_at": utc_now_iso(),
        "config": {
            "ado_org_url": cfg.get("ado_org_url"),
            "ado_project": cfg.get("ado_project"),
            "ado_repo_id": cfg.get("ado_repo_id"),
            "since_days": cfg.get("since_days"),
            "max_items": cfg.get("max_items"),
            "publish_confluence": cfg.get("publish_confluence"),
            "templates_dir": cfg.get("templates_dir"),
            "templates_override_dir": cfg.get("templates_override_dir"),
        },
        "traceability": {
            "commits_count": len(data.get("commits", [])),
            "pull_requests_count": len(data.get("prs", [])),
            "work_items_count": len(data.get("work_items", [])),
            "pipelines_count": len(data.get("pipelines", [])),
            "pipeline_runs_count": len(data.get("runs", [])),
        },
        "docs": written_docs,
        "build_context": {
            "build_id": os.getenv("BUILD_BUILDID", ""),
            "build_number": os.getenv("BUILD_BUILDNUMBER", ""),
            "source_branch": os.getenv("BUILD_SOURCEBRANCH", ""),
            "source_version": os.getenv("BUILD_SOURCEVERSION", ""),
            "repository_name": os.getenv("BUILD_REPOSITORY_NAME", ""),
        },
    }

    out_path = output_dir / "metadata_snapshot.json"
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out_path)


def publish_docs_to_confluence(cfg: Dict[str, Any], docs_written: Dict[str, str], context: Dict[str, str]) -> List[str]:
    if not cfg.get("publish_confluence"):
        return []

    required = [
        "confluence_base_url",
        "confluence_space_key",
        "confluence_user",
        "confluence_api_token",
    ]
    missing = [k for k in required if not str(cfg.get(k, "")).strip()]
    if missing:
        raise ValueError(f"Confluence habilitado pero faltan variables: {', '.join(missing)}")

    client = ConfluenceClient(
        base_url=cfg["confluence_base_url"],
        user=cfg["confluence_user"],
        api_token=cfg["confluence_api_token"],
    )

    project_name = context.get("project_name", "Project")
    parent_title = cfg.get("confluence_parent_title", "Technical Documentation")
    space_key = cfg["confluence_space_key"]

    parent_page = client.find_page(space_key, parent_title)
    if parent_page is None:
        parent_created = client.create_page(
            space_key=space_key,
            title=parent_title,
            body_storage=to_confluence_storage(f"Documentacion tecnica generada para {project_name}"),
            parent_id=None,
        )
        parent_id = str(parent_created.get("id"))
    else:
        parent_id = str(parent_page.get("id"))

    title_map = {
        "service_catalog": f"{project_name} - Catalogo de Servicios y APIs",
        "architecture_overview": f"{project_name} - Arquitectura de Alto Nivel",
        "changelog": f"{project_name} - Changelog Tecnico",
        "deployment_guide": f"{project_name} - Guia de Despliegue",
    }

    published_pages: List[str] = []
    for key, path in docs_written.items():
        title = title_map.get(key, f"{project_name} - {key}")
        markdown_text = Path(path).read_text(encoding="utf-8")
        body_storage = to_confluence_storage(markdown_text)

        existing = client.find_page(space_key, title)
        if existing is None:
            created = client.create_page(
                space_key=space_key,
                title=title,
                body_storage=body_storage,
                parent_id=parent_id,
            )
            page_id = created.get("id")
            published_pages.append(f"created:{title}:{page_id}")
        else:
            page_id = existing.get("id")
            version_number = ((existing.get("version") or {}).get("number") or 1)
            client.update_page(
                page_id=str(page_id),
                title=title,
                version_number=version_number,
                body_storage=body_storage,
            )
            published_pages.append(f"updated:{title}:{page_id}")

    return published_pages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera documentacion tecnica desde Azure DevOps")
    parser.add_argument("--config", required=True, help="Ruta del archivo JSON de configuracion")
    parser.add_argument("--repo-root", default=".", help="Raiz del repositorio local")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)

    try:
        cfg = load_config(config_path, repo_root)
        data = collect_all_data(cfg, repo_root)
        context = build_context(cfg, data)
        written_docs = write_docs(cfg, context)
        snapshot_path = write_metadata_snapshot(cfg, data, written_docs)
        published = publish_docs_to_confluence(cfg, written_docs, context)

        print("Documentacion generada correctamente")
        for k, p in written_docs.items():
            print(f"- {k}: {p}")
        print(f"- metadata: {snapshot_path}")
        if published:
            print("Paginas publicadas en Confluence:")
            for line in published:
                print(f"- {line}")
        return 0

    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
