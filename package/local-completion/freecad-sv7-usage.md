# FreeCAD-sv7: using native coupled beam results

The CalculiX solver's saved `BeamSectionForces` property enables native member-end forces, moments and section axes. It defaults to `False`. Enable it in the solver's **Data → Beam Section Forces** group, then write and run through the ordinary CalculiX solver panel. An empty `NativeAccountingSolver` selects the bundled qualified solver; an external solver must support the same diagnostics contract.

Use a linear, small-displacement `static` analysis in `ModelSpace = 3D`, with `ReducedIntegration = True`, `ExcludeBendingStiffness = False`, `Output3d = False` and `SplitInputWriter = False`. Set a finite positive `TimePeriod`. Keep `NativeForceAccounting = False` and `NativeContactOutputs` empty. The coupled workflows below also require an empty `NativeAccountingSupports` list: their own native observations identify every admitted physical support.

## Grounded scalar spring: V2

Create one straight, unbranched quadratic B32R beam chain with one uniform rectangular section and one linear elastic material. Create one **Elastic Connector (CalculiX)** with these saved properties:

| Property | Setting |
| --- | --- |
| `Attachment` | `Vertices` |
| `Kind` | `Translational` |
| `Mode` | `Ground` |
| `End1` | One original beam endpoint vertex |
| `Axis` | Global `X`, `Y` or `Z`, along the beam |
| `Orientation` / `OrientationReference` | Identity rotation / empty |
| `Stiffness` | Explicit, finite positive stiffness in N/mm |

At that endpoint, add one Displacement constraint: leave only the spring translation free, prescribe the other two translations to zero, and prescribe all three rotations to zero. Add one Force constraint on the opposite endpoint. Additional constraints, amplitudes, beam rotations and nonlinear material laws are outside this workflow. The connector writes a native SPRING1; the separate Elmer Spring Foundation object is not its substitute.

## Beam to a genuine solid port: V3

Use one straight B32R beam chain and one genuine CAD solid meshed with C3D4 tetrahedra, with one uniform rectangular beam section and one shared linear elastic material. Beam and solid node identities must be disjoint. Solid boundary faces may support CAD reference selection; standalone shell elements are excluded.

Create one explicit Rigid Body on a receiving region containing at least three noncollinear genuine solid mesh nodes. Set its `ReferenceNode` on the beam's global axis. Leave all `TranslationalModeX/Y/Z` and `RotationalModeX/Y/Z` values `Free`. Its receiving region must exclude every beam node and the physical solid support region.

Select one original beam endpoint vertex and the Rigid Body, then invoke **Elastic Connector (CalculiX)**. This creates the saved `Attachment = Vertex to rigid body port`, `Mode = Two points`, `Kind = Translational`, with the vertex in `End1` and the solid body in `RigidBody2`. Keep `End2` and `RigidBody1` empty. Set the global `Axis` and explicit positive `Stiffness`; use identity `Orientation` and no `OrientationReference`.

Add the same five-DOF zero beam guide described above at `End1`, one Force at the opposite beam endpoint, and one Fixed constraint on a separate solid region. The native SPRING2 connects the beam point to the Rigid Body's detached reference node. The qualification specimen is an axial series load path: this scalar translation does not establish a six-component joint law, a direct beam RBE/Tie connection, or an offset connection carrying an additional moment.

## Reading the results

Double-click **Native beam-end forces and moments**, or use **Inspect native beam-end actions** in its context menu. The inspector retains element/end identities, signed global forces in N, centroid-relative moments in N·mm and literal section axes. Its coupled-action tables distinguish physical support reactions from internal spring/RBE transfer. `TRANSLATION` contributes force; `ANGLE` contributes a physical couple; `ALGEBRAIC` records a native equation value and is excluded from the physical wrench. Coupled-action moments use the original global origin.

V3 also creates two ordinary mechanical results with separate post-processing pipelines: a mixed beam/solid **displacement-only** result, and a solid-only `SolidResults` result containing displacement and genuine native solid stress in MPa. Prefixes may vary. Use the solid result for von Mises and principal stresses. Beam FRD `S` slots contain N and N·mm section quantities, so they are never presented as MPa or padded with invented zero stresses. Saved `NativeSourceNodeNumbers` preserve original identities through mesh compaction.

V2/V3 section geometry is labelled `NATIVE_MAP_EXPANDED_SECTION`, with `NATIVE_MAP_FACE_BASIS` and `geometry_source = CO_PLUS_NATIVE_MAP_VOLD_ARGUMENT`. These mean the geometry supplied to the native section mapper, `co + vold`. In linear static execution, `vold` can still be the preceding state; the displayed centroid is not a guarantee of the final displaced position. Ordinary FRD displacement remains the solved displacement observation. The first-end section basis may be left handed, and native expanded-node stress averaging remains in the resultants.

## Saved history and scope

Current data requires a fresh owned solver completion with matching model, solver, input and output identities. Model or stiffness edits, a new attempt, failure or cancellation withdraw that availability. Save/reopen retains literal observations as **Historical** and clears `CompletedRun`; rerun to obtain **Current** data. Existing mechanical result objects remain saved snapshots.

This change does not qualify generic mixed meshes, beam-node rigid bodies, beam Tie, rotational scalar springs, contact in a beam analysis, or combined beam output and native solid/contact accounting. Existing solid-contact diagnostics remain a separate workflow. It neither changes nor accepts the original Oomakhi geometry, loads, joint laws, equilibrium limits or building design. Source semantics and numerical limitations are recorded in [the research note](freecad-sv7-research.md).
