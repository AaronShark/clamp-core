from __future__ import annotations

import argparse

from recall_common import RECALL_DB, RECALL_MANIFEST, rebuild_recall_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild the local recall index from sessions, memories, and skills.")
    parser.add_argument("--show-paths", action="store_true", help="Print the generated DB and manifest paths.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = rebuild_recall_index()
    counts = summary["counts"]
    print(
        "recall sync complete: "
        f"sessions={counts['session']} "
        f"memories={counts['memory']} "
        f"skills={counts['skill']} "
        f"total={counts['total']}"
    )
    if args.show_paths:
        print(f"db: {RECALL_DB}")
        print(f"manifest: {RECALL_MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
