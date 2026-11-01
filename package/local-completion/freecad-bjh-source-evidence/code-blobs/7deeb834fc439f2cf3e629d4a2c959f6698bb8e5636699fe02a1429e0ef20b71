# FreeCAD-bjh: predeclared native component and inactive-mechanics controls

This declaration precedes the first qualifying numerical V5 solve. It is
supporting evidence only. It cannot replace or weaken any failed frozen
member-end, physical-action, ownership, case or origin-moment criterion.

## Independently prescribed pure native T

Author an otherwise identical ordinary native T in a separate document:

* same A/J/B/C original coordinates, 19 nodes and nine B32R elements;
* same uniform RECT4×8mm, E200000MPa, ν0 and native section reference axes;
* same two public Force sources PB=(1,0,0.01)N and PC=(4,0,−0.02)N;
* same five original root guide prescriptions, all exactly zero;
* remove the actual root ElasticConnector object;
* change the existing root Displacement constraint to prescribe UX=0.0005mm
  and leave no root translation free.

The prescribed UX is independently 5N/(10000N/mm), from the external X free
body and declared spring stiffness. Neither a solved root nor a solved tip
displacement is used to set it. There is no ideal PL/EA or elementary beam
tip target. Use the stock writer, the same native candidate executable,
ordinary V1 section output, result import and unchanged executed deck bytes.

Primary native source supports the same kinematic comparison even with
nonzero bending/torsion: `gen3dconnect.f:159–216` connects the spring-attached
non-knot original root translation to its four expanded corners by their
sum minus four times the original-root displacement. In the no-spring case,
`gen3dboun.f:1175–1230` creates the same corner-mean translation equation for
an original-node Dirichlet value. The rotational guide/mean-rotation and
midside fixing are retained. This establishes the mean-translation seam;
it does not claim uniform section traction or a perfectly rigid end face.

V1 and V5 results have separate owned cases/requests. Compare exact original
node and (element,node,end) identity sets, not row order or document names.
Retain each format's literal native geometry labels rather than relabelling
one case's provenance as the other. Both must have one final physical
(step1,increment1,time1) frame and matching section/material/source settings.

## Budgets fixed before comparison

Native FRD displacement comparison uses a fixed mechanical equivalence
budget of 1e−7mm per component plus the reporting bounds for both emitted
numbers. The reporting bound for finite nonzero value v is

    r(v) = 0.5 × 10^(floor(log10(|v|)) − 5) + |v| × 2^(−24).

For zero, r(0)=0. The first term is the half last decimal place of the
native E12.5 (six significant digit) field; the second conservatively
accounts for its single-precision cast. The pinned native `frdvector.c:47–49`
and `71–73` explicitly print the three cast displacement components that way.
Thus require

    |uV5 − uV1| ≤ 1e−7mm + r(uV5) + r(uV1).

This is a declared wire-format precision bound, not a fit to an observed
displacement error. The independently accepted V5 spring-root relation
still has its separate stricter 1e−8mm budget.

For matching literal JSON native member-end observations, require per
component differences ≤1e−6N in global force and ≤1e−4Nmm in global moment.
Native raw section channels use the corresponding force or moment budget.
Centroid and basis component comparisons use1e−8mm and1e−8, respectively.
These compare the same native component under the same mean kinematics;
the independent analytic statics budgets remain as frozen separately.

All observed differences and both exact source/FRD/output hashes must be
retained. Any failed control remains nonqualifying; source/authoring/native
semantics must be investigated before changing a claim. A failed result
cannot set a replacement boundary value or a larger fitted tolerance.

## Ordinary mechanics preservation on byte-identical native input

Separately retain one real stock-written V5 input deck byte-for-byte and
run it in isolated directories with:

1. the candidate with owned native V5 diagnostics;
2. the same candidate with all diagnostic activation variables absent;
3. the previous `f494702b78138099d4e526862113e382e0ce863d5aa2ad023e7c15f7c7928925`
   native binary with all diagnostic activation variables absent.

The V5 diagnostic request does not edit mechanical keyword content. Each
run's executed input bytes must equal the original stock export. Match
ordinary execution controls/thread counts. Compare the complete literal
native FRD mesh and field lines exactly, excluding only nonphysical date,
wall-clock time and compiler-build-time headers (`1UDATE`, `1UTIME`,
`1UCOMPILETIME`). Do not compare NaN-containing generic-reader dictionaries
or permit numeric field tolerances in this exact preservation control.
Retain each executable/deck/FRD hash and native exit status independently.

No original project is opened, changed or solved by either supporting
control. Success establishes this specimen's component/mechanics
equivalence, not a universal beam theory, connection law or house acceptance.
