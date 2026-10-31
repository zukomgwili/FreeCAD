# FreeCAD-sv7 independent analytical oracles

This document freezes the first composition benchmark before its native run. It
specifies a software qualification fixture, not an Oomakhi model or a building
acceptance criterion. FreeCAD-960's completed pure-1D domain and limits remain
unchanged. The numerical load/wrench references below apply to the completed
end-time state, not blindly to every earlier incremental frame. Earlier frames
retain their actual native load, time and same-case action identities. Only
the root agent executes FreeCAD, CalculiX, GUI tests and builds.

## First domain: a grounded native scalar spring on a beam endpoint

Use the stock `ElasticConnector` with `Attachment=Vertices`,
`Kind=Translational`, `Mode=Ground`, `Axis=X`, identity orientation, no orientation
reference, `End1` the beam's first CAD vertex, empty `End2`, and no rigid-body
links. Its stock writer emits one `SPRING1` on one existing structural node.
There is no invented pad, RBE, auxiliary point or connector rest-length arm.
This is a distinct endpoint attachment domain; it does not waive the existing
solid RBE region's non-collinearity/rank requirements.

Freeze the following reference-state geometry and inputs:

| Quantity | Value |
| --- | --- |
| Beam start, end | `(10,20,30)`, `(110,20,30)` mm |
| Beam | Straight 100-mm B32R, rectangular 2 by 4 mm |
| Mesh | Five 20-mm quadratic elements, eleven nodes at 10-mm intervals |
| Material | `E=100000 N/mm²`, `nu=0.3`; linear, no density/body loading |
| Spring | `k=2000 N/mm`, global X, grounded at beam start |
| Beam-start displacement | X free; Y/Z and all rotations prescribed zero |
| Applied load | `(+10,0,0) N` at the beam end |
| Analysis | One unsplit, small-displacement, linear static 3D case, end time 1 |
| Outputs | Native six-component beam-end diagnostics plus actual native spring action and applicable physical support accounting |

If the mesh uses the controlled IDs 1 through 11, beam element `i=1..5`
has original CalculiX first/middle/last nodes `(2i-1,2i,2i+1)`. FreeCAD's mesh
connectivity order is different. Bind expectations to the emitted catalogue,
not to a mistaken reinterpretation of that order. The stock spring writer
allocates its element after the last actual mesh element (6 for those IDs).
The CAD endpoint must resolve to exactly one existing native node.

The native writer and solver must first prove that the spring acts on the beam
endpoint's intended translational motion, that the other five constraints are
actually exported, and that the beam expansion retains the intended motion.
The test must refuse an unsupported route rather than silently alter mechanics.

## Independent mechanics and signs

The cross-sectional area is `A=8 mm²`, hence `EA/L=8000 N/mm`.
The spring and beam are in series, so static determinacy fixes their axial
force to 10 N independently of small local beam-compliance effects:

```
spring/root displacement = P/k = 0.005 mm
beam relative extension  = PL/(EA) = 0.00125 mm
tip displacement        = P/k + PL/(EA) = 0.00625 mm
```

Forces below are forces **on the model**, in the original global frame. Moments
are about the global origin unless explicitly identified as centroid-relative.

| Quantity | Force (N) | Moment (N mm) |
| --- | --- | --- |
| Applied source at `(110,20,30)` | `(10,0,0)` | `(0,300,-200)` |
| Ground spring action on structural root node | `(-10,0,0)` | `(0,-300,200)` |
| Other physical beam-root restraints, aggregate | `(0,0,0)` | `(0,0,0)` |
| All external source plus physical support | `(0,0,0)` | `(0,0,0)` |

The equal/opposite force **on the foundation** is `(+10,0,0)` N, with origin
moment `(0,300,-200)` N mm. A native element's *resisting nodal-force* convention
may have that opposite sign. Preserve its literal native convention explicitly
and distinguish it from the ground-on-model reaction; do not name both rows
"reaction". The reported ground action must come from the solver's actual
element force. `-k*u` is the independent oracle, not a production force recovery.
Stock `NODE PRINT RF` is a combined native nodal quantity and is not an isolated
spring action in a connected assembly.

For every beam element, its first end has outward global force `(-10,0,0)` N
and its last end has `(10,0,0)` N. Both centroid-relative end moments are zero.
Projection on each reported outward normal gives positive 10-N tension at both
ends; both shears, both bending channels and torque are zero. Verify using the
literal reported face axes. The first-end basis is not assumed right-handed.
Origin moments for these beam-end forces are respectively `(0,-300,200)` and
`(0,300,-200)` N mm. Axial motion changes only X, so it does not change these
moment arms. Intermediate adjacent ends must cancel with exact owner/end
identity before their common-node reduction is considered.

All six components must be present and finite, with explicit element/end,
original node, position, literal axes, owner, units, case and frame identity.
The nonzero translated origin moments deliberately detect omission of force
transport, which a beam passing through the origin would hide.

## Frozen numerical limits and serialization budget

These are fixture-specific requirements selected before observing its result;
they are not a universal solver accuracy promise. Component/vector norms use
the following absolute budgets, including expected-zero channels:

| Check | Absolute limit | Reason |
| --- | --- | --- |
| Native ground action and source/physical-support force closure | `0.001 N` | 0.01% of the independently fixed 10-N scalar force |
| Their origin-moment closure | `0.1 N mm` | Same force budget transported through the 100-mm characteristic beam length |
| Ground action versus `-k*u_root` | `0.001 N` | Exact single-table linear scalar constitutive reference |
| Each native beam-end global force / its local force channels | `0.01 N` | 0.1% constant-traction patch requirement; separate conservative allowance for native stress extrapolation/integration |
| Each beam-end centroid-relative moment / moment channels | `0.04 N mm` | 0.1% of `P` times the 4-mm section depth, rather than a relative tolerance against zero |
| Scalar root displacement | `0.0000005 mm` | 0.01% of the exact `P/k` reference |

The 1D beam extension and tip displacement are additional response observations.
Do not weaken force or moment limits to accommodate a beam end-compliance
effect. If their exact 1D expressions do not hold to a separately justified
response requirement, retain the discrepancy explicitly rather than claim
compliance qualification from equilibrium alone.

Serialization is not the dominant allowance: `beamsection.c` writes vectors,
channels and time with `%.17g`; `forceaccounting.c` writes native wrench values
with `%.17g`. The stock connector writer writes stiffness with `.12e` and
orientation components with `.13G`; all specified constants/identity axes are
represented exactly for this purpose. Pristine CalculiX 2.23
`printoutnode.f` writes global U/RF with `1p,e13.6`, seven significant digits.
For a nonzero printed value `v`, its rounding bound is
`0.5*10**(floor(log10(abs(v)))-6)`: at 10 N it is `0.000005 N`, and at
0.005 mm it is `0.0000000005 mm`, only `0.000001 N` after multiplication by k.
Those explicit print bounds are already much smaller than the frozen budgets.
No result-driven tolerance changes are permitted.

## Conditional larger combined-load control: not executed or qualified

This larger combined-load proposal remains conditional, unexecuted and
unqualified. Its load and geometry estimates below motivate the separately
scaled companion defined next, before either combined-load case is run. Keep the first fixture's
geometry, mesh, spring, material, zero-five-DOF support, solver settings and
case duration. Change only the single endpoint force to `(10,0.1,0.2)` N.
Use the stock force object's vector direction and total magnitude
`sqrt(100.05)` N; the actual generated three CLOAD components must match that
vector within the documented writer rounding. This is a small-deflection
linear superposition control, not a change to any Oomakhi loading.

| Quantity | Force (N) | Origin moment (N mm) |
| --- | --- | --- |
| Applied source | `(10,0.1,0.2)` | `(1,278,-189)` |
| Ground spring action on model | `(-10,0,0)` | `(0,-300,200)` |
| Other physical root support | `(0,-0.1,-0.2)` | `(-1,22,-11)` |
| External sum | `(0,0,0)` | `(0,0,0)` |

The support moment is independently decomposed as
`r_root cross (0,-0.1,-0.2) = (-1,2,-1)` N mm plus the physical rotational
couple `(0,20,-10)` N mm. This nonzero couple detects omission of native
mean-rotation restraint actions. A solver-generated algebraic restraint value
may legitimately be nonzero: its value is retained as evidence but contributes
neither a spatial force at its dummy coordinate nor a physical couple.

Require the exact native support catalogue: two translational entries on the
original root node in directions 2 and 3, and the three proved generated
mean-rotation pairs corresponding to original directions 4, 5 and 6. Each pair
identifies the original root node/direction; auxiliary DOF1 is the physical
`ANGLE` action with its proved global unit axis, and auxiliary DOF2 is the
`ALGEBRAIC` action excluded from the physical wrench. Reject missing, repeated,
additional or relabelled pairs, rather than accepting mere presence of three
role names. Do not require algebraic values to be zero. Eight is the filtered
observation-role count, not an assertion that native `nboun` equals eight:
native arrays may also retain the original root DOF4/5/6 declarations.

At an element's first endpoint with original X coordinate `x`, expect outward
force `(-10,-0.1,-0.2)` N and centroid-relative moment
`(0,0.2*(110-x),-0.1*(110-x))` N mm. At its last endpoint `x`, expect outward
force `(10,0.1,0.2)` N and centroid-relative moment
`(0,-0.2*(110-x),0.1*(110-x))` N mm. In particular the chain's first moment is
`(0,20,-10)` and its loaded last moment is zero. Project these references on
the literal native axes when checking all six local channels.

Keep the native source/spring/support action force limit `0.001 N`, origin
moment limit `0.1 N mm`, spring-law limit `0.001 N`, root X-displacement limit
`0.0000005 mm`, and physical root-couple limit `0.1 N mm`. For the beam-end
global force components, use respective absolute limits
`(0.01,0.0001,0.0002)` N, each 0.1% of its independent applied component.
Use the already frozen `0.04 N mm` absolute section-centroid moment limit.
For local channels, project those same global reference/error boxes through
the reported unit axes; do not let the 10-N axial component mask a missing
0.1/0.2-N shear. These scalar/vector budgets are requirements of this fixture;
they do not certify universal section-integration or compliance accuracy.

## Frozen small-displacement companion: nonzero physical support couples

Before any companion run or companion implementation, retain the first
fixture's geometry, mesh, material, grounded X spring, zero-five-DOF restraint
and case duration, and use endpoint force `(0.01,0.0001,0.0002)` N. This scales
the preceding conditional vector by `0.001`; it does not change the first
10-N axial fixture, its recorded evidence or its acceptance criteria.

This scale is selected analytically because native end observations use the
current section geometry with linear stresses. A linear-theory reference and
current-geometry mapping can therefore differ by small geometric products.
For the 2-by-4-mm rectangle, the conservative minimum second moment of area is
`I_min = 4*2^3/12 = 8/3 mm^4`. Using that smaller inertia for both transverse
directions bounds the Euler-Bernoulli tip section rotations by:

```
theta_Y_load <= 0.0001*100^2/(2*100000*(8/3)) = 1.875e-6 rad
theta_Z_load <= 0.0002*100^2/(2*100000*(8/3)) = 3.750e-6 rad
combined rotation bound = sqrt(1.875^2+3.750^2)*1e-6 = 4.193e-6 rad
```

The conservative axial-force mapping contribution is then no more than
`0.01*4.193e-6 = 4.193e-8 N`, below 0.042% of the smaller 0.0001-N shear and
below its 0.1% force budget. Direction-specific products are smaller:
`1.875e-8 N` and `3.750e-8 N`, each 0.01875% of its transverse force. A
rectangular shear estimate using `G=E/(2*(1+nu))`, `A=8` and `kappa=5/6` adds
only `7.8e-10 rad` for the larger transverse load. These are pre-run geometric
scale estimates, not a numerical result used to relax a failed criterion.

The corresponding conservative transverse tip displacement bounds are
0.000125 and 0.000250 mm, norm 0.000280 mm. Even transporting the full 0.01-N
axial force through that displacement contributes less than
`2.80e-6 N mm`, below the separately frozen `4e-5 N mm` centroid-moment
budget. The root spring displacement is `5e-6 mm` and nominal beam axial
extension `1.25e-6 mm`; multiplying the full 6.25e-6-mm axial motion by the
transverse force norm adds less than `1.4e-9 N mm`. The scale therefore keeps
these known geometric products smaller than the physical comparison limits
without asserting that all native numerical errors are bounded by this model.

The independently derived completed-state references are:

| Quantity | Force (N) | Origin moment (N mm) |
| --- | --- | --- |
| Applied source | `(0.01,0.0001,0.0002)` | `(0.001,0.278,-0.189)` |
| Ground spring action on model | `(-0.01,0,0)` | `(0,-0.3,0.2)` |
| Other physical root support | `(0,-0.0001,-0.0002)` | `(-0.001,0.022,-0.011)` |
| External sum | `(0,0,0)` | `(0,0,0)` |

The physical root rotational couple is `(0,0.02,-0.01)` N mm. Its force
transport is `(-0.001,0.002,-0.001)` N mm. Preserve the exact eight filtered
support-role identities described above, including excluded, potentially
nonzero algebraic terms; never substitute auxiliary coordinates as force arms.

Every element's first end at original X coordinate `x` has reference force
`(-0.01,-0.0001,-0.0002)` N and centroid moment
`(0,0.0002*(110-x),-0.0001*(110-x))` N mm. Its last end has reference force
`(0.01,0.0001,0.0002)` N and centroid moment
`(0,-0.0002*(110-x),0.0001*(110-x))` N mm. The first chain moment is
`(0,0.02,-0.01)`; the loaded last moment is zero. Use literal current native
axes for channel projection, retaining the explicit small geometric allowance.

Freeze the scaled companion's limits before its first run:

| Scaled companion check | Absolute limit |
| --- | --- |
| Native source/spring/support force references and external force closure | `1e-6 N` |
| Their origin moments, physical root couple and external moment closure | `1e-4 N mm` |
| Native spring force versus signed `k*u_root` | `1e-6 N` |
| Root X displacement versus `5e-6 mm` | `5e-10 mm` |
| Beam-end global X/Y/Z force components | `(1e-5,1e-7,2e-7) N` |
| Beam-end section-centroid moment components | `4e-5 N mm` |

The source/spring/support limits remain the original case's budgets scaled by
0.001. Each beam-force component keeps its own 0.1% reference scale, so the
axial force cannot hide either small shear. Project the same reference/error
boxes through the literal axes for local-channel checks. Native `.17g`
serialization remains far finer than these limits. Even seven-significant-
digit prints round a 0.01-N force by at most `5e-9 N`, a 5e-6-mm displacement
by `5e-13 mm` (only `1e-9 N` after multiplication by k), and a 0.278-N-mm moment
by `5e-8 N mm`. The limits include these explicit reporting budgets.

This companion qualifies a bounded small-displacement output composition only
if it passes. It does not execute or qualify the earlier larger combined-load
proposal, guarantee arbitrary force magnitudes, or change Oomakhi's limits.

## Provenance, controls and refusals

Bind actual beam and spring element/node IDs to the unchanged stock-generated
deck, fresh owned request and selected binary. Retain exact native step,
increment, time/FRD frame identity, units and source hashes. A spring record
with a different node, DOF, axis, stiffness, case, source/request or native
element identity must not be imported as a matching current observation.

After a successful owned solve, save the literal diagnostics and provenance,
close the document/process, then cold-open. The saved quantities/identities
must survive exactly as Historical data; cold-open must not fabricate Current
process ownership. Altering connector stiffness, direction, endpoint, support,
load or mesh withdraws fresh-current access. Historical evidence remains
explicitly labelled. Native zero restraint reactions must not be fabricated by
omitting restraints from an accounting catalogue.

Retain all old 960 refusals outside the specifically proved extension. In
particular, this single grounded translational spring does not qualify
two-port springs, RBE receiving regions, rotational connectors, general
NativeForceAccounting graphs, mixed meshes, nonlinear cases or contact. When
any such unqualified opt-in is active, give an explicit refusal.

## Later domains remain conditional

### Frozen final mixed fixture: real prism with an explicit rigid loading face

The final mixed fixture is the ordinary authoring factory
`femtest.app.beam_coupling_fixtures.make_hybrid_series`. Its following inputs,
references and limits are frozen before any mixed solve. It replaces the
direct-Tet-vertex candidate retained below. A failure to author its requested
attachment is an authoring refusal, not permission to substitute a different
spring, manually edit a deck or dilute the requested incidence.

| Quantity | Frozen final mixed-domain value |
| --- | --- |
| Beam root, tip | `(0,17,-23)`, `(40,17,-23)` mm |
| Beam | Straight RECT 4 by 4 mm, L=40 mm, two B32R elements |
| Beam native nodes / elements | Nodes 1..5 at 10-mm X intervals; elements 1 and 2 |
| Prism far / near planes | X=-30 / X=-10 mm; length 20 mm |
| Triangle Y/Z vertices | `(12,-28)`, `(22,-28)`, `(17,-13)` mm |
| Prism cross-section / volume | 75 mm² / 1500 mm³ |
| Far nodes | 101,102,103 at X=-30, in the triangle order above |
| Near nodes | 104,105,106 at X=-10, in the same order |
| Tet elements | 101=(101,102,103,104); 102=(102,103,104,105); 103=(103,104,105,106) |
| Tet volumes | 500 mm³ each, nondegenerate |
| Material, shared by actual beam and solid | E=200000 N/mm²; nu=0; linear, no body loads |
| Physical solid support | Far triangular face Fixed, all three far nodes' translations zero |
| Physical beam guide | Root Y/Z and three rotations zero, X free |
| Explicit internal rigid loading face | Near nodes 104..106, noncollinear; reference `(-10,17,-23)` mm at their centroid; all six reference modes Free |
| Connector | One scalar global-X `SPRING2`, k=10000 N/mm, beam root to the detached rigid-face reference |
| Source | `(+100,0,0)` N at beam tip |
| Case | One unsplit, small-displacement linear static 3D case, end time 1 |

The listed Tet connectivity is the emitted CalculiX order. Native SMESH
authoring reverses the first two corner IDs because `writeABAQUS` applies
`(1,0,2,3)` when exporting Tet4. The initial authoring attempt used the
CalculiX order directly in SMESH and was rejected for nonpositive Jacobians.
Correcting that authoring permutation changes no vertex, physical cell,
material, load or numerical acceptance limit; the failed run remains evidence.

### Reviewed native beam displacement reference amendment

The initial total-tip `PL/EA` reference was an incorrect exact-discrete
assumption for the native B32R endpoint loading, not a demonstrated coupling
or observer regression. The failed 1e-6 mm comparison remains recorded:
ideal uniform-traction rod tip 0.01138333333333333 mm, native tip 0.0114182 mm.
Its tolerance is not enlarged, and ideal-rod beam compliance is not qualified.

Pinned `gen3dforc.f` and `gen3dconnect.f` couple the point source and spring
endpoint to the mean of four expanded corner translations. Virtual work
therefore gives four corner loads P/4 and no midside loads. Uniform axial
traction on an eight-node quadratic section instead gives corner loads
-P/12 and midside loads P/3. Consequently affine `PL/EA` is not the exact
solution of the actual discrete endpoint-loading problem, including at nu=0.

The unchanged-deck controls use both the new native solver with diagnostic
activation absent and the previously installed 3fdd solver. All eleven physical
displacement vectors match the observed case within 2e-7 mm. A separate pure V1
beam with the identical geometry, material, mesh and tip load, and independently
prescribed root Ux=P/K+PH/(EA_s)=0.010133333333333333 mm, also matches all five
mixed beam displacement vectors within 2e-7 mm. These tests demonstrate native
component equivalence, not a fitted displacement constant or a universal beam
accuracy guarantee. The 2e-7 mm limit was independently selected to cover two
six-significant-digit FRD reporting bounds, and is stricter than the earlier
1e-6 mm value. All force, moment, spring and affine-solid analytical checks and
their limits remain unchanged. No project model or engineering criterion changes.

### Native map geometry and solved displacement

The section centroid and face basis are observed from the actual native map
geometry `co+vold`. In the linear-static source path, current solved `v` is
written to FRD after section mapping; `vold` can still be the preceding or
reference configuration during that map. Section-map positions must therefore
not be interpreted as solved displacement, or shifted using FRD U while keeping
the original centroid-relative moment. Coupled V2/V3 output names this frame
`NATIVE_MAP_EXPANDED_SECTION` / `NATIVE_MAP_FACE_BASIS` and records the geometry
source explicitly. Published V1 marker strings are retained as legacy wire
names, with the same clarified native-map interpretation. Current status means
owned result availability, not a declaration that the map used solved geometry.

The specimen is a physical prism with a deliberately rigid loading face, not
a rank-padding device. The near triangle has base 10 mm and height 15 mm,
area 75 mm²; its centroid is exactly `(Y,Z)=(17,-23)` mm. The three Tet4s
partition the actual 20-mm extrusion. Actual volume-owned boundary triangles
201..208 must not become shell elements. Beam and solid element/node owners
are disjoint; no beam node is a member of the RBE receiving region. Bind the
actual stock-allocated spring and detached reference/rotation/auxiliary node
identities to their owners rather than assuming helper labels are spatial
structural points.

The independent completed-state statics are:

| Action on named owner | Force (N) | Origin moment (N mm) |
| --- | --- | --- |
| Beam tip source | `(100,0,0)` | `(0,-2300,-1700)` |
| Spring on beam root | `(-100,0,0)` | `(0,2300,1700)` |
| Spring on detached RBE reference | `(100,0,0)` | `(0,-2300,-1700)` |
| RBE on detached reference | `(-100,0,0)` | `(0,2300,1700)` |
| RBE on actual near-face receiving solid nodes, aggregate | `(100,0,0)` | `(0,-2300,-1700)` |
| Far-face physical supports, aggregate | `(-100,0,0)` | `(0,2300,1700)` |
| Beam guide physical actions, aggregate | `(0,0,0)` | `(0,0,0)` |

The source-plus-spring beam free body closes. Spring-plus-RBE actions close
on the detached reference. RBE-receiving action plus physical far support
closes on the real solid. Both spring-end wrenches cancel, both RBE-side
wrenches cancel, and source plus physical guide/far supports closes for the
whole model. The reference and receiving ports are internal transfer, not
external support. Their reference-centred couples are zero; their nonzero
origin moments are transported physical forces, not independent applied
couples. Observe the guide's expected-zero actions rather than omit its
catalogue. Nine native algebraic RBE equation terms are nonphysical and must
be retained/classified without adding them to a physical wrench, even if their
native values are nonzero. The beam's three algebraic mean-rotation terms
are likewise excluded; its three ANGLE terms remain physical couples.

Each B32R element has outward first/end forces `(-100,0,0)` and `(100,0,0)` N,
zero centroid-relative moments, positive 100-N axial tension and zero other
channels using the literal native face axes. The loaded line passes through
both rigid-face and beam centroids, so the axial source creates no physical
local bending/torque. Its global-origin moments remain nonzero as above.

This fixture also has an independent affine solid patch reference. Since
nu=0, the exact field
`u_x(x)=100*(x+30)/(200000*75)`, `u_y=u_z=0` satisfies the far-face clamp,
rigid near-face translation and zero lateral-face traction. Every Tet4
represents that affine displacement exactly, so all three element stresses
are the same constant tensor, and native nodal extrapolation/averaging of
that tensor should preserve it at all six original solid nodes. Thus:

```
solid Sxx = 100/75 = 1.3333333333333333 MPa
solid Syy=Szz=Sxy=Syz=Sxz = 0 MPa
near-face/reference Ux = 100*20/(200000*75)
                      = 0.0001333333333333333 mm
beam-root minus reference Ux = 100/10000 = 0.01 mm
beam-root Ux = 0.010133333333333333 mm
ideal uniform-traction rod extension (diagnostic only) = 0.00125 mm
ideal uniform-traction rod tip (diagnostic only) = 0.011383333333333333 mm
```

The original near-face nodes all share the reference translation; all far
nodes are zero. Other translational displacement components and reference
rotation are zero. The stiffness/compliance reference applies to this
specimen's stated affine patch and nu=0, not to arbitrary coarse solids,
joint stiffness, contact, or building performance. Preserve the six solid
stress components only on the exact original solid node catalogue 101..106.
Beam section-resultant slots and detached generalized coordinates must never
be imported as MPa stresses or averaged together with those solid owners.

The original analytical limits and the explicitly reviewed component-reference
amendment above are:

| Final mixed-fixture check | Absolute limit |
| --- | --- |
| Source, each spring/RBE side, guide and far-support force references; each owner/global force closure | `0.01 N` |
| Their origin moments and owner/global moment closure | `1 N mm` |
| Every beam-end global force / projected force channels | `0.1 N` |
| Every beam-end centroid moment / projected moment channels | `0.4 N mm` |
| Native spring force versus signed `k*(u_beam_root-u_reference)` | `0.01 N` |
| Spring relative displacement versus 0.01 mm | `0.000001 mm` |
| Original near-face / reference affine displacement components | `0.0000001 mm` |
| Beam-root displacement versus independent spring/solid boundary value | `0.000001 mm` |
| All five mixed beam displacement vectors versus the independently prescribed pure native beam | `0.0000002 mm` |
| Each of six solid stress components at each of six original solid nodes | `0.0001 MPa` |

The native action force budget is 0.01% of the determinate 100-N load. Its
1-N-mm moment budget transports that force budget through a conservative
100-mm enclosing length, larger than the 70-mm specimen span and maximum
physical origin radius below 50 mm. The beam requirements are the same
constant-traction 0.1% force criterion and 0.1% of `P*4-mm section depth` for
zero centroid moments, scaled independently from the earlier axial patch.
The spring displacement limit is 0.01% of its exact 0.01-mm extension. The
near/reference displacement limit is 0.075% of the affine 0.000133333-mm
translation. The original total-tip rod reference was retracted as described
above; its failed comparison is retained. The replacement component-equivalence
limit is independently justified by the two FRD reporting bounds, rather than
by the magnitude of the observed rod-reference discrepancy. The force, spring
and affine-solid limits were selected before observing the mixed result.

Native diagnostics retain `.17g` values. Pristine CalculiX `frdselect.c` casts
ordinary nodal fields to float and formats them with `%12.5E`, six significant
digits. At Sxx=4/3 MPa the decimal rounding bound is `5e-6 MPa`, with binary
float conversion below `8e-8 MPa`; the `1e-4 MPa` limit exceeds that explicit
combined reporting budget by more than 19 times. Near-port displacement's
FRD decimal bound is `5e-10 mm`, with float conversion below `8e-12 mm`,
well below its `1e-7 mm` limit. At beam-tip Ux approximately 0.0113833 mm,
the corresponding combined reporting bound is below `5.1e-8 mm`, over 19
times smaller than the `1e-6 mm` requirement. Native actual force, support
and port diagnostics must not be reconstructed from those rounded FRD fields.

Fresh case/request/deck/binary/FRD identity, exact node/end/owner/frame/units,
literal spring/port incidence, save/cold Historical behavior and stale-current
withdrawal apply to all these channels. This fixture alone does not qualify
arbitrary mixed meshes, arbitrary RBE graphs, contact, Tie, nonlinear laws,
other beam sections, a per-connector general API, or Oomakhi acceptance.

### Superseded direct-Tet-vertex candidate: retained planning only

The earlier candidate proposed a native two-vertex `SPRING2`, without any RBE,
between the beam root and an actual tetrahedral test specimen. It was not
executed or qualified; the frozen prism above replaces it. The candidate was
conditional on the normal native authoring/writer and
solver preserving the distinct beam/solid owners and enabling exactly this
mixed-element route. Keep the beam/material/load/zero-five-DOF restraint from
the first axial fixture. Remove its grounded spring and substitute:

| Quantity | Frozen second-domain value |
| --- | --- |
| Tet port A | `(0,20,30)` mm |
| Fixed-face vertices B, C, D | `(-10,20,30)`, `(-10,30,30)`, `(-10,20,40)` mm |
| Solid mesh | One real, nondegenerate C3D4; A/B/C/D have distinct IDs disjoint from all beam node IDs |
| Solid material | Linear isotropic `E=100000 N/mm²`, `nu=0.3`, no density/body loading |
| Physical solid support | Native Fixed on the actual B/C/D triangular face, all its translational DOFs zero |
| Connector | Vertices, Translational, Two points, global X, identity frame, `k=2000 N/mm` |
| Connector End1, End2 | Beam root `(10,20,30)`; Tet port A `(0,20,30)` |
| RBE, Tie, contact and general accounting | Absent; no corresponding qualification is inferred |

The tetrahedron has volume `1000/6 mm³`: its face area is `50 mm²` and its
normal altitude is 10 mm. It is an actual compliant solid specimen with a real
fixed face, not an invented geometric device to satisfy a rigid-port rank
test. The 10-mm connector span is collinear with its scalar X force; there is
no lever/couple hidden in dummy-node positions. Record actual native element,
node, CAD-reference and material/section owners before accepting the run.
No mesh node is shared by the beam and tetrahedron. Do not attach a beam
section to the Tet, reinterpret the Tet as beam output, or relabel beam
resultant slots as solid stress. Preserve ordinary solid stress observations
literally if requested, without an analytical solid stress/compliance claim.

The exact statics and reference-state origin moments are:

| Quantity, action on named model owner | Force (N) | Origin moment (N mm) |
| --- | --- | --- |
| Beam endpoint source | `(10,0,0)` | `(0,300,-200)` |
| Connector on beam root, End1 | `(-10,0,0)` | `(0,-300,200)` |
| Connector on solid port A, End2 | `(10,0,0)` | `(0,300,-200)` |
| Other beam-root stabilizing supports, aggregate | `(0,0,0)` | `(0,0,0)` |
| Real fixed-face solid supports, aggregate | `(-10,0,0)` | `(0,-300,200)` |

Consequently source plus connector plus stabilizers closes on the beam owner;
connector plus fixed-face support closes on the solid owner; the two connector
end actions cancel as full origin wrenches; and source plus all physical
supports closes on the whole model. Count connector transfer once in each
owner free body and zero times in the whole-model external support total.
Do not classify the moving Tet or beam connector endpoints as ground supports.
There is no ground spring in this second fixture.

Each beam element has the first axial fixture's `-10/+10 N` outward endpoint
forces, zero centroid moments and positive 10-N tension. The exact spring
response is only the relative displacement
`u_beam_root_X - u_Tet_A_X = 10/2000 = 0.005 mm`. No exact absolute Tet-port,
root or tip displacement is an acceptance target. Individual fixed-face
nodal reactions are not prescribed; their native aggregate force/moment is.
Native `NODE PRINT RF` on a moving connected endpoint remains a combined
nodal quantity and must not be labelled an isolated connector action.

Freeze this second fixture's numerical budgets before its first run:

| Second-domain check | Absolute limit |
| --- | --- |
| Each native connector endpoint action versus its signed 10-N reference | `0.001 N` |
| Source, beam-support and solid-support force references / each owner and whole-model force closure | `0.001 N` |
| Each referenced origin moment / owner and whole-model moment closure | `0.1 N mm` |
| Actual native connector force versus signed `k*(u_beam-u_Tet)` oracle | `0.001 N` |
| Spring relative X displacement versus 0.005 mm | `0.0000005 mm` |
| Every beam-end force and centroid moment | First axial limits `0.01 N`, `0.04 N mm` |

The force requirement is 0.01% of the statically determinate scalar load; the
moment requirement transports that force budget over the beam's 100-mm
characteristic length. Neither depends on a predicted Tet compliance or
stress distribution. Both specimens are small and nondegenerate, with a
linear scalar connector and no nonlinear/load-path ambiguity. Existing
17-significant-digit native diagnostic serialization is far finer than
these budgets; even seven-significant-digit 10-N prints round by at most
`0.000005 N`. Apply the previously documented per-value displacement rounding
bound to the two literal native port values before comparing a printed
difference; the owned diagnostic values should retain full precision.

The connector's two signed action records also have a separate wire-level
equal/opposite check, `1e-12*max(1,absolute component values)`, before engineering
reference checks. Their endpoint/element/DOF/axis/unit/case identities must be
exact. Since the separation is parallel to the force, their origin moments
must cancel to the same transported wire budget. Use original physical
coordinates for support transport; auxiliary mean-rotation coordinates are
axis data, not moment arms.

The physical support role catalogue is the first fixture's eight filtered
beam rows plus all nine original Tet B/C/D translational constraints, with
owner identities kept distinct. This filtered count of 17 does not prescribe
the native raw `nboun` count. Every beam ANGLE/ALGEBRAIC pair retains its
original-node/direction proof; no algebraic force enters the physical wrench.
Cold-save, fresh-case ownership, source hashing, staleness and wrong-identity
refusals apply to both connector endpoints and all mixed owner records. This
second fixture does not enable contact, Tie, arbitrary mixed meshes, rigid
ports, nonlinear springs or a per-solid stress-accuracy guarantee.

A separately frozen parallel spring fixture can subsequently test load sharing:
with a fixed beam root, the same spring at the tip and the same 10-N source,
`u_tip=10/(8000+2000)=0.001 mm`, beam force 8 N and spring force 2 N. It is not
the first series proof, and its stiffness-dependent beam response needs its
own accepted compliance domain.

Rigid ports need their own native beam rotational-compatibility and receiving
rank proof. A later connected mixed/contact topology may use a beam joined by
a proved native port to a solid platen pressing a supported solid block. Only
then can centered compression give a shared 10-N beam/contact/support path,
owner-specific contact action/reaction and meaningful closed/compressive state
controls. Ordinary solid faces can be used for the contact surfaces. Merely
placing disconnected beam and contact fixtures in the same analysis does not
demonstrate coupled transfer. No mixed/contact implementation or benchmark is
authorized by this proposed topology alone.

The Oomakhi equilibrium/paired-cut 1% and sensitivity 5% requirements, original
failed evidence, physical stiffness/support choices and project design duties
remain unchanged. This work neither opens nor solves Oomakhi.
