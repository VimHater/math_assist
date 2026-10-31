"""Run Lean on a candidate proof and parse diagnostics."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ACCEPTED = "accepted"
HAS_SORRY = "has_sorry"
FAILED = "failed"


@dataclass
class Diagnostic:
    severity: str
    data: str
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    kind: str | None = None
    file_name: str | None = None


@dataclass
class CheckResult:
    status: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    raw: str = ""


class LeanRunner:
    """Checks candidate proofs by running Lean on a scratch file inside a lake project."""

    def __init__(self, project_dir: Path | str, timeout: float = 60.0):
        self.project_dir = Path(project_dir)
        self.timeout = timeout
        self._scratch = self.project_dir / "_harness_check.lean"

    def build_source(self, prelude: str, proof: str) -> str:
        """Compose a full source file from an import+theorem prelude and a tactic body."""
        body = "\n".join(
            (f"  {line}" if line.strip() else line) for line in proof.splitlines()
        )
        return f"{prelude.rstrip()}\n{body}\n"

    def check(self, source: str) -> CheckResult:
        """Write `source`, run Lean, and return parsed diagnostics + goals."""
        self._scratch.write_text(source)
        try:
            proc = subprocess.run(
                ["lake", "env", "lean", "--json", str(self._scratch.resolve())],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            self._scratch.unlink(missing_ok=True)
            return CheckResult(
                status=FAILED,
                raw="timeout",
                diagnostics=[Diagnostic(severity="error", data="Lean check timed out.")],
            )
        except OSError as exc:
            self._scratch.unlink(missing_ok=True)
            return CheckResult(
                status=FAILED,
                raw=str(exc),
                diagnostics=[
                    Diagnostic(severity="error", data=f"Failed to run Lean: {exc}")
                ],
            )
        finally:
            self._scratch.unlink(missing_ok=True)

        diagnostics: list[Diagnostic] = []
        for line in proc.stdout.splitlines():
            text = line.strip()
            if not text.startswith("{"):
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            pos = obj.get("pos") or {}
            end = obj.get("endPos") or {}
            diagnostics.append(
                Diagnostic(
                    severity=obj.get("severity", "info"),
                    data=obj.get("data", "") or obj.get("caption", ""),
                    line=pos.get("line"),
                    column=pos.get("column"),
                    end_line=end.get("line"),
                    end_column=end.get("column"),
                    kind=obj.get("kind"),
                    file_name=obj.get("fileName"),
                )
            )

        if not diagnostics and proc.returncode != 0:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    data=(proc.stdout + proc.stderr).strip()
                    or "Lean exited with an error but produced no diagnostics.",
                )
            )

        goals: list[str] = []
        for diag in diagnostics:
            goals.extend(_extract_goals(diag.data))

        if any(d.severity == "error" for d in diagnostics):
            status = FAILED
        elif any(d.kind == "hasSorry" for d in diagnostics):
            status = HAS_SORRY
        else:
            status = ACCEPTED

        return CheckResult(
            status=status,
            diagnostics=diagnostics,
            goals=_dedupe(goals),
            raw=proc.stdout + proc.stderr,
        )


def make_prelude(imports: str, theorem: str) -> str:
    """Combine import lines and a `theorem ... := by` line into a checkable prelude."""
    imports = imports.strip()
    theorem = theorem.strip()
    if imports:
        return f"{imports}\n\n{theorem}"
    return theorem


def _extract_goals(message: str) -> list[str]:
    """Pull `⊢ <goal>` fragments out of a Lean message string."""
    goals: list[str] = []
    for line in message.splitlines():
        idx = line.find("⊢")
        if idx != -1:
            goals.append(line[idx + 1 :].strip())
    return goals


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
