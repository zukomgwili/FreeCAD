# FreeCAD-sv7: CalculiX 2.23 coupled beam-output semantics

Research date: 2026-10-31. This is a source-semantics investigation, not a runtime qualification or building-design acceptance. No FreeCAD, OpenCascade, solver, build, GUI or project execution was performed by the research agent. The installed baseline was reproduced by the coordinating agent before permission to inspect the affected FreeCAD implementation was given. No Oomakhi model was opened or changed.

## Evidence and version boundary

The primary sources are Guido Dhondt's [CalculiX 2.23 manual](https://www.dhondt.de/ccx_2.23.pdf) (19 October 2025), the [official 2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), and the repository's already-shipped native observer sources. Documentation for another CalculiX release was not substituted. The archive was read in memory, without extracting or executing it:

`/private/tmp/freecad-960-semantics-gdfoMero/ccx_2.23.src.tar.bz2`

SHA-256: `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7`.

All upstream source locations below mean members of `CalculiX/ccx_2.23/src/` in this pinned archive. The partial extracted source directory contains only selected files; references to other members are archive-member line numbers, not claims that those files were extracted. The official source-download link was verified on the [author's download page](https://www.dhondt.de/). The web fetch of the archive timed out, so its current remote bytes were not independently re-downloaded; the pinned local archive hash is the identity used here.

Baseline native extension: `3fdd2b7f7cc3198e7fd1a5dc89a71e0cfacbd1f6ee3e21b106e2171ed6b52d7a`. The source files inspected at the start of this investigation were:

| Repository artifact | SHA-256 |
| --- | --- |
| `package/calculix/force-accounting/beamsection.c` | `360a22558e769aac6259bb86c391e702bb928855c49a907733a0e9f4b97f10aa` |
| `package/calculix/force-accounting/beamsection.patch` | `69725584c7cbcd927fe02c0c2986b0545e2078a44371ac0b5bbc5f51e94e4b0e` |
| `package/calculix/force-accounting/hooks.patch` | `39898e56a8e4f6eb802d4ea5149d253f380d8f7a88f15af668c71a111f61f4af` |
| `package/calculix/force-accounting/forceaccounting.c` | `e25df61ffb38889a4287ce1eafc2b098a8b53dc7b272016d6b8bb722bfdcca91` |
| `package/calculix/force-accounting/contactstate.c` | `3c7e8d77f94bdd7c8bd54ac1cfe164a0577ca982bdc065f32c479c480f22a52e` |
| `package/calculix/force-accounting/contract.json` | `4f3859f919e6c765cc216aeca49a68cb7264e50c66d94a05ac1131e52448b46a` |

## What the official manual establishes

The 2.23 manual defines B32R through expansion to C3D20R (§6.2.33, pp119–126). Its direct common-node 3D-to-beam connection is hinged (§6.2.33, p123); a beam node is forbidden in an explicit rigid body (§7.113, p590), and ordinary Tie accepts true 3D elements rather than beams (§7.133, p620). SPRING1 is a grounded scalar spring; SPRING2 connects two scalar translational directions (§§6.2.40–41, pp128–129). OUTPUT=2D concerns expanded 1D/2D output; SECTION FORCES changes beam S channels, leaving other element types unaffected (§7.52, pp498–499). Generated connectivity, translation MPCs and rotation MPCs have different roles (§10.3, pp691–698). These are distinct restrictions, not a universal prohibition on an analysis containing both beams and genuine solids. [Primary manual](https://www.dhondt.de/ccx_2.23.pdf).

## Source-level identities and insertion points

1. `calinput.f:1325–1335` calls `gen3delem` before returning to the main C driver. Consequently the existing `fa_prepare`, `cs_prepare` and `bs_prepare` hooks in the main driver already see expanded topology. A classifier needing original beam incidence must capture it before this call or at the entry to `gen3delem`, before its topology mutation. Its input can retain the original element number, type, active state, original node tuple, and original node coordinates. It must distinguish elements originally authored as solids from beams that subsequently acquire a C3D label.
2. `gen3dfrom1d.f:35–57` retains each quadratic beam's three original nodes at `kon(ipkon(i)+20+j)`, `j=1..3`, while its first twenty entries become generated solid nodes. `gen3delem.f:385–390` changes B32R to `C3D20RB` at the same element number; it does not allocate a new element ID for the expansion. Generated node IDs are a separate namespace from the original three beam nodes. This explains why the baseline observer correctly binds the original tuple at C index `ipkon+20` in [beamsection.c:244](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/beamsection.c:244).
3. `elements.f:393–400` maps authored SPRING1 to native `ESPRNG10`, one node, and SPRING2 to `ESPRNG21`, two nodes. `elements.f:459–466` assigns its element number and connectivity offset independently. A mixed request must enumerate all original B32R elements and all admitted scalar springs exactly once, preserving their different identities and ownership. A spring element ID must never be used as a beam-end identity.
4. `gen3delem.f:426–434` calls `gen3dconnect` after expansion. For a non-knot beam node attached to a spring or solid, `gen3dconnect.f:158–214` creates the native relation `u1+u2+u3+u4−4u0=0` separately for each translation. The four expanded corner translations are linked to the original point. This is a translational mean, not a six-component rigid port.
5. `gen3delem.f:469–471` subsequently updates existing MPC terms. `gen3dmpc.f:294–299` explicitly rejects a RIGID MPC involving a non-knot beam node. At a knot, `gen3dmpc.f:65–75` maps authored rotational DOFs to the generated rotational node. `gen3dnor.f:891–915` creates that rotational node and an expansion node. An internally generated knot is not an ordinary user-authored rigid-body port, and its expansion/generalized coordinates must not be treated as physical force locations.

The early classifier is a read-only provenance hook. It must not change the user's mesh, construct extra solids, change stiffness, or manufacture RBE/Tie connections merely to fit an observer's existing domain.

## B32R resultants and the FRD S slots

The baseline observer copies the existing native integration increments; the following semantics remain applicable to a coupled analysis if that analysis is independently admitted:

- `map3dto1d2d.f:315–375` integrates each actual element end separately. Its supplied section-map coordinates are `co+vold`; the centroid is the mean of the four end corners. This history field is not guaranteed to contain the final solved displacement at mapping time; the exact linear-static call trace is audited below. The first end uses `e3=e2×e1`, while the last uses `e3=e1×e2`. The literal first-end basis is therefore left handed. Do not reconstruct it as a right-handed coordinate frame.
- `map3dto1d2d.f:425–450` interpolates the native extrapolated nodal stress and forms the quadrature traction. Lines460–488 project the native force and centroid-relative moment increments. [beamsection.patch:94](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/beamsection.patch:94) observes those already-computed values; [beamsection.c:389](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/beamsection.c:389) reports local projections and literal global vectors.
- The method still uses the prior expanded-node stress extrapolation and averaging in `extrapolate.f:1022–1062`. Capturing before **original beam-node** averaging does not remove this earlier averaging or make the end integral an exact equilibrium recovery. A coupled interface may introduce local stress gradients that require mesh sensitivity evidence.

| Native array component | Beam-section meaning | Legacy FRD name | Units |
| --- | --- | --- | --- |
| 1 | force along e1 | SXX | N |
| 2 | force along e2 | SYY | N |
| 3 | force along outward face normal | SZZ | N |
| 4 | moment about outward face normal | SXY | N·mm |
| 5 | moment about e2 | SZX | N·mm |
| 6 | moment about e1 | SYZ | N·mm |

The last two serialized names appear in the opposite order: `frd.c:1017–1027` writes SXX,SYY,SZZ,SXY,SYZ,SZX. The mapping is established by the actual source projections, not by interpreting the channel names as a stress tensor. Genuine solid-node rows still contain stress components in MPa; a mixed dataset can therefore contain different physical dimensions at different node owners.

`noelfiles.f:246–271` applies OUTPUT=2D through the output flags and marks section forces with `filab(3)(5:5)='M'`. Although the manual describes a last-selection rule, the pinned 2.23 implementation at `noelfiles.f:321–330` produces an input error if SECTION FORCES and active OUTPUT=3D coexist. The production writer should preserve an explicit conflict refusal.

`map3dto1d2d.f:63–147` skips genuine solid elements, identified by a blank/I seventh type character, but clears the result values and markers at original 1D/2D nodes before remapping. `frd.c:555–588` continues writing true Tet10/Tet4 topology. Therefore:

- A disjoint original-node partition between beams and genuine solids is a viable output candidate. A consumer can retain solid-only S rows as stress and beam-only rows as section quantities, provided it binds that exact original mesh and output context.
- A node shared by an original beam and solid has no unambiguous scalar-row ownership. Clearing/remapping the beam node can overwrite the solid nodal stress. Refuse that topology for a mixed nodal S import until a separate per-owner output is qualified; do not average N, N·mm and MPa together.
- Detaching nodes by identical coordinates is not sufficient evidence of a physical connection. Conversely, distinct node identities coupled by a legitimate native MPC preserve separate output ownership.
- Bare FRD rows without trusted deck/mesh context cannot establish these partitions. The 960 section-marker and stale-output protections still apply.

## SPRING1/2 semantics and diagnostic-only observations

`springforc_n2f.f:124–208` is the actual native scalar-spring force path. SPRING1 uses a three-entry direction vector and the three translational values at its node. SPRING2 uses two such directions; it calculates scalar extension from the two projections and returns `fnl(:,1)=fk*n1`, `fnl(:,2)=−fk*n2`. The source does not translate a requested DOF4–6 into beam rotation: it indexes a three-entry vector. Such direct rotational requests must be refused before reaching native code, even if the input parser stores the integer. A rotational spring on a detached angle auxiliary is a different, explicitly declared generalized-coordinate mechanism.

For a finite linear grounded spring, a read-only observer can safely capture:

- the original spring element ID, its sole original node, current native displacement, actual orientation/basis and law identity;
- the already-computed `fnl` global vector, with explicit signs: `spring_on_node = −fnl`; `node_on_spring = +fnl`;
- the corresponding force-only wrench about a declared origin, using a qualified original application point. It must label whether it is the force **on the structure** or **on the ground**. Dummy coordinates of angular auxiliaries are not force application points;
- the exact retained output case: step, increment, cumulative time, FRD dataset, and the same child/request/deck/binary identity as the beam rows.

No Python K·u recovery, FRD RF subtraction, changed law, altered displacement or extra stiffness is needed. K·u is useful as an independent analytical oracle, not as the source of an alleged native measured action. At the free spring node the assembled RF can combine beam, spring and constraint contributions; it is not an isolated spring action.

An appropriate hook is immediately after the genuine-spring `springforc_n2f` return in `resultsmech.f:412–420`, before its `fnl` is assembled into `fn` at 448–454. Each worker owns its element range. Allocate per-element slots before launch; validate completeness after `results.c:233–238` joins the workers. Capture begins for the actual retained `iout=1` or `iout=2` before that launch. The current [beamsection.patch:52](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/beamsection.patch:52) begins beam mapping only later, immediately before `resultsprint`, so its existing capture-start position cannot capture earlier spring callbacks. Commit the spring observations only when [beamsection.c:500](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/beamsection.c:500) binds the matching actual FRD stress dataset. Empty, duplicate, nonfinite, undeclared, wrong-time and incomplete observations must fail.

For the first candidate, require a straight, zero-offset, rectangular B32R endpoint with one native section and a finite positive linear translational spring. `gen3dconnect`'s arithmetic mean applies force to the expanded-section mean translation. A beam reference line offset from that centroid cannot silently supply the position for an original-origin moment. Beam observations use native map-supplied centroids, whereas V3 accounting uses original positions; transport and first-order/small-displacement tolerances must keep those conventions explicit. In the qualified linear-static path the section-map geometry can retain the prior/reference state; it is not a solved displacement result.

## Why the current accounting/contact opt-ins do not compose automatically

The shipped observers have independent global admission gates:

- [beamsection.c:183](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/beamsection.c:183) accepts every active element only if it is expanded B32R. Its complete requested beam catalogue check at260–262 is useful, but must become a complete **beam subset** check only after other element classes have explicit admission.
- [forceaccounting.c:313](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/forceaccounting.c:313) recognizes only original Tet4/Tet10 volumes. Lines1022–1043 additionally allow declared V3 ESPRNG21 and generated face-contact springs, while rejecting beams and SPRING1. Its body ownership and face tables are tetrahedron-specific, so labeling a beam expansion as an ordinary structural solid would be incorrect.
- V3 ports/spring endpoints must be detached from all recognized structural volumes ([forceaccounting.c:576](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/forceaccounting.c:576),622–657). Direct original beam endpoint springs have a different ownership rule. V3 requires every spring and port declaration to be used and validates actual native law/axis properties.
- V3's `fn−p` MPC projection and selected SPC residual are separate channels ([forceaccounting.c:1416](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/forceaccounting.c:1416),1470–1507). Spring forces already contribute to `fn`; adding them again to LOAD or MPC would double count. A grounded spring at a free displacement DOF is not an SPC support and needs its own observed physical support action.
- [contactstate.c:141](/Users/zukomgwili/src/FreeCAD/package/calculix/force-accounting/contactstate.c:141) currently rejects every active non-tetrahedron, even if a selected contact pair only involves valid Tet faces. The selected-face reader at263–284 is independently tetrahedral; generated contact catalogue and exact sample inventories are validated at357–500. A mixed analysis might relax the **unselected structural catalogue** after qualification while keeping selected contact faces strictly Tet4/Tet10. It must not silently turn an expanded beam face into a supported contact owner.
- Contact state is captured only at retained `iout=2`; beam output supports retained `iout=1` or `iout=2`. Same-case composition requires an actual common step/increment/time frame, not selecting each observer's last row independently. Existing contact state labels/point inventories, per-side force signs, original-coordinate protection and actual branch diagnostics remain intact.

## Capability classification before runtime qualification

| Composition | Source-semantics assessment | Defensible initial boundary |
| --- | --- | --- |
| Frozen pure B32R 960 case | Already qualified baseline | Preserve all existing checks and results. |
| Beam endpoint plus grounded SPRING1 translation | Native mean-translation connection and force evaluation exist | Candidate for a separately observed spring support, zero offset, simple endpoint, DOF1–3, finite positive single linear law, original coordinates, one retained static 3D case. |
| SPRING2 between original beam endpoints | Native translational path exists | Investigate separately: full two-end identity/action-reaction, correct application-point moments and scalar response; do not infer a general six-component joint law. |
| Original beam nodes as explicit RBE members | Explicitly forbidden by manual and non-knot native MPC code | Retain refusal; do not weaken solid-head noncollinearity checks. |
| Original B32R end as ordinary Tie surface | Explicitly outside native Tie's element domain | Retain refusal; internal solid expansion is not an authoring bypass. |
| Beam sharing one node with a genuine solid | Native translational hinge; ambiguous mixed nodal S row | Do not claim moment continuity or safe solid stress import. A separately qualified hinge model/output representation is required. |
| Separate beam and solid regions connected by admissible native translational equations/ports | No universal solver prohibition established | Investigate exact public authoring, constraint graph, owner partition, forces and origin moments; retain refusal without that evidence. |
| Mixed beam plus ordinary Tet-to-Tet Tie/contact elsewhere | No source reason SECTION FORCES itself destroys true-solid output | Candidate only with separate original node ownership, selected Tet faces, compatible observer admission and same-case force/contact checks. This does not qualify direct beam-face Tie/contact. |
| Six-component beam-to-solid rigid/elastic joint | Not established by a shared point or beam RBE membership | Requires a separately justified native interface; no automatic enabling based on B32R expansion. |

After the installed baseline, the public FreeCAD path was inspected statically. [ObjectsFem.py:346](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/ObjectsFem.py:346) creates ElasticConnector; `Attachment=Vertices`, `Kind=Translational`, `Mode=Ground` is the existing native SPRING1 route. [write_constraint_elastic_connector.py:43](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femsolver/calculix/write_constraint_elastic_connector.py:43) exports fresh scalar spring IDs, orientation and metadata. Its [output comments:121](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femsolver/calculix/write_constraint_elastic_connector.py:121) correctly warn that RF is not isolated connector action. The similarly named `ConstraintSpring` is an Elmer foundation, explicitly refused for CalculiX by [elastic_connector.py:412](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtools/elastic_connector.py:412). That object should not be repurposed implicitly.

## Numerical and evidential limits

Analytical fixture thresholds must be frozen independently of measured residuals. In particular, `printoutnode.f:36–42` writes native U with `(i10,1p,6(1x,e13.6))`, and lines 94–104 write RF with `(i10,1p,3(1x,e13.6))`: seven significant digits. Each nonzero printed scalar has rounding at most `0.5·10^(floor(log10(abs(value)))−6)`, before analytical propagation. Native observer JSON uses seventeen significant digits; stock writer spring stiffness uses `.12e` and orientation `.13G`. These serialization budgets do not replace spatial convergence, section-integration accuracy, mechanical response or independent equilibrium limits.

A beam/spring fixture can independently compare actual observed spring force against K times the projected printed displacement with its reporting budget, the spring's equal-and-opposite node/ground actions, six-component beam ends, external forces, and origin moments. A translated/rotated fixture can expose wrong moment arms and frames. A negative fixture must exercise illegal rotational scalar DOFs, unsupported port membership, wrong output flags, ambiguous shared ownership, and stale/incomplete source identities. Save/cold-reopen must retain literal historical output without inventing current process ownership. A runtime executor must establish these claims; this research note does not do so.

No source evidence here changes the original Oomakhi 1% equilibrium/paired-cut or 5% sensitivity limits, establishes its joint laws, approves its loads, or accepts its building design.

## Pinned upstream member hashes

| Upstream 2.23 member | SHA-256 |
| --- | --- |
| `calinput.f` | `4a6a4c43d6919857be539a532673780a6b528aee538dd4ec78269e07fb5bf32d` |
| `elements.f` | `39bed8cd895209c9fff63ba871460d379550f2777a2e87a64fb61c198262ba6f` |
| `gen3delem.f` | `85bf8fee6e5d240b4b1cf615e5daae37ccfa49590f0d5f1b2300210fe8429115` |
| `gen3dfrom1d.f` | `9115eb59a43467972581e71bbd123bfbb3858166b1927521f32ff0261ef57162` |
| `gen3dconnect.f` | `6786ae8bf9d62f1bbc2a8a308b8d3f0324ed52b336bc5f69510a76b149b34ca7` |
| `gen3dmpc.f` | `07a5125b59b3580c77231de148939dedc913edf6bcfcc0e1c3f6d4a070467574` |
| `gen3dnor.f` | `bfcd799e2edda32d800638781aa9502615209e643658c0c987b6f317da421192` |
| `springforc_n2f.f` | `706d066ef4b951c6382b754094bc576d98865b86f6272da535b588c7e7282d60` |
| `resultsmech.f` | `15fccc9fb553f259af5d33bc78e8d3808f1f9f338ee266ce92192bae33026fa6` |
| `results.c` | `9113a4984342355ff15bb16a609c5bdb034183c951719b064037b3858eac24dd` |
| `map3dto1d2d.f` | `ec0520c711784a4df7def04522c9d0b0b28980f63d8145a71018011f64d3bf87` |
| `extrapolate.f` | `504891169bcc6023841659df2fbba34d5d2f34a23e4bb396afc48b99d6112ac7` |
| `noelfiles.f` | `ed85b45d6987882e484f11a0be3dc9c2d716afba07d59483d364e0709107a59f` |
| `frd.c` | `6439bca2ae53c813ab6887c3c560dd15db5947fd8cf9b9f01ada5753d5ed9915` |
| `printoutnode.f` | `ed77454fbf771c38ebbb32f0785013dae3585eca50e5cc7b28c646dec0ce4b94` |

## Additional mixed-domain investigation

This section records static findings obtained after the coordinating agent began implementing the first SPRING1 domain. It does not certify that domain or a mixed-domain implementation.

### Public authoring and export

A hybrid connector directly from a beam vertex to a writer-created RBE reference cannot be authored through the current vertex route: [elastic_connector.py:245](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtools/elastic_connector.py:245) requires exactly one original mesh node found by a CAD vertex, while its lines 257–267 allocate detached reference/rotation node IDs only during writing. Rigid-body attachment requires both ends to be explicit rigid bodies; vertex attachment requires both rigid-body links empty. Neither mode silently supplies a mixed endpoint type.

An available public alternative is a translational two-point ElasticConnector between the beam endpoint vertex and an actual genuine-solid vertex. Each resolves to one original mesh node. That solid vertex could independently be a slave in an explicitly selected, noncollinear solid RBE region, with the RBE transferring its point load and moment; the beam vertex must remain outside the rigid-body membership. A first beam/solid series benchmark needs no RBE at all, so this extra mechanism can be qualified separately without weakening RBE rank checks.

The stock CalculiX mesh writer currently prevents the physical series from reaching the solver even after the high-level mixed-domain refusal is removed. [write_mesh.py:38](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femsolver/calculix/write_mesh.py:38) uses native `writeABAQUS` mode 1. [FemMesh.cpp:2031](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/App/FemMesh.cpp:2031) then omits all edges when genuine volumes exist. The existing public native mode 2 writes volumes, standalone faces and standalone edges, as implemented at lines 2009–2066. A narrowly admitted mixed analysis can select mode 2 through the ordinary writer; it does not require a new native export API, a manually edited deck, or additional structural elements.

Material/geometry set generation already appends the solid and beam sets independently for one material ([meshsetsgetter.py:790](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femmesh/meshsetsgetter.py:790)); its single-material solid set uses `Evolumes`, while beam sets use edge-direction catalogues. [meshtools.py:508](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femmesh/meshtools.py:508) already builds those beam tables from `EdgesOnly`, matching mode 2. Native `getEdgesOnly` at [FemMesh.cpp:799](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/App/FemMesh.cpp:799) checks whether an edge's nodes are contained in an explicit mesh face; it does not directly check volume incidence. Admission must therefore verify the actual exported beam catalogue and reject accidental solid-boundary edges. Mixed multiple-material selection is separately documented as unsupported at `meshsetsgetter.py:738–743`; one isotropic material is the appropriate initial boundary.

A second ordinary-writer defect matters for this route: [write_constraint_fixed.py:59](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femsolver/calculix/write_constraint_fixed.py:59) names mixed fixed sets `<name>Solid` and `<name>FaceEdge`, while [write_step_output.py:89](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femsolver/calculix/write_step_output.py:89) asks for RF on the unsuffixed `<name>`. The mixed production writer must bind that ordinary output to actual written node-set identities. A beam-root Displacement uses its normal unsplit node-set name.

### Minimal connected analytical series

One independently solvable discrete fixture consists of a real tetrahedral CAD solid and a separate straight beam line in a compound, linked only by an explicitly authored vertex SPRING2:

| Quantity | Frozen candidate value |
| --- | --- |
| Beam | x=0 to40 mm at y=17,z=−23 mm; rectangular 4×4 mm B32R chain |
| Material | One isotropic E=200000 N/mm², ν=0 |
| Spring | Global X, K=10000 N/mm, beam tip (40,17,−23) to solid apex (50,17,−23) |
| True tetrahedron | Apex above; base x=70 mm and yz vertices (12,−28),(22,−28),(17,−13) |
| Supports | Beam x=0 node: Y,Z and rotations X,Y,Z fixed at zero, X free; all three solid base vertices fixed in translation |
| Source | +100 N in global X on the beam x=0 vertex |

The tetrahedron has base area75 mm², height20 mm and volume500 mm³. For ν=0 its linear shape function at the apex is `N=(x_base−x)/H`; hence the exact *discrete Tet4* stiffness at the sole free axial apex DOF is `K_tet=E·V/H²=250000 N/mm`. This is an inference from the affine native shape functions in `shape4tet.f:45–71` and elastic strain energy, not a recovered solver force or a continuum point-load accuracy claim. All transverse apex freedom is stable through the fixed base. The expected displacements are apex0.0004 mm, spring relative0.01 mm, beam shortening0.00125 mm and source0.01165 mm. The beam end forces are +100 and−100 N in global X; physical stabilizer forces and couples are analytically zero but must still be observed and checked individually. Each solid base support has Fx=−100/3 N. The true constant Tet4 stress is Sxx=−4 MPa, with other components zero.

The translated source moment about the global origin is (0,−2300,−1700) N·mm, opposed by the solid supports. This checks physical reference coordinates without inventing an RBE, accepting a collinear rigid region, adding artificial material, or treating a scalar spring as a six-component joint. A separate load direction or offset fixture is needed before admitting general noncollinear scalar-spring arrangements.

### Additional native stress-averaging hazard

Disjoint beam/solid node ownership is necessary for mixed S slots but is **not sufficient** for a solid vertex directly attached to SPRING2. Pristine `extrapolate.f:400–406` increments `inum` for both SPRING2 endpoint nodes and cycles without adding a stress contribution. Its lines 1057–1061 subsequently divide the solid nodal stress by that count. In the one-Tet fixture the spring-attached apex therefore has a native FRD stress of −2 MPa despite a true element stress of −4 MPa; the three unconnected base nodes retain −4 MPa. The beam mapper resets the original beam-node counts, so this specific dilution does not change the already-qualified beam-end observation.

This is stock nodal-output averaging behavior. A safe consumer can explicitly withhold stresses at scalar-spring nodes while retaining trusted unaffected solid-node rows, or expose a separately qualified native solid integration/owner channel. It must not multiply FRD values by an inferred correction or silently modify native arrays. Existing `*EL PRINT` element stress would have separate semantics, but the stock writer currently leaves that request commented out and there is no established production reader here. A detached RBE reference spring endpoint avoids this direct structural-node averaging effect, but the public hybrid endpoint seam remains absent.

The normal mechanical result also has a field-identity limitation: [importToolsFem.py:372](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/feminout/importToolsFem.py:372) sets NodeNumbers from the displacement dictionary and then, at390–402, appends stress dictionary values without matching node keys. Simply deleting beam and spring-contaminated S rows from a mixed displacement result misaligns the stress arrays. Safe options include a separately named solid-stress result with a matching solid-only field/node catalogue, or a field-specific node-identity interface. Zero-padding absent beam stresses would falsely assert MPa=0. Retain the full mixed displacement-only result and native beam result independently.

### Accounting and contact consequence

The initial mixed observer can directly report the native two-ended SPRING2 action, the exact source and **both** physical support catalogues, using the already-calculated global internal/external residual and the actual native MPC graph. It should make no claim to extend the old solid cut format merely because it can report these global actions. A direct solid-node spring is an external action for the selected solid subbody; if the existing body accounting is extended, that action needs explicit attribution. The current detached-port V3 rule that spring effects must not be added again to LOAD/CONTACT/MPC cannot be copied indiscriminately to a spring attached inside a solid AccountingBody.

For a subsequent contact series, keep the selected contact faces genuine Tet4/Tet10, distinct original beam/solid nodes, exact existing contact inventories and constitutive branches. Replacing the solid's fixed base by a contact interface introduces real transverse/rotational stability questions. A moving frictionless contact body needs explicitly authored physical guides, and all guide reactions must be observed; no omitted reaction may be presumed zero. An opposing Tet prism with its remote face fixed is a straightforward contact partner. This remains a separate runtime qualification, including exact same retained step/increment/time binding, paired force/moment balance and unchanged 960 output mechanics.

Additional upstream hashes: `shape4tet.f` = `5563aae2e15402407c8f90058633aa8e097a051201a67c7dbc63f77edd1b362c`; `gen3dboun.f` = `e41bc5ea10d7d5e450677e89e1ce26aa56b304e4cb8c0520fcc5be0b857ef2f0`; `usermpc.f` = `d37704bb51f23394667af51096c9e8fab81a5731a2db1a165d45f22b8e55b3f9`.

## Conditional production route: saved vertex-to-solid-port attachment

The direct solid-vertex SPRING2 example above is an investigative discrete oracle, **not the recommended production route**, because its solid nodal S contamination is an actual native source behavior. A conditional alternative is to extend the existing ElasticConnector object's saved Attachment enumeration with an explicit `Vertex to rigid body port` value. This reuses the established ObjectsFem ElasticConnector and RigidBody classes and existing properties; it is not an additional public object class or an implicit rigid region. No implementation or runtime qualification of this option was performed by the research agent.

### Unambiguous saved interface

The new value should have exactly one interpretation:

| Property | Required meaning |
| --- | --- |
| Attachment | `Vertex to rigid body port` |
| Kind | `Translational` |
| Mode | `Two points` |
| End1 | One CAD vertex resolving to one original B32R endpoint node |
| RigidBody2 | One explicitly authored, active, same-analysis RigidBody on a genuine solid region |
| End2 and RigidBody1 | Empty; conflicting saved links refuse |
| Axis/Orientation/Stiffness | Existing saved scalar spring direction and finite positive N/mm stiffness |

Reversing the two physical endpoints is not needed for the first option: both actual native forces can still be inspected. Rotational hybrid attachment, Ground mode, an inactive/missing RBE, links outside the analysis/document, unresolved vertices and unknown attachment values must refuse. Do not silently ignore conflicting properties, infer a rigid region from a point, create material, or convert a beam node into a rigid-body slave.

[ConstraintElasticConnector.onDocumentRestored:54](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femobjects/constraint_elastic_connector.py:54) currently adds only **missing** properties. Merely extending `_properties()` therefore does not update the enumeration list in older files that already contain Attachment. A compatible migration must append the new enum choice while preserving the existing selected label, all physical links and their meanings. Existing `Vertices` and `Rigid body ports` models must continue to restore literally. The ordinary command at [commands.py:380](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femcommands/commands.py:380) currently rejects every mixture of vertex and RBE selections; its creation path can recognize exactly one of each and choose this saved option, while keeping all other mixed selections invalid. Validation must also apply to property-editor/programmatic authoring.

### Resolution, ownership and writer constraints

The resolver can retain the original beam vertex node and independently resolve the explicit solid RBE using the current strict `rigid_body_nodes()` and shared `PortResolutionContext`. Every receiving node must belong to a genuine Tet4/Tet10 volume, and the receiving region must contain at least three noncollinear nodes. Its nodes must be disjoint from **all** original beam nodes, not merely the chosen endpoint: membership in a solid volume alone does not make an original shared beam node legal in an RBE. Retain the existing unresolved-reference, rank, duplicate/overlapping-region, coordinate and owner checks.

Use `rigid_body_node_ids(analysis,mesh,body,context)` for the exact reference and rotation identities already emitted by the normal rigid-body writer. The hybrid SPRING2's two native nodes are `[beam_vertex_node, solid_reference_node]`. The rotation node is not a spring endpoint and does not belong to any element. Both reference and rotation nodes remain detached from the original solid connectivity. The RBE reference position has physical significance; the rotation node's stored coordinates are not a moment arm.

The current writer at [write_constraint_elastic_connector.py:50](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femsolver/calculix/write_constraint_elastic_connector.py:50) treats `bodies` as a homogeneous list and replaces **all** endpoint nodes with port nodes. The hybrid result therefore needs explicit ordered endpoint metadata, rather than reusing that branch with a one-body list. The metadata should bind the connector name, kind, spring element ID, original beam vertex identity, RBE owner, detached reference/rotation IDs and the exact receiving-node inventory. Do not misrepresent it as the existing two-RBE V3 declaration.

Include the new mode in the writer's owned-facts fence currently triggered only for `Rigid body ports` at lines 19–25. `_connector_state()` already records Attachment, Mode, Kind, End1/End2, RigidBody1/RigidBody2, direction and stiffness; register the hybrid state before its native resolutions. Fence active/suppressed membership as well as analysis ordering, native mesh identity and explicit RBE references. `get_member()` at [membertools.py:61](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtools/membertools.py:61) is suppression-aware, whereas a simple `body in analysis.Group` check is insufficient. Continue to allocate the spring element after the original mesh catalogue and to emit RBE nodes before spring elements through the ordinary stock writer.

The existing blanket `Rigid Body connector ports are qualified for solid-only analyses` predicate must remain applicable to unsupported combinations. A new exception can be confined to the explicitly qualified hybrid domain; it must not remove the beam/shell RBE prohibition or qualify arbitrary existing two-RBE connector graphs in a mixed analysis. Native export mode 2, single-material limitations and split Fixed NSET correction described above are still necessary.

### Why genuine solid S is preserved on this route

The scalar spring's `inum` increments now affect an original beam node and a detached RBE reference. Neither is an original Tet node. Consequently pristine `extrapolate.f:400–406` adds no spring count to the genuine solid stress nodes. This is a statement about incidence, not a claim that the RBE leaves the model mechanics unchanged: the user explicitly authors a rigid receiving face, and its effect on deformation/stress is real.

Solid mechanical stress output must include only the exact original Tet-node set. Beam-node section quantities and any reference/rotation/helper-node S rows are excluded. A new solid-only result must align its displacement, stress, strain and NodeNumbers keys before conversion and compaction; the existing full mixed displacement-only result and native beam result can remain separate. Reject shared original beam/Tet nodes or a scalar spring endpoint with direct Tet incidence. Preserve literal native solid S values; no count correction, extrapolation or Python stress recovery is justified.

### Minimal physical prism benchmark

Use a triangular solid prism, not an artificial eligibility pad: near face x=50 mm, far face x=70 mm, both with yz vertices (12,−28),(22,−28),(17,−13). The prism has area75 mm² and length20 mm; three positively oriented Tet4 elements can partition it. If near nodes are n0,n1,n2 and corresponding far nodes f0,f1,f2, one affine-compatible partition is `(n0,n1,n2,f0)`, `(n1,n2,f0,f1)`, `(n2,f0,f1,f2)`.

Create an explicit RBE only on the three near-face solid nodes, reference=(50,17,−23), with all six modes Free. Fix all three far-face nodes in translation. The fixed face stabilizes the solid; the RBE reference is a moving internal port and is **not an external support**. Connect the existing x=0..40 mm, 4×4 mm B32R beam tip to that reference through the hybrid scalar SPRING2, K=10000 N/mm. Retain the beam's five zero guide motions at x=0, apply +100 N in X there, and use one E=200000 N/mm², ν=0 material.

The exact affine discrete solution is uniform solid Sxx=−100/75 MPa, reference Ux=`P·H/(E·A)`=0.0001333333333 mm, spring relative Ux=0.01 mm, beam shortening0.00125 mm and source Ux=0.0113833333333 mm. The original solid node stresses all retain this MPa meaning and are not diluted by SPRING2. Every beam-guide force/couple and every solid-support component still requires an actual native observation; analytically zero channels are not optional. The global source moment remains (0,−2300,−1700) N·mm and must balance the observed supports. This is a deliberate rigid-face linear benchmark, not a statement that every engineering beam/solid joint is rigid or axial.

### Port actions and same-case accounting

The isolated native spring vector at the detached reference is an internal connector action, not the combined RF at a free port. The actual MPC graph can separately supply the aggregate RBE action on its solid receiving nodes and the opposite generalized action at reference/rotation DOFs. For a strict first benchmark with one RBE and no additional owner-sharing equations, the sum of native MPC nodal actions on the receiving region provides its force and reference-relative moment; the reference force plus the genuine rotation-node couple provides the opposite wrench. Translate reference forces using the actual original reference position, never the rotation node's dummy coordinates. Preserve old accounting's distinction between aggregate MPC action and per-law/individual-row multipliers.

Bind the two spring-end actions, RBE port actions, source, physical beam guides, solid fixed-face supports and beam ends to one retained native step/increment/time/FRD dataset and the same request/deck/binary/child provenance. Validate action/reaction independently in force and origin moment. A free RBE must not enter the legacy empty-support-list fallback, which currently selects all rigid bodies at [force_accounting.py:170](/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtools/force_accounting.py:170). Either keep legacy NativeForceAccounting explicitly unavailable for this new domain or qualify a separately declared complete support/port schema; do not relabel the moving port as a support to satisfy an old parser.

Only after that benchmark and its negative/lifecycle controls pass can a contact variant be considered. The selected contact surfaces must remain true Tet faces with unchanged native identities and local diagnostics. Native beam-RBE or beam-Tie membership stays forbidden. A contact variant must account for any added guides and preserve one actual common retained case; the presence of a valid spring/rigid port does not qualify the contact domain automatically.

## Correction: classical axial extension is not an exact native endpoint oracle

The earlier sections' statements treating the beam's `P·L/(E·A)` extension, and therefore the complete series tip displacement, as an exact affine **native B32R discrete** solution were too strong. The solid's ν=0 affine response, the scalar spring extension and the six-component equilibrium references remain independent analytical references. The following source evidence invalidates the claimed exactness for the native beam endpoint displacement. This is a correction to the reference, not a change of geometry, loading, mechanics or numerical acceptance limits.

The coordinating executor reported that `hybrid-green-r03` passes source/spring/RBE/physical-support force and origin-moment checks, beam Fx=±100 N, genuine solid Sxx=4/3 MPa, reference Ux=0.0001333333333 mm and spring relative Ux=0.01 mm. Its optional classical-series tip check fails: native FRD Ux=0.0114182 mm versus 0.0113833333333 mm. These are reported observations; the research agent did not execute or inspect that native run. Their difference is not used to choose a new expected constant or widen a tolerance.

### The pinned endpoint mechanism

In pristine CalculiX 2.23, a non-knot beam point force takes the branch `gen3dforc.f:842–900`. Lines 879–892 connect the four expanded section **corners** with coefficients +1,+1,+1,+1 and the original point with coefficient−4. Virtual work therefore couples a point force P to

`u_point=(u_corner1+u_corner2+u_corner3+u_corner4)/4`.

The conjugate section loads are P/4 at each corner and zero at the four midside nodes. `gen3dconnect.f:158–214` uses the same translational relation for the spring attachment. `gen3dboun.f:1173–1228` uses it for the prescribed original beam translation. The rotation-guide generation also constrains the quadratic section midsides at the guided root (`gen3dboun.f:966–1019`), but no corresponding rotation-guide midside condition is imposed at the free loaded tip in this fixture.

This source branch must be distinguished from the eight-node endpoint load vector described elsewhere in the manual. It is the actual pinned source mechanism being qualified. No blanket claim about another CalculiX release follows from it.

### Independent virtual-work proof

The native eight-node quadratic face shapes are explicit in `shape8q.f:63–70`. For a planar rectangular section, their face averages are −1/12 for each corner and +1/3 for each midside node. For example, a corner shape has the form

`N_corner=(1+s·ξ)(1+t·η)(s·ξ+t·η−1)/4`, with s,t=±1.

Integrating over the symmetric reference square eliminates the odd terms; its average is `(−1+1/3+1/3)/4=−1/12`. A midside shape has average `(1−1/3)/2=1/3`. Thus a uniform axial stress with resultant P supplies the consistent eight-node face load vector

`f_uniform = (−P/12 at each corner, +P/3 at each midside)`.

The native point-force relation instead supplies

`f_point = (+P/4 at each corner, 0 at each midside)`.

These vectors have the same resultant and the same first moment for the symmetric section, but they are not the same loading. Their difference is a self-equilibrated end load: +P/3 at each corner and−P/3 at each midside. A midside virtual displacement at the unconstrained free end therefore has nonzero residual under the presumed uniform-strain field. Consequently the affine `P·L/(E·A)` field is not an exact solution of this discrete endpoint problem. Setting ν=0 removes Poisson coupling; it does not remove the admissible section end-deformation modes excited by this load distribution. This argument is derived from the source and weak-form virtual work, independently of the reported displacement error. It does not predict or fit the error's numerical magnitude.

### Section-map position must not replace ordinary FRD displacement

The earlier version of this note incorrectly equated native section centroid minus original endpoint with final FRD U. Although both operations involve the same section corner identities, they do not consume the same displacement array at the same time. Ordinary U is mapped from solved `v` by `map3dto1d2d_v`; the stress/section mapper constructs its geometry from the separately passed `vold`. The linear-static driver updates `vold` only after that mapper returns. The detailed source audit below supersedes every earlier description of those geometry samples as guaranteed current solved positions. The paired beam-displacement acceptance uses ordinary FRD U, independently of those section geometry fields.

### A paired native control with the unchanged tolerance

A defensible composition control is a separate pure-beam native V1 case, authored through the ordinary writer, with identical original beam geometry, two Seg3/B32R elements, section, material, axes and +100 N tip force. It has no spring, solid, RBE or coupled request. At the root prescribe the **independently calculated** series translation

`Ux=P/K_spring + P·H/(E·A_solid)=0.01013333333333333 mm`,

with the same five zero Y/Z/rotation guides. This value comes from the analytical solid and spring laws; it must not be read from the mixed output. Native `gen3dboun` then imposes the same four-corner translation relation that `gen3dconnect` uses at the mixed spring endpoint. In a stable linear system, replacing the external series subsystem with this known root translation gives the same condensed beam boundary problem, irrespective of how the native solver pivots or decascades equivalent MPC equations.

Compare the actual mixed and pure-control original-node displacement vectors using the original absolute 1e−6 mm tolerance, including the tip, rather than substituting the observed mixed value as a reference. Preserve independent analytical spring, solid, support, port and six-component beam equilibrium checks and their existing limits. Inspect both native decks' unmodified beam declarations and physical constraints; bind actual original-node identities and the same component/frame. The paired check demonstrates that coupling has not changed the native beam mechanics. It does **not** validate classical rod stiffness or establish a new continuum accuracy tolerance.

The classical 0.0113833333333 mm tip value can remain visible as an ideal-rod diagnostic, explicitly outside exact-native-displacement acceptance. Any acceptance claim based on the revised control remains conditional on the executor actually running it successfully; this source investigation alone does not close the qualification. The fixed geometry, +100 N load, 1e−6 comparison tolerance, equilibrium limits and downstream project limits are unchanged.

Additional pinned member hashes: `gen3dforc.f` = `4585a7c01eb4b20667a99a5778154e4286c1fdd83d17ae8026d45598947ce7f5`; `shape8q.f` = `626d16d09d2d83a92a05e951d5d2c4f783f48946d44547a8e404bb891f6f3676`. All other source hashes are recorded above.

## Exact section-geometry state audit

The coordinating executor subsequently reported raw hybrid samples at exactly `(0,17,−23)`, `(20,17,−23)`, `(20,17,−23)`, `(40,17,−23)`, while native spring-end displacement was about0.0101333333 mm and ordinary FRD tip Ux about0.0114182 mm. That directly contradicts the earlier claim that captured section positions are necessarily final deformed positions. No run was executed by the research agent; the following independent source trace explains the reported distinction.

| Pinned 2.23 source | Actual data flow |
| --- | --- |
| `linstatic.c:346–373` | The preliminary evaluation uses `iout=−1`; the retained result is selected with `iout=1`. |
| `linstatic.c:793–830` | A fresh `v` allocation and the separate existing `vold` pointer are passed to the retained `results` call. |
| `results.c:170–174`; `resultsini.c:43–56,184–221,231–309` | `resultsini` puts the solved active values from `b`, prescribed SPC values and resolved MPC values into `v`. It does not copy that solved array into `vold`. |
| `results.c:460–462` | `resultsprint` receives both solved `v` and the distinct `vold` argument. |
| `resultsprint.f:166–173` | Ordinary original-node primary variables are mapped by `map3dto1d2d_v(v,...,nactdof)`. |
| `resultsprint.f:275–277` | The stress extrapolation, including SECTION FORCES, receives `vold`. |
| `extrapolate.f:1068–1070` | The stress extrapolator forwards `co,vold` unchanged to `map3dto1d2d`. |
| `map3dto1d2d.f:321–341` | Section coordinates are `co(node)+vold(node)`. Both centroid and face basis are calculated from this map-supplied geometry. |
| `linstatic.c:836` | Only after the retained `results` call has returned is solved `v` copied into `vold`. This occurs too late to alter the section geometry already observed. |
| `linstatic.c:858–865`; `frd.c:838–861` | FRD displacement output receives `v`, and `frdvector` serializes that solved displacement array. |

`map3dto1d2d_v.f:98–103,207–223` keeps active original-node values and maps other primary DOFs from the expanded corners; it is a different routine from the stress mapper. The original-node MPC relation still connects the beam point displacement to its corner mean, but this does not make the stress mapper's **older input field** equal to solved `v`. For the initially undeformed, zero-prescribed-motion hybrid case, an unchanged reference section geometry is therefore consistent with nonzero solved FRD displacement.

### Honest geometry and basis wording

The truthful general description is **native section-map geometry from `co+vold` at stress mapping time**. Its centroid is the arithmetic mean of the native section corners, and its basis is the literal orthonormal face basis calculated from those coordinates, including the first-end left-handed convention. Neither field should be advertised as final solved displacement, final deformed centroid or a guaranteed current-configuration material frame. Other solver paths can supply a different history state; the present audit establishes the precise qualified `linstatic` path rather than making a universal statement about every call site.

The existing V1 wire markers `CURRENT_EXPANDED_SECTION` and `NATIVE_CURRENT_FACE_BASIS` are historical protocol strings, not proof of final-state geometry. Compatibility can preserve those literal strings while documentation/UI describes the map-supplied meaning and an additive method field identifies, for example, `NATIVE_MAP_CO_PLUS_VOLD`. A separate declaration can state that final solved displacement comes from ordinary FRD U. The research agent has not changed native C, protocol strings, parsers, inspectors or qualification gates; the coordinating implementer owns that decision.

The captured global force and moment still copy the native stock section integral. The moment reference is the actual **supplied native map centroid**. Transport a native moment using its recorded centroid; do not first add solved FRD displacement to that centroid while retaining the same centroid-relative moment. Likewise do not rotate the captured native basis using an inferred solved rotation. The source, spring, RBE and physical-support action frames remain their separately declared original-global convention. Their successful force/moment checks are not invalidated by correcting this geometry description.

The optional classical EA discrepancy is still investigated through ordinary FRD U and the independent pure-beam control. This state audit neither justifies replacing a displacement oracle by a section position nor supplies a fitted displacement reference. Geometry, loads and acceptance limits remain unchanged.

Additional pinned member hashes:

| Member | SHA-256 |
| --- | --- |
| `linstatic.c` | `5fb7bca07b59886a35ff203ed7859c96a372f803477576320f0766d9b4e85fc8` |
| `resultsini.c` | `5dbd3d938722b157568a975091dde7baf738c564bd747ed7e0978f0d84222256` |
| `resultsprint.f` | `623792be43fcd68270eac18ab87e79acd0acdcc0f66e9fc87012438be6dc91cd` |
| `map3dto1d2d_v.f` | `ec2cdc18384150a26a5175cd453aea0f3ec0d7b5e6ffccade943097a43ca59f4` |
