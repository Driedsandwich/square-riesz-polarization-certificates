#!/usr/bin/env python3
"""Exact lower-bound certificate for a 16-light configuration in the unit square.

Problem
-------
For lights c_i in [0,1]^2, define
    F(p) = sum_i 1 / ||p-c_i||^2.
This script certifies, using exact rational arithmetic, that
    min_{p in [0,1]^2} F(p) >= 125.4580973
for the explicit 16-point configuration below.

Certificate method
------------------
The verifier covers the full unit square [0,1]^2. Each axis-aligned
rational box B receives two valid lower bounds:

1. Termwise distance bound:
       sum_i 1 / max_{p in B} ||p-c_i||^2.

2. A second-order Taylor bound, used only when B contains no source. For
   f_i(p)=1/||p-c_i||^2, the smallest Hessian eigenvalue is -2/||p-c_i||^4.
   If d_i is the minimum distance from c_i to B, then for box center m and
   half-width vector h,
       F(p) >= F(m) + grad F(m)·(p-m)
                - (sum_i d_i^-4) ||p-m||^2.
   Minimizing the right-hand side over the box gives an exact rational bound.

Boxes whose lower bound is below the target are bisected along their longest
side. Successful termination is a finite proof that the target holds globally.

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

from decimal import Decimal, getcontext
from fractions import Fraction as Q
from heapq import heappop, heappush
from typing import Iterable, NamedTuple

ZERO = Q(0)
HALF = Q(1, 2)
ONE = Q(1)
TARGET = Q("125.4580973")

Point = tuple[Q, Q]
Box = tuple[Q, Q, Q, Q]  # x0, x1, y0, y1

LIGHTS: list[Point] = [
    (Q("0.08518537338203566"), Q("0.06432949502974639")),
    (Q("0.91481462661796434"), Q("0.06432949502974639")),
    (Q("0.08518537338203566"), Q("0.93567050497025361")),
    (Q("0.91481462661796434"), Q("0.93567050497025361")),
    (Q("0.35994192007809434"), Q("0.06606796739705495")),
    (Q("0.64005807992190566"), Q("0.06606796739705495")),
    (Q("0.35994192007809434"), Q("0.93393203260294505")),
    (Q("0.64005807992190566"), Q("0.93393203260294505")),
    (Q("0.11086712059728927"), Q("0.28980650746561964")),
    (Q("0.88913287940271073"), Q("0.28980650746561964")),
    (Q("0.11086712059728927"), Q("0.71019349253438036")),
    (Q("0.88913287940271073"), Q("0.71019349253438036")),
    (Q("0.50000000000000000"), Q("0.36647125656508145")),
    (Q("0.50000000000000000"), Q("0.63352874343491855")),
    (Q("0.12038506766617012"), Q("0.50000000000000000")),
    (Q("0.87961493233382988"), Q("0.50000000000000000")),
]
assert len(LIGHTS) == 16
assert len(set(LIGHTS)) == 16



def min_sq_1d(source: Q, lo: Q, hi: Q) -> Q:
    if source < lo:
        return (lo - source) ** 2
    if source > hi:
        return (source - hi) ** 2
    return ZERO


def max_sq_1d(source: Q, lo: Q, hi: Q) -> Q:
    a = (lo - source) ** 2
    b = (hi - source) ** 2
    return max(a, b)


def potential_at(point: Point) -> Q:
    x, y = point
    total = ZERO
    for sx, sy in LIGHTS:
        r2 = (x - sx) ** 2 + (y - sy) ** 2
        if r2 == 0:
            raise ValueError("Potential is +infinity at a light source")
        total += ONE / r2
    return total


def box_lower_bound(box: Box) -> Q:
    x0, x1, y0, y1 = box
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2, (y1 - y0) / 2

    # Bound 1: valid for every box, including boxes containing a source.
    distance_bound = ZERO

    # Quantities for bound 2.
    source_in_or_on_box = False
    value_at_center = ZERO
    grad_x = ZERO
    grad_y = ZERO
    curvature_sum = ZERO

    for sx, sy in LIGHTS:
        max_d2 = max_sq_1d(sx, x0, x1) + max_sq_1d(sy, y0, y1)
        distance_bound += ONE / max_d2

        min_d2 = min_sq_1d(sx, x0, x1) + min_sq_1d(sy, y0, y1)
        if min_d2 == 0:
            source_in_or_on_box = True

        dx, dy = mx - sx, my - sy
        r2 = dx * dx + dy * dy
        if r2 != 0:
            value_at_center += ONE / r2
            grad_x += -2 * dx / (r2 * r2)
            grad_y += -2 * dy / (r2 * r2)

        if min_d2 != 0:
            curvature_sum += ONE / (min_d2 * min_d2)

    if source_in_or_on_box:
        return distance_bound

    taylor_bound = (
        value_at_center
        - abs(grad_x) * hx
        - abs(grad_y) * hy
        - curvature_sum * (hx * hx + hy * hy)
    )
    return max(distance_bound, taylor_bound)


class CertificateResult(NamedTuple):
    certified: bool
    splits: int
    leaf_count: int
    maximum_depth: int
    minimum_leaf_lower_bound: Q | None
    failed_lower_bound: Q | None
    failed_box: Box | None


def certify(target: Q = TARGET, max_splits: int = 2_000_000) -> CertificateResult:
    root: Box = (ZERO, ONE, ZERO, ONE)
    serial = 0
    heap: list[tuple[Q, int, int, Box]] = []
    heappush(heap, (box_lower_bound(root), 0, serial, root))
    serial += 1

    splits = 0
    leaves = 0
    maximum_depth = 0
    minimum_leaf_lower_bound: Q | None = None

    while heap:
        lower_bound, depth, _, box = heappop(heap)
        if lower_bound >= target:
            leaves += 1
            maximum_depth = max(maximum_depth, depth)
            if minimum_leaf_lower_bound is None:
                minimum_leaf_lower_bound = lower_bound
            else:
                minimum_leaf_lower_bound = min(minimum_leaf_lower_bound, lower_bound)
            continue

        if splits >= max_splits:
            return CertificateResult(
                False,
                splits,
                leaves,
                maximum_depth,
                minimum_leaf_lower_bound,
                lower_bound,
                box,
            )

        x0, x1, y0, y1 = box
        if (x1 - x0) >= (y1 - y0):
            mid = (x0 + x1) / 2
            children = ((x0, mid, y0, y1), (mid, x1, y0, y1))
        else:
            mid = (y0 + y1) / 2
            children = ((x0, x1, y0, mid), (x0, x1, mid, y1))

        for child in children:
            heappush(heap, (box_lower_bound(child), depth + 1, serial, child))
            serial += 1
        splits += 1

    return CertificateResult(
        True,
        splits,
        leaves,
        maximum_depth,
        minimum_leaf_lower_bound,
        None,
        None,
    )


def decimal_string(value: Q, precision: int = 60) -> str:
    getcontext().prec = precision
    return str(Decimal(value.numerator) / Decimal(value.denominator))


def coordinate_strings(points: Iterable[Point]) -> list[tuple[str, str]]:
    return [(decimal_string(x, 30), decimal_string(y, 30)) for x, y in points]


def main() -> None:
    result = certify()
    corner_upper_bound = potential_at((ZERO, ZERO))

    print("status:", "CERTIFIED" if result.certified else "NOT_CERTIFIED")
    print("target_exact:", TARGET)
    print("target_decimal:", decimal_string(TARGET))
    print("splits:", result.splits)
    print("leaf_count:", result.leaf_count)
    print("maximum_depth:", result.maximum_depth)
    if result.minimum_leaf_lower_bound is not None:
        print(
            "minimum_leaf_lower_bound_decimal:",
            decimal_string(result.minimum_leaf_lower_bound),
        )
    print("corner_value_upper_bound_decimal:", decimal_string(corner_upper_bound))
    print("rigorous_interval_for_true_minimum:")
    print("  lower:", decimal_string(TARGET))
    print("  upper:", decimal_string(corner_upper_bound))
    print("coordinates:")
    for index, (x, y) in enumerate(coordinate_strings(LIGHTS), start=1):
        print(f"  {index:02d}: ({x}, {y})")

    assert result.certified
    assert result.minimum_leaf_lower_bound is not None
    assert result.minimum_leaf_lower_bound >= TARGET
    assert corner_upper_bound >= TARGET


if __name__ == "__main__":
    main()
