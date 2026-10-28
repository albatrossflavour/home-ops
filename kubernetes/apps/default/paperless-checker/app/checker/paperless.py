"""Paperless API client. Deliberately has no way to delete anything."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TRAILING_DATE = re.compile(r"\s*\d{4}-\d{2}(-\d{2})?$")


class PaperlessClient:
    def __init__(self, base_url, token, opener=urllib.request.urlopen):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Token {token}", "Accept": "application/json; version=9"}
        self.opener = opener

    def _call(self, method, path, params=None, body=None):
        url = path if path.startswith("http") else f"{self.base}/api/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = dict(self.headers, **({"Content-Type": "application/json"} if data else {}))
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with self.opener(req, timeout=60) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def _all(self, path, params):
        page = self._call("GET", path, params)
        results = list(page["results"])
        while page.get("next"):
            page = self._call("GET", page["next"])
            results += page["results"]
        return results

    def ready_documents(self, since, exclude_tag_ids, limit):
        params = {"modified__gt": since, "ordering": "modified", "page_size": limit}
        if exclude_tag_ids:
            params["tags__id__none"] = ",".join(map(str, exclude_tag_ids))
        return self._call("GET", "documents/", params)["results"]

    def document(self, doc_id):
        try:
            return self._call("GET", f"documents/{doc_id}/")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def neighbours(self, doc, n=5):
        query = TRAILING_DATE.sub("", doc["title"])
        found = self._call("GET", "documents/", {"query": query, "page_size": n + 1})["results"]
        return [d for d in found if d["id"] != doc["id"]][:n]

    def history(self, doc_id):
        return self._call("GET", f"documents/{doc_id}/history/")

    def notes(self, doc_id):
        return self._call("GET", f"documents/{doc_id}/notes/")

    def tagged(self, tag_id):
        return self._all("documents/", {"tags__id__all": tag_id, "ordering": "-modified", "page_size": 100})

    def add_note(self, doc_id, text):
        self._call("POST", f"documents/{doc_id}/notes/", body={"note": text})

    def patch(self, doc_id, fields):
        return self._call("PATCH", f"documents/{doc_id}/", body=fields)

    def lookup(self, kind):
        key = "username" if kind == "users" else "name"
        return {o[key]: o["id"] for o in self._all(f"{kind}/", {"page_size": 500})}

    def create_correspondent(self, name):
        return self._call("POST", "correspondents/", body={"name": name, "matching_algorithm": 0})["id"]
