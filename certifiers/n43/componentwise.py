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
TARGET = Q("390.6283")
Point=tuple[Q,Q]
Box=tuple[Q,Q,Q,Q]
LIGHTS: list[Point] = [
    (Q("0.0441824024835093"), Q("0.2990918682153380")),
    (Q("0.9558175975164907"), Q("0.2990918682153380")),
    (Q("0.0441824024835093"), Q("0.7009081317846620")),
    (Q("0.9558175975164907"), Q("0.7009081317846620")),
    (Q("0.0624432130918208"), Q("0.0154478877621927")),
    (Q("0.9375567869081792"), Q("0.0154478877621927")),
    (Q("0.0624432130918208"), Q("0.9845521122378073")),
    (Q("0.9375567869081792"), Q("0.9845521122378073")),
    (Q("0.0547897455105250"), Q("0.1429426601710737")),
    (Q("0.9452102544894750"), Q("0.1429426601710737")),
    (Q("0.0547897455105250"), Q("0.8570573398289263")),
    (Q("0.9452102544894750"), Q("0.8570573398289263")),
    (Q("0.2452483721169832"), Q("0.0206727860216172")),
    (Q("0.7547516278830168"), Q("0.0206727860216172")),
    (Q("0.2452483721169832"), Q("0.9793272139783828")),
    (Q("0.7547516278830168"), Q("0.9793272139783828")),
    (Q("0.2464387344904050"), Q("0.2235308726488525")),
    (Q("0.7535612655095950"), Q("0.2235308726488525")),
    (Q("0.2464387344904050"), Q("0.7764691273511475")),
    (Q("0.7535612655095950"), Q("0.7764691273511475")),
    (Q("0.5000000000000000"), Q("0.0315845278421691")),
    (Q("0.5000000000000000"), Q("0.9684154721578309")),
    (Q("0.5000000000000000"), Q("0.0325845258148004")),
    (Q("0.5000000000000000"), Q("0.9674154741851996")),
    (Q("0.5000000000000000"), Q("0.0335845231315821")),
    (Q("0.5000000000000000"), Q("0.9664154768684179")),
    (Q("0.5000000000000000"), Q("0.0345845211341944")),
    (Q("0.5000000000000000"), Q("0.9654154788658056")),
    (Q("0.5000000000000000"), Q("0.2579076620960186")),
    (Q("0.5000000000000000"), Q("0.7420923379039814")),
    (Q("0.5000000000000000"), Q("0.2697021996891678")),
    (Q("0.5000000000000000"), Q("0.7302978003108322")),
    (Q("0.0484473445573267"), Q("0.5000000000000000")),
    (Q("0.9515526554426733"), Q("0.5000000000000000")),
    (Q("0.0494473443882495"), Q("0.5000000000000000")),
    (Q("0.9505526556117505"), Q("0.5000000000000000")),
    (Q("0.2123206652876316"), Q("0.5000000000000000")),
    (Q("0.7876793347123684"), Q("0.5000000000000000")),
    (Q("0.2858821393513143"), Q("0.5000000000000000")),
    (Q("0.7141178606486857"), Q("0.5000000000000000")),
    (Q("0.2868821394230859"), Q("0.5000000000000000")),
    (Q("0.7131178605769141"), Q("0.5000000000000000")),
    (Q("0.5000000000000000"), Q("0.5000000000000000")),
]
assert len(LIGHTS) == 43
assert len(set(LIGHTS)) == 43

WITNESS_POINT: Point = (Q("0.1744387251323918"), Q("0.3326651308790007"))
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
