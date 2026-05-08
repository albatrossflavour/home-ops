"""Shitbox Rally donation tracker — Prometheus exporter + JSON writer.

Polls the team fundraising page every POLL_INTERVAL seconds, parses out
the running total and goal, and exposes the values two ways:

  - Prometheus /metrics on :8000 (gauges, scraped by Prometheus)
  - donation.json on a shared volume (served by the SoT nginx pod)

Both feeds are derived from the same scrape, so the website and the
Grafana dashboard never disagree.

The fundraising platform doesn't expose a JSON endpoint we can use, so
this is HTML scraping. The CSS classes (.team-header-raised /
.team-header-goal) are stable enough across page changes that this is
unlikely to break, but if it does the regex below is the only thing
to retune.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from prometheus_client import Gauge, start_http_server

URL = os.environ.get(
    "DONATION_URL",
    "https://autumn2026.shitboxrally.com.au/a-team-has-no-name",
)
OUTPUT_PATH = Path(os.environ.get("OUTPUT_PATH", "/shared/donation.json"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8000"))

raised_g = Gauge("shitbox_donation_raised_aud", "Total donations raised, AUD")
goal_g = Gauge("shitbox_donation_goal_aud", "Donation goal, AUD")
fetch_ok_g = Gauge(
    "shitbox_donation_fetch_ok", "1 if last fetch succeeded, 0 otherwise"
)

RAISED_RE = re.compile(r'team-header-raised">.*?\$([0-9,]+)</strong>', re.S)
GOAL_RE = re.compile(r'team-header-goal">.*?\$([0-9,]+)</strong>', re.S)


def fetch_once() -> None:
    try:
        resp = requests.get(
            URL, timeout=15, headers={"User-Agent": "shitbox-donation/1"}
        )
        resp.raise_for_status()
        html = resp.text
        m_r = RAISED_RE.search(html)
        m_g = GOAL_RE.search(html)
        if not (m_r and m_g):
            print(
                "could not parse raised/goal from page — selectors may have changed",
                file=sys.stderr,
            )
            fetch_ok_g.set(0)
            return
        raised = int(m_r.group(1).replace(",", ""))
        goal = int(m_g.group(1).replace(",", ""))
        raised_g.set(raised)
        goal_g.set(goal)
        fetch_ok_g.set(1)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(
                {
                    "raised_aud": raised,
                    "goal_aud": goal,
                    "percent": round(raised * 100 / goal, 1) if goal else 0,
                    "team": "A Team Has No Name",
                    "url": URL,
                    "updated_at_utc": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                }
            )
        )
        print(f"raised=${raised:,} goal=${goal:,} ({round(raised * 100 / goal, 1)}%)")
    except Exception as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        fetch_ok_g.set(0)


def main() -> None:
    start_http_server(METRICS_PORT)
    print(f"metrics on :{METRICS_PORT}, polling every {POLL_INTERVAL}s")
    while True:
        fetch_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
