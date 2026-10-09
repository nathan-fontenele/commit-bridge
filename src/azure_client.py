"""Small Azure DevOps REST 7.1 client with bounded retries and pagination."""

import base64
import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


LOG = logging.getLogger(__name__)
PAGE_SIZE = 100


class AzureError(RuntimeError):
    pass


class AzureClient:
    def __init__(self, organization: str, pat: str, *, pause=time.sleep):
        self.organization = organization
        self.pause = pause
        credentials = base64.b64encode(f":{pat}".encode()).decode()
        self.headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
        self.base = f"https://dev.azure.com/{quote(organization, safe='')}"

    def get(self, path: str, params: dict | None = None):
        query = urlencode({"api-version": "7.1", **(params or {})})
        url = f"{self.base}/{path.lstrip('/')}?{query}"
        request = Request(url, headers=self.headers)
        for attempt in range(5):
            try:
                with urlopen(request, timeout=30) as response:
                    return json.load(response), response.headers
            except HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504):
                    raise AzureError(f"Azure API returned HTTP {exc.code} for {path}") from exc
                retry_after = exc.headers.get("Retry-After", "")
                delay = min(60, int(retry_after)) if retry_after.isdigit() else min(2**attempt, 16)
                LOG.warning("Azure API HTTP %s; retrying in %ss", exc.code, delay)
            except (URLError, TimeoutError) as exc:
                delay = min(2**attempt, 16)
                LOG.warning("Azure API unavailable (%s); retrying in %ss", type(exc).__name__, delay)
            if attempt == 4:
                raise AzureError(f"Azure API failed after retries for {path}")
            self.pause(delay)
        raise AssertionError("unreachable")

    def projects(self):
        token = None
        seen = set()
        project_ids = set()
        skip = 0
        while True:
            params = {"$top": PAGE_SIZE}
            if token:
                params["continuationToken"] = token
            else:
                params["$skip"] = skip
            body, headers = self.get("_apis/projects", params)
            page = body.get("value", [])
            for project in page:
                if project["id"] in project_ids:
                    raise AzureError("Azure projects pagination returned a repeated project")
                project_ids.add(project["id"])
                yield project
            token = headers.get("x-ms-continuationtoken")
            if token in seen:
                raise AzureError("Azure projects pagination repeated a continuation token")
            if not token and len(page) < PAGE_SIZE:
                break
            if token:
                seen.add(token)
            skip += len(page)

    def repositories(self, project_id: str):
        # This endpoint returns the complete repository collection; it has no paging arguments.
        body, _ = self.get(f"{quote(project_id, safe='')}/_apis/git/repositories")
        return body.get("value", [])

    def branches(self, project_id: str, repository_id: str):
        path = f"{quote(project_id, safe='')}/_apis/git/repositories/{quote(repository_id, safe='')}/refs"
        token = None
        seen = set()
        while True:
            params = {"filter": "heads/", "$top": 1000}
            if token:
                params["continuationToken"] = token
            body, headers = self.get(path, params)
            for ref in body.get("value", []):
                if ref.get("name", "").startswith("refs/heads/"):
                    yield ref["name"][len("refs/heads/"):]
            token = headers.get("x-ms-continuationtoken")
            if token in seen:
                raise AzureError("Azure refs pagination repeated a continuation token")
            if not token:
                if len(body.get("value", [])) == 1000:
                    raise AzureError("Azure refs returned a full page without a continuation token")
                break
            seen.add(token)

    def commits(self, project_id: str, repository_id: str, branch: str, from_date: str):
        path = f"{quote(project_id, safe='')}/_apis/git/repositories/{quote(repository_id, safe='')}/commits"
        skip = 0
        while True:
            params = {
                "searchCriteria.itemVersion.version": branch,
                "searchCriteria.itemVersion.versionType": "branch",
                "searchCriteria.fromDate": from_date,
                "searchCriteria.$top": PAGE_SIZE,
                "searchCriteria.$skip": skip,
            }
            body, _ = self.get(path, params)
            page = body.get("value", [])
            yield from page
            if len(page) < PAGE_SIZE:
                break
            skip += len(page)

    def commit(self, project_id: str, repository_id: str, sha: str):
        path = f"{quote(project_id, safe='')}/_apis/git/repositories/{quote(repository_id, safe='')}/commits/{quote(sha, safe='')}"
        body, _ = self.get(path)
        return body
