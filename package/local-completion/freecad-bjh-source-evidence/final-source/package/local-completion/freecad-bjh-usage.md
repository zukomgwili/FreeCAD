# Branching beam and scalar-spring observations (V5)

FreeCAD-bjh extends the existing saved **BeamSectionForces** request to a
bounded family of branching beam networks. It uses the ordinary CalculiX
writer, the bundled solver's native diagnostic observations, normal result
import, and the existing beam-result inspector. It does not add a replacement
beam solver or recover forces from Python displacements or stresses.

## Qualified model family

Use one small-displacement, linear, global mechanical static step with
second-order reduced-integration B32R beams. Every beam component must be a
connected, acyclic tree containing a genuine shared-node branch. Its quadratic
elements must be straight and centered, with zero-offset rectangular sections.
Each component has one ordinary linear-elastic material and one uniform
rectangular section; different components may have different materials and
section dimensions. Every element retains its own native section axes.

The scalar support path consists of exactly one translational **Ground**
ElasticConnector (native SPRING1) and zero or more translational **Two points**
ElasticConnectors (native SPRING2). All connectors use the same global X, Y or Z
translation and a finite positive linear stiffness. The SPRING2 connections
join different beam components into one connected, acyclic tree. Their actual
beam endpoints have distinct positions, with the gap aligned to that common
global axis. A one-component specimen therefore has one grounded spring; a
three-component tree has one ground spring and two internal springs.

Each beam component has one saved Displacement guide at a genuine leaf
endpoint. The guide leaves only the common spring translation free and
prescribes the other two translations and all three physical rotations to
zero. Its incident beam follows the free global axis. The ground spring is
attached at the root component's guide. Following the connection tree away
from ground, each downstream SPRING2 end is the downstream component's guide.
These are physical beam vertices, not explicit RigidBody receiving sets.

Multiple ordinary Force objects may load distinct owned leaf endpoints.
A loaded leaf can also be an upstream internal-spring port; a physical guide
cannot also be a source node. CAD edge ownership, mesh node/element groups,
material assignments, and section assignments must be complete and current.
Coincident coordinates do not establish a shared node or a physical owner.

The qualified examples include one branching component, two connected
components with independent materials/sections, and a three-component fork.
Their 18, 36 and 54 native member ends are checked separately against frozen
analytical statics. Qualification of those controls does not make arbitrary
beam networks or arbitrary meshes accepted examples.

## Request and inspect

Author the beams, material/section references, Forces, Displacement guides and
ElasticConnectors through the existing FEM objects. Enable the saved solver's
**BeamSectionForces** property, use reduced-integration second-order beam
elements, and retain the supported original-node beam output configuration.
Run the normal prerequisites, input writer, CalculiX solve and result import.
The bundled solver must advertise `CCX_BEAM_SECTION_V5` through
`--freecad-beam-network-version`; a generic CalculiX executable without this
diagnostic capability cannot produce this saved observation.

Double-click the saved native beam-result object, or choose **Inspect native
beam-end actions** from its context menu. Select the saved frame to inspect:

- Each actual element/end has its original node identity, exact CAD member,
  component, section and material owner, literal native basis, section
  centroid, global force/moment, and native local channels. Incident ends at
  a real branch remain distinct. Ownership is joined through the written
  element catalogue rather than guessed from a node or a displayed sample.
- Sources and physical guides retain separate owner names, positions and
  signed actions. Each actual spring end retains its spring owner, native
  element, mode, direction, stiffness, displacement, native resisting force,
  and action on the beam vertex. Ground SPRING1 has one observed beam end;
  there is no invented ground node. Internal SPRING2 has two observed ends.
- Physical guide DOFs distinguish translational forces, physical rotational
  couples, and native algebraic helper values. The value, prescription and
  displacement each retain their own explicit units.
- A separate generated-knot table records the original beam node, rotation,
  expansion, receiving and algebraic node identities, direction, native MPC
  row, and final native knot formulation code. The formulation code does not
  claim the geometric rank of the receiving cloud.

Member forces are in N, moments in N*mm, and positions in mm. Member moments
refer to the native section-map centroid. The centroid and basis preserve the
native mapper's `co + vold` geometry argument; they are not relabelled as
guaranteed final displaced geometry. The first end's literal face basis may
be left-handed.

Source, guide and spring actions use original global axes, with moments about
the global origin, acting on the structural model. Physical guide rotations
contribute couples. The ground spring contributes an external support action;
the two internal-spring end actions are transfers between components and are
not additional external ground supports. Native spring resisting force and
force acting on the beam are separately named observations with their native
sign convention preserved.

`ALGEBRAIC` observations retain `NATIVE_EQUATION_VALUE` units. They remain
uninterpreted and are excluded from physical force and moment balances.
Equation-node coordinates are not physical force application locations.
Beam section forces and moments are also not MPa stress values: their
diagnostic identity remains separate from ordinary FRD stress fields and
displacement results.

## Saved state and boundaries

The result records its case, frame, units, model/input provenance and completed
child run. Save and reopen preserves the typed observation. The public
`getSectionForces` accessor validates availability; saved historical output
requires the explicit historical path and does not become Current merely
because it can be displayed. A model, connector, load, guide, material,
section or mesh edit invalidates Current availability. An open inspector
withdraws its member, action, guide and knot rows together when availability
changes; rerun the ordinary solver workflow for a new Current result.

The V5 path refuses unsupported or ambiguous ownership, foreign ports,
disconnected/cyclic support graphs, redundant grounding, missing guides,
nonzero guide prescriptions, non-common or rotational spring directions,
nonlinear laws, user MPCs, explicit beam RBE receiving sets, contact, Tie,
thermal/prestress/body/distributed loads, and other unqualified mechanics.
Unknown generated equations or native identities fail observation rather
than being accepted as physical supports. Existing V1 pure-beam and V2–V4
qualified coupling routes remain separate.

The observations are solver evidence, not building-design acceptance. This
work does not alter or solve Oomakhi, qualify its load paths, change its
acceptance limits, or install an application.
