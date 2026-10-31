# FreeCAD-9rc: contact in a coupled beam–solid analysis

Research date: 2026-10-31. This note distinguishes official/native semantics from runtime qualification. The research agent does not execute FreeCAD, OpenCascade, CalculiX, builds or GUI tests. The coordinating agent owns those serial gates. No original Oomakhi model or installed application is changed by this research.

## Primary-source boundary

The [official CalculiX site](https://www.dhondt.de/) and [2.23 manual](https://www.dhondt.de/ccx_2.23.pdf) were checked on the research date. The PDF identifies version 2.23, dated 19 October 2025. The native source identity is the retained [official 2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `/private/tmp/freecad-960-semantics-gdfoMero/ccx_2.23.src.tar.bz2`, SHA-256 `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7`. That local archive identity was rehashed; its remote bytes were not re-downloaded.

The baseline is the installed `FreeCAD-sv7` application, revision `49261 +242`, with native solver SHA-256 `1f6281e8d779deeeb0f6a587d2cdcb5a7fc935e95f90b394cb28e761b22a603e`. The repository starts at metadata commit `54b924391c01e33e9538be15801df851a14f8243`; the compiled application source is `2f6ed5df7bd9786449230ad01366a7d8e10ae0e2`.

Affected implementation inspection began only after the coordinator reproduced both installed refusals through an actual GUI session: selected `NativeContactOutputs` produced `Beam section output is separate from solid accounting/contact diagnostics`; an active but unselected Contact produced `Beam-to-solid output does not support other constraints, cuts or contact`. The retained private evidence is `/private/tmp/freecad-9rc-9im9ovtw/installed-baseline-r01/{execution.json,cases/observation.json}`. It identifies the literal installed runtime, a detached scalar port, five explicit physical RBE guide DOFs, distinct beam/loaded-solid/backing-solid node sets, no solver execution, and unchanged app/three profiles. This is an intentional unsupported-domain refusal, not a demonstrated regression in the already-qualified sv7 or 9ii domains.

## Official constraints relevant to the candidate

The manual distinguishes node-to-face and face-to-face penalty contact; their algorithms cannot be mixed. Face-to-face penalty contact acts between a slave integration point and a master face, distributing forces to both sides. It requires `TYPE=SURFACE TO SURFACE`, without an explicit `SMALL SLIDING` parameter. [Manual §§6.7.6–7, pp226–245](https://www.dhondt.de/ccx_2.23.pdf).

Node-to-face `LINEAR` is regularized: `p = K d [1/2 + atan(d/epsilon)/pi]`, with `epsilon = pi sigma_inf/K`; it can retain a small tensile asymptote. Face-to-face `LINEAR` needs only `K`; the other normal-law parameters are irrelevant. Do not apply the unregularized `p/K` penetration oracle to node-to-face contact. [Manual §6.7.6, p230; §7.130, pp614–616](https://www.dhondt.de/ccx_2.23.pdf).

Friction separates elastic tangential motion from irreversible slip, using a stick slope and Coulomb bound. Nonzero tangential relative displacement alone therefore does not prove sliding. Beam nodes remain forbidden in an explicit rigid body. [Manual §6.7.6, pp231–238; §7.64, pp519–520; §7.113, pp589–590](https://www.dhondt.de/ccx_2.23.pdf).

## Prior qualified domains

The existing [sv7 source investigation](freecad-sv7-research.md), [sv7 usage boundary](freecad-sv7-usage.md), and [9ii contact-output investigation](freecad-9ii-contact-output-research.md) establish the work that must be preserved. Their source-level statements will be rechecked against the pinned native archive and current observer implementation after the fresh baseline. In particular, ordinary local contact output does not establish native sample identity or stick/slip state; a simultaneous coupled result must retain the existing actual-branch diagnostics rather than infer state from ordinary `CDIS` values.

## Physical stability of the proposed series fixture

The initial geometrical candidate is a straight beam connected by one translational scalar spring to a detached reference node of a genuine solid-face RBE. That solid meets a second genuine solid through a planar contact face; the second solid has a separate physical Fixed face. Contact nodes have distinct identities even when their reference coordinates coincide. No original beam node belongs to a rigid-body receiving region or contact face.

Independent statics exposes an important limitation before a solve: a fully free loaded-solid RBE and an axial scalar spring do not gain transverse translations and axial rotation restraint from frictionless planar contact. Replacing the sv7 specimen's fixed face by frictionless contact can therefore introduce rigid modes. A force-controlled open interface also removes the axial reaction path; a positive opening gap under a nonzero isolated dead load is not a static-equilibrium benchmark. These are model-stability observations, not failures of a diagnostic.

A valid qualification must identify actual physical guides or a compatible prescribed-motion path, or restrict a first candidate to a mechanically stable closed-contact state. Finite friction with an actual native sticking branch is another possible physical restraint, but its initial stiffness and retained state require native confirmation. No extra volumes, arbitrary springs, invented zero reactions or relaxed equilibrium limits should conceal a mechanism. The fixture's chosen constraints and claimed state domain must be frozen explicitly before its qualifying run.

## Inspected baseline implementation identities

These hashes identify the source read after the fresh refusal and before any 9rc implementation. They are not hashes of a later candidate. All source-member line references in the following section refer to `./CalculiX/ccx_2.23/src/` in the pinned upstream archive; repository references refer to the baseline commit above.

| Baseline repository file | SHA-256 |
| --- | --- |
| `package/calculix/force-accounting/beamsection.c` | `57fdc19718b2be319f76604ce7c3edce6a739358160ee98868660897d22be29d` |
| `package/calculix/force-accounting/beamsection.patch` | `2ab702fe5ef6ebf67c9baf80bfece9430e08c2cdb9f3501f47a39bb9dfde2885` |
| `package/calculix/force-accounting/forceaccounting.c` | `e25df61ffb38889a4287ce1eafc2b098a8b53dc7b272016d6b8bb722bfdcca91` |
| `package/calculix/force-accounting/hooks.patch` | `39898e56a8e4f6eb802d4ea5149d253f380d8f7a88f15af668c71a111f61f4af` |
| `package/calculix/force-accounting/contactstate.c` | `3c7e8d77f94bdd7c8bd54ac1cfe164a0577ca982bdc065f32c479c480f22a52e` |
| `src/Mod/Fem/femtools/beam_section_forces.py` | `ae362eae85f1492ec72dad04da49472d853f47389751e6d71ed4372d4f11da7c` |
| `src/Mod/Fem/femtools/beam_solid_coupling.py` | `fc8145c06d203483da9ca2461a2c29eb69da3a95355ad13e63addd21bcdb5246` |
| `src/Mod/Fem/femtools/contact_state.py` | `f4a1dc5c83f277a69fb369a5ff903db0ea6065679cf9b00c8d5b36ca9f440b8b` |
| `src/Mod/Fem/femtools/ccxtools.py` | `2a460d92901048225a7d5da6e7f7f0be57d8d5d759d5a2f23c1e3f637a9d8b53` |

## Actual contact force and identity seam

The native force source is already available without another force recovery. Upstream `resultsmech.f:430–437` calls `springforc_f2f`; lines448–454 then assemble its returned `fnl` into the nodal internal-force vector. The existing patch inserts `fa_contact(i,nope,konl,fnl,lakonl)` immediately after that return. At this point the complete contact nodal force distribution has already been evaluated by the unchanged mechanics routine.

Upstream `springforc_f2f.f:53–59` obtains the master-node count from the last character of the generated contact element's type; the slave count is the remainder. `gencontelem_f2f.f:682–716` writes the `ESPRNGC` type, master-node count, master nodes followed by slave nodes, native integration-point identity, and source-face pointer. The implementation must not split the connectivity by half: master/slave faces can have different node counts. A first all-Tet4 qualification may narrow both sides to three nodes, while still validating the actual type and tuple.

For a linear face-to-face law, `springforc_f2f.f:186–200` computes normal force from representative area, actual clearance, stiffness and the native `kscale`; lines250–253 initialize the point force and pressure. Lines374–405 execute the actual stick or slip branch, including the elastic override. Finally, lines426–437 distribute the complete point force to master and slave nodes using the actual shape functions. Sampling the returned `fnl` therefore observes normal and friction contributions together, after all actual distribution. This is preferable to calculating a global vector from printed pressure/shear or multiplying an imported pressure by a guessed area.

The already-qualified native accounting observer provides a sign and moment precedent: baseline `forceaccounting.c:1205–1230` records force on each structure node as `-fnl` and sums its moment using the retained original global coordinate. It identifies the volume parent of each side from its complete face node tuple. A beam/contact observer can copy the same read-only pattern into a separately admitted V4 catalogue. It must retain the actual contact owner, master/slave side, original face and original node identities; it must not treat a beam's internal expansion as a true solid contact owner.

The callback executes inside the existing parallel element workers (`results.c:189–238`). Several contact elements can contribute to one face or original node, so direct shared per-owner or per-node accumulation would race. Existing `fa_begin_results` sizes storage from the actual evaluation's `ne`, and `fa_contact` writes a distinct slot for each contact element and side. A composed observer should retain that pattern and aggregate only after the workers join. Generated contact element numbers can exceed the `ne` captured before contact generation, so the original beam catalogue's array bound is not a valid generated-contact storage bound.

Original-global contact action moments and native current sample positions are different observations. The native contact law uses actual positions (`co + v`, with the native clearance correction), while original-origin wrenches use the declared original application nodes. The comparison budgets must account for the declared small-displacement convention; a consumer must not silently replace original points by deformed contact points in only one channel.

## Admission changes required by composition

Baseline `contactstate.c:117–151` requires one small-displacement global mechanical static face-to-face penalty step and rejects every active structural element except `C3D4`/`C3D10`. Its selected-face helper at263–284 separately requires an original tetrahedral face. The global structural check is the relevant composition barrier; the selected-face check remains correct. Baseline Python `contact_state.prepare_request` already validates selected ordinary Contacts through actual stock-writer master/slave face tables and requires Tet4/Tet10 volumes at those faces. It does not itself impose a global pure-Tet mesh test.

The baseline beam observer independently refuses contact and two separate solid owners. `beamsection.c:863–1158` admits the exact V1/V2/V3 structural catalogue; its coupled branch rejects any `ntie`. Its V3 SOLID parser retains a single owner name, and the geometry validator requires one connected solid body. The baseline V3 physical SPC catalogue at756–860 contains only the beam guide, a true-solid Fixed region and the RBE's receiving-node algebraic prescriptions. A five-DOF physical guide at the detached RBE reference/rotation nodes is a new declared support type, not a relaxation of the old algebraic exclusion.

The proposed separate `CCX_BEAM_SECTION_V4` domain therefore needs a complete, independently validated catalogue containing the beam chain, its one scalar SPRING2, the two genuine tetrahedral owners, their distinct nodes and connected element groups, one selected native contact pair and both selected exterior faces, one detached solid-only RBE receiving region, physical beam/port/backing supports and one declared source. Source and support moment conventions remain explicit. A force source and an optional prescribed-translation actuator must have distinct source kinds: the latter reports its actual native projected SPC force, rather than pretending it is a point load.

The five physical RBE guide DOFs are reference-node transverse translations and rotation-node physical angles. Their translation reactions contribute forces at the reference point; their angle reactions contribute genuine couples. The separate receiving-node `typeboun='R'` dummy SPCs stay algebraic and are excluded from physical wrenches. Upstream `rigidmpc.f:73–126` shows why: each rigid equation contains receiving, reference, rotation and dummy terms, and generates a dummy R-type prescription. Baseline `bs_mpc_term` already observes the unchanged equation multiplier and coefficient contributions. The rigid-reference free body in V4 must include all three channels: spring end, internal rigid-reference action and physical guide action.

The official native restriction on a beam node in an RBE is also enforced by upstream `gen3dmpc.f:294–299`. Keeping original beam nodes disjoint from both true-solid owners, every contact face and every RBE receiving region is essential, not an artificial rank workaround.

## Authenticated coexistence and retained-frame lifecycle

The baseline patch prepares observers in the order force accounting, contact state, then beam. A mixed-domain authorization cannot simply test whether a beam request environment variable exists: malformed or legacy beam requests must not bypass the pure-Tet contact gate. One defensible diagnostic-only arrangement is to validate the complete V4 beam catalogue first, then expose a read-only authorization to contact preparation for exactly its admitted beam and scalar-spring elements. Legacy V1/V2/V3 and pure contact continue through their old paths. Reordering only observer preparation does not change solver mechanics.

The child requests must authenticate one another. Baseline `ccxtools.start_ccx` creates the contact run context before the beam run context and passes the resulting private child environment onward. The V4 child request can therefore bind the actual child contact request nonce and selected pair/surface identities. Both independent native observers must agree with that declaration; the existence of two unrelated environment variables is insufficient.

At the start of `results.c`, the patched `bs_begin_actions` precedes the contact-state inventory preparation and mechanical workers. Baseline `cs_begin_results` captures only retained `iout=2` evaluations. It obtains native point numbers, face labels, parameters, weights, original pair identity and preserved master projections before the actual constitutive callbacks. The callbacks then capture normal values, real stick/slip branches, elastic override and plastic increments. Baseline `cs_emit` validates and copies that complete retained frame before `resultsforc`. Only afterward does `bs_begin_results` begin the beam section-map observation, and `bs_frd_frame` commits the actual FRD STRESS dataset counter.

A V4 handshake must consequently require exact step, increment and cumulative-time equality between the already-copied contact frame, native mechanical actions and the actual beam STRESS dataset. These identifiers have different roles: contact-state V1 does not have a STRESS dataset number. Matching each observer's last row, pairing by list index, or renaming a contact sample ordinal as a FRD frame number would be incorrect. The baseline contact emitter replaces a duplicate evaluation of the same retained increment/time; a composed importer must still reject an ambiguous association with multiple matching STRESS datasets.

For active samples, the actual native contact branch and identities remain as already qualified by 9ii. For an inactive preserved projection, pressure/shear/plastic values remain unavailable rather than invented zeros; an unpaired sample also lacks measured clearance. A native assembled contact-action sum of zero is a separate mechanics observation and must not be relabelled as a measured zero local traction. The same distinction applies when contact elements are absent in an open state.

These are source-backed implementation seams and proposed safeguards. They do not by themselves enable a domain, qualify numerical tolerances, or establish that every open/stick/slip coupled fixture is mechanically stable. Runtime outcomes and final scope belong in the coordinating agent's retained validation record.
