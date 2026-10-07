"""Explore the official FPL API once and save trimmed response samples to ``tests/fixtures/``.

Calls bootstrap-static, fixtures, element-summary/{id} and event/{gw}/live with a browser-like
User-Agent and a 0.25 s pause between calls, then prints every field name it saw. The samples are
what the (network-free) tests and P5's schema checks run against.

    python scripts/explore_api.py            # element = most-selected player, gw = 1
    python scripts/explore_api.py --element 430 --gw 3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fPLense import config
from fPLense.etl import net

N_KEEP = 5  # list items kept per array in the saved samples


def save(name: str, payload: object) -> Path:
    path = config.TESTS_FIXTURES_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def field_names(records: list[dict]) -> list[str]:
    return sorted({k for r in records for k in r})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Explore the FPL API and save samples")
    parser.add_argument("--element", type=int, help="player id for element-summary")
    parser.add_argument("--gw", type=int, default=1, help="gameweek for event/{gw}/live")
    args = parser.parse_args(argv)

    base = config.FPL_API_BASE_URL
    session = net.make_session()
    fields: dict[str, list[str]] = {}

    boot = net.get_json(f"{base}/bootstrap-static/", session)
    fields["bootstrap-static (top level)"] = sorted(boot)
    for key in ("elements", "teams", "events", "element_types"):
        fields[f"bootstrap-static.{key}"] = field_names(boot[key])
    elements = sorted(boot["elements"], key=lambda e: -float(e["selected_by_percent"]))
    element_id = args.element or elements[0]["id"]
    save(
        "bootstrap_static_sample.json",
        {
            "elements": elements[:N_KEEP],
            "teams": boot["teams"],
            "events": boot["events"][:N_KEEP],
            "element_types": boot["element_types"],
        },
    )

    fixtures = net.get_json(f"{base}/fixtures/", session)
    fields["fixtures"] = field_names(fixtures)
    save("fixtures_sample.json", fixtures[:N_KEEP])

    summary = net.get_json(f"{base}/element-summary/{element_id}/", session)
    fields["element-summary (top level)"] = sorted(summary)
    for key in ("history", "fixtures", "history_past"):
        fields[f"element-summary.{key}"] = field_names(summary[key])
    save(
        "element_summary_sample.json",
        {"element": element_id, **{k: summary[k][:N_KEEP] for k in summary}},
    )

    live = net.get_json(f"{base}/event/{args.gw}/live/", session)
    live_elements = live["elements"]
    fields["event-live.elements"] = field_names(live_elements)
    fields["event-live.elements[].stats"] = field_names([e["stats"] for e in live_elements])
    save("event_live_sample.json", {"gw": args.gw, "elements": live_elements[:N_KEEP]})

    save("api_fields.json", fields)
    for name, cols in fields.items():
        print(f"\n{name} ({len(cols)}):\n  " + ", ".join(cols))
    print(f"\nsamples saved to {config.TESTS_FIXTURES_DIR}")


if __name__ == "__main__":
    main()
