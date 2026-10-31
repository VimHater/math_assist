# LLM + Lean proof harness

A minimal generate-and-check loop that asks an LLM to complete a Lean 4 /
Mathlib proof, then verifies the result with Lean and feeds errors back for
retries.

## Layout

```
src/harness/lean_runner.py   Runs `lake env lean --json` and parses diagnostics
src/harness/llm.py           OpenAI-compatible chat client
src/harness/loop.py          Prompt -> check -> feedback loop
src/harness/problems.py      Sample theorem statements
src/harness/cli.py           Command-line entry point
```

## Setup

```bash
.python_venv/bin/python -m pip install -r requirements.txt
```

> Note: use `python -m pip`, not the `pip` script. The venv's script shebangs
> still point at the old `python_venv/` path that no longer exists.

## Configuration (environment variables)

| Variable               | Default                     | Meaning                          |
|------------------------|-----------------------------|----------------------------------|
| `DEEPSEEK_API_KEY`     | *(required)*                | DeepSeek API key                 |
| `DEEPSEEK_BASE_URL`    | `https://api.deepseek.com`  | Endpoint (rarely changed)        |
| `DEEPSEEK_MODEL`       | `deepseek-flash`           | Model id                         |
| `LEAN_PROJECT_DIR`     | `<repo>/infinite_nat`       | Lake project used for checking    |
| `LEAN_MAX_ITER`        | `8`                         | Proof attempts before giving up  |
| `LEAN_DIRECT_TRIES`    | `2`                         | One-shot proofs before the tactic loop |
| `LEAN_TIMEOUT`         | `60`                        | Seconds per Lean check            |
| `LEAN_IMPORT`          | `import Mathlib.Tactic`     | Import line(s) for the `--lean` path |
| `LEAN_LLM_RETRIES`     | `3`                         | Retries on 429 / 5xx / network    |
| `LEAN_LLM_BACKOFF`     | `5`                         | Base backoff seconds per retry    |
| `LEAN_TEMP`            | `0.0`                       | Sampling temperature              |

Alternate model: `deepseek-v4-pro` (stronger reasoning, slower). Set
`DEEPSEEK_MODEL` to switch.

Performance note: the harness uses a narrow import (`Mathlib.Tactic` by default)
so every Lean check reloads a small olean set instead of the whole `Mathlib`
(which is ~10x slower to load). The NL translation step picks imports itself.

The lake project `infinite_nat/` must already be built (run `lake build` there)
so Mathlib oleans exist and each check is fast.

## Run

```bash
export DEEPSEEK_API_KEY=...
cd /home/khoanguyen/math_assistant
PYTHONPATH=src .python_venv/bin/python -m harness.cli
```

The positional argument is a natural-language theorem:

```bash
PYTHONPATH=src .python_venv/bin/python -m harness.cli \
  'for every natural number n, n plus 0 equals n'
```

Pass `--lean` to give an exact `theorem ... := by` line instead, skipping the
translation step:

```bash
PYTHONPATH=src .python_venv/bin/python -m harness.cli --lean \
  'theorem target (n : Nat) : n + 0 = n := by'
```

## How it works

1. NL translation: the LLM turns the natural-language statement into a
   `theorem target ... := by` line. That line is checked with a `sorry` body;
   if it does not typecheck, errors feed back to the loop.
2. Proof loop, two tiers:
   - Direct pass: up to `LEAN_DIRECT_TRIES` one-shot complete proofs, verified
     by Lean, with light feedback between tries. Simple problems finish here fast.
   - Tactic fallback: if the direct pass fails, an iterative loop runs with full
     error + goal feedback (up to `LEAN_MAX_ITER`).
3. `LeanRunner` writes the source to a scratch file inside the lake project
   and runs `lake env lean --json`.
4. Diagnostics are parsed as JSON (severity, position, message). Goals are
   extracted from `⊢ ...` fragments inside messages.
5. The result is classified as `accepted`, `has_sorry`, or `failed`. Errors and
   goals are appended to the conversation and the loop retries.

On success the harness captures the elaborated proof term via `show_term` and
feeds it back so the model can explain what Lean actually did.
