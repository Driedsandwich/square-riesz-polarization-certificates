#!/usr/bin/env python3
"""Exact full-square spectral-Hessian certificate for n=21."""
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
def min_sq_1d(s,lo,hi):
 if s<lo:return (lo-s)**2
 if s>hi:return (s-hi)**2
 return ZERO
def max_sq_1d(s,lo,hi):return max((lo-s)**2,(hi-s)**2)
def potential_at(p):
 x,y=p;t=ZERO
 for sx,sy in LIGHTS:
  r2=(x-sx)**2+(y-sy)**2
  if r2==0:raise ValueError('infinite potential at source')
  t+=ONE/r2
 return t
def box_lower_bound(box):
 x0,x1,y0,y1=box;mx,my=(x0+x1)/2,(y0+y1)/2;hx,hy=(x1-x0)/2,(y1-y0)/2
 direct=ZERO;inside=False;val=gx=gy=curv=ZERO
 for sx,sy in LIGHTS:
  maxd2=max_sq_1d(sx,x0,x1)+max_sq_1d(sy,y0,y1);direct+=ONE/maxd2
  mind2=min_sq_1d(sx,x0,x1)+min_sq_1d(sy,y0,y1)
  if mind2==0:inside=True
  dx,dy=mx-sx,my-sy;r2=dx*dx+dy*dy
  if r2!=0:
   val+=ONE/r2;gx+=-2*dx/(r2*r2);gy+=-2*dy/(r2*r2)
  if mind2!=0:curv+=ONE/(mind2*mind2)
 if inside:return direct
 taylor=val-abs(gx)*hx-abs(gy)*hy-curv*(hx*hx+hy*hy)
 return max(direct,taylor)
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
 r=certify();upper=potential_at(WITNESS)
 print('status:','CERTIFIED' if r.certified else 'NOT_CERTIFIED');print('method: spectral_hessian_full_unit_square');print('target_exact:',TARGET);print('target_decimal:',dec(TARGET));print('splits:',r.splits);print('leaf_count:',r.leaves);print('maximum_depth:',r.maximum_depth)
 if r.minimum_leaf_lower_bound is not None:print('minimum_leaf_lower_bound_decimal:',dec(r.minimum_leaf_lower_bound))
 print('witness_point:',dec(WITNESS[0],30),dec(WITNESS[1],30));print('witness_upper_bound_decimal:',dec(upper));print('rigorous_interval_for_true_minimum:');print('  lower:',dec(TARGET));print('  upper:',dec(upper))
 assert r.certified and r.minimum_leaf_lower_bound is not None and r.minimum_leaf_lower_bound>=TARGET and upper>=TARGET
if __name__=='__main__':main()
