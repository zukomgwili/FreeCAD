# FreeCAD-9rc: contact in a native beam–solid analysis

This extends the [sv7 beam/scalar-port workflow](freecad-sv7-usage.md) with a
separate `CCX_BEAM_SECTION_V4` contract. Enable the saved solver property
`BeamSectionForces` and select the one ordinary Contact in
`NativeContactOutputs`. Leave `NativeForceAccounting` false and
`NativeAccountingSupports` empty. An empty `NativeAccountingSolver` selects
the bundled solver; an external binary must advertise the V4 capability.

Use one small-displacement, unsplit, three-dimensional static step with a
finite positive period, reduced integration, bending stiffness enabled and
`Output3d = False`. The qualified path contains one straight quadratic B32R
chain, a uniform rectangular section, a translational scalar SPRING2, and
two independently owned genuine C3D4 solids sharing a material. Their mesh
node identities must be disjoint, including coincident contact nodes.

Create the scalar connection from one beam endpoint to a detached Rigid
Body reference. Its receiving region belongs entirely to the loaded solid
and contains at least three noncollinear solid nodes. Keep the reference
on the beam axis. Leave only its axial translation free; prescribe its two
transverse translations and three rotations to zero. These five physical
port guides are distinct from the rigid equations' algebraic helper rows.
At the connected beam endpoint, apply the same five zero guides, leaving
the spring translation free. Apply one axial compressive Force at the
opposite beam endpoint.

The ordinary Contact joins exterior planar faces of the two true solids,
with opposite axial outward normals. Use `TYPE=SURFACE TO SURFACE` through
the stock writer, a positive linear normal slope, zero adjustment and the
original face orientations. Put a separate Fixed region on the backing
solid. The selected contact must be the only active Contact. Native CAD
mesh groups and written face ownership must agree; beam nodes and their
internal expansion never qualify as solid receiving or contact faces.

The independent analytical specimen qualifies closed, frictionless
compression and a genuine frictional **STICK** state with zero tangential
loading. It uses real, manually authored analytical tetrahedra and public
CAD ownership groups. It does not establish generic joint stiffness,
sliding, prescribed opening, beam-face contact, beam Tie or a six-component
beam-to-solid joint. Force-controlled separation is refused because the
free loaded body loses its static axial reaction path. The independently
derived opening proposal in the oracle document remains unimplemented and
unqualified.

Double-click the native beam result to inspect beam ends and the separate
source, beam guide, spring ends, internal rigid port, physical port guide,
backing support and owned contact-side actions. Forces are N and moments
are N·mm about the original global origin. Physical `ANGLE` rows contribute
couples; `ALGEBRAIC` rows remain excluded from physical wrenches. V4 records
both the native boundary prescription and converged displacement: numerical
round-off in a converged value does not turn an exactly zero prescribed
restraint into a different support.

The contact result retains actual native sample identities, availability,
state, pressure, clearance, axes and friction observations. It shares the
beam result's owned solver child, input, executable, model and physical
step/increment/time. The beam STRESS dataset number and contact integration
point numbers retain their distinct meanings.

Ordinary result import creates a mixed displacement-only result and two
solid stress results, each with its own solid-only mesh and post-processing
pipeline. Beam section quantities are never labelled as MPa. Saved source
node/element labels identify each solid partition.

Both native observations become Current together. A physical edit, detached
or deleted companion, altered source bytes, new attempt or failed partial
publication withdraws availability for both while retaining saved literals.
Save/reopen preserves both as Historical; a fresh owned run is required to
restore Current availability. Existing mechanical results remain saved
snapshots. No project model or engineering acceptance limit is changed.
