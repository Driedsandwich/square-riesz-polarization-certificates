#!/usr/bin/env python3
"""Second exact certificate using componentwise Hessian intervals.

For the literal decimal configuration below, this program proves on the full
unit square that F(x,y) = sum_i 1/((x-x_i)^2+(y-y_i)^2) is at least TARGET.
All coordinates, boxes, derivatives, interval endpoints, and comparisons use
fractions.Fraction, so no floating-point rounding enters the proof.

This verifier uses a different second-order remainder bound from the companion spectral verifier:
it never uses the Hessian eigenvalue bound.  Instead, it encloses H_xx, H_yy,
and H_xy separately over each box and applies a componentwise Taylor remainder.
Dependencies: Python 3 standard library only.
"""
from __future__ import annotations
from decimal import Decimal, getcontext
from fractions import Fraction as Q
from heapq import heappop, heappush
from typing import NamedTuple

ZERO=Q(0); ONE=Q(1)
TARGET=Q("125.4580973")
Point=tuple[Q,Q]
Box=tuple[Q,Q,Q,Q]
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
assert len(LIGHTS)==16
assert len(set(LIGHTS))==16


def square_interval(lo: Q, hi: Q) -> tuple[Q,Q]:
    if lo <= 0 <= hi:
        lower=ZERO
    else:
        lower=min(lo*lo,hi*hi)
    return lower,max(lo*lo,hi*hi)


def multiply_intervals(a:Q,b:Q,c:Q,d:Q)->tuple[Q,Q]:
    values=(a*c,a*d,b*c,b*d)
    return min(values),max(values)


def divide_by_positive_interval(a:Q,b:Q,c:Q,d:Q)->tuple[Q,Q]:
    assert a<=b and ZERO<c<=d
    values=(a/c,a/d,b/c,b/d)
    return min(values),max(values)


def potential_and_gradient(point:Point)->tuple[Q,Q,Q]:
    x,y=point; value=gx=gy=ZERO
    for sx,sy in LIGHTS:
        dx=x-sx; dy=y-sy; r2=dx*dx+dy*dy
        if r2==0:
            raise ValueError("potential is infinite at a light")
        value += ONE/r2
        gx += -2*dx/(r2*r2)
        gy += -2*dy/(r2*r2)
    return value,gx,gy


def direct_inverse_distance_bound(box:Box)->Q:
    x0,x1,y0,y1=box; total=ZERO
    for sx,sy in LIGHTS:
        _,dx2max=square_interval(x0-sx,x1-sx)
        _,dy2max=square_interval(y0-sy,y1-sy)
        total += ONE/(dx2max+dy2max)
    return total


def hessian_entry_intervals(box:Box):
    x0,x1,y0,y1=box
    hxx=(ZERO,ZERO); hyy=(ZERO,ZERO); hxy=(ZERO,ZERO)
    for sx,sy in LIGHTS:
        dx0,dx1=x0-sx,x1-sx
        dy0,dy1=y0-sy,y1-sy
        dx2lo,dx2hi=square_interval(dx0,dx1)
        dy2lo,dy2hi=square_interval(dy0,dy1)
        r2lo=dx2lo+dy2lo; r2hi=dx2hi+dy2hi
        if r2lo==0:
            return None
        r6lo=r2lo**3; r6hi=r2hi**3
        # f_xx=(6 dx^2-2 dy^2)/r^6; f_yy analogously; f_xy=8 dx dy/r^6.
        nxx=(6*dx2lo-2*dy2hi,6*dx2hi-2*dy2lo)
        nyy=(6*dy2lo-2*dx2hi,6*dy2hi-2*dx2lo)
        dxy=multiply_intervals(dx0,dx1,dy0,dy1)
        nxy=(8*dxy[0],8*dxy[1])
        ix=divide_by_positive_interval(*nxx,r6lo,r6hi)
        iy=divide_by_positive_interval(*nyy,r6lo,r6hi)
        ixy=divide_by_positive_interval(*nxy,r6lo,r6hi)
        hxx=(hxx[0]+ix[0],hxx[1]+ix[1])
        hyy=(hyy[0]+iy[0],hyy[1]+iy[1])
        hxy=(hxy[0]+ixy[0],hxy[1]+ixy[1])
    return hxx,hyy,hxy


def componentwise_taylor_bound(box:Box)->Q|None:
    x0,x1,y0,y1=box
    mx=(x0+x1)/2; my=(y0+y1)/2
    hx=(x1-x0)/2; hy=(y1-y0)/2
    intervals=hessian_entry_intervals(box)
    if intervals is None:
        return None
    value,gx,gy=potential_and_gradient((mx,my))
    hxx,hyy,hxy=intervals
    remainder=(min(ZERO,hxx[0])*hx*hx + min(ZERO,hyy[0])*hy*hy)/2
    remainder -= max(abs(hxy[0]),abs(hxy[1]))*hx*hy
    return value-abs(gx)*hx-abs(gy)*hy+remainder


def box_lower_bound(box:Box)->Q:
    direct=direct_inverse_distance_bound(box)
    taylor=componentwise_taylor_bound(box)
    if taylor is None:
        return direct
    return max(direct,taylor)


class Result(NamedTuple):
    certified:bool
    splits:int
    leaves:int
    maximum_depth:int
    minimum_leaf_lower_bound:Q|None
    failed_lower_bound:Q|None
    failed_box:Box|None


def certify(target:Q=TARGET,max_splits:int=2_000_000)->Result:
    root=(ZERO,ONE,ZERO,ONE)
    heap=[]; serial=0
    heappush(heap,(box_lower_bound(root),0,serial,root)); serial+=1
    splits=leaves=maximum_depth=0
    minimum_leaf=None
    while heap:
        lower,depth,_,box=heappop(heap)
        if lower>=target:
            leaves+=1; maximum_depth=max(maximum_depth,depth)
            minimum_leaf=lower if minimum_leaf is None else min(minimum_leaf,lower)
            continue
        if splits>=max_splits:
            return Result(False,splits,leaves,maximum_depth,minimum_leaf,lower,box)
        x0,x1,y0,y1=box
        if x1-x0>=y1-y0:
            mid=(x0+x1)/2
            children=((x0,mid,y0,y1),(mid,x1,y0,y1))
        else:
            mid=(y0+y1)/2
            children=((x0,x1,y0,mid),(x0,x1,mid,y1))
        for child in children:
            heappush(heap,(box_lower_bound(child),depth+1,serial,child)); serial+=1
        splits+=1
    return Result(True,splits,leaves,maximum_depth,minimum_leaf,None,None)


def decimal(value:Q,precision:int=70)->str:
    getcontext().prec=precision
    return str(Decimal(value.numerator)/Decimal(value.denominator))


def main()->None:
    result=certify()
    corner=potential_and_gradient((ZERO,ZERO))[0]
    print("status:","CERTIFIED" if result.certified else "NOT_CERTIFIED")
    print("method: componentwise_hessian_intervals_full_unit_square")
    print("target_exact:",TARGET)
    print("target_decimal:",decimal(TARGET))
    print("splits:",result.splits)
    print("leaf_count:",result.leaves)
    print("maximum_depth:",result.maximum_depth)
    if result.minimum_leaf_lower_bound is not None:
        print("minimum_leaf_lower_bound_decimal:",decimal(result.minimum_leaf_lower_bound))
    print("corner_value_upper_bound_decimal:",decimal(corner))
    print("rigorous_interval_for_true_minimum:")
    print("  lower:",decimal(TARGET))
    print("  upper:",decimal(corner))
    assert result.certified
    assert result.minimum_leaf_lower_bound is not None
    assert result.minimum_leaf_lower_bound>=TARGET
    assert corner>=TARGET

if __name__=="__main__":
    main()
