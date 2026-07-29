#!/usr/bin/env python3
"""Exact full-square componentwise-Hessian certificate for n=21."""
from __future__ import annotations
from decimal import Decimal,getcontext
from fractions import Fraction as Q
from heapq import heappop,heappush
from typing import NamedTuple
ZERO=Q(0);ONE=Q(1);TARGET=Q("184.4391")
LIGHTS=[
    (Q("0.06404431693476983"),Q("0.06047088010849638")),
    (Q("0.93584570347805041"),Q("0.06035701104330040")),
    (Q("0.06465502156510652"),Q("0.94008788292923295")),
    (Q("0.93524168383841111"),Q("0.94019784911055126")),
    (Q("0.28010052610425140"),Q("0.06257577977880907")),
    (Q("0.71956113136998889"),Q("0.06233140170283436")),
    (Q("0.28236064451326887"),Q("0.93810234355524758")),
    (Q("0.71729849090816022"),Q("0.93836779900038736")),
    (Q("0.04341832304702747"),Q("0.28386968274977487")),
    (Q("0.95678790673933545"),Q("0.28376979529994850")),
    (Q("0.06966041641665113"),Q("0.73113022030628871")),
    (Q("0.93026151311413874"),Q("0.73138219872884402")),
    (Q("0.49975751964353898"),Q("0.07106272558728544")),
    (Q("0.49974988591351205"),Q("0.92503842609058806")),
    (Q("0.07047031121068784"),Q("0.51523757058716679")),
    (Q("0.92968119494936463"),Q("0.51542106855416869")),
    (Q("0.71060354625409294"),Q("0.35792392448956206")),
    (Q("0.35528558748279065"),Q("0.65960087809022094")),
    (Q("0.29056654641265361"),Q("0.35772817410047930")),
    (Q("0.64452297348309184"),Q("0.66011046510734939")),
    (Q("0.50133665655105830"),Q("0.37631099664402512")),
]
WITNESS=(Q("0.76130868178555600"),Q("0.54078968834512231"))
assert len(LIGHTS)==21 and len(set(LIGHTS))==21
Point=tuple[Q,Q];Box=tuple[Q,Q,Q,Q]
def square_interval(lo,hi):
 return (ZERO if lo<=0<=hi else min(lo*lo,hi*hi),max(lo*lo,hi*hi))
def mulint(a,b,c,d):
 v=(a*c,a*d,b*c,b*d);return min(v),max(v)
def divpos(a,b,c,d):
 assert a<=b and ZERO<c<=d;v=(a/c,a/d,b/c,b/d);return min(v),max(v)
def potential_gradient(p):
 x,y=p;v=gx=gy=ZERO
 for sx,sy in LIGHTS:
  dx=x-sx;dy=y-sy;r2=dx*dx+dy*dy
  if r2==0:raise ValueError('infinite')
  v+=ONE/r2;gx+=-2*dx/(r2*r2);gy+=-2*dy/(r2*r2)
 return v,gx,gy
def direct(box):
 x0,x1,y0,y1=box;t=ZERO
 for sx,sy in LIGHTS:
  _,xx=square_interval(x0-sx,x1-sx);_,yy=square_interval(y0-sy,y1-sy);t+=ONE/(xx+yy)
 return t
def hessints(box):
 x0,x1,y0,y1=box;hxx=(ZERO,ZERO);hyy=(ZERO,ZERO);hxy=(ZERO,ZERO)
 for sx,sy in LIGHTS:
  dx0,dx1=x0-sx,x1-sx;dy0,dy1=y0-sy,y1-sy
  xlo,xhi=square_interval(dx0,dx1);ylo,yhi=square_interval(dy0,dy1);rlo=xlo+ylo;rhi=xhi+yhi
  if rlo==0:return None
  r6lo=rlo**3;r6hi=rhi**3
  nxx=(6*xlo-2*yhi,6*xhi-2*ylo);nyy=(6*ylo-2*xhi,6*yhi-2*xlo);xy=mulint(dx0,dx1,dy0,dy1);nxy=(8*xy[0],8*xy[1])
  ix=divpos(*nxx,r6lo,r6hi);iy=divpos(*nyy,r6lo,r6hi);iz=divpos(*nxy,r6lo,r6hi)
  hxx=(hxx[0]+ix[0],hxx[1]+ix[1]);hyy=(hyy[0]+iy[0],hyy[1]+iy[1]);hxy=(hxy[0]+iz[0],hxy[1]+iz[1])
 return hxx,hyy,hxy
def taylor(box):
 x0,x1,y0,y1=box;mx=(x0+x1)/2;my=(y0+y1)/2;hx=(x1-x0)/2;hy=(y1-y0)/2;ints=hessints(box)
 if ints is None:return None
 v,gx,gy=potential_gradient((mx,my));hxx,hyy,hxy=ints
 rem=(min(ZERO,hxx[0])*hx*hx+min(ZERO,hyy[0])*hy*hy)/2-max(abs(hxy[0]),abs(hxy[1]))*hx*hy
 return v-abs(gx)*hx-abs(gy)*hy+rem
def box_lower_bound(box):
 d=direct(box);t=taylor(box);return d if t is None else max(d,t)
class Result(NamedTuple):
 certified:bool;splits:int;leaves:int;maximum_depth:int;minimum_leaf_lower_bound:Q|None;failed_lower_bound:Q|None;failed_box:Box|None
def certify(target=TARGET,max_splits=4000000):
 root=(ZERO,ONE,ZERO,ONE);heap=[];serial=0;heappush(heap,(box_lower_bound(root),0,serial,root));serial+=1
 splits=leaves=maxdepth=0;minleaf=None
 while heap:
  lb,depth,_,box=heappop(heap)
  if lb>=target:
   leaves+=1;maxdepth=max(maxdepth,depth);minleaf=lb if minleaf is None else min(minleaf,lb);continue
  if splits>=max_splits:return Result(False,splits,leaves,maxdepth,minleaf,lb,box)
  x0,x1,y0,y1=box
  if x1-x0>=y1-y0:
   m=(x0+x1)/2;children=((x0,m,y0,y1),(m,x1,y0,y1))
  else:
   m=(y0+y1)/2;children=((x0,x1,y0,m),(x0,x1,m,y1))
  for c in children:heappush(heap,(box_lower_bound(c),depth+1,serial,c));serial+=1
  splits+=1
 return Result(True,splits,leaves,maxdepth,minleaf,None,None)
def dec(q,prec=70):getcontext().prec=prec;return str(Decimal(q.numerator)/Decimal(q.denominator))
def main():
 r=certify();upper=potential_gradient(WITNESS)[0]
 print('status:','CERTIFIED' if r.certified else 'NOT_CERTIFIED');print('method: componentwise_hessian_intervals_full_unit_square');print('target_exact:',TARGET);print('target_decimal:',dec(TARGET));print('splits:',r.splits);print('leaf_count:',r.leaves);print('maximum_depth:',r.maximum_depth)
 if r.minimum_leaf_lower_bound is not None:print('minimum_leaf_lower_bound_decimal:',dec(r.minimum_leaf_lower_bound))
 print('witness_point:',dec(WITNESS[0],30),dec(WITNESS[1],30));print('witness_upper_bound_decimal:',dec(upper));print('rigorous_interval_for_true_minimum:');print('  lower:',dec(TARGET));print('  upper:',dec(upper))
 assert r.certified and r.minimum_leaf_lower_bound is not None and r.minimum_leaf_lower_bound>=TARGET and upper>=TARGET
if __name__=='__main__':main()
