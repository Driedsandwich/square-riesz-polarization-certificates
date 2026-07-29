#!/usr/bin/env python3
"""Exact lower-bound certificate for a 47-light configuration in the unit square.

Problem
-------
For lights c_i in [0,1]^2, define
    F(p) = sum_i 1 / ||p-c_i||^2.
This script certifies, using exact rational arithmetic, that
    min_{p in [0,1]^2} F(p) >= 419.3108
for the explicit 47-point configuration below.

Certificate method
------------------
The verifier covers [0,1/2]^2 after exact assertions of left-right and top-bottom reflection symmetry; this rigorously covers the full unit square. Each axis-aligned
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
TARGET = Q("419.3108")

Point = tuple[Q, Q]
Box = tuple[Q, Q, Q, Q]  # x0, x1, y0, y1

LIGHTS: list[Point] = [
    (Q("0.0366743214765413"), Q("0.2899820729949854")),
    (Q("0.9633256785234587"), Q("0.2899820729949854")),
    (Q("0.0366743214765413"), Q("0.7100179270050146")),
    (Q("0.9633256785234587"), Q("0.7100179270050146")),
    (Q("0.0605634522635049"), Q("0.0153076706903918")),
    (Q("0.9394365477364951"), Q("0.0153076706903918")),
    (Q("0.0605634522635049"), Q("0.9846923293096082")),
    (Q("0.9394365477364951"), Q("0.9846923293096082")),
    (Q("0.0560684068349853"), Q("0.1371583649001528")),
    (Q("0.9439315931650147"), Q("0.1371583649001528")),
    (Q("0.0560684068349853"), Q("0.8628416350998472")),
    (Q("0.9439315931650147"), Q("0.8628416350998472")),
    (Q("0.2386234488311943"), Q("0.0203920424804106")),
    (Q("0.7613765511688057"), Q("0.0203920424804106")),
    (Q("0.2386234488311943"), Q("0.9796079575195894")),
    (Q("0.7613765511688057"), Q("0.9796079575195894")),
    (Q("0.2432641520413606"), Q("0.2202307769668890")),
    (Q("0.7567358479586394"), Q("0.2202307769668890")),
    (Q("0.2432641520413606"), Q("0.7797692230331110")),
    (Q("0.7567358479586394"), Q("0.7797692230331110")),
    (Q("0.5000000000000000"), Q("0.0326664773884336")),
    (Q("0.5000000000000000"), Q("0.9673335226115664")),
    (Q("0.5000000000000000"), Q("0.0336664750775574")),
    (Q("0.5000000000000000"), Q("0.9663335249224426")),
    (Q("0.5000000000000000"), Q("0.0346664717268830")),
    (Q("0.5000000000000000"), Q("0.9653335282731170")),
    (Q("0.5000000000000000"), Q("0.0356664683706375")),
    (Q("0.5000000000000000"), Q("0.9643335316293625")),
    (Q("0.5000000000000000"), Q("0.0366664661528762")),
    (Q("0.5000000000000000"), Q("0.9633335338471238")),
    (Q("0.5000000000000000"), Q("0.2808837898842576")),
    (Q("0.5000000000000000"), Q("0.7191162101157424")),
    (Q("0.5000000000000000"), Q("0.2818837897128289")),
    (Q("0.5000000000000000"), Q("0.7181162102871711")),
    (Q("0.0370414019454228"), Q("0.5000000000000000")),
    (Q("0.9629585980545772"), Q("0.5000000000000000")),
    (Q("0.0380414015278918"), Q("0.5000000000000000")),
    (Q("0.9619585984721082"), Q("0.5000000000000000")),
    (Q("0.1729701835825934"), Q("0.5000000000000000")),
    (Q("0.8270298164174066"), Q("0.5000000000000000")),
    (Q("0.1739702151728672"), Q("0.5000000000000000")),
    (Q("0.8260297848271328"), Q("0.5000000000000000")),
    (Q("0.2981493453190407"), Q("0.5000000000000000")),
    (Q("0.7018506546809593"), Q("0.5000000000000000")),
    (Q("0.2991493451224835"), Q("0.5000000000000000")),
    (Q("0.7008506548775165"), Q("0.5000000000000000")),
    (Q("0.5000000000000000"), Q("0.5000000000000000")),
]
assert len(LIGHTS) == 47
assert len(set(LIGHTS)) == 47

WITNESS_POINT: Point = (Q("0.3291483384057615"), Q("0.3200271994936768"))
LIGHT_SET=set(LIGHTS)
assert {(ONE-x,y) for x,y in LIGHT_SET} == LIGHT_SET
assert {(x,ONE-y) for x,y in LIGHT_SET} == LIGHT_SET




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
    root: Box = (ZERO, HALF, ZERO, HALF)
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
    witness_upper_bound = potential_at(WITNESS_POINT)

    print("status:", "CERTIFIED" if result.certified else "NOT_CERTIFIED")
    print("method: spectral_hessian_exact_symmetry_quarter_square")
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
    print("witness_value_upper_bound_decimal:", decimal_string(witness_upper_bound))
    print("rigorous_interval_for_true_minimum:")
    print("  lower:", decimal_string(TARGET))
    print("  upper:", decimal_string(witness_upper_bound))
    print("coordinates:")
    for index, (x, y) in enumerate(coordinate_strings(LIGHTS), start=1):
        print(f"  {index:02d}: ({x}, {y})")

    assert result.certified
    assert result.minimum_leaf_lower_bound is not None
    assert result.minimum_leaf_lower_bound >= TARGET
    assert witness_upper_bound >= TARGET


if __name__ == "__main__":
    main()
