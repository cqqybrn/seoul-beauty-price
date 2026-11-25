import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from pipeline.analyst.client import AnalystAPIError, check_connection
from pipeline.budget import BudgetExceeded
from pipeline.config import Settings
from pipeline.db import migrate
from pipeline.ingest import export_unlabeled
from pipeline.runner import STEPS, run
from pipeline.sources.base import SourceNotReady


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="Seoul beauty price pipeline")
    parser.add_argument("--db", type=Path, help="Override SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "step"):
        p = sub.add_parser(name)
        if name == "step":
            p.add_argument("name", choices=STEPS)
        p.add_argument("--live", action="store_true", help="Require implemented live steps")
    sub.add_parser("migrate")
    sub.add_parser("analyst-check", help="Make one small paid analysis API connection check")
    sub.add_parser("batch-submit", help="Submit pending options to native Gemini batch API")
    batch_poll = sub.add_parser("batch-poll", help="Poll once and import a recorded Gemini batch")
    batch_poll.add_argument("batch_name")
    golden = sub.add_parser(
        "evaluate", help="Evaluate 100 designer gold labels against predictions"
    )
    golden.add_argument("golden", type=Path)
    golden.add_argument("predictions", type=Path)
    export = sub.add_parser(
        "export-unlabeled", help="Export exactly 100 real options for annotation"
    )
    export.add_argument("--output", type=Path, default=Path("tests/golden/unlabeled.jsonl"))
    args = parser.parse_args(argv)
    try:
        overrides = {"database": args.db} if args.db else {}
        settings = Settings(**overrides)
        if args.command == "migrate":
            print(
                json.dumps(
                    {"migrations_applied": migrate(settings.database, settings.migrations_dir)}
                )
            )
        elif args.command == "analyst-check":
            print(json.dumps(check_connection(settings), ensure_ascii=False))
        elif args.command in {"batch-submit", "batch-poll"}:
            from pipeline.extract.batch import poll_batch, submit_batch

            migrate(settings.database, settings.migrations_dir)
            value = (
                submit_batch(settings)
                if args.command == "batch-submit"
                else poll_batch(settings, args.batch_name)
            )
            print(json.dumps(value))
        elif args.command == "evaluate":
            from pipeline.extract.evaluate import evaluate

            value = evaluate(args.golden, args.predictions)
            print(json.dumps(value))
            return 0 if value["accepted"] else 1
        elif args.command == "export-unlabeled":
            count = export_unlabeled(settings.database, args.output)
            print(json.dumps({"exported": count, "output": str(args.output.resolve())}))
        else:
            run(
                settings,
                step=getattr(args, "name", None),
                live=args.live,
                emit=lambda row: print(json.dumps(row)),
            )
    except ValidationError as exc:
        # Do not print Pydantic input values: an invalid env field could contain a secret.
        print(
            json.dumps(
                {
                    "error": "Invalid configuration",
                    "fields": [
                        ".".join(map(str, e["loc"])) for e in exc.errors(include_input=False)
                    ],
                }
            ),
            file=sys.stderr,
        )
        return 2
    except (SourceNotReady, AnalystAPIError, BudgetExceeded, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
