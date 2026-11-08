"""Direct tests of the n=22 certifiers' mathematical core.

Every other test treats a certifier as a black box: it runs the file and checks
what it printed. These tests import ``certifiers/n22/spectral.py`` and
``componentwise.py`` and call their bound functions and their branch and bound
directly, on a lowered target so that a run takes about a second.

The n=22 sources are the same program as n=36 and n=52 apart from their data,
so the syntax-tree comparison below ties these tests to those certifiers too,
and fails as soon as one of the three drifts from the others.

The certifiers are only read and imported, never modified. Bytecode writing is
switched off before the import so that no ``__pycache__`` appears under
``certifiers/``.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import sys
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path

sys.dont_write_bytecode = True

from support import REPO_ROOT, read_text, replace_once, write_text  # noqa: E402

METHODS = ("spectral", "componentwise")

#: Module-level names whose values are the configuration's data, not its logic.
DATA_NAMES = frozenset({"TARGET", "LIGHTS", "WITNESS_POINT"})


def certifier_path(n: int, method: str) -> Path:
    return REPO_ROOT / "certifiers" / f"n{n:02d}" / f"{method}.py"


def load_certifier(n: int, method: str):
    """Import one certifier under a unique module name, without running main()."""
    name = f"_certifier_n{n:02d}_{method}"
    spec = importlib.util.spec_from_file_location(name, certifier_path(n, method))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_len_assert(node: ast.stmt) -> bool:
    """``assert len(...) == <int>``, the light-count checks."""
    return (
        isinstance(node, ast.Assert)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Call)
        and isinstance(node.test.left.func, ast.Name)
        and node.test.left.func.id == "len"
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and type(node.test.comparators[0].value) is int
    )


def normalized_program(source: str) -> "tuple[list[str], int]":
    """The module's statements with the configuration data blanked out.

    Drops the module docstring, replaces the values assigned to ``TARGET``,
    ``LIGHTS`` and ``WITNESS_POINT`` and the integer in each ``assert len(...)
    == N``, and dumps every statement. Returns the dumps and how many
    replacements were made, so a test can insist that nothing else was blanked.
    """
    tree = ast.parse(source)
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    replaced = 0
    dumps: list[str] = []
    for node in body:
        node = copy.deepcopy(node)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in DATA_NAMES for target in targets):
                node.value = ast.Constant(None)
                replaced += 1
        elif _is_len_assert(node):
            node.test.comparators = [ast.Constant(None)]
            replaced += 1
        dumps.append(ast.dump(node))
    return dumps, replaced


class N22IsTheSameProgramAsN36AndN52(unittest.TestCase):
    def assert_same_program(self, left: str, right: str, label: str) -> None:
        left_dumps, left_replaced = normalized_program(left)
        right_dumps, right_replaced = normalized_program(right)
        self.assertEqual(left_replaced, 5, f"{label}: unexpected data statements in the left program")
        self.assertEqual(right_replaced, 5, f"{label}: unexpected data statements in the right program")
        self.assertEqual(len(left_dumps), len(right_dumps), f"{label}: statement counts differ")
        for index, (a, b) in enumerate(zip(left_dumps, right_dumps)):
            self.assertEqual(a, b, f"{label}: top-level statement {index} differs")

    def test_n22_matches_n36_and_n52(self) -> None:
        for method in METHODS:
            reference = read_text(certifier_path(22, method))
            for other in (36, 52):
                with self.subTest(method=method, other=other):
                    self.assert_same_program(reference, read_text(certifier_path(other, method)), f"n22/n{other} {method}")

    def test_a_change_to_the_logic_is_detected(self) -> None:
        """Negative control: the normalisation must not hide a change to a bound."""
        mutations = {
            "spectral": ("return max(distance_bound, taylor_bound)", "return min(distance_bound, taylor_bound)"),
            "componentwise": ("return max(direct,taylor)", "return min(direct,taylor)"),
        }
        for method, (old, new) in mutations.items():
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temporary:
                mutated = Path(temporary) / f"{method}.py"
                write_text(mutated, read_text(certifier_path(36, method)))
                replace_once(mutated, old, new)
                with self.assertRaises(AssertionError):
                    self.assert_same_program(read_text(certifier_path(22, method)), read_text(mutated), method)


class N22Core(unittest.TestCase):
    """The bound functions and the branch and bound, called directly."""

    LOWERED_TARGET = Q(150)

    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = {method: load_certifier(22, method) for method in METHODS}

    @staticmethod
    def potential(module, point) -> Q:
        if hasattr(module, "potential_at"):
            return module.potential_at(point)
        return module.potential_and_gradient(point)[0]

    @staticmethod
    def grid_boxes(parts: int = 4):
        """A ``parts`` x ``parts`` grid of boxes over the quarter square."""
        step = Q(1, 2 * parts)
        for i in range(parts):
            for j in range(parts):
                yield (i * step, (i + 1) * step, j * step, (j + 1) * step)

    def test_configuration_is_the_one_both_methods_certify(self) -> None:
        spectral, componentwise = self.modules["spectral"], self.modules["componentwise"]
        self.assertEqual(spectral.LIGHTS, componentwise.LIGHTS)
        self.assertEqual(spectral.TARGET, componentwise.TARGET)
        self.assertEqual(spectral.WITNESS_POINT, componentwise.WITNESS_POINT)
        self.assertEqual(len(spectral.LIGHTS), 22)
        light_set = set(spectral.LIGHTS)
        self.assertEqual({(1 - x, y) for x, y in light_set}, light_set)
        self.assertEqual({(x, 1 - y) for x, y in light_set}, light_set)

    def test_witness_value_is_an_exact_upper_bound_above_the_target(self) -> None:
        values = {method: self.potential(module, module.WITNESS_POINT) for method, module in self.modules.items()}
        self.assertEqual(values["spectral"], values["componentwise"])
        self.assertGreaterEqual(values["spectral"], self.modules["spectral"].TARGET)

    def test_box_lower_bound_never_exceeds_the_potential_in_the_box(self) -> None:
        for method, module in self.modules.items():
            for box in self.grid_boxes():
                x0, x1, y0, y1 = box
                bound = module.box_lower_bound(box)
                for point in ((x0, y0), (x0, y1), (x1, y0), (x1, y1), ((x0 + x1) / 2, (y0 + y1) / 2)):
                    if point in module.LIGHTS:
                        continue
                    with self.subTest(method=method, box=box, point=point):
                        self.assertLessEqual(bound, self.potential(module, point))

    def test_componentwise_hessian_intervals_contain_the_exact_hessian(self) -> None:
        module = self.modules["componentwise"]
        for box in self.grid_boxes():
            intervals = module.hessian_entry_intervals(box)
            if intervals is None:
                continue  # a light lies in or on the box
            x0, x1, y0, y1 = box
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            exact_xx = exact_yy = exact_xy = Q(0)
            for sx, sy in module.LIGHTS:
                dx, dy = mx - sx, my - sy
                r6 = (dx * dx + dy * dy) ** 3
                exact_xx += (6 * dx * dx - 2 * dy * dy) / r6
                exact_yy += (6 * dy * dy - 2 * dx * dx) / r6
                exact_xy += 8 * dx * dy / r6
            for (lo, hi), exact, name in zip(intervals, (exact_xx, exact_yy, exact_xy), ("xx", "yy", "xy")):
                with self.subTest(box=box, entry=name):
                    self.assertLessEqual(lo, exact)
                    self.assertLessEqual(exact, hi)

    def test_quick_certification_at_a_lowered_target(self) -> None:
        for method, module in self.modules.items():
            with self.subTest(method=method):
                result = module.certify(self.LOWERED_TARGET)
                self.assertTrue(result[0])
                splits, leaves, minimum_leaf = result[1], result[2], result[4]
                self.assertEqual(leaves, splits + 1, "every split turns one box into two")
                self.assertIsNotNone(minimum_leaf)
                self.assertGreaterEqual(minimum_leaf, self.LOWERED_TARGET)
                self.assertIsNone(result[5])
                self.assertIsNone(result[6])

    def test_split_budget_exhaustion_is_not_a_certificate(self) -> None:
        for method, module in self.modules.items():
            with self.subTest(method=method):
                result = module.certify(module.TARGET, max_splits=50)
                self.assertFalse(result[0])
                self.assertEqual(result[1], 50)
                self.assertLess(result[5], module.TARGET)
                self.assertIsNotNone(result[6])


if __name__ == "__main__":
    unittest.main()
