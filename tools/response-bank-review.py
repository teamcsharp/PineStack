"""Import reviewed source responses or retire unsuitable text without deleting audio."""
import argparse
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("seeds", nargs="?", type=Path)
    parser.add_argument("--retire", action="append", default=[])
    parser.add_argument("--retire-file", type=Path, help="JSON list of exact response texts to retire")
    parser.add_argument("--reason", default="Retired after source and conversational quality review")
    args = parser.parse_args()
    if args.retire_file:
        args.retire.extend(json.loads(args.retire_file.read_text(encoding="utf-8-sig")))
    entries = json.loads(args.seeds.read_text(encoding="utf-8-sig")) if args.seeds else []
    if not entries and not args.retire:
        parser.error("Provide reviewed seeds or an exact response text to retire")
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    with httpx.Client(base_url="http://127.0.0.1:8096", headers=headers, timeout=900) as client:
        response = client.post("/api/dj/responses/catalog", json={"entries": entries,
            "retire": [{"text": text, "reason": args.reason} for text in args.retire]})
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
