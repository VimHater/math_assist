"""Sample theorem statements for the proof loop.

The natural-language sample is what the CLI takes by default. The Lean sample
is used when `--lean` is passed.
"""

SAMPLE_NL = (
    "For every natural number n, (n + 1) times (n + 1) equals "
    "n times n plus 2 times n plus 1."
)

SAMPLE_STATEMENT = (
    "theorem target (n : Nat) : (n + 1) * (n + 1) = n * n + 2 * n + 1 := by"
)

PROBLEMS: list[dict] = [
    {
        "name": "square_expansion_nat",
        "nl": SAMPLE_NL,
        "statement": SAMPLE_STATEMENT,
    },
]
