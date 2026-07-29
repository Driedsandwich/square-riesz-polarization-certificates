#!/usr/bin/env python3
"""Second exact rational certificate for the same fixed 11-light configuration.

This verifier does not use a Hessian eigenvalue formula.  It encloses H_xx,
H_yy, and H_xy separately on every rational box and applies a componentwise
second-order Taylor remainder.  The full unit square is covered.
Dependencies: Python 3 standard library only.
"""
from __future__ import annotations
from decimal import Decimal,getcontext
from fractions import Fraction as Q
from heapq import heappop,heappush
from typing import NamedTuple
ZERO=Q(0);ONE=Q(1);TARGET=Q("74.3527")
Point=tuple[Q,Q];Box=tuple[Q,Q,Q,Q]
LIGHTS=[
(Q("0.10935319353733548"),Q("0.33756158091155750")),
(Q("0.89064680646266452"),Q("0.33756158091155750")),
(Q("0.10935319353733548"),Q("0.66243841908844250")),
(Q("0.89064680646266452"),Q("0.66243841908844250")),
(Q("0.12922380456227803"),Q("0.04862374718378315")),
(Q("0.87077619543772197"),Q("0.04862374718378315")),
(Q("0.12922380456227803"),Q("0.95137625281621685")),
(Q("0.87077619543772197"),Q("0.95137625281621685")),
(Q("0.50000000000000000"),Q("0.07034885925315561")),
(Q("0.50000000000000000"),Q("0.92965114074684439")),
(Q("0.50000000000000000"),Q("0.50000000000000000")),
]
assert len(LIGHTS)==11 and len(set(LIGHTS))==11
assert set(LIGHTS)=={(ONE-x,y) for x,y in LIGHTS}
assert set(LIGHTS)=={(x,ONE-y) for x,y in LIGHTS}

def square_interval(lo:Q,hi:Q)->tuple[Q,Q]:
    lower=ZERO if lo<=0<=hi else min(lo*lo,hi*hi)
    return lower,max(lo*lo,hi*hi)

def mulint(a:Q,b:Q,c:Q,d:Q)->tuple[Q,Q]:
    v=(a*c,a*d,b*c,b*d);return min(v),max(v)

def divpos(a:Q,b:Q,c:Q,d:Q)->tuple[Q,Q]:
    assert a<=b and ZERO<c<=d
    v=(a/c,a/d,b/c,b/d);return min(v),max(v)

def potgrad(p:Point)->tuple[Q,Q,Q]:
    x,y=p;v=gx=gy=ZERO
    for sx,sy in LIGHTS:
        dx=x-sx;dy=y-sy;r2=dx*dx+dy*dy
        if r2==0:raise ValueError("potential is infinite at a source")
        v+=ONE/r2;gx+=-2*dx/(r2*r2);gy+=-2*dy/(r2*r2)
    return v,gx,gy

def direct(box:Box)->Q:
    x0,x1,y0,y1=box;total=ZERO
    for sx,sy in LIGHTS:
        _,dxm=square_interval(x0-sx,x1-sx)
        _,dym=square_interval(y0-sy,y1-sy)
        total+=ONE/(dxm+dym)
    return total

def hessian_intervals(box:Box):
    x0,x1,y0,y1=box;hxx=(ZERO,ZERO);hyy=(ZERO,ZERO);hxy=(ZERO,ZERO)
    for sx,sy in LIGHTS:
        dx0,dx1=x0-sx,x1-sx;dy0,dy1=y0-sy,y1-sy
        dx2lo,dx2hi=square_interval(dx0,dx1);dy2lo,dy2hi=square_interval(dy0,dy1)
        r2lo=dx2lo+dy2lo;r2hi=dx2hi+dy2hi
        if r2lo==0:return None
        r6lo=r2lo**3;r6hi=r2hi**3
        nxx=(6*dx2lo-2*dy2hi,6*dx2hi-2*dy2lo)
        nyy=(6*dy2lo-2*dx2hi,6*dy2hi-2*dx2lo)
        dxy=mulint(dx0,dx1,dy0,dy1);nxy=(8*dxy[0],8*dxy[1])
        ix=divpos(*nxx,r6lo,r6hi);iy=divpos(*nyy,r6lo,r6hi);ixy=divpos(*nxy,r6lo,r6hi)
        hxx=(hxx[0]+ix[0],hxx[1]+ix[1]);hyy=(hyy[0]+iy[0],hyy[1]+iy[1]);hxy=(hxy[0]+ixy[0],hxy[1]+ixy[1])
    return hxx,hyy,hxy

def taylor(box:Box)->Q|None:
    x0,x1,y0,y1=box;mx=(x0+x1)/2;my=(y0+y1)/2;hx=(x1-x0)/2;hy=(y1-y0)/2
    ints=hessian_intervals(box)
    if ints is None:return None
    value,gx,gy=potgrad((mx,my));hxx,hyy,hxy=ints
    rem=(min(ZERO,hxx[0])*hx*hx+min(ZERO,hyy[0])*hy*hy)/2
    rem-=max(abs(hxy[0]),abs(hxy[1]))*hx*hy
    return value-abs(gx)*hx-abs(gy)*hy+rem

def lower(box:Box)->Q:
    d=direct(box);t=taylor(box);return d if t is None else max(d,t)

class Result(NamedTuple):
    certified:bool;splits:int;leaves:int;maximum_depth:int;minimum_leaf_lower_bound:Q|None;failed_lower_bound:Q|None;failed_box:Box|None

def certify(target:Q=TARGET,max_splits:int=2_000_000)->Result:
    root=(ZERO,ONE,ZERO,ONE);heap=[];serial=0
    heappush(heap,(lower(root),0,serial,root));serial+=1
    splits=leaves=dmax=0;minleaf=None
    while heap:
        lb,depth,_,box=heappop(heap)
        if lb>=target:
            leaves+=1;dmax=max(dmax,depth);minleaf=lb if minleaf is None else min(minleaf,lb);continue
        if splits>=max_splits:return Result(False,splits,leaves,dmax,minleaf,lb,box)
        x0,x1,y0,y1=box
        if x1-x0>=y1-y0:
            m=(x0+x1)/2;children=((x0,m,y0,y1),(m,x1,y0,y1))
        else:
            m=(y0+y1)/2;children=((x0,x1,y0,m),(x0,x1,m,y1))
        for child in children:
            heappush(heap,(lower(child),depth+1,serial,child));serial+=1
        splits+=1
    return Result(True,splits,leaves,dmax,minleaf,None,None)

def dec(q:Q,prec:int=70)->str:
    getcontext().prec=prec;return str(Decimal(q.numerator)/Decimal(q.denominator))

def main()->None:
    r=certify();corner=potgrad((ZERO,ZERO))[0]
    print("status:","CERTIFIED" if r.certified else "NOT_CERTIFIED")
    print("method: componentwise_hessian_intervals_full_unit_square")
    print("target_exact:",TARGET);print("target_decimal:",dec(TARGET))
    print("splits:",r.splits);print("leaf_count:",r.leaves);print("maximum_depth:",r.maximum_depth)
    if r.minimum_leaf_lower_bound is not None:print("minimum_leaf_lower_bound_decimal:",dec(r.minimum_leaf_lower_bound))
    print("corner_value_upper_bound_decimal:",dec(corner))
    print("rigorous_interval_for_true_minimum:");print("  lower:",dec(TARGET));print("  upper:",dec(corner))
    assert r.certified and r.minimum_leaf_lower_bound is not None
    assert r.minimum_leaf_lower_bound>=TARGET and corner>=TARGET
if __name__=="__main__":main()
