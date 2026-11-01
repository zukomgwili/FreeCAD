# FreeCAD-bjh: connected-branches pre-solve oracle

This declaration freezes the second native vertical slice before its first
solve. It changes no first-slice fixture, mathematical oracle or tolerance.
The first declaration remains `freecad-bjh-oracles.md`, SHA-256
`5fa2860dbe013d119c9b471376e88ab77fa1e09af0140df5c2525a1a652cf43b`.

The independent private derivation was retained before either two-T fixture
or response existed, SHA-256
`e69c0393d9e5af9a42fba4f13e74187b5a54aba4a8a3a310cb45a33baba57895`.
The chosen topology, source vectors, section/material values, k2 and budgets
below are exactly that predeclared derivation. The implementation uses public
native CAD, FemMesh, constraint, stock writer, bundled solver, import and
result getter interfaces; executed decks are never edited.

All original coordinates are mm, forces N and moments N·mm:

| Point | Original node | Position |
| --- | ---: | --- |
| Left root A | 1 | (0,17,−23) |
| Left fork J | 11 | (100,17,−23) |
| Left upper B | 15 | (100,57,−23) |
| Left lower C | 19 | (100,−23,−23) |
| Right root R | 20 | (110,57,−23) |
| Right fork K | 30 | (210,57,−23) |
| Right upper D | 34 | (210,97,−23) |
| Right lower E | 38 | (210,17,−23) |

Each T has five quadratic 20 mm stem elements and two such elements in each
40 mm arm. The second T repeats the first connectivity with node offset19
and element offset9. There are 38 genuine original beam nodes, 18 B32R
elements, two distinct native knots and no shell/volume elements.

The left T retains E200000MPa, ν0 and RECT4×8mm. Right values are
E100000MPa, ν0 and RECT6×6mm. All six actual members are loaded; changing
these positive elastic stiffnesses changes deflection but not the following
statically determinate force/moment balances. Each T uses its own real
material/section references, constant over its own three CAD edges.

Ground SPRING1 S1 acts in X at A with k1=10000N/mm. Internal SPRING2 S2 acts
in global X between B (end1) and R (end2), with k2=2500N/mm. Its
10mm original gap is along X. Native SPRING2 acts on relative displacement,
not an invented initial axial strain. At both A and R, UY/UZ and all three
rotations are prescribed zero; UX is free. R has no second ground spring.
No original beam node belongs to an explicit RigidBody receiving region.

These five-mode guides are physical declared restraints needed because a
scalar X link alone does not stabilize the other five rigid-body modes.
Both elastic connections carry nonzero force. The combined beam/spring
graph is connected and acyclic although the beam-only graph has two T
components; no redundant unloaded port or padding member is introduced.

## Exact sources

| Source | Force | Origin moment r×P |
| --- | --- | --- |
| B | (1,0,0.01) | (0.57,−24,−57) |
| C | (4,0,−0.02) | (0.46,−90,92) |
| D | (1,0,0.03) | (2.91,−29.3,−97) |
| E | (2,0,−0.01) | (−0.17,−43.9,−34) |
| Sum | (8,0,0.01) | (3.77,−187.2,−96) |

Right-body X equilibrium gives S2 action on R = (−3,0,0), hence S2 action on
B = (3,0,0). Left-body X equilibrium then gives S1 action on A = (−8,0,0).
Each of these follows a separate physical free body, not spring-force
recovery from a solved displacement.

## Physical supports and actual port ends

| Native observation, action on its beam body | Force | Origin moment |
| --- | --- | --- |
| S1 actual end at A | (−8,0,0) | (0,184,136) |
| S2 actual end1 at B | (3,0,0) | (0,−69,−171) |
| S2 actual end2 at R | (−3,0,0) | (0,69,171) |
| A physical guide | (0,0,0.01) | (−1.03,−1,0) |
| R physical guide | (0,0,−0.02) | (−2.74,4.2,−40) |

At J, the upper effective load is PB+S2B=(4,0,0.01), and the lower load is
PC=(4,0,−0.02). Their J-relative couple is (1.2,0,0). Therefore A's physical
guide couple is (−1.2,−1,0). Its origin moment includes A×(0,0,0.01).

At K, PD+PE=(3,0,0.02) and their K-relative couple is (1.6,0,40). Therefore
R's guide couple is (−1.6,2,−40), plus R×(0,0,−0.02) for its origin moment.

The two S2 origin moments sum exactly to zero because (B−R)×(3,0,0)=0.
The external physical supports S1+Aguide+Rguide sum to F=(−8,0,−0.01),
Morigin=(−3.77,187.2,96), opposite the four source totals above. S2 is internal
and must not be counted again as an external ground support.

Left-body source-plus-port origin moment is (1.03,−183,−136), balanced by
S1+Aguide=(−1.03,183,136). Right-source origin moment is
(2.74,−73.2,−131), balanced by S2R+Rguide=(−2.74,73.2,131).

S1 native resisting force is (8,0,0), opposite its action on the model.
S2 native resisting forces are (−3,0,0) at B and (3,0,0) at R. Its actual
displacement relation is uR−uB=3/k2=0.0012mm. The ground relation is
uA=8/k1=0.0008mm. The unknown beam flexural displacement at B is not fitted
or replaced by an elementary beam formula. No imaginary ground second end
is claimed for SPRING1.

## Original-reference section cuts

For each row below, these are the first-end actions; the last-end action
has opposite signs at its own coordinate. d is the remaining positive arm
distance from the cut to its tip. Each member's transported first-end
origin moment is constant along that member.

| Member | First-end force | First-end local moment | First-end origin moment |
| --- | --- | --- | --- |
| Left stem at x | (−8,0,0.01) | (−1.2,−0.01(100−x),0) | (−1.03,183,136) |
| Left upper | (−4,0,−0.01) | (−0.01d,0,4d) | (−0.57,93,228) |
| Left lower | (−4,0,0.02) | (−0.02d,0,−4d) | (−0.46,90,−92) |
| Right stem at x | (−3,0,−0.02) | (−1.6,0.02(210−x),−40) | (−2.74,73.2,131) |
| Right upper | (−1,0,−0.03) | (−0.03d,0,d) | (−2.91,29.3,97) |
| Right lower | (−2,0,0.01) | (−0.01d,0,−2d) | (0.17,43.9,34) |

At J, left stem last moment (1.2,0,0), upper first (−0.4,0,160) and lower
first (−0.8,0,−160) sum to zero. Their forces also sum to zero.
At K, right stem last moment (1.6,0,40), upper first (−1.2,0,40) and lower
first (−0.4,0,−80) sum to zero. Again their forces sum to zero.

The original node11 and node30 end triplets remain independent identities:
left {(5,11,3),(6,11,1),(8,11,1)} and
right {(14,30,3),(15,30,1),(17,30,1)}. They cannot be collapsed by nodal
averaging, coordinates or the fact that the two materials differ.

## Frozen second-slice budgets, before any second-case response

Retain the first-slice native action budgets (1e−5N,1e−3Nmm), native end-force
component budgets (0.005,0.00001,0.0001)N, centroid1e−8mm and axis1e−8.
Spring displacement controls use1e−8mm. Moment component budgets follow the
same first-slice 1% of independent member component demand, with 0.1Nmm scale
for an undriven component:

| Member | Mx budget | My budget | Mz budget |
| --- | ---: | ---: | ---: |
| Left stem | 0.012 | 0.01 | 0.001 |
| Left upper | 0.004 | 0.001 | 1.6 |
| Left lower | 0.008 | 0.001 | 1.6 |
| Right stem | 0.016 | 0.02 | 0.4 |
| Right upper | 0.012 | 0.001 | 0.4 |
| Right lower | 0.004 | 0.001 | 0.8 |

Origin moment budgets propagate those fixed force/moment bounds by the
known original coordinates, as in the frozen first-slice declaration.
No budget is chosen from an observed native response. Native field failures
must remain recorded and distinguished from native action/case/identity
failures; no engineering or Oomakhi acceptance follows from this specimen.

## Identity and interpretation controls

All 36 signed original beam-end samples must occur exactly once, keyed by
(element,node,end). Neither real scalar spring element produces a beam
section sample. Each sample joins its element to the completed native
provenance catalogue; section/material/member ownership is not invented as
an extra repeated native sample field. Elements1–9 belong to the left
material/section and three actual left compound edges; elements10–18 belong
to the distinct right material/section and three actual right compound edges.
Their section axes retain the first fixture's stem/upper/lower reference
directions and literal observed native face basis.

The two real root guides each expose their actual two translation and three
physical-angle observations separately from three generated U algebraic
rows. Authenticated generated knot R rows remain raw algebraic observations
and never add a second physical force or moment. There is no fixed guessed
knot receiving-node count or geometric rank. The SPRING1 has only its one
actual structural endpoint; SPRING2 has end1 atB and end2 atR. Both native
resisting forces are observed literally and the action-on-model sign is
checked independently. The internal pair is checked separately, the two
physical bodies are checked separately, and the external global sum excludes
the internal pair.

The first cold linear-static map uses its native pre-update vOld argument.
The original reference coordinates are checked against the observed section
centroids for this case. This does not reinterpret map geometry as final
displacement in arbitrary later frames. Forces and moments are N and Nmm;
beam section channels must not appear as MPa stress aliases in the ordinary
mechanical result. The owned result remains Current after a native save.
