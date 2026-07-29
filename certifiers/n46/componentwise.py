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
TARGET = Q("413.3754")
Point=tuple[Q,Q]
Box=tuple[Q,Q,Q,Q]
LIGHTS: list[Point] = [
    (Q("0.0385340822167699"), Q("0.2918863215616364")),
    (Q("0.9614659177832301"), Q("0.2918863215616364")),
    (Q("0.0385340822167699"), Q("0.7081136784383636")),
    (Q("0.9614659177832301"), Q("0.7081136784383636")),
    (Q("0.0607799072094557"), Q("0.0157038819441998")),
    (Q("0.9392200927905443"), Q("0.0157038819441998")),
    (Q("0.0607799072094557"), Q("0.9842961180558002")),
    (Q("0.9392200927905443"), Q("0.9842961180558002")),
    (Q("0.0559674346191043"), Q("0.1387089879059009")),
    (Q("0.9440325653808957"), Q("0.1387089879059009")),
    (Q("0.0559674346191043"), Q("0.8612910120940991")),
    (Q("0.9440325653808957"), Q("0.8612910120940991")),
    (Q("0.2392228516974955"), Q("0.0216856001282071")),
    (Q("0.7607771483025045"), Q("0.0216856001282071")),
    (Q("0.2392228516974955"), Q("0.9783143998717929")),
    (Q("0.7607771483025045"), Q("0.9783143998717929")),
    (Q("0.2439533891098954"), Q("0.2226901111343653")),
    (Q("0.7560466108901046"), Q("0.2226901111343653")),
    (Q("0.2439533891098954"), Q("0.7773098888656347")),
    (Q("0.7560466108901046"), Q("0.7773098888656347")),
    (Q("0.5000000000000000"), Q("0.0363177743564221")),
    (Q("0.5000000000000000"), Q("0.9636822256435779")),
    (Q("0.5000000000000000"), Q("0.0373177722062277")),
    (Q("0.5000000000000000"), Q("0.9626822277937723")),
    (Q("0.5000000000000000"), Q("0.0383177689983663")),
    (Q("0.5000000000000000"), Q("0.9616822310016337")),
    (Q("0.5000000000000000"), Q("0.0393177658666257")),
    (Q("0.5000000000000000"), Q("0.9606822341333743")),
    (Q("0.5000000000000000"), Q("0.0403177637922386")),
    (Q("0.5000000000000000"), Q("0.9596822362077614")),
    (Q("0.5000000000000000"), Q("0.2979076620960186")),
    (Q("0.5000000000000000"), Q("0.7020923379039814")),
    (Q("0.5000000000000000"), Q("0.2989085036637353")),
    (Q("0.5000000000000000"), Q("0.7010914963362647")),
    (Q("0.0417186141439553"), Q("0.5000000000000000")),
    (Q("0.9582813858560447"), Q("0.5000000000000000")),
    (Q("0.0427186138015634"), Q("0.5000000000000000")),
    (Q("0.9572813861984366"), Q("0.5000000000000000")),
    (Q("0.1729513498089803"), Q("0.5000000000000000")),
    (Q("0.8270486501910197"), Q("0.5000000000000000")),
    (Q("0.1739516442247638"), Q("0.5000000000000000")),
    (Q("0.8260483557752362"), Q("0.5000000000000000")),
    (Q("0.3258821393513143"), Q("0.5000000000000000")),
    (Q("0.6741178606486857"), Q("0.5000000000000000")),
    (Q("0.3268821394230859"), Q("0.5000000000000000")),
    (Q("0.6731178605769141"), Q("0.5000000000000000")),
]
assert len(LIGHTS) == 46
assert len(set(LIGHTS)) == 46

WITNESS_POINT: Point = (Q("0.0000000000000000"), Q("0.2065274166894918"))
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
