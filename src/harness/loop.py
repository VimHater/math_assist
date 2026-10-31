"""The generate-and-check proof loop."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .lean_runner import ACCEPTED, FAILED, HAS_SORRY, CheckResult, LeanRunner
from .llm import LLM

SYSTEM_PROMPT = (
    "You are an expert in Lean 4 and Mathlib. "
    "The user gives you a Lean theorem statement whose proof is incomplete: "
    "the statement ends with `:= by` and the tactic body is missing. "
    "Your only job is to produce the tactic script that completes the proof. "
    "Reply with ONLY the tactic code. No markdown fences, no explanation, "
    "no preamble. Do not use `sorry`, `admit`, or `by_contra!`. "
    "Every answer must be a complete tactic proof."
)

DIRECT_PROMPT = (
    "You are an expert in Lean 4 and Mathlib. "
    "Write a complete, correct Lean proof of the given theorem in one pass. "
    "Study the statement, choose the right approach, then output only the tactic "
    "script that follows `:= by`. No markdown fences, no explanation, no preamble. "
    "Do not use `sorry`, `admit`, or `by_contra!`. Every answer must be a complete "
    "tactic proof."
)

EXPLAIN_PROMPT = (
    "You are a mathematics tutor. "
    "The user shows a Lean 4 theorem and one proof of it. "
    "Explain the mathematical argument in natural language: what the theorem "
    "claims, why it is true, and the key algebraic or logical steps. "
    "Do not mention Lean tactics or syntax. Present the mathematics, not the code."
)

EXPLAIN_LEAN_PROMPT = (
    "You are an expert on Lean 4 internals and Mathlib tactics. "
    "The user shows a Lean 4 theorem, the tactic script that proves it, and the "
    "exact elaborated proof term Lean produced (captured via `show_term`). "
    "Explain, from the term itself, what Lean did mechanically: which lemmas and "
    "constructions the term references, and what normalization or rewriting "
    "happened to close the goal. Name the constants visible in the term. "
    "Plain prose, no code blocks."
)

STATEMENT_PROMPT = (
    "Translate the user's natural-language mathematical statement into Lean 4 code, "
    "using Mathlib. Output one or more `import` lines, then a single theorem "
    "declaration named `target` ending in `:= by` (the proof is filled in later). "
    "Choose narrow imports: always include `import Mathlib.Tactic`, plus any "
    "specific modules the statement's types or definitions require. Default "
    "quantifiers to Nat unless the statement says otherwise. Output only the code, "
    "no markdown fences, no explanation."
)


@dataclass
class SolveResult:
    status: str
    proof: str
    check: CheckResult
    iterations: int
    source: str = ""
    explanation: str = ""
    lean_explanation: str = ""
    term: str = ""


def extract_code(response: str) -> str:
    """Strip markdown code fences if the model added them."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence line and optional language tag.
        if len(lines) >= 2:
            lines = lines[1:]
        # Drop the closing fence if present.
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _clip(text: str, limit: int) -> str:
    """Truncate long text to keep the model context bounded."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… (truncated)"


class Loop:
    def __init__(self, runner: LeanRunner, llm: LLM, config: Config):
        self.runner = runner
        self.llm = llm
        self.config = config

    def solve(self, statement: str) -> SolveResult:
        if self.config.direct_tries > 0:
            direct = self._solve_direct(statement)
            if direct.status == ACCEPTED:
                return direct
            print("direct attempt failed, falling back to tactic loop", flush=True)
        return self._solve_tactic(statement)

    def _solve_direct(self, statement: str) -> SolveResult:
        """Fast path: a few one-shot complete proofs, light feedback between tries."""
        messages: list[dict] = [
            {"role": "system", "content": DIRECT_PROMPT},
            {
                "role": "user",
                "content": (
                    "Write a complete proof for this Lean theorem. The file imports "
                    "Mathlib already. Output only the tactics after `:= by`.\n\n"
                    f"```lean\n{statement}\n  <your tactic script here>\n```"
                ),
            },
        ]
        last_proof = ""
        last_check: CheckResult = CheckResult(FAILED)
        for i in range(self.config.direct_tries):
            response = self.llm.complete(messages)
            proof = extract_code(response) or response
            if not proof.strip():
                proof = "sorry"
            last_proof = proof
            print(f"  [direct {i + 1}/{self.config.direct_tries}] checking…", flush=True)
            last_check = self.runner.check(self.runner.build_source(statement, proof))
            if last_check.status == ACCEPTED:
                return SolveResult(
                    ACCEPTED,
                    proof,
                    last_check,
                    i + 1,
                    self.runner.build_source(statement, proof),
                )
            messages.append({"role": "assistant", "content": proof})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That proof was rejected. Write a correct, complete proof. "
                        "Take a different approach if needed. Output only the tactics."
                    ),
                }
            )
        return SolveResult(
            FAILED,
            last_proof,
            last_check,
            self.config.direct_tries,
            self.runner.build_source(statement, last_proof),
        )

    def _solve_tactic(self, statement: str) -> SolveResult:
        """Fallback: iterative loop with full error/goal feedback."""
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Complete this Lean proof. The file imports Mathlib already.\n\n"
                    f"```lean\n{statement}\n  <your tactic script here>\n```"
                ),
            },
        ]

        last_proof = ""
        last_check: CheckResult | None = None

        for _ in range(self.config.max_iter):
            response = self.llm.complete(messages)
            proof = extract_code(response) or response
            if not proof.strip():
                proof = "sorry"
            last_proof = proof

            last_check = self.runner.check(self.runner.build_source(statement, proof))

            if last_check.status == ACCEPTED:
                source = self.runner.build_source(statement, proof)
                return SolveResult(ACCEPTED, proof, last_check, len(messages), source)
            if last_check.status == HAS_SORRY:
                messages.append({"role": "assistant", "content": proof})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your proof typechecks but uses `sorry`, which is "
                            "forbidden. Replace `sorry` with a real, complete proof. "
                            "Output only the corrected tactic script."
                        ),
                    }
                )
                continue
            # FAILED: give concrete error + goal feedback.
            messages.append({"role": "assistant", "content": proof})
            messages.append(
                {"role": "user", "content": self._feedback(last_check)}
            )

        return SolveResult(
            "budget_exhausted",
            last_proof,
            last_check or CheckResult("failed"),
            self.config.max_iter,
            self.runner.build_source(statement, last_proof),
        )

    def translate(self, natural_language: str) -> str:
        """Turn a natural-language statement into a `theorem target ... := by` line."""
        messages: list[dict] = [
            {"role": "system", "content": STATEMENT_PROMPT},
            {"role": "user", "content": natural_language},
        ]
        for i in range(self.config.max_iter):
            response = self.llm.complete(messages)
            statement = (extract_code(response) or response).strip()
            if not statement:
                statement = natural_language
            print(f"  candidate [{i + 1}/{self.config.max_iter}]: {statement}", flush=True)
            check = self.runner.check(self.runner.build_source(statement, "sorry"))
            if check.status in (HAS_SORRY, ACCEPTED):
                return statement
            messages.append({"role": "assistant", "content": statement})
            messages.append(
                {"role": "user", "content": self._statement_feedback(check)}
            )
        return statement

    def explain(self, statement: str, proof: str) -> str:
        """Ask the model to explain the proof it produced."""
        return self.llm.complete(
            [
                {"role": "system", "content": EXPLAIN_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Statement:\n```lean\n{statement}\n```\n\n"
                        f"Proof:\n```lean\n{proof}\n```"
                    ),
                },
            ]
        )

    def explain_lean(self, statement: str, proof: str, term: str = "") -> str:
        """Ask the model to explain the compiled proof term Lean produced."""
        parts = [
            f"Statement:\n```lean\n{statement}\n```",
            f"Proof:\n```lean\n{proof}\n```",
        ]
        if term:
            parts.append(f"Elaborated proof term (`show_term`):\n{_clip(term, 4000)}")
        return self.llm.complete(
            [
                {"role": "system", "content": EXPLAIN_LEAN_PROMPT},
                {"role": "user", "content": "\n\n".join(parts)},
            ]
        )

    @staticmethod
    def _feedback(check: CheckResult) -> str:
        lines = ["Lean rejects this attempt. Here are the errors:"]
        for diag in check.diagnostics:
            loc = ""
            if diag.file_name and diag.line is not None:
                loc = f"{diag.file_name}:{diag.line}:{diag.column}"
            lines.append(f"- [{diag.severity}] {loc} {diag.data}".rstrip())
        if check.goals:
            lines.append("Remaining goals:")
            for goal in check.goals:
                lines.append(f"  ⊢ {goal}")
        lines.append(
            "Fix the proof and output only the corrected tactic script."
        )
        return "\n".join(lines)

    @staticmethod
    def _statement_feedback(check: CheckResult) -> str:
        lines = ["Lean rejects this statement translation. Errors:"]
        for diag in check.diagnostics:
            loc = ""
            if diag.file_name and diag.line is not None:
                loc = f"{diag.file_name}:{diag.line}:{diag.column}"
            lines.append(f"- [{diag.severity}] {loc} {diag.data}".rstrip())
        if check.goals:
            lines.append("Goals:")
            for goal in check.goals:
                lines.append(f"  ⊢ {goal}")
        lines.append(
            "Rewrite the `theorem target ... := by` declaration so it typechecks. "
            "Output only the corrected declaration."
        )
        return "\n".join(lines)
