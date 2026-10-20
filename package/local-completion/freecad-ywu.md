# FreeCAD-ywu: moving connector ports and selected physical supports

This is a software/output-method extension, not engineering acceptance. It does
not open, alter, remesh or solve Oomakhi, and does not replace the installed app.
The versioned native contract is in
[`../calculix/force-accounting/contract.json`](../calculix/force-accounting/contract.json).

## User interface and mechanical meaning

Enable `NativeForceAccounting` on the CalculiX solver, then set its saved
`NativeAccountingSupports` list to the physical external constraints to report.
Select fully fixed zero-motion RigidBody constraints and/or ordinary Fixed or
zero Displacement constraints from that analysis. A Displacement support can
leave directions free: only its actual prescribed translations are reported.
Ordinary supports must be outside every requested accounting cut body.

The list does not add restraints, change stiffness, or make a moving port fixed.
Omit internal moving RigidBody connector ports from the external support list;
their actual transfer remains in the aggregate `MPC` body channel. Empty lists
retain the earlier all-fixed-RBE selection behavior, including its refusal of
moving RBEs as external supports. Empty lists do not automatically select
ordinary Fixed/Displacement constraints. A selected subset is not proof that all
external restraints have been included.

The writer rejects ambiguous selected physical degrees of freedom, including
duplicates introduced by unselected ordinary constraints and ordinary restraints
on a selected external RBE's receiving region. It uses the stock writer's exact
nodes, directions and scalar-spring IDs. It does not patch a model's native deck
or replace finite receiving patches with vertices.

## Native V3 composition

Fresh runs require `CCX_FORCE_ACCOUNTING_V3`. Native V1/V2 requests and
matching-version outputs remain supported within their earlier domains. Literal
older reports are readable without fabricating channels or upgrading their
provenance.

| Request | Meaning |
| --- | --- |
| `SUPPORT` | Selected native RBE reference/rotation nodes, all six zero-prescribed |
| `SPC_SUPPORT` | Selected ordinary physical `(node, translation direction)` terms |
| `PORT` | Exact native RBE identity, separate from its external-support role |
| `ANGLE` | Actual scalar auxiliary-angle equation bound to an RBE rotation node |
| `SPRING` | Exact native two-port scalar `SPRING2` identity and connectivity |

Original RIGID/angular equations are captured before native decascade to verify
the declared ports and angle equations. The actual output-state acyclic MPC
graph still determines the aggregate body action. Scalar spring forces already
enter native internal nodal force and are not added a second time. Angular
auxiliaries are generalized coordinates, not physical external supports or
forces applied at their dummy coordinates.

Support reactions use native internal force minus actual external loads after
MPC projection. Ordinary support wrenches sum only the selected restrained
components at original physical nodal positions. RBE rotational residuals remain
reference-point couples. All reported moments are about the original global
origin. `CUT = -(LOAD + CONTACT + MPC)` remains explicitly equilibrium-derived,
not recovered-stress integration. Standard `RF`, `SOF/SOM` and `CF` are unchanged.

The supported extension is one small-displacement mechanical static step with
Tet4/Tet10 solids, explicit non-collinear native RBE receiving regions and
finite positive linear two-port scalar connectors. Grounded/direct-solid-node
springs, nonzero/amplitude-bearing ordinary supports, transformed coordinates,
SPCs in cut bodies and ambiguous shared-cut point loads remain outside its
domain. Existing Tie/contact ownership and original-coordinate guards remain.

## Analytical evidence and scope

The retained initial installed-app attempt reaches an actual `SPRING2` volume
refusal before the originally suspected six-motion support guard. It is not
reported as a reproduction of that later error. The original longitudinal
side-load fixture also creates real concentrated load terms on shared cut
nodes; its native refusal remains a negative control.

A separate end-edge-loaded benchmark was declared before execution. Two real
finite receiving faces move in X and rotate about X, connected by six positive
scalar springs. Applied load is `[12,0,0,6,36,-24]` in N/Nmm about the original
origin. Physical support is its negative; the two retained cut bodies have
opposite known cut/MPC wrenches. Both nonzero force and moment errors use their
independent reference-vector norms and the unchanged 1% ceiling. Zero channels
use the declared applied-load scales, 12 N and `sqrt(1908)` Nmm; no fitted signs,
denominators, corrections or raw-RF substitutes are used.

The ordinary-support benchmark retains the same physical beams, material,
connectors and end loads, with conforming selectable cell partitions. A finite
Fixed patch and a disjoint finite Ux-only Displacement patch are separated by a
0.5 mm gap. Aggregate support is independently known; individual patch force
shares are not fitted targets. Actual transverse movement verifies the partial
patch is not silently fixed. Independent audits check native owner identities,
finite-face motion, actual load placement, cut unions and original-origin
wrenches separately from application lifecycle checks.

These axial/torsional fixtures do not qualify arbitrary noncentral transverse
scalar-connector layouts. Separated references can produce a spatial couple
from transverse connector forces. Actual geometry, constitutive response and
force/moment duties require their own assessment; no blanket joint or mesh
accuracy guarantee follows from native composition.

The registered native tests exercise stock export, the bundled solver, physical
movement, result import, selection/domain refusals and save/reopen. The related
FreeCAD-y44 fix classifies stock FRD pipelines, result meshes and DAT text as
outputs rather than physical model changes. Real support-selection/connector
edits still make reports stale, and reversing an edit does not promote history.
Separate cold-process checks preserve literal accounting data and saved support
links; restore remains historical until a normal fresh run.

Source qualification receipts and their exact-byte index are published in
`freecad-ywu-source-evidence`; the summary is `freecad-ywu-validation.json`.
Historical failed attempts remain classified separately from final gates.

## Engineering holds

Oomakhi has not been replayed or accepted. The frozen R49 displacement comparison
of 11.123267892% and R51 comparison of 5.240441298% remain failed against 5%.
Original 1% wrench limits, all 97 pairs/194 owner vectors, 48 raw pairs, eight
support controls, overclosure/slip and contact engagement/transfer/area/state
duties remain. This source extension neither accepts anchorage, whole-house or
R30/BIM design nor authorizes an automatic engineering solve.
