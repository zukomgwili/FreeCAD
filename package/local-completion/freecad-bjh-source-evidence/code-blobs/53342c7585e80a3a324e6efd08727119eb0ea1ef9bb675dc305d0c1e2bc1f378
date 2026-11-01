# FreeCAD-bjh: three-component scalar fork pre-solve oracle

This optional third slice is declared before its first native execution.
It adds a second real SPRING2 child at the parent's other arm, so the
component connection graph branches instead of remaining a scalar chain.
The earlier one-T and two-T factories, inputs, budgets and acceptance
declarations remain unchanged. The solver mechanics and observer source
remain frozen at C07f/patch1f2 while this fixture is authored. This document
qualifies no result until the coordinator runs the frozen native test.

## Geometry, real ownership and stabilization

Each T repeats the original 19-node, nine-element B32R mesh: five 20 mm
quadratic stem elements and two 20 mm elements in each 40 mm arm. Parent
and first child are exactly the existing connected fixture. The new third
T is the parent mesh translated by (220,-40,0) mm. It uses node offset38
and element offset18, producing 57 original nodes and 27 B32R elements.

| Original identity | Node | Coordinate, mm |
| --- | ---: | --- |
| Parent root A | 1 | (0,17,-23) |
| Parent fork J | 11 | (100,17,-23) |
| Parent upper B | 15 | (100,57,-23) |
| Parent lower C | 19 | (100,-23,-23) |
| First child root R1 | 20 | (110,57,-23) |
| First child fork K1 | 30 | (210,57,-23) |
| First child upper D | 34 | (210,97,-23) |
| First child lower E | 38 | (210,17,-23) |
| Second child root R2 | 39 | (220,-23,-23) |
| Second child fork K2 | 49 | (320,-23,-23) |
| Second child upper H | 53 | (320,17,-23) |
| Second child lower I | 57 | (320,-63,-23) |

The parent retains its actual E200000MPa, nu0, RECT4x8mm material/section.
Both children use the actual E100000MPa, nu0, RECT6x6mm material/section,
with its real reference list extended to all six child CAD edges. There
are two real material objects, two real section objects and three genuine
beam components; the second child does not claim invented duplicate owners.
All nine CAD edges carry nonzero beam forces. Mesh groups map each edge
and actual external vertex truthfully to the public CAD compound.

S1 is the existing ground X SPRING1 at A, k1=10000N/mm. S2 is the existing
X SPRING2 B(end1) to R1(end2), k2=2500N/mm. S3 is a new X SPRING2 C(end1)
to R2(end2), k3=5000N/mm. The original gaps are 10mm and 120mm along X;
native scalar SPRING2 uses relative displacement, with no invented initial
axial strain. At A, R1 and R2, UY/UZ and all three rotations are physically
prescribed zero while UX remains free. These are three real external
five-mode guides, not internal joint modes or automatic-knot reactions.
The component graph has one ground and two child edges; it is connected
and acyclic. No beam node enters an explicit RigidBody receiving set.

## Independent source and port free bodies

Forces are N; moments are Nmm about the global origin.

| Source | Force | Origin moment r cross P |
| --- | --- | --- |
| B | (1,0,.01) | (.57,-24,-57) |
| C | (4,0,-.02) | (.46,-90,92) |
| D | (1,0,.03) | (2.91,-29.3,-97) |
| E | (2,0,-.01) | (-.17,-43.9,-34) |
| H | (2,0,.02) | (.34,-52.4,-34) |
| I | (3,0,-.01) | (.63,-65.8,189) |
| Sum | (13,0,.02) | (4.74,-305.4,59) |

First-child X equilibrium requires action -3X at R1 and +3X at B.
Second-child X equilibrium independently requires -5X at R2 and +5X at C.
Parent X equilibrium then requires ground action -13X at A. Thus every
connection carries nonzero action; neither child is an unloaded padding
component. These values come from separate physical bodies, not observed
deflections, stress recovery or fitted beam formulas.

| Actual spring end, action on its beam | Force | Origin moment |
| --- | --- | --- |
| S1 end1 at A | (-13,0,0) | (0,299,221) |
| S2 end1 at B | (3,0,0) | (0,-69,-171) |
| S2 end2 at R1 | (-3,0,0) | (0,69,171) |
| S3 end1 at C | (5,0,0) | (0,-115,115) |
| S3 end2 at R2 | (-5,0,0) | (0,115,-115) |

Literal native resisting forces are the opposites of those applied actions.
Each internal pair has zero total force and origin moment because its two
physical positions lie on the action axis. Ground SPRING1 has only its
single actual beam endpoint; no second imaginary ground endpoint appears.

| Physical guide | Force | Physical angle couple | Origin moment including r cross F |
| --- | --- | --- | --- |
| A | (0,0,.01) | (-1.2,-1,-200) | (-1.03,-1,-200) |
| R1 | (0,0,-.02) | (-1.6,2,-40) | (-2.74,4.2,-40) |
| R2 | (0,0,-.01) | (-1.2,1,-40) | (-.97,3.2,-40) |

At J, the effective upper/lower tip forces are (4,0,.01) and (9,0,-.02).
Their fork-relative couple is (1.2,0,200). At K1 the unchanged first-child
couple is (1.6,0,40). At K2 the new child's tip couple is (1.2,0,40).
The 100mm stem transports each force sum to its actual root, giving the
three guide couples above. No algebraic U or automatic-knot R value is
added to these physical couples.

S1 plus all three physical guides totals F=(-13,0,-.02) and
Morigin=(-4.74,305.4,-59), opposite the six sources. S2/S3 are internal and
are excluded from the external support total. Each of the three beam-body
free bodies is also checked separately with its own actual spring ends.

Independent port displacement controls are uA=13/10000=.0013mm,
uR1-uB=3/2500=.0012mm and uR2-uC=5/5000=.001mm. The unknown bending
displacements at B and C are not replaced by ideal beam-tip formulas.

## All original element/end cuts

The table gives first-end force and centroid-relative moment at an original
cut. The last end has opposite action evaluated at its own cut coordinate.
d is remaining positive arm distance to its tip. Each first-end origin
moment below is constant over its member and is independent of a solved
native force or displacement.

| Member | First-end force | First-end moment | First-end origin moment |
| --- | --- | --- | --- |
| Parent stem at x | (-13,0,.01) | (-1.2,-.01(100-x),-200) | (-1.03,298,21) |
| Parent upper | (-4,0,-.01) | (-.01d,0,4d) | (-.57,93,228) |
| Parent lower | (-9,0,.02) | (-.02d,0,-9d) | (-.46,205,-207) |
| First child stem at x | (-3,0,-.02) | (-1.6,.02(210-x),-40) | (-2.74,73.2,131) |
| First child upper | (-1,0,-.03) | (-.03d,0,d) | (-2.91,29.3,97) |
| First child lower | (-2,0,.01) | (-.01d,0,-2d) | (.17,43.9,34) |
| Second child stem at x | (-5,0,-.01) | (-1.2,.01(320-x),-40) | (-.97,118.2,-155) |
| Second child upper | (-2,0,-.02) | (-.02d,0,2d) | (-.34,52.4,34) |
| Second child lower | (-3,0,.01) | (-.01d,0,-3d) | (-.63,65.8,-189) |

The nine native fork ends remain independent identities:
J={(5,11,3),(6,11,1),(8,11,1)},
K1={(14,30,3),(15,30,1),(17,30,1)}, and
K2={(23,49,3),(24,49,1),(26,49,1)}.
There are 54 distinct signed (element,node,end) beam samples; no spring
element is a beam-section sample. Native element metadata joins each sample
to its real CAD edge, section and material owner; these fields are not
invented as repeated native sample properties.

## Fixed third-slice budgets and identity controls

Retain native action budgets 1e-5N and 1e-3Nmm, end-force component budgets
(.005,.00001,.0001)N, original-centroid budget1e-8mm, axis norm/dot/handedness
budget1e-8 and each scalar displacement budget1e-8mm. Moment budgets are
the same predeclared first/second-slice rule: 1% of each independent member
component demand, with 0.1Nmm scale for an undriven component.

| Member | Mx budget | My budget | Mz budget |
| --- | ---: | ---: | ---: |
| Parent stem | .012 | .01 | 2.0 |
| Parent upper | .004 | .001 | 1.6 |
| Parent lower | .008 | .001 | 3.6 |
| First child stem | .016 | .02 | .4 |
| First child upper | .012 | .001 | .4 |
| First child lower | .004 | .001 | .8 |
| Second child stem | .012 | .01 | .4 |
| Second child upper | .008 | .001 | .8 |
| Second child lower | .004 | .001 | 1.2 |

Origin-moment budgets propagate these fixed component bounds using the
known original cut position: deltaM_i + abs(r_j)deltaF_k +
abs(r_k)deltaF_j. The first cold linear map's reference centroid is checked;
the general geometry source remains CO_PLUS_NATIVE_MAP_VOLD_ARGUMENT,
not guaranteed final displaced geometry.

Every physical guide must expose two translation rows, three angle rows
and three separately typed U algebraic rows. Each physical angle value
must match its independent couple component. Generated knot R rows are
retained as ALGEBRAIC, with unique actual row identities and the three
distinct original fork references; no receiving-node count or geometric
rank is guessed. Their raw values never enter physical equilibrium sums.
Literal reference axes, actual orthonormal face bases, global action signs,
units, single retained physical frame, stock deck immutability, Current
result/save and absence of MPa stress aliases remain required. A native
failure is retained without fitting loads, mesh, geometry or budgets.
This analytical count/connection composition does not accept Oomakhi or
establish rotational springs, arbitrary releases or full six-mode joints.
