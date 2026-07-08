#!/usr/bin/env python3
"""Minimal Cloudflare zone-analytics exporter for free-plan zones.

lablabs/cloudflare-exporter filters out free-plan zones (see their issue #32),
so it emits nothing for an all-free account. This talks to the GraphQL
Analytics API directly and exposes per-zone metrics in Prometheus text format.

Requests/bytes/cached are a rolling last-24h window via the
httpRequestsAdaptiveGroups dataset (free zones can read it, and it takes an
arbitrary datetime range) so the numbers are meaningful the moment the pod
starts, with no daily-reset cliff. Unique visitors come from
httpRequests1dGroups for the current UTC day — adaptive has no uniq field, and
a set union can't be reconstructed over a rolling window anyway. Note that
Cloudflare counts uniques by client IP, so many devices behind one connection
(or a shared VPN exit) collapse to a single unique.

Standard library only, so it runs on a stock python image with no build step.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CF_API = "https://api.cloudflare.com/client/v4"
GRAPHQL = CF_API + "/graphql"
TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8080"))
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))
WINDOW_HOURS = int(os.environ.get("WINDOW_HOURS", "24"))
# Cloudflare's GraphQL API rejects more than ~10 zones per query ("too many
# zones requested"), so query in chunks and merge.
ZONE_CHUNK = int(os.environ.get("ZONE_CHUNK", "10"))
TIMEOUT = 15

_cache = {"ts": 0.0, "text": ""}

# (metric name, prometheus type, help text, key in the per-zone stats dict)
METRICS = [
    (
        "cf_zone_requests_24h",
        "gauge",
        "HTTP requests for the zone over the last 24h",
        "requests",
    ),
    (
        "cf_zone_cached_requests_24h",
        "gauge",
        "Cached HTTP requests for the zone over the last 24h",
        "cached",
    ),
    (
        "cf_zone_bytes_24h",
        "gauge",
        "Bytes served for the zone over the last 24h",
        "bytes",
    ),
    (
        "cf_zone_uniques_today",
        "gauge",
        "Unique visitors (by client IP) for the zone today (UTC)",
        "uniques",
    ),
]

_CACHE_STATUSES = ["hit", "stale", "updating", "revalidated"]

_QUERY = """
query($tags: [String!], $start: Time!, $end: Time!, $today: Date!) {
  viewer {
    zones(filter: {zoneTag_in: $tags}) {
      zoneTag
      all: httpRequestsAdaptiveGroups(limit: 1, filter: {datetime_geq: $start, datetime_leq: $end}) {
        count
        sum { edgeResponseBytes }
      }
      cached: httpRequestsAdaptiveGroups(limit: 1, filter: {datetime_geq: $start, datetime_leq: $end, cacheStatus_in: %s}) {
        count
      }
      day: httpRequests1dGroups(limit: 1, filter: {date_geq: $today, date_leq: $today}) {
        uniq { uniques }
      }
    }
  }
}""" % json.dumps(_CACHE_STATUSES)


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


def _query_chunk(tags, start, end, today):
    variables = {"tags": tags, "start": start, "end": end, "today": today}
    body = json.dumps({"query": _QUERY, "variables": variables}).encode()
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
    """Per-zone stats: rolling-24h requests/bytes/cached plus today's uniques."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = (now - timedelta(hours=WINDOW_HOURS)).isoformat()
    end = now.isoformat()
    today = now.date().isoformat()
    tags = list(tags)
    out = {}
    for i in range(0, len(tags), ZONE_CHUNK):
        for z in _query_chunk(tags[i : i + ZONE_CHUNK], start, end, today):
            allg = z.get("all") or []
            cachedg = z.get("cached") or []
            dayg = z.get("day") or []
            out[z["zoneTag"]] = {
                "requests": allg[0]["count"] if allg else 0,
                "bytes": allg[0]["sum"]["edgeResponseBytes"] if allg else 0,
                "cached": cachedg[0]["count"] if cachedg else 0,
                "uniques": dayg[0]["uniq"]["uniques"] if dayg else 0,
            }
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
        # Emit every zone, defaulting quiet zones (no data) to 0 so each domain
        # always has a series rather than dropping off the dashboard.
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
