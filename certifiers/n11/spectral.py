#!/usr/bin/env python3
"""Exact rational lower-bound certificate for a 11-light square configuration.

For the literal decimal coordinates below, this program proves
    min_{p in [0,1]^2} sum_i 1/||p-c_i||^2 >= 74.3527.
It uses exact fractions.Fraction arithmetic, a termwise distance lower bound,
and a second-order Taylor bound based on the minimum Hessian eigenvalue of
1/||p-c||^2.  The full unit square is covered by rational branch-and-bound.
Dependencies: Python 3 standard library only.
"""
from __future__ import annotations
from decimal import Decimal, getcontext
from fractions import Fraction as Q
from heapq import heappop, heappush
from typing import NamedTuple

ZERO=Q(0); HALF=Q(1,2); ONE=Q(1)
TARGET=Q("74.3527")
Point=tuple[Q,Q]
Box=tuple[Q,Q,Q,Q]

PARAMETERS={
    "ax":Q("0.10935319353733548"), "ay":Q("0.33756158091155750"),
    "ux":Q("0.12922380456227803"), "uy":Q("0.04862374718378315"),
    "c":Q("0.07034885925315561"),
}

def reflected_orbit4(x:Q,y:Q)->list[Point]:
    return [(x,y),(ONE-x,y),(x,ONE-y),(ONE-x,ONE-y)]

def build_lights()->list[Point]:
    L=[]
    L += reflected_orbit4(PARAMETERS["ax"],PARAMETERS["ay"])
    L += reflected_orbit4(PARAMETERS["ux"],PARAMETERS["uy"])
    L += [(HALF,PARAMETERS["c"]),(HALF,ONE-PARAMETERS["c"]),(HALF,HALF)]
    assert len(L)==11 and len(set(L))==11
    assert set(L)=={(ONE-x,y) for x,y in L}
    assert set(L)=={(x,ONE-y) for x,y in L}
    assert all(ZERO<=x<=ONE and ZERO<=y<=ONE for x,y in L)
    return L
LIGHTS=build_lights()

def min_sq_1d(s:Q,lo:Q,hi:Q)->Q:
    if s<lo:return (lo-s)**2
    if s>hi:return (s-hi)**2
    return ZERO

def max_sq_1d(s:Q,lo:Q,hi:Q)->Q:
    return max((lo-s)**2,(hi-s)**2)

def potential_at(p:Point)->Q:
    x,y=p; total=ZERO
    for sx,sy in LIGHTS:
        r2=(x-sx)**2+(y-sy)**2
        if r2==0: raise ValueError("potential is infinite at a source")
        total += ONE/r2
    return total

def box_lower_bound(box:Box)->Q:
    x0,x1,y0,y1=box
    mx,my=(x0+x1)/2,(y0+y1)/2
    hx,hy=(x1-x0)/2,(y1-y0)/2
    direct=ZERO; source_in=False
    value=gx=gy=curv=ZERO
    for sx,sy in LIGHTS:
        maxd2=max_sq_1d(sx,x0,x1)+max_sq_1d(sy,y0,y1)
        direct += ONE/maxd2
        mind2=min_sq_1d(sx,x0,x1)+min_sq_1d(sy,y0,y1)
        if mind2==0: source_in=True
        dx,dy=mx-sx,my-sy; r2=dx*dx+dy*dy
        if r2!=0:
            value += ONE/r2
            gx += -2*dx/(r2*r2)
            gy += -2*dy/(r2*r2)
        if mind2!=0: curv += ONE/(mind2*mind2)
    if source_in:return direct
    taylor=value-abs(gx)*hx-abs(gy)*hy-curv*(hx*hx+hy*hy)
    return max(direct,taylor)

class Result(NamedTuple):
    certified:bool; splits:int; leaves:int; maximum_depth:int
    minimum_leaf_lower_bound:Q|None; failed_lower_bound:Q|None; failed_box:Box|None

def certify(target:Q=TARGET,max_splits:int=2_000_000)->Result:
    root=(ZERO,ONE,ZERO,ONE); heap=[]; serial=0
    heappush(heap,(box_lower_bound(root),0,serial,root)); serial+=1
    splits=leaves=depthmax=0; minleaf=None
    while heap:
        lower,depth,_,box=heappop(heap)
        if lower>=target:
            leaves+=1; depthmax=max(depthmax,depth)
            minleaf=lower if minleaf is None else min(minleaf,lower)
            continue
        if splits>=max_splits:return Result(False,splits,leaves,depthmax,minleaf,lower,box)
        x0,x1,y0,y1=box
        if x1-x0>=y1-y0:
            m=(x0+x1)/2; children=((x0,m,y0,y1),(m,x1,y0,y1))
        else:
            m=(y0+y1)/2; children=((x0,x1,y0,m),(x0,x1,m,y1))
        for child in children:
            heappush(heap,(box_lower_bound(child),depth+1,serial,child)); serial+=1
        splits+=1
    return Result(True,splits,leaves,depthmax,minleaf,None,None)

def dec(q:Q,prec:int=70)->str:
    getcontext().prec=prec
    return str(Decimal(q.numerator)/Decimal(q.denominator))

def main()->None:
    r=certify(); corner=potential_at((ZERO,ZERO))
    print("status:","CERTIFIED" if r.certified else "NOT_CERTIFIED")
    print("method: spectral_hessian_full_unit_square")
    print("target_exact:",TARGET)
    print("target_decimal:",dec(TARGET))
    print("splits:",r.splits)
    print("leaf_count:",r.leaves)
    print("maximum_depth:",r.maximum_depth)
    if r.minimum_leaf_lower_bound is not None:
        print("minimum_leaf_lower_bound_decimal:",dec(r.minimum_leaf_lower_bound))
    print("corner_value_upper_bound_decimal:",dec(corner))
    print("rigorous_interval_for_true_minimum:")
    print("  lower:",dec(TARGET)); print("  upper:",dec(corner))
    assert r.certified and r.minimum_leaf_lower_bound is not None
    assert r.minimum_leaf_lower_bound>=TARGET and corner>=TARGET
if __name__=="__main__":main()
