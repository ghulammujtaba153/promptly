import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.graph import build_app_graph

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promptly — build HTML/CSS/JS apps with plan → architecture → step-by-step files"
    )
    parser.add_argument(
        "request",
        nargs="?",
        help='App description, e.g. "A todo list with add, complete, and delete"',
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Root folder for generated projects (default: output)",
    )
    args = parser.parse_args()

    user_request = args.request
    if not user_request:
        user_request = input("Describe the app you want to build: ").strip()
    if not user_request:
        print("Error: no app description provided.", file=sys.stderr)
        return 1

    graph = build_app_graph()
    result = graph.invoke(
        {
            "user_request": user_request,
            "ui_style": "",
            "output_root": str(Path(args.output)),
            "current_file_index": 0,
            "generated_files": {},
            "ui_fix_rounds": 0,
            "status": "starting",
        }
    )

    print("\n=== DONE ===")
    print(f"Project: {result.get('project_name', 'unknown')}")
    print(f"Location: {result.get('output_root')}")
    print(f"Files created: {len(result.get('generated_files', {}))}")
    for path in result.get("generated_files", {}):
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
