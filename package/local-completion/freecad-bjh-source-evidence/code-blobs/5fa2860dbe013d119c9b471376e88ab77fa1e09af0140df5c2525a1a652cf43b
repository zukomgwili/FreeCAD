# FreeCAD-bjh: independent branching-network controls

This is a pre-solve declaration for the first bounded V5 slice. Its geometry,
loads, spring stiffness and budgets are fixed before a qualifying native run.
They are derived from ordinary free bodies, not solver output or a fitted beam
displacement. The coordinating agent owns all native execution. Oomakhi and
its engineering acceptance limits remain outside this software specimen.

## Public interfaces and native meaning

The specimen uses ordinary Part lines/compound geometry, FemMesh Seg3 edges,
material/rectangular-section objects, Force and Displacement constraints, an
Elastic Connector, the stock CalculiX writer, bundled solver, ordinary result
import and `BeamSectionForceResult.getSectionForces`. Mesh groups are authored
from the real CAD edges/vertices and constructed connectivity. No Gmsh run,
input-deck edit, explicit beam-node RBE or force/stress recovery is involved.

A shared original beam node is a native stiff joint, not an inferred hinge.
The non-collinear fork invokes native knot equations. Native section forces
remain those calculated before nodal averaging; native physical support and
scalar-spring observations are separate from section quadrature.

The source investigation uses the [official CalculiX 2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2),
SHA-256 `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7`.
`linstatic.c:810–836` evaluates results with the preceding `vold`, then copies
the solved displacement into it. `map3dto1d2d.f:328–335` uses `co + vold` and
its expanded-corner average. Thus this first, cold, linear, zero-initial-state
one-step specimen checks reference section centroids. This does not claim
that arbitrary later/increment mapper geometry is a final displaced position.
The general output labels remain `NATIVE_MAP_EXPANDED_SECTION`,
`NATIVE_MAP_FACE_BASIS`, `CO_PLUS_NATIVE_MAP_VOLD_ARGUMENT` and
`moment_reference = NATIVE_SECTION_CENTROID`.

## Frozen first specimen

All coordinates are mm, forces N, moments N·mm. The original points are:

| Point | Original node | Position |
| --- | ---: | --- |
| A, root | 1 | (0, 17, −23) |
| J, stiff fork | 11 | (100, 17, −23) |
| B, upper tip | 15 | (100, 57, −23) |
| C, lower tip | 19 | (100, −23, −23) |

The stem has five quadratic 20 mm elements, with original nodes at 10 mm
spacing. Each 40 mm arm has two quadratic 20 mm elements. There are exactly
19 original nodes and nine genuine B32R elements, with no faces or volumes.
The fork end identities are (element5,node11,end3), (6,11,1), (8,11,1).

All three members use one explicit rectangular 4×8 mm section and one linear
elastic material, E = 200000 MPa and ν = 0. Density is saved but no gravity is
applied. The native written section reference `n1` is (0,1,0) on the stem,
(−1,0,0) on the upper arm and (1,0,0) on the lower arm. Actual mapped axes
remain literal native observations, including the first-end left-handed basis.

At A, one genuine ground SPRING1 has global direction X and k = 10000 N/mm.
The physical guide fixes UY, UZ and all three rotations to zero; UX is free.
The guide is a declared real restraint, not an added equation to hide a rank
deficiency. A scalar spring alone would not stabilize the other five modes.
The two independent public Force objects apply:

| Source | Node | Force | Original-global origin moment |
| --- | ---: | --- | --- |
| Upper | 15 | (1, 0, 0.01) | (0.57, −24, −57) |
| Lower | 19 | (4, 0, −0.02) | (0.46, −90, 92) |
| Sum | — | (5, 0, −0.01) | (1.03, −114, 35) |

Their force magnitudes are assigned with explicit N units, and the physical
direction lines encode the normalized vectors above. Bare internal numbers
are not substituted for N-valued Force or N/mm-valued stiffness quantities.

## Independent support and port statics

At J, rJB × PB + rJC × PC = (1.2,0,120). Transporting the total force from J
to A adds (0,1,0), so the physical root couple is (−1.2,−1,−120).
The scalar spring carries the root X action; it does not carry a couple.

| Observation, action on the beam | Force | Origin moment |
| --- | --- | --- |
| Ground spring's one actual beam end A | (−5,0,0) | (0,115,85) |
| Physical guide at A | (0,0,0.01) | (−1.03,−1,−120) |
| Total physical support | (−5,0,0.01) | (−1.03,114,−35) |

The guide origin moment includes A × (0,0,0.01) = (0.17,0,0) plus its actual
couple. All source plus physical support forces and original-origin moments
sum to zero. Generated U/R equation values are algebraic and must not be
counted again as physical supports. Their identities still need native
authentication; absence from a physical sum is not permission to ignore an
unknown native boundary row.

The native spring resisting force on its actual beam end is (5,0,0), opposite
the spring action on the model. Its displacement is UX = 5/10000 = 0.0005 mm.
Ground SPRING1 has one actual structural end; no imaginary ground node or
invented second measured end is part of the observation.

No ideal PL/EA or elementary cantilever tip displacement is accepted here.
The existing native beam point-load/corner-mean semantics are retained.

## Independent signed section-end controls

At each member's first end, the action balances its prescribed downstream
loads; at the last end it acts on the preceding member segment. These are
centroid-relative moments. Every original element/end identity is tested.

For a stem cut at original x, the first-end action is:

* F = (−5,0,0.01);
* M = (−1.2, −0.01(100−x), −120).

The last-end action at its own x has the opposite signs. For an upper-arm
cut a remaining distance d from B, first-end F = (−1,0,−0.01) and
M = (−0.01d,0,d); its last-end action has opposite signs at its own d.
For the lower arm a remaining distance d from C, first-end
F = (−4,0,0.02), M = (−0.02d,0,−4d), with the opposite last-end signs.

At J these give:

| Member end | Force | Centroid-relative moment |
| --- | --- | --- |
| Stem last | (5,0,−0.01) | (1.2,0,120) |
| Upper first | (−1,0,−0.01) | (−0.4,0,40) |
| Lower first | (−4,0,0.02) | (−0.8,0,−160) |

Both force and moment sums vanish. Distinct member ends at the same original
node must remain distinct; grouping by coordinates or nodal averaging would
destroy that control.

For each end, transport M + c × F to the original global origin and compare
with the independently prescribed downstream free body. This coordinate
transport does not recover a force from displacement or stress. The first-step
centroid c is separately checked against its original endpoint coordinate.

## Predeclared numerical budgets

Physical source, spring and support actions use componentwise 1e−5 N and
1e−3 N·mm budgets, including their global sum. Spring UX has a 1e−8 mm budget.
These direct native action observations are distinct from section-field
quadrature, whose following budgets deliberately preserve the small Z demand:

| Quantity | X | Y | Z |
| --- | ---: | ---: | ---: |
| Every section-end force, N | 0.005 | 0.00001 | 0.0001 |
| Stem section moment, N·mm | 0.012 | 0.01 | 1.2 |
| Upper-arm section moment, N·mm | 0.004 | 0.001 | 0.4 |
| Lower-arm section moment, N·mm | 0.008 | 0.001 | 1.6 |

Moment budgets are 1% of the independently imposed component demand scales
on each member, with a 0.1 N·mm fixed scale for an undriven component. A tip's
zero moment therefore does not create a relative division by zero. The force
budgets are fixed absolute component controls, not the norm of a dominant X
force that could conceal the much smaller transverse force.

For transported component i, the fixed error budget is the local moment
budget plus |cj| times the force budget k plus |ck| times the force budget j.
Positions use 1e−8 mm and native basis norms/handedness use 1e−8. These are
software benchmark budgets, not universal solver accuracy or Oomakhi's house
acceptance limits. A failed criterion must remain recorded; none may be
relaxed using observed error.

## Scope and persistence

The first tracer requires a real V5 Current owned completion, two source
owners, one actual ground-spring end, one physical guide and separate member
ends. It must not skip because a default solver lacks V5. Input bytes are
captured before execution and checked unchanged afterward. Beam S channels
remain N/N·mm resultants and must not appear as MPa in the ordinary result.

Later slices may qualify a second genuine T joined by one native two-point
SPRING2, two material/section groups, refusal controls and actual save/cold
history. They are not established by this pre-run document or first tracer.
General released joints, beam-node RBE, contact, nonlinear frames, arbitrary
multiple materials per beam component, and project design acceptance remain
unqualified until separately evidenced.
