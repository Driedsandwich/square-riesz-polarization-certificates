#!/usr/bin/env python3
"""Second exact certificate using componentwise Hessian intervals.

For the literal decimal configuration below, this program proves on the quarter square [0,1/2]^2 after exact reflection-symmetry checks; this implies the result on the full
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

ZERO=Q(0); HALF=Q(1,2); ONE=Q(1)
TARGET = Q("403.2479")
Point=tuple[Q,Q]
Box=tuple[Q,Q,Q,Q]
LIGHTS: list[Point] = [
    (Q("0.0381992777501205"), Q("0.2872785822793564")),
    (Q("0.9618007222498795"), Q("0.2872785822793564")),
    (Q("0.0381992777501205"), Q("0.7127214177206436")),
    (Q("0.9618007222498795"), Q("0.7127214177206436")),
    (Q("0.0629448881030922"), Q("0.0117416286601175")),
    (Q("0.9370551118969078"), Q("0.0117416286601175")),
    (Q("0.0629448881030922"), Q("0.9882583713398825")),
    (Q("0.9370551118969078"), Q("0.9882583713398825")),
    (Q("0.0578762074571618"), Q("0.1330124449982078")),
    (Q("0.9421237925428382"), Q("0.1330124449982078")),
    (Q("0.0578762074571618"), Q("0.8669875550017922")),
    (Q("0.9421237925428382"), Q("0.8669875550017922")),
    (Q("0.2461793858793828"), Q("0.0176295436999975")),
    (Q("0.7538206141206172"), Q("0.0176295436999975")),
    (Q("0.2461793858793828"), Q("0.9823704563000025")),
    (Q("0.7538206141206172"), Q("0.9823704563000025")),
    (Q("0.2492765201156981"), Q("0.2175210274060164")),
    (Q("0.7507234798843019"), Q("0.2175210274060164")),
    (Q("0.2492765201156981"), Q("0.7824789725939836")),
    (Q("0.7507234798843019"), Q("0.7824789725939836")),
    (Q("0.5000000000000000"), Q("0.0276028698299714")),
    (Q("0.5000000000000000"), Q("0.9723971301700286")),
    (Q("0.5000000000000000"), Q("0.0286031301292193")),
    (Q("0.5000000000000000"), Q("0.9713968698707807")),
    (Q("0.5000000000000000"), Q("0.0296046838042895")),
    (Q("0.5000000000000000"), Q("0.9703953161957105")),
    (Q("0.5000000000000000"), Q("0.0306049767213085")),
    (Q("0.5000000000000000"), Q("0.9693950232786915")),
    (Q("0.5000000000000000"), Q("0.2434554216111965")),
    (Q("0.5000000000000000"), Q("0.7565445783888035")),
    (Q("0.5000000000000000"), Q("0.2655930580542937")),
    (Q("0.5000000000000000"), Q("0.7344069419457063")),
    (Q("0.0398029064442991"), Q("0.5000000000000000")),
    (Q("0.9601970935557009"), Q("0.5000000000000000")),
    (Q("0.0408029080335107"), Q("0.5000000000000000")),
    (Q("0.9591970919664893"), Q("0.5000000000000000")),
    (Q("0.1729642089278726"), Q("0.5000000000000000")),
    (Q("0.8270357910721274"), Q("0.5000000000000000")),
    (Q("0.1739642519554268"), Q("0.5000000000000000")),
    (Q("0.8260357480445732"), Q("0.5000000000000000")),
    (Q("0.3089319596064399"), Q("0.5000000000000000")),
    (Q("0.6910680403935601"), Q("0.5000000000000000")),
    (Q("0.3099319742513665"), Q("0.5000000000000000")),
    (Q("0.6900680257486335"), Q("0.5000000000000000")),
    (Q("0.5000000000000000"), Q("0.5000000000000000")),
]
assert len(LIGHTS) == 45
assert len(set(LIGHTS)) == 45

WITNESS_POINT: Point = (Q("0.1547820238276396"), Q("0.0000000000000000"))
LIGHT_SET=set(LIGHTS)
assert {(ONE-x,y) for x,y in LIGHT_SET} == LIGHT_SET
assert {(x,ONE-y) for x,y in LIGHT_SET} == LIGHT_SET



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
    root=(ZERO,HALF,ZERO,HALF)
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
    witness=potential_and_gradient(WITNESS_POINT)[0]
    print("status:","CERTIFIED" if result.certified else "NOT_CERTIFIED")
    print("method: componentwise_hessian_intervals_exact_symmetry_quarter_square")
    print("target_exact:",TARGET)
    print("target_decimal:",decimal(TARGET))
    print("splits:",result.splits)
    print("leaf_count:",result.leaves)
    print("maximum_depth:",result.maximum_depth)
    if result.minimum_leaf_lower_bound is not None:
        print("minimum_leaf_lower_bound_decimal:",decimal(result.minimum_leaf_lower_bound))
    print("witness_value_upper_bound_decimal:",decimal(witness))
    print("rigorous_interval_for_true_minimum:")
    print("  lower:",decimal(TARGET))
    print("  upper:",decimal(witness))
    assert result.certified
    assert result.minimum_leaf_lower_bound is not None
    assert result.minimum_leaf_lower_bound>=TARGET
    assert witness>=TARGET

if __name__=="__main__":
    main()
