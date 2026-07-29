#!/usr/bin/env python3
"""Exact rational spectral-Hessian certificate for a fixed 12-light square configuration.
Proves min over the full unit square of sum_i 1/||p-c_i||^2 >= 83.57159574.
The decimal coordinates are interpreted literally as exact rational numbers.
Python standard library only.
"""
from __future__ import annotations
from decimal import Decimal,getcontext
from fractions import Fraction as Q
from heapq import heappop,heappush
from typing import NamedTuple
ZERO=Q(0);ONE=Q(1);TARGET=Q("83.57159574");WITNESS=(Q("0.22822614598846336"),ZERO)
Point=tuple[Q,Q];Box=tuple[Q,Q,Q,Q]
LIGHTS=[
(Q("0.09310808609823491"),Q("0.42496101064219466")),
(Q("0.90688976439566416"),Q("0.42488626872541069")),
(Q("0.12291148090637921"),Q("0.72499807254074111")),
(Q("0.87711708365972807"),Q("0.72494536381801877")),
(Q("0.36075028604007509"),Q("0.12324584840981972")),
(Q("0.92092400906383876"),Q("0.10209834518865736")),
(Q("0.13068801245371242"),Q("0.97366968839171641")),
(Q("0.86931961017613191"),Q("0.97364989794753232")),
(Q("0.63914187346301521"),Q("0.12320944504383401")),
(Q("0.50000997974148220"),Q("0.95156099497983970")),
(Q("0.50002535492169109"),Q("0.54878423743347271")),
(Q("0.07903142322698788"),Q("0.10213559182720713")),
]
assert len(LIGHTS)==12 and len(set(LIGHTS))==12
assert all(ZERO<=x<=ONE and ZERO<=y<=ONE for x,y in LIGHTS)
def min_sq_1d(s,lo,hi):
    if s<lo:return (lo-s)**2
    if s>hi:return (s-hi)**2
    return ZERO
def max_sq_1d(s,lo,hi):return max((lo-s)**2,(hi-s)**2)
def potential_at(p):
    x,y=p;t=ZERO
    for sx,sy in LIGHTS:
        r2=(x-sx)**2+(y-sy)**2
        if r2==0:raise ValueError('infinite at source')
        t+=ONE/r2
    return t
def box_lower_bound(box):
    x0,x1,y0,y1=box;mx,my=(x0+x1)/2,(y0+y1)/2;hx,hy=(x1-x0)/2,(y1-y0)/2
    direct=ZERO;source_in=False;value=gx=gy=curv=ZERO
    for sx,sy in LIGHTS:
        maxd2=max_sq_1d(sx,x0,x1)+max_sq_1d(sy,y0,y1);direct+=ONE/maxd2
        mind2=min_sq_1d(sx,x0,x1)+min_sq_1d(sy,y0,y1)
        if mind2==0:source_in=True
        dx,dy=mx-sx,my-sy;r2=dx*dx+dy*dy
        if r2!=0:
            value+=ONE/r2;gx+=-2*dx/(r2*r2);gy+=-2*dy/(r2*r2)
        if mind2!=0:curv+=ONE/(mind2*mind2)
    if source_in:return direct
    taylor=value-abs(gx)*hx-abs(gy)*hy-curv*(hx*hx+hy*hy)
    return max(direct,taylor)
class Result(NamedTuple):
    certified:bool;splits:int;leaves:int;maximum_depth:int;minimum_leaf_lower_bound:Q|None;failed_lower_bound:Q|None;failed_box:Box|None
def certify(target=TARGET,max_splits=2_000_000):
    root=(ZERO,ONE,ZERO,ONE);heap=[];serial=0;heappush(heap,(box_lower_bound(root),0,serial,root));serial+=1
    splits=leaves=dmax=0;minleaf=None
    while heap:
        lb,depth,_,box=heappop(heap)
        if lb>=target:
            leaves+=1;dmax=max(dmax,depth);minleaf=lb if minleaf is None else min(minleaf,lb);continue
        if splits>=max_splits:return Result(False,splits,leaves,dmax,minleaf,lb,box)
        x0,x1,y0,y1=box
        if x1-x0>=y1-y0:m=(x0+x1)/2;children=((x0,m,y0,y1),(m,x1,y0,y1))
        else:m=(y0+y1)/2;children=((x0,x1,y0,m),(x0,x1,m,y1))
        for child in children:heappush(heap,(box_lower_bound(child),depth+1,serial,child));serial+=1
        splits+=1
    return Result(True,splits,leaves,dmax,minleaf,None,None)
def dec(q,prec=80):getcontext().prec=prec;return str(Decimal(q.numerator)/Decimal(q.denominator))
def main():
    r=certify();upper=potential_at(WITNESS)
    print('status:','CERTIFIED' if r.certified else 'NOT_CERTIFIED');print('method: spectral_hessian_full_unit_square')
    print('target_exact:',TARGET);print('target_decimal:',dec(TARGET));print('splits:',r.splits);print('leaf_count:',r.leaves);print('maximum_depth:',r.maximum_depth)
    if r.minimum_leaf_lower_bound is not None:print('minimum_leaf_lower_bound_decimal:',dec(r.minimum_leaf_lower_bound))
    print('upper_witness_point:',WITNESS);print('upper_witness_value_decimal:',dec(upper));print('rigorous_interval_for_true_minimum:');print('  lower:',dec(TARGET));print('  upper:',dec(upper))
    assert r.certified and r.minimum_leaf_lower_bound is not None and r.minimum_leaf_lower_bound>=TARGET and upper>=TARGET
if __name__=='__main__':main()
