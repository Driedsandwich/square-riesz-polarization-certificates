#!/usr/bin/env python3
"""Exact-arithmetic helpers and safe introspection of the certifier sources.

The certifier programs are the mathematical corpus of this repository. The
checking tools never import, exec, eval or runpy them: importing a certifier
would run a full branch-and-bound proof, and executing a file in order to read
a constant would make a check trust the very file it is auditing. Constants are
recovered instead by parsing the source into an AST and evaluating an explicit
allow-list of nodes.

Scope of the static checks, stated precisely because it is easy to overclaim:

* the *expression* allow-list is fail-closed. Any expression node, name or
  callee outside it raises CertifierSourceError instead of being skipped, so a
  construct that was never understood cannot be reported as "checked";
* the *entry point* is checked separately by `verify_entry_point`, against a
  narrow shape derived from an inventory of the 88 certifiers in this
  repository. That check is what rejects a module whose `__main__` guard prints
  a status without running the proof;
* whether the proof actually holds is decided by running the certifier, not by
  reading it. Static checks here establish that the source still has the shape
  the replay evidence was produced from; they do not verify any mathematics.

Two module-level shapes are recognised explicitly rather than silently ignored:

* type aliases such as ``Point = tuple[Q, Q]`` evaluate to a TYPE_ALIAS
  sentinel, and using that sentinel in arithmetic raises;
* the ``if __name__ == "__main__":`` guard is matched structurally, and any
  other module-level ``if`` raises.

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import ast
import csv
import json
import operator
import os
import re
import tempfile
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]

METHODS: tuple[str, ...] = ("spectral", "componentwise")

#: The certified configuration sizes, fixed by the published corpus.
EXPECTED_NS: tuple[int, ...] = tuple(sorted({7, 8, 10, 11, 12} | set(range(14, 53))))

#: The subset ``verify_all.py --quick`` runs. Defined here, not in the writer,
#: so the validator checks a fresh replay's declared selection against the same
#: constant the run used instead of a second copy that could drift.
QUICK_NS: tuple[int, ...] = (14, 15, 21, 36, 52)

#: What a replay's ``selection`` field may say, and the exact configuration list
#: each choice implies.
SELECTION_CONFIGURATIONS: dict[str, tuple[int, ...]] = {"quick": QUICK_NS, "all": EXPECTED_NS}

RESULTS_CSV = ROOT / "data" / "certified-results.csv"
RESULTS_JSON = ROOT / "data" / "certified-results.json"
RESULTS_METADATA = ROOT / "data" / "results-metadata.json"
FULL_REPLAY_JSON = ROOT / "evidence" / "full-cleanroom-replay" / "PUBLIC_REPO_FULL_REPLAY.json"

#: Column order of ``data/certified-results.csv``; also the JSON key order.
RESULT_FIELDS: tuple[str, ...] = (
    "n",
    "certified_lower_bound",
    "rigorous_upper_witness",
    "interval_width",
    "source_count",
    "minimum_source_separation",
    "symmetry_or_family",
    "all_local_minima_count",
    "spectral_splits",
    "spectral_maximum_depth",
    "componentwise_splits",
    "componentwise_maximum_depth",
    "submitted_lower_bound",
    "external_status",
    "configuration_path",
    "spectral_verifier_path",
    "componentwise_verifier_path",
    "full_replay_status",
    "notes",
)

#: Fields supplied by ``data/results-metadata.json`` because they are not
#: derivable from the configurations, the certifiers or the replay evidence.
METADATA_FIELDS: tuple[str, ...] = (
    "minimum_source_separation",
    "symmetry_or_family",
    "all_local_minima_count",
    "submitted_lower_bound",
    "external_status",
    "notes",
    "upper_decimal_places",
)

Point = tuple[Fraction, Fraction]

DECIMAL_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


class CertifierSourceError(Exception):
    """A certifier source used a construct outside the audited allow-list."""


# --------------------------------------------------------------------------
# exact decimal helpers
# --------------------------------------------------------------------------


def parse_exact_decimal(text: str) -> Fraction:
    """Parse a plain finite decimal literal exactly.

    Scientific notation and ratio syntax are rejected: every published number
    in this repository is a finite decimal, and accepting other spellings would
    let a malformed field pass as a number.
    """
    if not isinstance(text, str) or not DECIMAL_RE.fullmatch(text.strip()):
        raise ValueError(f"not a plain finite decimal: {text!r}")
    return Fraction(text.strip())


def decimal_places(text: str) -> int:
    """Number of digits after the decimal point of a plain decimal literal."""
    parse_exact_decimal(text)
    stripped = text.strip()
    return len(stripped.split(".")[1]) if "." in stripped else 0


def _format_scaled(scaled: int, places: int) -> str:
    if places < 0:
        raise ValueError("places must be non-negative")
    sign = "-" if scaled < 0 else ""
    magnitude = abs(scaled)
    if places == 0:
        return f"{sign}{magnitude}"
    scale = 10**places
    return f"{sign}{magnitude // scale}.{str(magnitude % scale).zfill(places)}"


def round_up_to_places(value: Fraction, places: int) -> str:
    """Round ``value`` outward (towards +infinity) to ``places`` decimals.

    Implemented with integer arithmetic only: binary floating point cannot
    represent these magnitudes, and ``decimal`` would need a precision that
    depends on the value. The positivity precondition is checked explicitly
    rather than asserted, so that it still holds under ``python -O``.
    """
    if not isinstance(value, Fraction):
        raise TypeError("round_up_to_places expects a Fraction")
    if value <= 0:
        raise ValueError(f"expected a positive potential value, got {value}")
    if places < 0:
        raise ValueError("places must be non-negative")
    scale = 10**places
    numerator = value.numerator * scale
    denominator = value.denominator
    # ceil(numerator / denominator) for positive denominators.
    scaled_ceiling = -((-numerator) // denominator)
    return _format_scaled(scaled_ceiling, places)


def format_exact_decimal(value: Fraction, places: int) -> str:
    """Format ``value`` with exactly ``places`` decimals, refusing to round."""
    if not isinstance(value, Fraction):
        raise TypeError("format_exact_decimal expects a Fraction")
    scale = 10**places
    scaled = value * scale
    if scaled.denominator != 1:
        raise ValueError(f"{value} is not exactly representable with {places} decimals")
    return _format_scaled(int(scaled), places)


def certifier_decimal_string(value: Fraction, precision: int) -> str:
    """Reproduce the certifier ``decimal_string``/``dec`` helpers exactly.

    Those helpers set ``getcontext().prec`` and divide two Decimals, i.e. they
    round to ``precision`` *significant* digits, half-to-even. Replicating it
    here lets the checks compare a recomputed value against the historical
    stdout logs without executing a certifier.
    """
    with localcontext() as context:
        context.prec = precision
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def exact_potential(lights: Iterable[Point], point: Point) -> Fraction:
    """Exact sum of 1 / ((px - xi)^2 + (py - yi)^2) over the sources."""
    px, py = point
    total = Fraction(0)
    for sx, sy in lights:
        squared_distance = (px - sx) ** 2 + (py - sy) ** 2
        if squared_distance == 0:
            raise ValueError("potential is infinite at a source point")
        total += Fraction(1) / squared_distance
    return total


def minimum_separation_squared(lights: list[Point]) -> Fraction:
    """Exact minimum squared distance between two distinct sources."""
    if len(lights) < 2:
        raise ValueError("need at least two sources")
    best: Fraction | None = None
    for i in range(len(lights)):
        for j in range(i + 1, len(lights)):
            dx = lights[i][0] - lights[j][0]
            dy = lights[i][1] - lights[j][1]
            candidate = dx * dx + dy * dy
            if best is None or candidate < best:
                best = candidate
    assert best is not None  # unreachable: len(lights) >= 2 was checked above
    return best


# --------------------------------------------------------------------------
# repository paths
# --------------------------------------------------------------------------


class WitnessPointError(Exception):
    """An upper witness point cannot support an upper bound."""


def validate_witness_point(point: Any, lights: Iterable[Point], where: str) -> Point:
    """Require the witness point to be an exact rational point of [0,1]^2.

    The potential at a point is an upper bound for the minimum *over the unit
    square* only if the point lies in the unit square. Every published witness
    does, but nothing checked it, so a future edit that moved a witness outside
    the domain would have produced a number that is not an upper bound at all.
    Boundary points are valid: sixteen certifiers use the corner (0, 0).
    """
    if not isinstance(point, tuple) or len(point) != 2:
        raise WitnessPointError(f"{where}: witness point is not a 2-tuple")
    px, py = point
    for name, value in (("x", px), ("y", py)):
        if not isinstance(value, Fraction):
            raise WitnessPointError(f"{where}: witness {name} is {type(value).__name__}, expected an exact rational")
    if not (0 <= px <= 1) or not (0 <= py <= 1):
        raise WitnessPointError(f"{where}: witness point ({px}, {py}) is outside the unit square [0,1]^2")
    if (px, py) in set(lights):
        raise WitnessPointError(f"{where}: witness point coincides with a source, where the potential is infinite")
    return (px, py)


#: The eight symmetries of the square, as exact rational maps of [0,1]^2.
SQUARE_SYMMETRIES: tuple[tuple[str, Any], ...] = (
    ("identity", lambda x, y: (x, y)),
    ("reflect_x", lambda x, y: (Fraction(1) - x, y)),
    ("reflect_y", lambda x, y: (x, Fraction(1) - y)),
    ("rotate_180", lambda x, y: (Fraction(1) - x, Fraction(1) - y)),
    ("reflect_diagonal", lambda x, y: (y, x)),
    ("reflect_antidiagonal", lambda x, y: (Fraction(1) - y, Fraction(1) - x)),
    ("rotate_90", lambda x, y: (Fraction(1) - y, x)),
    ("rotate_270", lambda x, y: (y, Fraction(1) - x)),
)


def exact_square_symmetries(points: Iterable[Point]) -> tuple[str, ...]:
    """Which of the eight square symmetries fix the point set exactly.

    Exact means as sets of rationals, not to within a tolerance: a
    configuration whose published decimals are symmetric to 1e-17 is *not*
    symmetric here, and saying otherwise in prose is what this is used to catch.
    """
    point_set = set(points)
    return tuple(
        name for name, transform in SQUARE_SYMMETRIES if {transform(x, y) for x, y in point_set} == point_set
    )


def certifier_relpath(n: int, method: str) -> str:
    if method not in METHODS:
        raise ValueError(f"unknown method: {method!r}")
    return f"certifiers/n{n:02d}/{method}.py"


def log_stem(n: int, method: str) -> str:
    if method not in METHODS:
        raise ValueError(f"unknown method: {method!r}")
    return f"n{n:02d}_{method}"


def canonical_log_name(n: int, method: str, stream: str, *, prefix: str = "") -> str:
    """The only file name a log for ``(n, method)`` may have.

    Historical records store ``logs/nNN_method.stdout.txt`` relative to
    ``evidence/full-cleanroom-replay/``; fresh replay records store the bare
    file name. Both are derived here so that a record cannot point at another
    configuration's log — which is invisible to any check that only asks
    whether the file exists.
    """
    if stream not in ("stdout", "stderr"):
        raise ValueError(f"unknown stream: {stream!r}")
    return f"{prefix}{log_stem(n, method)}.{stream}.txt"


HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
#: A top-level ``key: value`` line of certifier stdout. Indented continuation
#: lines (the interval block, the coordinate listing) deliberately do not match.
STRUCTURED_LINE = re.compile(r"^([a-z_]+):[ \t]*(.*?)[ \t]*$", re.MULTILINE)


def is_strict_int(value: Any) -> bool:
    """int, and not bool. ``bool`` is a subclass of ``int`` in Python."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_strict_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) and value == value and abs(value) != float("inf")


def parse_certifier_stdout(text: str, where: str) -> dict[str, str]:
    """Index the top-level ``key: value`` lines of a certifier's stdout.

    A key that appears twice is an error rather than a last-one-wins: two
    different ``splits:`` lines must not be reconcilable with one record.
    """
    fields: dict[str, str] = {}
    for key, value in STRUCTURED_LINE.findall(text):
        if key in fields:
            raise ValueError(f"{where}: duplicate structured line {key!r} in stdout")
        fields[key] = value
    return fields


#: The names a certifier may give the stdout line carrying its upper witness
#: value. All 88 use one of these and exactly one of them.
UPPER_VALUE_LINE_NAMES: tuple[str, ...] = (
    "witness_value_upper_bound_decimal",
    "corner_value_upper_bound_decimal",
    "upper_witness_value_decimal",
    "witness_upper_bound_decimal",
)

#: The measurement lines every successful certifier run must print exactly once.
REQUIRED_PROOF_OUTPUT_LINES: tuple[str, ...] = (
    "status",
    "target_decimal",
    "splits",
    "leaf_count",
    "maximum_depth",
    "minimum_leaf_lower_bound_decimal",
)

#: A non-negative integer, canonically spelled: no sign, no leading zero, no
#: whitespace, no exponent, no separator. ``-1``, ``+1``, ``01``, ``1_0``,
#: ``1e3``, ``True`` and ``nonsense`` are all rejected.
CANONICAL_INTEGER = re.compile(r"^(?:0|[1-9][0-9]*)$")


def parse_canonical_integer(text: str, where: str, field: str, *, minimum: int = 0) -> int:
    """Read a measurement that must be a plain non-negative integer."""
    if not isinstance(text, str) or not CANONICAL_INTEGER.fullmatch(text):
        raise ValueError(f"{where}: {field} is {text!r}, not a canonical non-negative integer")
    value = int(text)
    if value < minimum:
        raise ValueError(f"{where}: {field} is {value}, expected at least {minimum}")
    return value


def validate_proof_output(
    text: str,
    facts: "CertifierFacts",
    where: str,
    *,
    lights: list[Point] | None = None,
) -> list[str]:
    """Check that one successful certifier stdout actually reports a proof.

    A ``status: CERTIFIED`` line on its own is not evidence: a file containing
    only that line satisfied every exit-code, status and hash check in the
    replay pipeline. What makes the line mean something is the rest of the
    output — the target it proved, how many boxes it split, and the two numbers
    that bracket the minimum — so each of those is required exactly once, read
    strictly, and tied back to the certifier source.

    Returns the problems found; an empty list means the output is sound.
    """
    problems: list[str] = []
    try:
        fields = parse_certifier_stdout(text, where)
    except ValueError as error:
        return [str(error)]

    for name in REQUIRED_PROOF_OUTPUT_LINES:
        if name not in fields:
            problems.append(f"{where}: stdout has no {name!r} line")

    present = [name for name in UPPER_VALUE_LINE_NAMES if name in fields]
    if len(present) != 1:
        problems.append(
            f"{where}: stdout must carry exactly one upper witness value line "
            f"out of {list(UPPER_VALUE_LINE_NAMES)}, found {present}"
        )

    if fields.get("status") not in (None, "CERTIFIED"):
        problems.append(f"{where}: stdout status is {fields['status']!r}, expected 'CERTIFIED'")

    if "target_decimal" in fields:
        try:
            if parse_exact_decimal(fields["target_decimal"]) != facts.target:
                problems.append(
                    f"{where}: stdout target_decimal={fields['target_decimal']!r} is not the "
                    f"certifier TARGET {facts.target_literal!r}"
                )
        except ValueError as error:
            problems.append(f"{where}: target_decimal: {error}")

    counts: dict[str, int] = {}
    for field, minimum in (("splits", 0), ("leaf_count", 1), ("maximum_depth", 0)):
        if field not in fields:
            continue
        try:
            counts[field] = parse_canonical_integer(fields[field], where, field, minimum=minimum)
        except ValueError as error:
            problems.append(str(error))

    if "minimum_leaf_lower_bound_decimal" in fields:
        try:
            bound = parse_exact_decimal(fields["minimum_leaf_lower_bound_decimal"])
        except ValueError as error:
            problems.append(f"{where}: minimum_leaf_lower_bound_decimal: {error}")
        else:
            if bound < facts.target:
                problems.append(
                    f"{where}: minimum_leaf_lower_bound_decimal "
                    f"{fields['minimum_leaf_lower_bound_decimal']} is below the certified target "
                    f"{facts.target_literal}; the run did not prove what it claims"
                )

    if len(present) == 1:
        logged = fields[present[0]]
        try:
            parse_exact_decimal(logged)
        except ValueError as error:
            problems.append(f"{where}: {present[0]}: {error}")
        else:
            points = facts.lights if lights is None else lights
            expected = certifier_decimal_string(
                exact_potential(points, facts.witness), facts.decimal_precision
            )
            if logged != expected:
                problems.append(
                    f"{where}: {present[0]}={logged} does not reproduce the exact potential at this "
                    f"certifier's witness point, which prints as {expected}"
                )
    return problems


def csv_text(value: Any) -> str:
    """The exact string ``csv.DictWriter`` writes for a JSON-decoded value.

    Used by both the writer and the checker so that comparing a CSV cell with
    a JSON value never depends on two independent guesses about formatting.
    ``None`` becomes the empty field; ``True`` becomes ``True``, not ``true``.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def configuration_relpath(n: int) -> str:
    return f"data/configurations/n{n:02d}/coordinates.csv"


def configuration_source_relpath(n: int) -> str:
    return f"data/configurations/n{n:02d}/coordinates-source.txt"


def read_coordinates_csv(path: Path) -> list[Point]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty configuration: {path}")
    expected_columns = ["index", "x", "y"]
    if list(rows[0].keys()) != expected_columns:
        raise ValueError(f"unexpected columns in {path}: {list(rows[0].keys())}")
    points: list[Point] = []
    for position, row in enumerate(rows, start=1):
        if row["index"].strip() != str(position):
            raise ValueError(f"{path}: index column is not 1..N in order")
        points.append((parse_exact_decimal(row["x"]), parse_exact_decimal(row["y"])))
    return points


INDEX_RE = re.compile(r"^\d{1,3}$")


def read_coordinates_source(path: Path, expected_count: int) -> list[Point]:
    """Read the human-readable provenance listing of a configuration.

    These files carry free-form headers and prose that differ per family, so a
    line is only accepted when it has exactly three fields shaped as
    ``index x y``. The caller supplies the expected point count and the indices
    must be 1..N in order, which is what makes a stray prose line an error
    rather than a silently dropped point.
    """
    points: list[Point] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) != 3 or not INDEX_RE.fullmatch(fields[0]):
            continue
        if not DECIMAL_RE.fullmatch(fields[1]) or not DECIMAL_RE.fullmatch(fields[2]):
            continue
        if int(fields[0]) != len(points) + 1:
            raise ValueError(f"{path}: index {fields[0]} is out of order")
        points.append((parse_exact_decimal(fields[1]), parse_exact_decimal(fields[2])))
    if len(points) != expected_count:
        raise ValueError(f"{path}: parsed {len(points)} coordinate lines, expected {expected_count}")
    return points


# --------------------------------------------------------------------------
# safe AST evaluation of certifier constants
# --------------------------------------------------------------------------


class _TypeAlias:
    """Sentinel for ``Point = tuple[Q, Q]``-style aliases (never a value)."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<type alias>"


TYPE_ALIAS = _TypeAlias()

_ALLOWED_IMPORT_MODULES = frozenset({"__future__", "decimal", "fractions", "heapq", "typing"})
_TYPE_ALIAS_ROOTS = frozenset({"tuple", "list", "dict", "set", "frozenset"})

_BINARY_OPERATORS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_COMPARE_OPERATORS: dict[type[ast.cmpop], Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
#: Builtins the certifier assertions rely on. Deliberately tiny.
_ALLOWED_BUILTINS: dict[str, Any] = {"len": len, "set": set, "all": all}

#: Module-level names that may hold the upper witness point.
WITNESS_NAMES: tuple[str, ...] = ("UPPER_WITNESS", "WITNESS_POINT", "WITNESS")


class CertifierFacts(NamedTuple):
    path: Path
    target: Fraction
    target_literal: str
    lights: list[Point]
    witness: Point
    witness_origin: str
    checked_assertions: int
    decimal_precision: int


class _Unevaluable:
    """Marker for a module-level binding whose value was not understood."""

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason


class _CertifierReader:
    """Evaluate the allow-listed subset of one certifier source."""

    MAX_DEPTH = 60

    def __init__(self, path: Path) -> None:
        self.path = path
        self.source = path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source, filename=str(path))
        self.module: dict[str, Any] = {}
        self.functions: dict[str, ast.FunctionDef] = {}
        self.fraction_names: set[str] = set()
        self.checked_assertions = 0
        self.guards: list[ast.If] = []
        self.main_definitions = 0

    # -- errors ----------------------------------------------------------
    def fail(self, node: ast.AST, message: str) -> CertifierSourceError:
        line = getattr(node, "lineno", "?")
        return CertifierSourceError(f"{self.path}:{line}: {message}")

    # -- module ----------------------------------------------------------
    def load(self) -> None:
        for node in self.tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue  # module docstring
            if isinstance(node, ast.ImportFrom):
                self._handle_import(node)
                continue
            if isinstance(node, ast.FunctionDef):
                if node.name == "main":
                    self.main_definitions += 1
                self.functions[node.name] = node
                continue
            if isinstance(node, ast.ClassDef):
                self.module[node.name] = _Unevaluable("class definitions are not evaluated")
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                self._handle_assign(node)
                continue
            if isinstance(node, ast.Assert):
                self._handle_module_assert(node)
                continue
            if isinstance(node, ast.If):
                self._require_main_guard(node)
                continue
            raise self.fail(node, f"unsupported module-level statement {type(node).__name__}")

    def _handle_import(self, node: ast.ImportFrom) -> None:
        if node.level or node.module not in _ALLOWED_IMPORT_MODULES:
            raise self.fail(node, f"import from unexpected module: {node.module!r}")
        for alias in node.names:
            if node.module == "fractions" and alias.name == "Fraction":
                self.fraction_names.add(alias.asname or alias.name)

    def _handle_assign(self, node: ast.Assign | ast.AnnAssign) -> None:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        else:
            targets = [node.target]
            value = node.value
        names: list[str] = []
        for target in targets:
            if not isinstance(target, ast.Name):
                raise self.fail(node, "only simple name assignment targets are supported")
            names.append(target.id)
        if value is None:
            for name in names:
                self.module[name] = _Unevaluable("annotation without a value")
            return
        try:
            evaluated = self.evaluate(value, {}, 0)
        except CertifierSourceError as error:
            # Keep going, but poison the name: any later use raises. This is
            # what lets `Point = tuple[Q, Q]`-adjacent shapes exist without
            # silently accepting an unparsed value we actually depend on.
            evaluated = _Unevaluable(str(error))
        for name in names:
            self.module[name] = evaluated

    def _handle_module_assert(self, node: ast.Assert) -> None:
        outcome = self.evaluate(node.test, {}, 0)
        if outcome is not True:
            raise self.fail(node, f"module-level assertion is not satisfied: {ast.get_source_segment(self.source, node)!r}")
        self.checked_assertions += 1

    def _require_main_guard(self, node: ast.If) -> None:
        test = node.test
        matches = (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        )
        if not matches:
            raise self.fail(node, "module-level `if` other than the __main__ guard")
        self.guards.append(node)

    # -- expressions -----------------------------------------------------
    def evaluate(self, node: ast.expr, scope: dict[str, Any], depth: int) -> Any:
        if depth > self.MAX_DEPTH:
            raise self.fail(node, "expression nesting is too deep")
        method = getattr(self, f"_eval_{type(node).__name__}", None)
        if method is None:
            raise self.fail(node, f"unsupported expression node {type(node).__name__}")
        return method(node, scope, depth)

    def _lookup(self, node: ast.Name, scope: dict[str, Any]) -> Any:
        for namespace in (scope, self.module):
            if node.id in namespace:
                value = namespace[node.id]
                if isinstance(value, _Unevaluable):
                    raise self.fail(node, f"name {node.id!r} was never understood: {value.reason}")
                return value
        if node.id in self.fraction_names or node.id in self.functions or node.id in _ALLOWED_BUILTINS:
            raise self.fail(node, f"name {node.id!r} may only be used as a call")
        raise self.fail(node, f"unknown name {node.id!r}")

    def _eval_Constant(self, node: ast.Constant, scope: dict[str, Any], depth: int) -> Any:
        if isinstance(node.value, (int, str, bool)):
            return node.value
        raise self.fail(node, f"unsupported constant of type {type(node.value).__name__}")

    def _eval_Name(self, node: ast.Name, scope: dict[str, Any], depth: int) -> Any:
        return self._lookup(node, scope)

    def _eval_Tuple(self, node: ast.Tuple, scope: dict[str, Any], depth: int) -> Any:
        return tuple(self.evaluate(element, scope, depth + 1) for element in node.elts)

    def _eval_List(self, node: ast.List, scope: dict[str, Any], depth: int) -> Any:
        return [self.evaluate(element, scope, depth + 1) for element in node.elts]

    def _eval_Set(self, node: ast.Set, scope: dict[str, Any], depth: int) -> Any:
        return {self.evaluate(element, scope, depth + 1) for element in node.elts}

    def _eval_Dict(self, node: ast.Dict, scope: dict[str, Any], depth: int) -> Any:
        result: dict[Any, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                raise self.fail(node, "dict unpacking is not supported")
            key = self.evaluate(key_node, scope, depth + 1)
            if not isinstance(key, str):
                raise self.fail(node, "only string dict keys are supported")
            result[key] = self.evaluate(value_node, scope, depth + 1)
        return result

    def _eval_BinOp(self, node: ast.BinOp, scope: dict[str, Any], depth: int) -> Any:
        handler = _BINARY_OPERATORS.get(type(node.op))
        if handler is None:
            raise self.fail(node, f"unsupported binary operator {type(node.op).__name__}")
        left = self.evaluate(node.left, scope, depth + 1)
        right = self.evaluate(node.right, scope, depth + 1)
        self._reject_sentinels(node, (left, right))
        return handler(left, right)

    def _eval_UnaryOp(self, node: ast.UnaryOp, scope: dict[str, Any], depth: int) -> Any:
        operand = self.evaluate(node.operand, scope, depth + 1)
        self._reject_sentinels(node, (operand,))
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return not operand
        raise self.fail(node, f"unsupported unary operator {type(node.op).__name__}")

    def _eval_Compare(self, node: ast.Compare, scope: dict[str, Any], depth: int) -> Any:
        left = self.evaluate(node.left, scope, depth + 1)
        for op_node, comparator_node in zip(node.ops, node.comparators):
            handler = _COMPARE_OPERATORS.get(type(op_node))
            if handler is None:
                raise self.fail(node, f"unsupported comparison {type(op_node).__name__}")
            right = self.evaluate(comparator_node, scope, depth + 1)
            self._reject_sentinels(node, (left, right))
            if not handler(left, right):
                return False
            left = right
        return True

    def _eval_BoolOp(self, node: ast.BoolOp, scope: dict[str, Any], depth: int) -> Any:
        values = [self.evaluate(value, scope, depth + 1) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(bool(value) for value in values)
        if isinstance(node.op, ast.Or):
            return any(bool(value) for value in values)
        raise self.fail(node, f"unsupported boolean operator {type(node.op).__name__}")

    def _eval_Subscript(self, node: ast.Subscript, scope: dict[str, Any], depth: int) -> Any:
        if isinstance(node.value, ast.Name) and node.value.id in _TYPE_ALIAS_ROOTS and node.value.id not in self.module:
            return TYPE_ALIAS  # `Point = tuple[Q, Q]` and friends
        container = self.evaluate(node.value, scope, depth + 1)
        index = self.evaluate(node.slice, scope, depth + 1)
        self._reject_sentinels(node, (container, index))
        if isinstance(container, dict):
            if index not in container:
                raise self.fail(node, f"missing dict key {index!r}")
            return container[index]
        if isinstance(container, (list, tuple)):
            if not isinstance(index, int) or isinstance(index, bool):
                raise self.fail(node, "sequence subscript must be an integer")
            return container[index]
        raise self.fail(node, "unsupported subscript target")

    def _eval_Call(self, node: ast.Call, scope: dict[str, Any], depth: int) -> Any:
        if node.keywords:
            raise self.fail(node, "keyword arguments are not supported")
        if not isinstance(node.func, ast.Name):
            raise self.fail(node, "only direct calls to named functions are supported")
        name = node.func.id
        arguments = [self.evaluate(argument, scope, depth + 1) for argument in node.args]
        if name in self.fraction_names:
            for argument in arguments:
                if not isinstance(argument, (int, str)) or isinstance(argument, bool):
                    raise self.fail(node, "Fraction arguments must be int or str literals")
            if len(arguments) == 1 and isinstance(arguments[0], str):
                parse_exact_decimal(arguments[0])  # reject exotic spellings
            return Fraction(*arguments)
        if name in _ALLOWED_BUILTINS:
            self._reject_sentinels(node, arguments)
            return _ALLOWED_BUILTINS[name](*arguments)
        if name in self.functions:
            return self._call(self.functions[name], arguments, depth + 1, node)
        raise self.fail(node, f"call to unsupported function {name!r}")

    def _comprehension(self, node: ast.expr, generators: list[ast.comprehension], element: ast.expr, scope: dict[str, Any], depth: int):
        if len(generators) != 1:
            raise self.fail(node, "only single-generator comprehensions are supported")
        generator = generators[0]
        if generator.is_async:
            raise self.fail(node, "async comprehensions are not supported")
        iterable = self.evaluate(generator.iter, scope, depth + 1)
        self._reject_sentinels(node, (iterable,))
        if not isinstance(iterable, (list, tuple, set, frozenset)):
            raise self.fail(node, "comprehension source must be a sequence or set")
        for item in iterable:
            inner = dict(scope)
            self._bind(generator.target, item, inner, node)
            if all(bool(self.evaluate(condition, inner, depth + 1)) for condition in generator.ifs):
                yield self.evaluate(element, inner, depth + 1)

    def _eval_ListComp(self, node: ast.ListComp, scope: dict[str, Any], depth: int) -> Any:
        return list(self._comprehension(node, node.generators, node.elt, scope, depth))

    def _eval_SetComp(self, node: ast.SetComp, scope: dict[str, Any], depth: int) -> Any:
        return set(self._comprehension(node, node.generators, node.elt, scope, depth))

    def _eval_GeneratorExp(self, node: ast.GeneratorExp, scope: dict[str, Any], depth: int) -> Any:
        return list(self._comprehension(node, node.generators, node.elt, scope, depth))

    def _bind(self, target: ast.expr, value: Any, scope: dict[str, Any], node: ast.AST) -> None:
        if isinstance(target, ast.Name):
            scope[target.id] = value
            return
        if isinstance(target, ast.Tuple):
            if not isinstance(value, (list, tuple)) or len(value) != len(target.elts):
                raise self.fail(node, "tuple unpacking shape mismatch")
            for sub_target, sub_value in zip(target.elts, value):
                self._bind(sub_target, sub_value, scope, node)
            return
        raise self.fail(node, "unsupported assignment target")

    def _reject_sentinels(self, node: ast.AST, values: Iterable[Any]) -> None:
        for value in values:
            if isinstance(value, (_TypeAlias, _Unevaluable)):
                raise self.fail(node, "a type alias or unparsed value was used as data")

    # -- function calls --------------------------------------------------
    def _call(self, function: ast.FunctionDef, arguments: list[Any], depth: int, call_site: ast.AST) -> Any:
        if depth > self.MAX_DEPTH:
            raise self.fail(call_site, "call nesting is too deep")
        spec = function.args
        if spec.posonlyargs or spec.vararg or spec.kwonlyargs or spec.kwarg or spec.defaults:
            raise self.fail(function, f"unsupported signature for {function.name!r}")
        if len(arguments) != len(spec.args):
            raise self.fail(call_site, f"{function.name!r} expects {len(spec.args)} arguments")
        scope = {parameter.arg: value for parameter, value in zip(spec.args, arguments)}
        for statement in function.body:
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                continue  # docstring
            if isinstance(statement, ast.Return):
                if statement.value is None:
                    return None
                return self.evaluate(statement.value, scope, depth + 1)
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                if value is None:
                    raise self.fail(statement, "annotation without a value inside a function")
                evaluated = self.evaluate(value, scope, depth + 1)
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    self._bind(target, evaluated, scope, statement)
                continue
            if isinstance(statement, ast.AugAssign):
                if not isinstance(statement.target, ast.Name):
                    raise self.fail(statement, "augmented assignment needs a simple name target")
                handler = _BINARY_OPERATORS.get(type(statement.op))
                if handler is None:
                    raise self.fail(statement, f"unsupported augmented operator {type(statement.op).__name__}")
                current = self._lookup(statement.target, scope)
                addition = self.evaluate(statement.value, scope, depth + 1)
                scope[statement.target.id] = handler(current, addition)
                continue
            if isinstance(statement, ast.Assert):
                outcome = self.evaluate(statement.test, scope, depth + 1)
                if outcome is not True:
                    raise self.fail(statement, f"assertion inside {function.name!r} is not satisfied")
                self.checked_assertions += 1
                continue
            raise self.fail(statement, f"unsupported statement {type(statement).__name__} inside {function.name!r}")
        raise self.fail(function, f"{function.name!r} fell through without returning")

    # -- extraction ------------------------------------------------------
    def target_literal(self) -> str:
        for node in self.tree.body:
            targets: list[ast.expr]
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            if not any(isinstance(t, ast.Name) and t.id == "TARGET" for t in targets):
                continue
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in self.fraction_names
                and len(value.args) == 1
                and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)
            ):
                return value.args[0].value
            raise self.fail(node, "TARGET is not a Fraction built from a decimal string literal")
        raise CertifierSourceError(f"{self.path}: no TARGET assignment")

    def decimal_precision(self) -> int:
        """The significant-digit precision this certifier prints its decimals at.

        Each certifier defines exactly one of ``dec`` / ``decimal`` /
        ``decimal_string`` as ``(value, precision=<int>)`` and prints every
        decimal through it. Recovering the literal here lets a check reproduce
        the printed string exactly, instead of inferring the precision from the
        length of the string it is trying to verify — which a truncated log
        would satisfy trivially.
        """
        found: list[tuple[str, int]] = []
        for name in sorted(PRINT_ARGUMENT_HELPERS):
            function = self.functions.get(name)
            if function is None:
                continue
            defaults = function.args.defaults
            if len(function.args.args) != 2 or len(defaults) != 1:
                raise CertifierSourceError(
                    f"{self.path}: {name}() is not the expected (value, precision=<int>) helper"
                )
            literal = defaults[0]
            if not (isinstance(literal, ast.Constant) and is_strict_int(literal.value) and literal.value > 0):
                raise CertifierSourceError(
                    f"{self.path}: {name}()'s precision default is not a positive integer literal"
                )
            found.append((name, literal.value))
        if len(found) != 1:
            raise CertifierSourceError(
                f"{self.path}: expected exactly one decimal helper, found {[name for name, _ in found]}"
            )
        return found[0][1]

    def witness(self) -> tuple[Point, str]:
        for name in WITNESS_NAMES:
            if name in self.module:
                value = self.module[name]
                if isinstance(value, _Unevaluable):
                    raise CertifierSourceError(f"{self.path}: {name} was never understood: {value.reason}")
                return _as_point(value, f"{self.path}:{name}"), name
        return self._witness_from_main()

    def _witness_from_main(self) -> tuple[Point, str]:
        """Recover the upper-bound point from the single-argument call in main().

        Twelve certifiers evaluate the potential at the corner (0, 0) with no
        named constant. Rather than assume the corner, the argument expression
        is evaluated and the result must be a unique point, so a certifier that
        silently used a different point could not pass unnoticed.
        """
        main = self.functions.get("main")
        if main is None:
            raise CertifierSourceError(f"{self.path}: no main() to recover the witness point from")
        candidates: set[Point] = set()
        for node in ast.walk(main):
            if not isinstance(node, ast.Call) or node.keywords or len(node.args) != 1:
                continue
            try:
                value = self.evaluate(node.args[0], {}, 0)
            except CertifierSourceError:
                continue
            if (
                isinstance(value, tuple)
                and len(value) == 2
                and all(isinstance(component, Fraction) for component in value)
            ):
                candidates.add(value)  # type: ignore[arg-type]
        if len(candidates) != 1:
            raise CertifierSourceError(
                f"{self.path}: expected exactly one candidate witness point in main(), found {len(candidates)}"
            )
        return candidates.pop(), "main()"


#: The four assertion roles every certifier's main() is required to carry.
REQUIRED_FINAL_ASSERTIONS = frozenset({"certified", "leaf_not_none", "leaf_ge_target", "upper_ge_target"})

#: Helpers a certifier may use in main() to evaluate the potential at the upper
#: witness point. From an inventory of the 88 entry points in this repository.
UPPER_VALUE_HELPERS = frozenset({"potential_at", "potential_and_gradient", "potgrad", "potential_gradient"})

#: Helpers a certifier may call inside a print() argument.
PRINT_ARGUMENT_HELPERS = frozenset({"dec", "decimal", "decimal_string"})

#: Attributes of the certify() result a certifier may print.
RESULT_ATTRIBUTES = frozenset(
    {"certified", "splits", "leaves", "leaf_count", "maximum_depth", "minimum_leaf_lower_bound"}
)

#: The coordinate display loop, verbatim. All 38 entry points that have a loop
#: have exactly this one, so it is matched as a whole rather than by parts.
COORDINATE_LOOP_SOURCE = (
    "for index, (x, y) in enumerate(coordinate_strings(LIGHTS), start=1):\n"
    "    print(f'  {index:02d}: ({x}, {y})')"
)

#: Constructs that must not appear anywhere inside main(). Each one is a way to
#: make the printed status and the executed proof come apart: an early ``return``
#: turns the proof and the assertions into dead code, ``try`` swallows a failing
#: assertion, a nested function or lambda hides a second definition, and a walrus
#: or augmented assignment rebinds the result after the call.
_FORBIDDEN_IN_MAIN: tuple[type[ast.AST], ...] = (
    ast.Return,
    ast.Raise,
    ast.Try,
    ast.TryStar,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
    ast.Match,
    ast.Yield,
    ast.YieldFrom,
    ast.Await,
    ast.Break,
    ast.Continue,
    ast.NamedExpr,
    ast.Lambda,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Import,
    ast.ImportFrom,
    ast.Starred,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


class EntryPointError(Exception):
    """A certifier's entry point is outside the audited shape."""


def _flatten_and(condition: ast.expr) -> list[ast.expr]:
    if isinstance(condition, ast.BoolOp) and isinstance(condition.op, ast.And):
        return [part for value in condition.values for part in _flatten_and(value)]
    return [condition]


def _is_attribute_of(node: ast.expr, name: str, attribute: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == attribute
        and isinstance(node.value, ast.Name)
        and node.value.id == name
    )


class _EntryPointChecker:
    """Check that a certifier still runs its proof before declaring a status.

    The shape enforced here is not invented: it is the shape every one of the
    88 certifiers in this repository actually has, taken from an inventory of
    their entry points. Anything outside it is rejected rather than skipped,
    because the mutations that matter are the ones that keep a plausible shape.
    Counting ``certify()`` calls with :func:`ast.walk` accepted all of these,
    and every one of them ran to exit code 0 printing ``status: CERTIFIED``
    without proving anything:

    * ``result = certify() if False else CertificateResult(True, ...)`` — the
      call is present in the tree but on the arm that never executes;
    * ``certify = lambda: CertificateResult(True, ...)`` at module level, with
      ``main()`` untouched — the name in ``main()`` no longer reaches the proof;
    * a second ``def certify(...)`` shadowing the first;
    * ``print("status:", "CERTIFIED"); return`` before the call, leaving the
      proof and the four final assertions as dead code;
    * ``result = certify()`` followed by ``result = CertificateResult(True, ...)``,
      which runs the proof and then throws the answer away.
    """

    def __init__(self, reader: "_CertifierReader") -> None:
        self.reader = reader
        self.path = reader.path

    def fail(self, node: ast.AST | None, message: str) -> EntryPointError:
        line = getattr(node, "lineno", "?") if node is not None else "?"
        return EntryPointError(f"{self.path}:{line}: {message}")

    def check(self) -> None:
        self._check_guard()
        self._check_module_bindings()
        self._check_import_time_safety()
        main = self._check_main_definition()
        result_name = self._check_proof_call(main)
        upper_name = self._check_upper_value(main)
        self._check_statements(main, result_name, upper_name)
        self._check_final_assertions(main, result_name, upper_name)

    # -- module level ----------------------------------------------------
    def _check_module_bindings(self) -> None:
        """Require that the names ``main()`` uses still mean what they read as."""
        defined: dict[str, ast.stmt] = {}
        for node in self.reader.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in defined:
                    raise self.fail(
                        node,
                        f"{node.name!r} is defined more than once at module level; "
                        f"the later definition (line {node.lineno}) is the one that runs",
                    )
                defined[node.name] = node
        for required in ("main", "certify"):
            node = defined.get(required)
            if not isinstance(node, ast.FunctionDef):
                raise self.fail(None, f"expected exactly one module-level `def {required}()`")
        protected = set(defined) | {"print"}
        for node in self.reader.tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in protected:
                    raise self.fail(
                        node,
                        f"module level rebinds {target.id!r}; the call in main() would not "
                        f"reach the definition it appears to name",
                    )

    def _check_import_time_safety(self) -> None:
        """Refuse every way this corpus could run code while being imported.

        The statement-by-statement check of ``main()`` says nothing about what
        already happened by the time ``main()`` starts. Three shapes rebound
        ``certify`` during import and were accepted end to end — entry check,
        exit code 0, ``status: CERTIFIED``, and zero proof-output problems,
        because a fake ``CertificateResult(True, 0, 1, 0, TARGET, None, None)``
        prints measurements that are internally consistent:

        * ``@skip_proof`` on ``certify``, or on any unrelated helper whose
          decorator writes into ``globals()``;
        * ``def poison(_=globals().__setitem__("certify", ...))`` — a default
          expression is evaluated at definition time;
        * ``POISON = globals().__setitem__("certify", ...)`` — a module-level
          assignment whose value the reader could not evaluate and therefore
          kept as an unused, unexamined binding.

        The allow-list below is the measured shape of the 88 certifiers: 927
        definitions, all module-level, all undecorated; no ``async`` and no
        lambda anywhere; 264 default expressions, every one a bare name or an
        integer constant; one ``NamedTuple`` class per module whose body is
        annotations only.
        """
        tree = self.reader.tree

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.decorator_list:
                    raise self.fail(
                        node.decorator_list[0],
                        f"{node.name!r} is decorated; a decorator runs at import time and can "
                        f"replace any name in the module, including certify",
                    )
            if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
                raise self.fail(node, f"{type(node).__name__} is not part of the audited certifier shape")
            if isinstance(node, ast.Lambda):
                raise self.fail(node, "lambda is not part of the audited certifier shape")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                for default in list(arguments.defaults) + [d for d in arguments.kw_defaults if d is not None]:
                    self._check_default(node, default)

        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        if len(classes) != 1:
            raise self.fail(None, f"expected exactly one module-level class, found {len(classes)}")
        self._check_result_class(classes[0])

        bound: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            self._check_module_value(node, targets, bound)

    def _check_default(self, function: ast.AST, default: ast.expr) -> None:
        if isinstance(default, ast.Name):
            return
        if isinstance(default, ast.Constant) and not isinstance(default.value, bool) and isinstance(
            default.value, (int, float, str, type(None))
        ):
            return
        raise self.fail(
            default,
            f"default expression {ast.unparse(default)!r} in {getattr(function, 'name', '?')}() is outside "
            f"the audited shape (a bare name or a plain constant); defaults are evaluated at import time",
        )

    def _check_result_class(self, node: ast.ClassDef) -> None:
        bases = [ast.unparse(base) for base in node.bases]
        if bases != ["NamedTuple"]:
            raise self.fail(node, f"the result class must derive from NamedTuple alone, found {bases}")
        if node.keywords:
            raise self.fail(
                node,
                f"the result class must not take class keywords (found "
                f"{[keyword.arg for keyword in node.keywords]}); a metaclass runs arbitrary code at import time",
            )
        for statement in node.body:
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(
                statement.value.value, str
            ):
                continue  # a docstring
            if not isinstance(statement, ast.AnnAssign) or statement.value is not None:
                raise self.fail(
                    statement,
                    f"the result class body must be annotations without values, found "
                    f"{type(statement).__name__}",
                )
            for inner in ast.walk(statement.annotation):
                if isinstance(inner, ast.Call):
                    raise self.fail(statement, "a field annotation must not contain a call")

    def _check_module_value(self, node: ast.stmt, targets: list[ast.expr], bound: set[str]) -> None:
        """Every module-level binding must have a value this reader understood.

        ``_handle_assign`` keeps an unreadable right-hand side as an
        ``_Unevaluable`` placeholder and lets it through as long as nothing
        later reads it. That is right for constant extraction — an unused
        binding cannot change TARGET — and wrong here, because the statement
        still executes on import. ``POISON = globals().__setitem__(...)`` is
        exactly that shape.

        The verdict is read from what ``load()`` already produced rather than
        evaluated a second time. Re-evaluating would re-run the inlined body of
        a helper such as ``LIGHTS = build_lights()``, and the assertions inside
        it would be counted twice — five certifiers use that shape, and the
        reported ``certifier_module_assertions_evaluated`` went from 317 to 335
        before this was fixed.
        """
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if len(names) != len(targets):
            raise self.fail(node, "only simple name assignment targets are part of the audited shape")
        for name in names:
            if name in bound:
                raise self.fail(
                    node,
                    f"module level binds {name!r} more than once; only the last value survives, so "
                    f"an earlier one could carry a side effect nothing later reads",
                )
            bound.add(name)
            if name not in self.reader.module:
                raise self.fail(node, f"module-level binding {name!r} was never recorded")
            evaluated = self.reader.module[name]
            if isinstance(evaluated, _Unevaluable):
                raise self.fail(
                    node,
                    f"module-level binding {name!r} has a value this checker cannot evaluate, so what "
                    f"it does on import is unknown: {evaluated.reason}",
                )

    def _check_guard(self) -> None:
        guards = self.reader.guards
        if len(guards) != 1:
            raise self.fail(None, f"expected exactly one `if __name__ == \"__main__\"` guard, found {len(guards)}")
        guard = guards[0]
        if guard.orelse:
            raise self.fail(guard, "the __main__ guard must not have an else branch")
        if len(guard.body) != 1:
            raise self.fail(guard, f"the __main__ guard body must be a single statement, found {len(guard.body)}")
        statement = guard.body[0]
        call = statement.value if isinstance(statement, ast.Expr) else None
        ok = (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "main"
            and not call.args
            and not call.keywords
        )
        if not ok:
            raise self.fail(statement, "the __main__ guard body must be exactly `main()`")

    def _check_main_definition(self) -> ast.FunctionDef:
        if self.reader.main_definitions != 1:
            raise self.fail(None, f"expected exactly one main() definition, found {self.reader.main_definitions}")
        main = self.reader.functions.get("main")
        if main is None:
            raise self.fail(None, "no module-level main()")
        if main.decorator_list:
            raise self.fail(main, "main() must not be decorated; a decorator can replace it wholesale")
        arguments = main.args
        if (
            arguments.posonlyargs
            or arguments.args
            or arguments.kwonlyargs
            or arguments.vararg
            or arguments.kwarg
            or arguments.defaults
            or arguments.kw_defaults
        ):
            raise self.fail(main, "main() must take no arguments")
        returns = main.returns
        if returns is not None and not (isinstance(returns, ast.Constant) and returns.value is None):
            raise self.fail(main, f"main() must be annotated `-> None` or not at all, found {ast.unparse(returns)!r}")
        if len(main.body) < 3:
            raise self.fail(
                main,
                f"main() has {len(main.body)} statements, too few to hold the proof call, "
                f"the witness value and the final assertions",
            )
        return main

    # -- the two assignments ---------------------------------------------
    def _check_proof_call(self, main: ast.FunctionDef) -> str:
        """Require ``<name> = certify()`` as the first statement, and nothing else."""
        statement = main.body[0]
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            raise self.fail(
                statement,
                f"the first statement of main() must assign certify()'s result to one name, "
                f"found {type(statement).__name__}",
            )
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            raise self.fail(statement, "the certify() result must be bound to a simple name")
        call = statement.value
        if not isinstance(call, ast.Call):
            raise self.fail(
                statement,
                f"main() must call certify() directly, found {type(call).__name__}: {ast.unparse(call)!r}. "
                f"A call nested in a conditional, a container or another call may never execute",
            )
        if not (isinstance(call.func, ast.Name) and call.func.id == "certify"):
            raise self.fail(call, f"main() must call certify() directly, found a call to {ast.unparse(call.func)!r}")
        if call.args or call.keywords:
            raise self.fail(call, "certify() must be called with no arguments, so the target cannot be swapped at the call site")
        mentions = [node for node in ast.walk(main) if isinstance(node, ast.Name) and node.id == "certify"]
        if len(mentions) != 1 or mentions[0] is not call.func:
            raise self.fail(
                main,
                f"main() must name certify() exactly once, as the callee of its first statement; "
                f"found {len(mentions)} mentions",
            )
        return target.id

    def _check_upper_value(self, main: ast.FunctionDef) -> str:
        """Require the second statement to evaluate the potential at the witness point."""
        statement = main.body[1]
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            raise self.fail(
                statement,
                f"the second statement of main() must assign the upper witness value to one name, "
                f"found {type(statement).__name__}",
            )
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            raise self.fail(statement, "the upper witness value must be bound to a simple name")
        value: ast.expr = statement.value
        if isinstance(value, ast.Subscript):
            index = value.slice
            if not (isinstance(index, ast.Constant) and index.value == 0 and not isinstance(index.value, bool)):
                raise self.fail(value, "only index 0 of a (value, gradient) pair may be taken as the upper witness value")
            value = value.value
        if not isinstance(value, ast.Call) or value.keywords or len(value.args) != 1:
            raise self.fail(
                statement,
                "the upper witness value must come from a single-argument call to a potential helper",
            )
        function = value.func
        if not (isinstance(function, ast.Name) and function.id in UPPER_VALUE_HELPERS):
            raise self.fail(
                value,
                f"unknown upper witness helper {ast.unparse(function)!r}; "
                f"the allow-list is {sorted(UPPER_VALUE_HELPERS)}",
            )
        if function.id not in self.reader.functions:
            raise self.fail(value, f"{function.id}() is not defined in this module")
        try:
            evaluated = self.reader.evaluate(value.args[0], {}, 0)
            point = _as_point(evaluated, f"{self.path}: upper witness argument")
            expected, origin = self.reader.witness()
        except CertifierSourceError as error:
            raise self.fail(value, f"the upper witness argument could not be resolved: {error}") from error
        if point != expected:
            raise self.fail(
                value,
                f"main() evaluates the potential at {point}, not at this certifier's witness point "
                f"{expected} (from {origin})",
            )
        return target.id

    # -- the rest of the body --------------------------------------------
    def _check_statements(self, main: ast.FunctionDef, result: str, upper: str) -> None:
        for node in ast.walk(main):
            if node is main:
                continue
            if isinstance(node, _FORBIDDEN_IN_MAIN):
                raise self.fail(
                    node,
                    f"main() must not contain {type(node).__name__}; it would let the printed "
                    f"status and the executed proof come apart",
                )

        assignments = [node for node in ast.walk(main) if isinstance(node, ast.Assign)]
        if len(assignments) != 2:
            raise self.fail(
                main,
                f"main() must contain exactly two assignments — the proof result and the upper "
                f"witness value — found {len(assignments)}. A third rebinds one of them",
            )

        body = main.body
        status_prints: list[ast.Call] = []
        printed_names: set[str] = set()
        seen_if = 0
        seen_for = 0
        first_assert: int | None = None
        for position, statement in enumerate(body):
            if isinstance(statement, ast.Assert):
                if first_assert is None:
                    first_assert = position
                continue
            if first_assert is not None:
                raise self.fail(
                    statement,
                    "the final assertions must be the last statements of main(); nothing may run after them",
                )
            if position < 2:
                continue  # the two assignments, already checked
            if isinstance(statement, ast.Expr):
                call = self._check_print(statement, result, upper, printed_names)
                if call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == "status:":
                    status_prints.append(call)
            elif isinstance(statement, ast.If):
                seen_if += 1
                if seen_if > 1:
                    raise self.fail(statement, "main() may contain at most one if statement")
                self._check_leaf_bound_if(statement, result, upper, printed_names)
            elif isinstance(statement, ast.For):
                seen_for += 1
                if seen_for > 1:
                    raise self.fail(statement, "main() may contain at most one for statement")
                self._check_coordinate_loop(statement)
            else:
                raise self.fail(
                    statement,
                    f"unexpected {type(statement).__name__} in main(); the entry-point shape is not on the allow-list",
                )
        if first_assert is None:
            raise self.fail(main, "main() does not end with the required final assertions")

        if len(status_prints) != 1:
            raise self.fail(main, f"main() must print exactly one `status:` line, found {len(status_prints)}")
        arguments = status_prints[0].args
        if len(arguments) != 2 or not self._is_status_conditional(arguments[1], result):
            raise self.fail(
                status_prints[0],
                f"the status line must be `print(\"status:\", \"CERTIFIED\" if {result}.certified "
                f"else \"NOT_CERTIFIED\")`, so the printed verdict is the proof's own",
            )
        if upper not in printed_names:
            raise self.fail(main, f"main() never prints the upper witness value it bound to {upper!r}")

    def _is_status_conditional(self, node: ast.expr, result: str) -> bool:
        return (
            isinstance(node, ast.IfExp)
            and _is_attribute_of(node.test, result, "certified")
            and isinstance(node.body, ast.Constant)
            and isinstance(node.body.value, str)
            and isinstance(node.orelse, ast.Constant)
            and isinstance(node.orelse.value, str)
        )

    def _check_print(
        self, statement: ast.Expr, result: str, upper: str, printed_names: set[str]
    ) -> ast.Call:
        call = statement.value
        if not isinstance(call, ast.Call):
            raise self.fail(
                statement, f"only print() may stand alone in main(), found {type(call).__name__}"
            )
        if not (isinstance(call.func, ast.Name) and call.func.id == "print"):
            raise self.fail(
                call,
                f"only print() may be called for effect in main(), found {ast.unparse(call.func)!r}. "
                f"An unknown call could exit before the final assertions run",
            )
        if call.keywords:
            raise self.fail(call, "print() must be called with positional arguments only")
        for argument in call.args:
            self._check_print_argument(argument, result, upper, printed_names)
        return call

    def _check_print_argument(
        self, node: ast.expr, result: str, upper: str, printed_names: set[str]
    ) -> None:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (str, int)):
                raise self.fail(node, f"unexpected constant {node.value!r} in a print() argument")
            return
        if isinstance(node, ast.Name):
            if node.id in (result, upper) or node.id in self.reader.module:
                printed_names.add(node.id)
                return
            raise self.fail(
                node,
                f"print() reads {node.id!r}, which is neither a module-level binding nor a value main() computed",
            )
        if isinstance(node, ast.Attribute):
            if not (isinstance(node.value, ast.Name) and node.value.id == result):
                raise self.fail(
                    node, f"print() reads {ast.unparse(node)!r}; only the certify() result's attributes may be printed"
                )
            if node.attr not in RESULT_ATTRIBUTES:
                raise self.fail(
                    node, f"unknown result attribute {node.attr!r}; the allow-list is {sorted(RESULT_ATTRIBUTES)}"
                )
            printed_names.add(node.value.id)
            return
        if isinstance(node, ast.Subscript):
            if not (isinstance(node.value, ast.Name) and node.value.id in self.reader.module):
                raise self.fail(
                    node, f"print() subscripts {ast.unparse(node)!r}; only module-level constants may be subscripted"
                )
            index = node.slice
            if not (isinstance(index, ast.Constant) and isinstance(index.value, int) and not isinstance(index.value, bool)):
                raise self.fail(node, "only a constant integer index may be printed")
            printed_names.add(node.value.id)
            return
        if isinstance(node, ast.IfExp):
            if not self._is_status_conditional(node, result):
                raise self.fail(
                    node,
                    f"the only conditional a certifier may print is "
                    f"`<str> if {result}.certified else <str>`, found {ast.unparse(node)!r}",
                )
            printed_names.add(result)
            return
        if isinstance(node, ast.Call):
            function = node.func
            if not (isinstance(function, ast.Name) and function.id in PRINT_ARGUMENT_HELPERS):
                raise self.fail(
                    node,
                    f"print() calls {ast.unparse(function)!r}; the allow-list is {sorted(PRINT_ARGUMENT_HELPERS)}",
                )
            if function.id not in self.reader.functions:
                raise self.fail(node, f"{function.id}() is not defined in this module")
            if node.keywords:
                raise self.fail(node, f"{function.id}() must be called with positional arguments only")
            for argument in node.args:
                self._check_print_argument(argument, result, upper, printed_names)
            return
        raise self.fail(
            node,
            f"unexpected {type(node).__name__} in a print() argument; the entry-point shape is not on the allow-list",
        )

    def _check_leaf_bound_if(
        self, statement: ast.If, result: str, upper: str, printed_names: set[str]
    ) -> None:
        if statement.orelse:
            raise self.fail(statement, "the leaf-bound if must not have an else branch")
        test = statement.test
        recognised = (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.IsNot)
            and _is_attribute_of(test.left, result, "minimum_leaf_lower_bound")
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is None
        )
        if not recognised:
            raise self.fail(
                statement,
                f"the only if allowed in main() is `{result}.minimum_leaf_lower_bound is not None`, "
                f"found {ast.unparse(test)!r}",
            )
        if len(statement.body) != 1 or not isinstance(statement.body[0], ast.Expr):
            raise self.fail(statement, "the leaf-bound if body must be a single print()")
        self._check_print(statement.body[0], result, upper, printed_names)

    def _check_coordinate_loop(self, statement: ast.For) -> None:
        if "coordinate_strings" not in self.reader.functions:
            raise self.fail(statement, "coordinate_strings() is not defined in this module")
        rendered = ast.unparse(statement)
        if rendered != COORDINATE_LOOP_SOURCE:
            raise self.fail(
                statement,
                "the only loop allowed in main() is the coordinate display loop, verbatim; found:\n" + rendered,
            )

    def _check_final_assertions(self, main: ast.FunctionDef, result: str, upper: str) -> None:
        body = main.body
        start = len(body)
        while start > 0 and isinstance(body[start - 1], ast.Assert):
            start -= 1
        suffix = body[start:]
        if not suffix:
            raise self.fail(main, "main() does not end with the required final assertions")
        roles: set[str] = set()
        for statement in suffix:
            for condition in _flatten_and(statement.test):  # type: ignore[union-attr]
                role = self._assertion_role(condition, result, upper)
                if role in roles:
                    raise self.fail(condition, f"the {role!r} assertion appears more than once")
                roles.add(role)
        if roles != REQUIRED_FINAL_ASSERTIONS:
            missing = sorted(REQUIRED_FINAL_ASSERTIONS - roles)
            unexpected = sorted(roles - REQUIRED_FINAL_ASSERTIONS)
            raise self.fail(
                main, f"main()'s final assertions are wrong: missing {missing}, unexpected {unexpected}"
            )

    def _assertion_role(self, condition: ast.expr, result: str, upper: str) -> str:
        if _is_attribute_of(condition, result, "certified"):
            return "certified"
        if isinstance(condition, ast.Compare) and len(condition.ops) == 1:
            operator_node = condition.ops[0]
            right = condition.comparators[0]
            left = condition.left
            if _is_attribute_of(left, result, "minimum_leaf_lower_bound"):
                if isinstance(operator_node, ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
                    return "leaf_not_none"
                if isinstance(operator_node, ast.GtE) and isinstance(right, ast.Name) and right.id == "TARGET":
                    return "leaf_ge_target"
            if (
                isinstance(left, ast.Name)
                and left.id == upper
                and isinstance(operator_node, ast.GtE)
                and isinstance(right, ast.Name)
                and right.id == "TARGET"
            ):
                return "upper_ge_target"
        raise self.fail(condition, "unrecognised assertion in main(); the entry-point shape is not on the allow-list")


def _as_point(value: Any, where: str) -> Point:
    if not isinstance(value, tuple) or len(value) != 2:
        raise CertifierSourceError(f"{where}: expected a 2-tuple")
    x, y = value
    if not isinstance(x, Fraction) or not isinstance(y, Fraction):
        raise CertifierSourceError(f"{where}: expected exact rational coordinates")
    return (x, y)


def extract_certifier_facts(path: Path, *, verify_entry_point: bool = False) -> CertifierFacts:
    """Recover TARGET, the configuration and the witness point from a source.

    ``verify_entry_point`` additionally requires the module to still run its
    proof before printing a status. It is off by default so that constant
    extraction stays independent of the entry-point policy, and on wherever a
    check is claiming that the source is sound.
    """
    reader = _CertifierReader(path)
    reader.load()
    if verify_entry_point:
        _EntryPointChecker(reader).check()
    target_literal = reader.target_literal()
    target = reader.module.get("TARGET")
    if not isinstance(target, Fraction):
        raise CertifierSourceError(f"{path}: TARGET did not evaluate to a Fraction")
    lights_value = reader.module.get("LIGHTS")
    if isinstance(lights_value, _Unevaluable):
        raise CertifierSourceError(f"{path}: LIGHTS was never understood: {lights_value.reason}")
    if not isinstance(lights_value, list):
        raise CertifierSourceError(f"{path}: LIGHTS did not evaluate to a list")
    lights = [_as_point(item, f"{path}:LIGHTS") for item in lights_value]
    witness, origin = reader.witness()
    return CertifierFacts(
        path=path,
        target=target,
        target_literal=target_literal,
        lights=lights,
        witness=witness,
        witness_origin=origin,
        checked_assertions=reader.checked_assertions,
        decimal_precision=reader.decimal_precision(),
    )


# --------------------------------------------------------------------------
# strict JSON
# --------------------------------------------------------------------------


class StrictJSONError(Exception):
    """A JSON document used a shape this repository refuses to accept."""


#: Expected type of each field of ``data/results-metadata.json``.
METADATA_FIELD_TYPES: dict[str, type] = {
    "upper_decimal_places": int,
    "minimum_source_separation": str,
    "symmetry_or_family": str,
    "all_local_minima_count": str,
    "submitted_lower_bound": str,
    "external_status": str,
    "notes": str,
}

#: Fields of each record of the stored clean-room replay.
REPLAY_RECORD_FIELDS: tuple[str, ...] = (
    "n",
    "method",
    "repo_relative_script",
    "script_sha256",
    "return_code",
    "timed_out",
    "elapsed_seconds",
    "status",
    "splits",
    "maximum_depth",
    "minimum_leaf_lower_bound",
    "stdout_log",
    "stderr_log",
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate object key: {key!r}")
        result[key] = value
    return result


def _reject_non_finite(name: str) -> Any:
    raise StrictJSONError(f"non-finite JSON constant: {name}")


def load_json_strict(path: Path, expected_type: type | None = None) -> Any:
    """Parse JSON, refusing shapes that the default parser silently accepts.

    ``json.loads`` keeps the last value of a duplicated object key and accepts
    ``NaN``/``Infinity``. Either would let a document that two readers disagree
    about pass as evidence, so both are errors here.
    """
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except StrictJSONError as error:
        raise StrictJSONError(f"{path}: {error}") from None
    except json.JSONDecodeError as error:
        raise StrictJSONError(f"{path}: {error}") from None
    if expected_type is not None and not isinstance(value, expected_type):
        raise StrictJSONError(f"{path}: top-level value is {type(value).__name__}, expected {expected_type.__name__}")
    return value


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    """Replace ``path`` with ``payload`` without ever leaving it half-written.

    The bytes are completed in memory, written to a temporary file in the same
    directory, flushed and fsynced, then moved into place with ``os.replace``,
    which is atomic within a filesystem. Two files still cannot be replaced as
    one operation — see docs/data-schema.md — so an interruption between them
    leaves the CSV and JSON inconsistent, which ``--check`` and the semantic
    consistency check both detect.
    """
    directory = path.parent
    handle = tempfile.NamedTemporaryFile(dir=directory, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------
# published data loaders
# --------------------------------------------------------------------------


def load_results_csv(path: Path = RESULTS_CSV, *, require_expected_set: bool = True) -> list[dict[str, str]]:
    """Read the result table.

    The header and column set are always enforced: without them the rows do not
    mean anything. ``require_expected_set`` additionally requires 44 rows with
    distinct n values equal to the published set, which is what a consumer such
    as the audit needs before it turns the rows into a dictionary keyed by n.
    ``check_semantic_consistency`` passes False so that it can report a
    configuration-set mismatch as one of its structured problems rather than
    aborting the whole run on the first bad table.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(RESULT_FIELDS):
            raise ValueError(f"{path}: unexpected header {reader.fieldnames}")
        rows = list(reader)
    for row in rows:
        if list(row.keys()) != list(RESULT_FIELDS):
            raise ValueError(f"{path}: unexpected column set {list(row.keys())}")
    if not require_expected_set:
        return rows
    if len(rows) != len(EXPECTED_NS):
        raise ValueError(f"{path}: {len(rows)} rows, expected {len(EXPECTED_NS)}")
    ns = [int(row["n"]) for row in rows]
    if len(set(ns)) != len(ns):
        raise ValueError(f"{path}: duplicate n values")
    if set(ns) != set(EXPECTED_NS):
        missing = sorted(set(EXPECTED_NS) - set(ns))
        unexpected = sorted(set(ns) - set(EXPECTED_NS))
        raise ValueError(f"{path}: configuration set mismatch missing={missing} unexpected={unexpected}")
    return rows


def load_results_json(path: Path = RESULTS_JSON) -> list[dict[str, str]]:
    return load_json_strict(path, list)


def load_results_metadata(path: Path = RESULTS_METADATA) -> dict[int, dict[str, Any]]:
    """Read the non-derivable metadata, with an exact schema."""
    raw = load_json_strict(path, dict)
    keys: list[int] = []
    for key in raw:
        if not isinstance(key, str) or not key.isdigit():
            raise StrictJSONError(f"{path}: metadata key {key!r} is not a decimal integer string")
        keys.append(int(key))
    if sorted(keys) != list(EXPECTED_NS):
        missing = sorted(set(EXPECTED_NS) - set(keys))
        unexpected = sorted(set(keys) - set(EXPECTED_NS))
        raise StrictJSONError(f"{path}: configuration set mismatch missing={missing} unexpected={unexpected}")
    entries: dict[int, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            raise StrictJSONError(f"{path}: entry for n={key} is not an object")
        if set(entry) != set(METADATA_FIELD_TYPES):
            missing = sorted(set(METADATA_FIELD_TYPES) - set(entry))
            unexpected = sorted(set(entry) - set(METADATA_FIELD_TYPES))
            raise StrictJSONError(f"{path}: n={key} field mismatch missing={missing} unexpected={unexpected}")
        for field, expected in METADATA_FIELD_TYPES.items():
            value = entry[field]
            if not isinstance(value, expected) or isinstance(value, bool):
                raise StrictJSONError(
                    f"{path}: n={key} field {field} is {type(value).__name__}, expected {expected.__name__}"
                )
        entries[int(key)] = entry
    return entries


def load_full_replay(path: Path = FULL_REPLAY_JSON) -> dict[str, Any]:
    """Read the stored clean-room replay, with an exact per-record schema."""
    replay = load_json_strict(path, dict)
    records = replay.get("results")
    if not isinstance(records, list):
        raise StrictJSONError(f"{path}: results is not a list")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise StrictJSONError(f"{path}: results[{index}] is not an object")
        if set(record) != set(REPLAY_RECORD_FIELDS):
            missing = sorted(set(REPLAY_RECORD_FIELDS) - set(record))
            unexpected = sorted(set(record) - set(REPLAY_RECORD_FIELDS))
            raise StrictJSONError(f"{path}: results[{index}] field mismatch missing={missing} unexpected={unexpected}")
    return replay
