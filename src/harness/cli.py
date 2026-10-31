"""Command-line entry point for the proof loop."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config
from .lean_runner import ACCEPTED, LeanRunner, make_prelude
from .llm import LLM
from .loop import Loop
from .problems import SAMPLE_NL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Turn a natural-language theorem into a Lean proof via an LLM loop."
    )
    parser.add_argument(
        "statement",
        nargs="?",
        default=SAMPLE_NL,
        help="Mathematical theorem in natural language. Defaults to a sample.",
    )
    parser.add_argument(
        "--lean",
        action="store_true",
        help="Treat the positional argument as a raw `theorem ... := by` line; skip translation.",
    )
    parser.add_argument("--model", default=None, help="Override DEEPSEEK_MODEL.")
    parser.add_argument(
        "--import",
        dest="imports",
        default=None,
        help="Import line(s) for the --lean path (default: import Mathlib.Tactic).",
    )
    parser.add_argument(
        "--iter", type=int, default=None, help="Override LEAN_MAX_ITER."
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Path to the lake project dir (default: <repo>/infinite_nat).",
    )
    args = parser.parse_args(argv)

    config = Config.from_env()
    if args.model:
        config.model = args.model
    if args.iter is not None:
        config.max_iter = args.iter
    if args.imports:
        config.imports = args.imports
    if args.project:
        config.lean_project_dir = Path(args.project)

    try:
        llm = LLM(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            temperature=config.temperature,
            max_retries=config.llm_retries,
            backoff=config.llm_backoff,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    runner = LeanRunner(config.lean_project_dir, timeout=config.timeout)
    loop = Loop(runner, llm, config)

    print(f"request: {args.statement}", flush=True)
    print(f"model: {config.model} | budget: {config.max_iter} iterations\n", flush=True)

    if args.lean:
        prelude = make_prelude(config.imports, args.statement)
    else:
        print("translating statement…", flush=True)
        try:
            prelude = loop.translate(args.statement)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"translated statement:\n{prelude}\n", flush=True)

    try:
        result = loop.solve(prelude)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "hint: 429/5xx means rate limited or server error. "
            "Wait and retry, lower LEAN_MAX_ITER, or switch DEEPSEEK_MODEL "
            "(deepseek-v4-pro / deepseek-flash).",
            file=sys.stderr,
        )
        return 2

    if result.status == ACCEPTED:
        try:
            result.term = runner.capture_proof_term(prelude, result.proof)
        except Exception:
            result.term = ""
        try:
            result.explanation = loop.explain(prelude, result.proof)
        except Exception as exc:
            result.explanation = f"(explanation unavailable: {exc})"
        try:
            result.lean_explanation = loop.explain_lean(
                prelude, result.proof, result.term
            )
        except Exception as exc:
            result.lean_explanation = f"(explanation unavailable: {exc})"

    print(f"status: {result.status} (iterations used: {result.iterations})")
    print("proof (method):")
    print(result.proof)
    print()
    print("full Lean source:")
    print(result.source)
    print()
    if result.status == ACCEPTED:
        print("accepted by Lean.")
        print()
        print("mathematical proof:")
        print(result.explanation)
        print()
        if result.term:
            print("compiled proof term (from Lean `show_term`, truncated):")
            print(result.term[:1200] + ("..." if len(result.term) > 1200 else ""))
            print()
        print("what Lean did:")
        print(result.lean_explanation)
    else:
        print("not accepted. last diagnostics:")
        for diag in result.check.diagnostics:
            print(f"  [{diag.severity}] {diag.data}")
        for goal in result.check.goals:
            print(f"  goal: {goal}")
    return 0 if result.status == ACCEPTED else 1


if __name__ == "__main__":
    raise SystemExit(main())
