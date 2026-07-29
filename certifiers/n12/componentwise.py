#!/usr/bin/env python3
"""Exact rational componentwise-Hessian interval certificate for the same fixed 12-light configuration."""
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
def square_interval(lo,hi):lower=ZERO if lo<=0<=hi else min(lo*lo,hi*hi);return lower,max(lo*lo,hi*hi)
def mulint(a,b,c,d):v=(a*c,a*d,b*c,b*d);return min(v),max(v)
def divpos(a,b,c,d):
    assert a<=b and ZERO<c<=d;v=(a/c,a/d,b/c,b/d);return min(v),max(v)
def potgrad(p):
    x,y=p;v=gx=gy=ZERO
    for sx,sy in LIGHTS:
        dx=x-sx;dy=y-sy;r2=dx*dx+dy*dy
        if r2==0:raise ValueError('infinite at source')
        v+=ONE/r2;gx+=-2*dx/(r2*r2);gy+=-2*dy/(r2*r2)
    return v,gx,gy
def direct(box):
    x0,x1,y0,y1=box;t=ZERO
    for sx,sy in LIGHTS:
        _,dxm=square_interval(x0-sx,x1-sx);_,dym=square_interval(y0-sy,y1-sy);t+=ONE/(dxm+dym)
    return t
def hessian_intervals(box):
    x0,x1,y0,y1=box;hxx=(ZERO,ZERO);hyy=(ZERO,ZERO);hxy=(ZERO,ZERO)
    for sx,sy in LIGHTS:
        dx0,dx1=x0-sx,x1-sx;dy0,dy1=y0-sy,y1-sy
        dx2lo,dx2hi=square_interval(dx0,dx1);dy2lo,dy2hi=square_interval(dy0,dy1)
        r2lo=dx2lo+dy2lo;r2hi=dx2hi+dy2hi
        if r2lo==0:return None
        r6lo=r2lo**3;r6hi=r2hi**3
        nxx=(6*dx2lo-2*dy2hi,6*dx2hi-2*dy2lo);nyy=(6*dy2lo-2*dx2hi,6*dy2hi-2*dx2lo)
        dxy=mulint(dx0,dx1,dy0,dy1);nxy=(8*dxy[0],8*dxy[1])
        ix=divpos(*nxx,r6lo,r6hi);iy=divpos(*nyy,r6lo,r6hi);ixy=divpos(*nxy,r6lo,r6hi)
        hxx=(hxx[0]+ix[0],hxx[1]+ix[1]);hyy=(hyy[0]+iy[0],hyy[1]+iy[1]);hxy=(hxy[0]+ixy[0],hxy[1]+ixy[1])
    return hxx,hyy,hxy
def taylor(box):
    x0,x1,y0,y1=box;mx=(x0+x1)/2;my=(y0+y1)/2;hx=(x1-x0)/2;hy=(y1-y0)/2
    ints=hessian_intervals(box)
    if ints is None:return None
    value,gx,gy=potgrad((mx,my));hxx,hyy,hxy=ints
    rem=(min(ZERO,hxx[0])*hx*hx+min(ZERO,hyy[0])*hy*hy)/2-max(abs(hxy[0]),abs(hxy[1]))*hx*hy
    return value-abs(gx)*hx-abs(gy)*hy+rem
def lower(box):
    d=direct(box);t=taylor(box);return d if t is None else max(d,t)
class Result(NamedTuple):
    certified:bool;splits:int;leaves:int;maximum_depth:int;minimum_leaf_lower_bound:Q|None;failed_lower_bound:Q|None;failed_box:Box|None
def certify(target=TARGET,max_splits=2_000_000):
    root=(ZERO,ONE,ZERO,ONE);heap=[];serial=0;heappush(heap,(lower(root),0,serial,root));serial+=1
    splits=leaves=dmax=0;minleaf=None
    while heap:
        lb,depth,_,box=heappop(heap)
        if lb>=target:
            leaves+=1;dmax=max(dmax,depth);minleaf=lb if minleaf is None else min(minleaf,lb);continue
        if splits>=max_splits:return Result(False,splits,leaves,dmax,minleaf,lb,box)
        x0,x1,y0,y1=box
        if x1-x0>=y1-y0:m=(x0+x1)/2;children=((x0,m,y0,y1),(m,x1,y0,y1))
        else:m=(y0+y1)/2;children=((x0,x1,y0,m),(x0,x1,m,y1))
        for child in children:heappush(heap,(lower(child),depth+1,serial,child));serial+=1
        splits+=1
    return Result(True,splits,leaves,dmax,minleaf,None,None)
def dec(q,prec=80):getcontext().prec=prec;return str(Decimal(q.numerator)/Decimal(q.denominator))
def main():
    r=certify();upper=potgrad(WITNESS)[0]
    print('status:','CERTIFIED' if r.certified else 'NOT_CERTIFIED');print('method: componentwise_hessian_intervals_full_unit_square')
    print('target_exact:',TARGET);print('target_decimal:',dec(TARGET));print('splits:',r.splits);print('leaf_count:',r.leaves);print('maximum_depth:',r.maximum_depth)
    if r.minimum_leaf_lower_bound is not None:print('minimum_leaf_lower_bound_decimal:',dec(r.minimum_leaf_lower_bound))
    print('upper_witness_point:',WITNESS);print('upper_witness_value_decimal:',dec(upper));print('rigorous_interval_for_true_minimum:');print('  lower:',dec(TARGET));print('  upper:',dec(upper))
    assert r.certified and r.minimum_leaf_lower_bound is not None and r.minimum_leaf_lower_bound>=TARGET and upper>=TARGET
if __name__=='__main__':main()
