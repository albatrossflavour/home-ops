#!/usr/bin/env python3
"""Turn a pdctng dashboard export into boards this cluster can actually draw.

pdctng's `rake dashboards:export` writes artefacts that know nothing about any
particular Grafana: panels point at `${DS_PROMETHEUS}` and friends, and the job
name textboxes carry the module's defaults. This applies our local policy to
that output and nothing else, so the module stays free of home-ops and the
lab-specific decisions live here where they belong.

Three things happen:

  * Panels reading a datasource we do not run (Loki, Infinity) are removed,
    along with any row they leave empty, because a "Datasource not found" panel
    is worse than an absent one.
  * gridPos is compacted so the holes those removals leave close up. Rows are
    full width, so the same overlap rule that packs panels also stops anything
    rising past a row header.
  * Job-name textboxes are retargeted at our scrape config, which names its
    node exporter job `node-exporter` rather than the module's `node`.

`${DS_PROMETHEUS}` is resolved here rather than by the chart. The chart's
`datasource:` key does the job with

    sed '/-- .* --/! s/"datasource":.*,/"datasource": "Prometheus",/g'

which needs the whole datasource on one line ending in a comma. pdctng writes
pretty-printed JSON, so `"datasource": {` matches nothing and the variable
survives into the provisioned board. Verified on the cluster: 27 surviving
references in pdctng-estate.json after a real download. Baking the UID in is
also the better answer regardless, because it removes a picker that would
otherwise default to whichever Prometheus Grafana happened to list first, and
this cluster has three.

The guard rails matter more than the transforms. This is a fork by
transformation of someone else's build artefact, so a pdctng release that adds
a datasource or restructures a panel must fail here loudly rather than quietly
emit a half-patched board. cert-manager taught us what a silently bad dashboard
looks like: a literal "404: Not Found" provisioned as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Every datasource variable we expect pdctng to emit. An unrecognised one is a
# hard error: it means a release started using something we have not decided
# about, and guessing is how you end up provisioning a broken board.
KNOWN_DATASOURCES = {
    "DS_PROMETHEUS",
    "DS_LOKI",
    "DS_YESOREYERAM_INFINITY_DATASOURCE",
}

DEFAULT_DROP = ["DS_LOKI", "DS_YESOREYERAM_INFINITY_DATASOURCE"]

# The datasource variable to resolve to a real UID, and what to resolve it to.
# `prometheus` is the Thanos-backed default; `prometheus-local` and `shitbox`
# are the other two, which is exactly why this is not left to a picker.
RESOLVE_DATASOURCE = "DS_PROMETHEUS"
DEFAULT_UID = "prometheus"

# Our scrape config's job names, where they differ from the module's defaults.
# `pdctng_job` already matches (`puppet`), and `windows_job` is left alone: we
# run no windows exporter, so those panels are empty rather than broken, and an
# empty panel is an honest answer.
DEFAULT_VARS = {"node_job": "node-exporter"}

# A board that loses most of its content to the drop pass is not a board any
# more, it is a heading with a stat under it. Better to leave it out and say so
# than to provision something that looks broken for a reason nobody remembers.
MIN_PANELS = 3


class BoardError(Exception):
    """A board we will not write, with the reason a human needs."""


def datasource_uid(node):
    """The DS_ variable a panel or target reads, or None."""
    ds = node.get("datasource") if isinstance(node, dict) else None
    if isinstance(ds, dict):
        uid = ds.get("uid", "")
    elif isinstance(ds, str):
        uid = ds
    else:
        return None
    if uid.startswith("${") and uid.endswith("}"):
        return uid[2:-1]
    return None


def panel_datasources(panel):
    """Every DS_ variable this panel reads, panel level and per target."""
    found = set()
    for node in [panel, *panel.get("targets", [])]:
        uid = datasource_uid(node)
        if uid:
            found.add(uid)
    return found


def check_datasources(board, name):
    declared = {
        v["name"]
        for v in board.get("templating", {}).get("list", [])
        if v.get("type") == "datasource"
    }
    referenced = set()
    for panel in walk_panels(board):
        referenced |= panel_datasources(panel)
    unknown = (declared | referenced) - KNOWN_DATASOURCES
    if unknown:
        raise BoardError(
            f"{name}: unrecognised datasource variable(s) {sorted(unknown)}. "
            "A pdctng release has started using a datasource this script has "
            "no policy for. Decide what to do with it, then add it to "
            "KNOWN_DATASOURCES."
        )


def walk_panels(board):
    """Every content panel, including any nested inside a collapsed row."""
    for panel in board.get("panels", []):
        yield panel
        yield from panel.get("panels", [])


def drop_panels(board, drop):
    """Remove panels reading a dropped datasource. Returns how many went."""
    drop = set(drop)

    def keep(panel):
        return not (panel_datasources(panel) & drop)

    removed = 0
    kept = []
    for panel in board.get("panels", []):
        if panel.get("type") == "row":
            nested = panel.get("panels")
            if nested is not None:
                before = len(nested)
                panel["panels"] = [p for p in nested if keep(p)]
                removed += before - len(panel["panels"])
            kept.append(panel)
        elif keep(panel):
            kept.append(panel)
        else:
            removed += 1
    board["panels"] = kept
    return removed


def drop_empty_rows(board):
    """Remove a row header with nothing left under it.

    Rows here are expanded separators rather than containers, so "under it"
    means between this row and the next one in panel order, not a child list.
    """
    panels = board.get("panels", [])
    keep = [True] * len(panels)
    for i, panel in enumerate(panels):
        if panel.get("type") != "row":
            continue
        if panel.get("panels"):
            continue
        following = panels[i + 1 :]
        band = []
        for other in following:
            if other.get("type") == "row":
                break
            band.append(other)
        if not band:
            keep[i] = False
    removed = keep.count(False)
    board["panels"] = [p for p, k in zip(panels, keep) if k]
    return removed


def compact(board):
    """Close the vertical gaps a removal leaves behind.

    Grafana's own packing rule: a panel may rise until it hits the bottom of
    something it overlaps horizontally. Order is never changed, so the layout
    the board's author drew survives; only the slack goes. Rows span the full
    width, so they act as barriers for free.
    """
    panels = sorted(
        (p for p in board.get("panels", []) if "gridPos" in p),
        key=lambda p: (p["gridPos"].get("y", 0), p["gridPos"].get("x", 0)),
    )
    placed = []
    for panel in panels:
        pos = panel["gridPos"]
        left, right = pos.get("x", 0), pos.get("x", 0) + pos.get("w", 24)
        ceiling = 0
        for other in placed:
            o = other["gridPos"]
            o_left, o_right = o.get("x", 0), o.get("x", 0) + o.get("w", 24)
            if o_left < right and left < o_right:
                ceiling = max(ceiling, o.get("y", 0) + o.get("h", 0))
        pos["y"] = min(pos.get("y", 0), ceiling)
        placed.append(panel)


def prune_variables(board, drop):
    """Drop datasource variables nothing references any more."""
    still_used = set()
    for panel in walk_panels(board):
        still_used |= panel_datasources(panel)
    variables = board.get("templating", {}).get("list", [])
    kept = [
        v
        for v in variables
        if not (v.get("type") == "datasource" and v.get("name") in drop and v.get("name") not in still_used)
    ]
    board.setdefault("templating", {})["list"] = kept
    return len(variables) - len(kept)


def set_textboxes(board, overrides, name):
    """Retarget job-name textboxes at our scrape config."""
    changed = {}
    for var in board.get("templating", {}).get("list", []):
        if var.get("type") != "textbox":
            continue
        want = overrides.get(var.get("name"))
        if want is None or var.get("query") == want:
            continue
        changed[var["name"]] = (var.get("query"), want)
        entry = {"selected": True, "text": want, "value": want}
        var["query"] = want
        var["options"] = [entry]
        var["current"] = dict(entry)
    return changed


def resolve_datasource(board, variable, uid):
    """Replace a datasource variable with a real UID, then drop the variable.

    A `${DS_...}` reference is only a picker, and a picker with three
    Prometheus datasources to choose from is a coin toss dressed up as
    configuration.
    """
    text = json.dumps(board)
    before = text.count("${%s}" % variable)
    if before:
        board.clear()
        board.update(json.loads(text.replace("${%s}" % variable, uid)))
    # The variable goes even when nothing referenced it. The index board is all
    # text and links, so it has the declaration and no queries, and leaving it
    # would put an orphan datasource picker on the one board that exists to be
    # the front door.
    variables = board.get("templating", {}).get("list", [])
    board["templating"]["list"] = [
        v
        for v in variables
        if not (v.get("type") == "datasource" and v.get("name") == variable)
    ]
    return before


def verify(board, drop, name):
    """Nothing we dropped may survive anywhere in the document."""
    text = json.dumps(board)
    for ds in drop:
        if "${%s}" % ds in text:
            raise BoardError(
                f"{name}: {ds} still referenced after the drop pass. The board "
                "uses it somewhere this script does not look (an annotation, a "
                "library panel, a variable definition), so the output would "
                "provision broken."
            )


def process(path, drop, overrides, uid):
    name = path.stem
    board = json.loads(path.read_text())
    check_datasources(board, name)

    before = sum(1 for _ in walk_panels(board))
    dropped = drop_panels(board, drop)
    rows = drop_empty_rows(board)
    if dropped or rows:
        compact(board)
    pruned = prune_variables(board, drop)
    retargeted = set_textboxes(board, overrides, name)
    resolved = resolve_datasource(board, RESOLVE_DATASOURCE, uid)
    verify(board, drop, name)
    if "${DS_" in json.dumps(board):
        raise BoardError(
            f"{name}: an unresolved datasource reference survived. Grafana "
            "would provision this with a picker rather than a datasource."
        )
    after = sum(1 for _ in walk_panels(board))

    return board, {
        "name": name,
        "before": before,
        "after": after,
        "dropped": dropped,
        "rows": rows,
        "variables": pruned,
        "retargeted": retargeted,
        "resolved": resolved,
    }


def helm_values(names, repo, branch, path, datasource):
    """The dashboards block to paste into the Grafana HelmRelease."""
    base = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    lines = ["      pdctng:"]
    for name in names:
        lines.append(f"        {name}:")
        lines.append(f"          url: {base}/{name}.json")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="pdctng `rake dashboards:export` output directory",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "kubernetes/apps/observability/grafana/app/dashboards/pdctng",
        help="where to write the patched boards",
    )
    parser.add_argument(
        "--drop-datasource",
        action="append",
        default=None,
        metavar="DS_NAME",
        help=f"datasource variable to strip (default: {', '.join(DEFAULT_DROP)})",
    )
    parser.add_argument(
        "--set-var",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=f"override a textbox variable (default: {DEFAULT_VARS})",
    )
    parser.add_argument(
        "--min-panels",
        type=int,
        default=MIN_PANELS,
        help=f"skip a board left with fewer panels than this (default {MIN_PANELS})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and report without writing anything",
    )
    parser.add_argument(
        "--print-values",
        action="store_true",
        help="print the HelmRelease dashboards block for the boards written",
    )
    parser.add_argument("--repo", default="albatrossflavour/home-ops")
    parser.add_argument("--branch", default="master")
    parser.add_argument(
        "--datasource",
        default=DEFAULT_UID,
        help=f"datasource UID to bake in for {RESOLVE_DATASOURCE} (default {DEFAULT_UID})",
    )
    args = parser.parse_args()

    drop = args.drop_datasource if args.drop_datasource is not None else DEFAULT_DROP
    overrides = dict(DEFAULT_VARS)
    for pair in args.set_var:
        key, _, value = pair.partition("=")
        if not value:
            parser.error(f"--set-var wants NAME=VALUE, got {pair!r}")
        overrides[key] = value

    sources = sorted(args.source.rglob("*.json"))
    if not sources:
        parser.error(f"no boards under {args.source}")

    boards, reports, failures = {}, [], []
    for path in sources:
        try:
            board, report = process(path, drop, overrides, args.datasource)
        except BoardError as exc:
            failures.append(str(exc))
            continue
        except json.JSONDecodeError as exc:
            failures.append(f"{path.stem}: not valid JSON ({exc})")
            continue
        reports.append(report)
        if report["after"] < args.min_panels:
            report["skipped"] = True
            continue
        boards[report["name"]] = board

    for report in reports:
        bits = []
        if report["dropped"]:
            bits.append(f"-{report['dropped']} panels")
        if report["rows"]:
            bits.append(f"-{report['rows']} empty rows")
        if report["variables"]:
            bits.append(f"-{report['variables']} vars")
        if report["resolved"]:
            bits.append(f"{report['resolved']} ds refs resolved")
        for name, (was, now) in report["retargeted"].items():
            bits.append(f"{name} {was}->{now}")
        if report.get("skipped"):
            bits.append("SKIPPED, too little left")
        if bits:
            print(f"{report['name']}: {report['before']}->{report['after']} panels, "
                  + ", ".join(bits))

    total = sum(r["dropped"] for r in reports)
    skipped = sum(1 for r in reports if r.get("skipped"))
    print(f"\n{len(boards)} boards written, {total} panels dropped, "
          f"{skipped} boards skipped, {len(failures)} failed")

    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1

    if not args.check:
        args.out.mkdir(parents=True, exist_ok=True)
        for stale in args.out.glob("*.json"):
            if stale.stem not in boards:
                stale.unlink()
                print(f"removed stale {stale.name}")
        for name, board in boards.items():
            (args.out / f"{name}.json").write_text(
                json.dumps(board, indent=2, sort_keys=False) + "\n"
            )
        print(f"wrote {len(boards)} boards to {args.out}")

    if args.print_values:
        rel = "kubernetes/apps/observability/grafana/app/dashboards/pdctng"
        print()
        print(helm_values(sorted(boards), args.repo, args.branch, rel, args.datasource))

    return 0


if __name__ == "__main__":
    sys.exit(main())
