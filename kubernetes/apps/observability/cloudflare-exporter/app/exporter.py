#!/usr/bin/env python3
"""Minimal Cloudflare zone-analytics exporter for free-plan zones.

lablabs/cloudflare-exporter filters out free-plan zones (see their issue #32),
so it emits nothing for an all-free account. This talks to the GraphQL
Analytics API directly using the httpRequests1dGroups dataset, which free
zones CAN read, and exposes per-zone daily totals in Prometheus text format.

Standard library only, so it runs on a stock python image with no build step.
Values are "today so far" in UTC; the Cloudflare daily bucket rolls at UTC
midnight (10:00 AEST), which is worth remembering when reading the graphs.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CF_API = "https://api.cloudflare.com/client/v4"
GRAPHQL = CF_API + "/graphql"
TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8080"))
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))
# Cloudflare's GraphQL API rejects more than ~10 zones per query ("too many
# zones requested"), so query in chunks and merge.
ZONE_CHUNK = int(os.environ.get("ZONE_CHUNK", "10"))
TIMEOUT = 15

_cache = {"ts": 0.0, "text": ""}

# (metric name, prometheus type, help text, key in the per-zone stats dict)
#
# The request/byte metrics are today's running total in UTC, which climbs
# through the day and drops to ~0 at UTC midnight. Exposed as counters so
# Prometheus reads that drop as a counter reset: increase(<metric>[$__range])
# then yields the count over whatever window the Grafana time picker is set
# to, with no daily cliff. Uniques stay a gauge — a set union can't be summed
# across days, so "uniques over an arbitrary window" isn't reconstructable.
METRICS = [
    (
        "cf_zone_requests_total",
        "counter",
        "HTTP requests for the zone today (UTC), resets at UTC midnight; window with increase()",
        "requests",
    ),
    (
        "cf_zone_bytes_total",
        "counter",
        "Bytes served for the zone today (UTC), resets at UTC midnight; window with increase()",
        "bytes",
    ),
    (
        "cf_zone_cached_requests_total",
        "counter",
        "Cached HTTP requests for the zone today (UTC), resets at UTC midnight; window with increase()",
        "cachedRequests",
    ),
    (
        "cf_zone_cached_bytes_total",
        "counter",
        "Cached bytes served for the zone today (UTC), resets at UTC midnight; window with increase()",
        "cachedBytes",
    ),
    (
        "cf_zone_uniques_today",
        "gauge",
        "Unique visitors for the zone so far today (UTC); not windowable",
        "uniques",
    ),
]


def _api_get(path):
    req = urllib.request.Request(
        CF_API + path, headers={"Authorization": "Bearer " + TOKEN}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def list_zones():
    """Return {zoneTag: zoneName} for every zone the token can see."""
    zones = {}
    page = 1
    while True:
        data = _api_get(f"/zones?per_page=50&page={page}")
        for z in data.get("result", []):
            zones[z["id"]] = z["name"]
        info = data.get("result_info") or {}
        if page >= (info.get("total_pages") or 1):
            break
        page += 1
    return zones


_QUERY = """
query($tags: [String!], $day: Date!) {
  viewer {
    zones(filter: {zoneTag_in: $tags}) {
      zoneTag
      httpRequests1dGroups(limit: 1, filter: {date_geq: $day, date_leq: $day}) {
        sum { requests bytes cachedRequests cachedBytes }
        uniq { uniques }
      }
    }
  }
}"""


def _query_chunk(tags, today):
    body = json.dumps(
        {"query": _QUERY, "variables": {"tags": tags, "day": today}}
    ).encode()
    req = urllib.request.Request(
        GRAPHQL,
        data=body,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        payload = json.load(r)
    if payload.get("errors"):
        raise RuntimeError(f"graphql errors: {payload['errors']}")
    return payload["data"]["viewer"]["zones"]


def query_analytics(tags):
    """Today's daily HTTP totals per zone, batched to respect the API's cap."""
    today = datetime.now(timezone.utc).date().isoformat()
    tags = list(tags)
    out = {}
    for start in range(0, len(tags), ZONE_CHUNK):
        for z in _query_chunk(tags[start : start + ZONE_CHUNK], today):
            groups = z.get("httpRequests1dGroups") or []
            if not groups:
                continue
            g = groups[0]
            out[z["zoneTag"]] = {**g["sum"], "uniques": g["uniq"]["uniques"]}
    return out


def _esc(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render():
    zones = list_zones()
    stats = query_analytics(zones.keys())
    lines = [
        "# HELP cf_exporter_up 1 if the last Cloudflare scrape succeeded",
        "# TYPE cf_exporter_up gauge",
        "cf_exporter_up 1",
    ]
    for name, mtype, help_text, key in METRICS:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")
        # Emit every zone, defaulting idle zones (no data today) to 0 so each
        # domain always has a series rather than dropping off the dashboard.
        for tag, zone_name in zones.items():
            value = stats.get(tag, {}).get(key, 0)
            lines.append(f'{name}{{zone="{_esc(zone_name)}"}} {value}')
    return "\n".join(lines) + "\n"


def get_metrics():
    now = time.time()
    if _cache["text"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["text"]
    try:
        text = render()
        _cache.update(ts=now, text=text)
        return text
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as err:
        print(f"scrape error: {err}", flush=True)
        return "# HELP cf_exporter_up 1 if the last Cloudflare scrape succeeded\n# TYPE cf_exporter_up gauge\ncf_exporter_up 0\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/healthz":
            self._send(200, "ok\n", "text/plain")
        elif path in ("/metrics", ""):
            self._send(200, get_metrics(), "text/plain; version=0.0.4")
        else:
            self._send(404, "not found\n", "text/plain")

    def _send(self, code, body, content_type):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silence per-request logging
        pass


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("CF_API_TOKEN is not set")
    print(
        f"cf-zone-exporter serving on :{LISTEN_PORT}/metrics (cache {CACHE_TTL}s)",
        flush=True,
    )
    ThreadingHTTPServer(("", LISTEN_PORT), Handler).serve_forever()
