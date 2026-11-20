"""Exact linear algebra over the rationals.

The disclosure review must decide whether a set of published sum equations
uniquely determines any individual batch mean.  Float-based rank computations
could misjudge near-singular systems, so every coefficient is reduced through
fractions.Fraction before elimination.  Batch means enter as exact decimal
strings (never parsed floats), keeping the proof independent of the stored
float precision.
"""
from fractions import Fraction
def _fraction(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    # Decimal strings such as "73.20" stay exact; floats are refused upstream
    # but guarded here by routing through their shortest repr anyway.
    return Fraction(str(value))
def _normalize(rows):
    matrix=[[_fraction(v) for v in row] for row in rows if row]
    cols=max((len(r) for r in matrix), default=0)
    for row in matrix:
        row.extend([Fraction(0)] * (cols - len(row)))
    return matrix, cols
def rank(rows):
    """Rank of a matrix given as iterables of numbers/decimal strings."""
    matrix, _ = _normalize(rows)
    return _rank_of(matrix)
def solvable_columns(existing_rows, candidate_row):
    """Return the zero-based columns that become uniquely solvable once the
    candidate equation is appended to the already published equations.

    A variable x_j is uniquely determined by a consistent linear system iff
    the unit vector e_j (1 in column j, 0 elsewhere) lies in the row space of
    the coefficient matrix: then x_j = e_j . x is a fixed linear combination
    of the equations and cannot vary.  Equivalently, appending e_j must not
    raise the rank.  A pivot column alone is not enough (pivot variables still
    co-vary with free variables), which is why row-space membership is used.
    """
    def determined_columns(rows):
        matrix, cols = _normalize(rows)
        base_rank = _rank_of(matrix)
        determined = set()
        for j in range(cols):
            unit = [Fraction(0)] * cols
            unit[j] = Fraction(1)
            if _rank_of([row[:] for row in matrix] + [unit]) == base_rank:
                determined.add(j)
        return determined
    before = determined_columns(existing_rows)
    after = determined_columns(list(existing_rows) + [list(candidate_row)])
    return sorted(after - before)
def _rank_of(matrix):
    cols = len(matrix[0]) if matrix else 0
    pivot_rows = 0
    for col in range(cols):
        pivot = next((r for r in range(pivot_rows, len(matrix)) if matrix[r][col] != 0), None)
        if pivot is None:
            continue
        matrix[pivot_rows], matrix[pivot] = matrix[pivot], matrix[pivot_rows]
        scale = matrix[pivot_rows][col]
        matrix[pivot_rows] = [v / scale for v in matrix[pivot_rows]]
        for r in range(len(matrix)):
            if r != pivot_rows and matrix[r][col] != 0:
                factor = matrix[r][col]
                matrix[r] = [v - factor * u for v, u in zip(matrix[r], matrix[pivot_rows])]
        pivot_rows += 1
        if pivot_rows == len(matrix):
            break
    return pivot_rows
