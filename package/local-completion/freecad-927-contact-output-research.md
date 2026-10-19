# FreeCAD-927: native contact output and owner-restricted probing

Research date: 19 October 2026. This is a capability/limitations investigation, not original-fixture movement acceptance. It does not change the physical model or the declared sampled criteria. FreeCAD implementation inspection was deferred until the read-only original availability reproduction completed; the final source-seam section was added afterward.

## Conclusion

CalculiX contact movement and a pair of independently owned displacement values at one declared physical point are different observations. An owner-restricted VTK dataset can preserve disconnected coincident bodies and expose separate native interpolation results, but the ordinary probe's validity mask and even zero explicit tolerance do not alone prove that a point is inside its owner. Both the native solver's submodel interpolation and the VTK probe have permissive boundary/projection behavior that must be established before either is an applicable reporting operation. These are source and synthetic-runtime findings, not proof for the retained collector.

## Primary-source custody

The [CalculiX author download page](https://www.dhondt.de/) identifies 2.23 as the available version. The following official distributions were fetched into a private research directory, without changing the repository's solver or application:

| Distribution | SHA-256 |
|---|---|
| [CalculiX 2.23 source](https://www.dhondt.de/ccx_2.23.src.tar.bz2) | `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7` |
| [CalculiX 2.23 HTML manual](https://www.dhondt.de/ccx_2.23.htm.tar.bz2) | `ed14b31b51972d5492209a42fcd52a062e36cbc7843bcd358617cb3aee0da736` |
| [CalculiX 2.23 PDF manual](https://www.dhondt.de/ccx_2.23.pdf) | `a0bf3fc03f374912ff2bf28da3f7dfb6a61428dd7f41b281a2e7e1fdb318f330` |

CalculiX file references below are paths inside `CalculiX/ccx_2.23/src/` in that source archive. Manual references name sections and the matching HTML member. Source behavior is reported separately where it differs from the manual. The installed project's Python environment reported VTK 9.7.0; VTK references are pinned to upstream tag `v9.7.0`, peeled commit `23f0a095621e91bbdbeace8451e22b950c8e5f46`, rather than mutable nightly documentation.

## CalculiX movement sample and output identity

The manual distinguishes `.dat` contact samples at active slave nodes for node-to-face penalty contact and active slave-face integration points for face-to-face penalty contact. Its `.frd` contact channels are `COPEN`, `CSLIP1`, `CSLIP2`, `CPRESS`, `CSHEAR1`, and `CSHEAR2`. The normal is master-local; tangent 1 is the projected global X direction, falling back to Z near an X-normal, and tangent 2 is normal cross tangent 1. The manual says slip needs a `*FRICTION` definition. See [manual](https://www.dhondt.de/ccx_2.23.pdf), §§7.20 and 7.23 (`node247.html`, `node250.html`).

The official source establishes the actual face-to-face observation more precisely. `springforc_f2f.f:83–164` uses the native slave integration point's surface coordinates and shape functions, its corresponding master-face surface coordinates and shape functions, and current positions. Its raw normal value is

`(current slave integration-point position − current corresponding master position) · master normal`,

with the documented initial-penetration reduction term applied where enabled. Thus it is neither a nodal `U` pair nor necessarily a comparison of identical original undeformed coordinates. `springforc_f2f.f:301–343` obtains relative displacement from weighted slave and master `U`, then updates tangential state incrementally; lines 420–421 project that state onto the native tangents. The local directions are computed at lines 286–305. These are native contact-law observations, including their history and initial-clearance conventions. [Official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), member `springforc_f2f.f` (SHA-256 `3be67688eb16a95739e09990c34ae0d2614acff216b254ea474bbf7c4d9e1ba4`).

`printout.f:395–505` emits the face-to-face displacement header with slave element and face and then iterates generated contact elements. `printoutelem.f:78–105` writes those element/face identifiers and the three raw values; it does not print the native integration-point index or master face. Multiple native samples can therefore have the same printed slave element/face label. The output alone is not a unique owner-pair/location record. [Official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), members `printout.f` (SHA-256 `ae2b60b4e086846e2833a1d723c37645c0ff6701d2e28dc7e3163d0a4d136f32`) and `printoutelem.f` (`e5da47dd83dd8e796fcbf8ec81e220b5139211b8f411c03adb17a782436e2544`).

For face-to-face `.frd` output, `resultsprint.f:236–256` explicitly calls `extrapolatecontact`. That routine recovers native integration-point values to slave nodes, includes component limiting against native sample extrema and midside averaging, and averages contributions sharing a node (`extrapolatecontact.f:175–400`, `:410–537`). `frd.c:1683–1708` exports this recovered `cdn` array, not independent raw owner displacements. Therefore a recovered `COPEN` at a slave vertex is not automatically the declared original-point comparison. [Official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), members `resultsprint.f` (`623792be43fcd68270eac18ab87e79acd0acdcc0f66e9fc87012438be6dc91cd`), `extrapolatecontact.f` (`d93677913f1c0ea4445feae821dfbc8cfd1ea70dc9db5fb4a6236d7473cd5264`), and `frd.c` (`6439bca2ae53c813ab6887c3c560dd15db5947fd8cf9b9f01ada5753d5ed9915`).

### Sign, activation, and TIED qualifications

The manual's `.dat` positive-overlap statement conflicts with its `.frd` negative-penetration statement. Source does not justify silently treating these as opposite signs: `resultsmech.f:430–436` passes `stx` directly into `springforc_f2f`, whose `cstr(1)=clear`; `printoutelem.f:83–91` prints the same first component without negation. In a simple outward-master-normal case, penetration is negative raw clearance. Any consumer must qualify the exact shipped solver and mode experimentally rather than infer a sign solely from these manual descriptions. [Official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), members `resultsmech.f` (`15fccc9fb553f259af5d33bc78e8d3808f1f9f338ee266ce92192bae33026fa6`), `springforc_f2f.f`, and `printoutelem.f`.

For ordinary face-to-face penalty contact, `gencontelem_f2f.f:319–329`, `:556–670` distinguishes failed opposite-face finding, open gap, cutback/history, and generated contact state. TIED behavior bypasses several ordinary gap-based exclusions, but still requires an opposite face. An absent native record is consequently not a measured zero. The generated contact topology, step/increment, and pair must be retained to distinguish unavailable from active results. [Official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), member `gencontelem_f2f.f`.

`PRESSURE-OVERCLOSURE=TIED` is face-to-face penalty behavior, not the separate `*TIE` MPC operation. The former requires a stick slope; `springforc_f2f.f:257–283` enforces that requirement and makes the Coulomb limit effectively unlimited. The latter generates constraints and may adjust node coordinates. Changing either to obtain output would change the physical setup, not merely add observations. See [manual](https://www.dhondt.de/ccx_2.23.pdf), §§7.130 and 7.133 (`node357.html`, `node360.html`), and [source](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `springforc_f2f.f`.

## Existing native owner-restricted interpolation: a qualified candidate, not an established route

`*NODE PRINT,U` selects existing node IDs; it does not create values at missing nodes. By contrast, `*SUBMODEL,TYPE=NODE,INPUT=...,GLOBAL ELSET=...` can limit interpolation to explicitly listed original global elements. The submodel nodes must be independent named nodes; one cannot assign one submodel node to both owners. The required boundary request specifies a source step or dataset. For a static step, the last stored increment is selected. These are separate volumetric-submodel boundary conditions, not an ordinary original-analysis point report. See [manual](https://www.dhondt.de/ccx_2.23.pdf), §§7.4, 7.99, and 7.126 (`node227.html`, `node326.html`, `node353.html`).

This capability does not satisfy strict missing-location behavior by itself. `interpolsubmodel.f:128–141` receives `dist` from `basis` but does not reject finite distance. `basis.f:293–299` chooses a closest admissible tetrahedral candidate when no containing one exists; `:362–509` minimizes attachment distance and `:513–541` returns a field at the closest native parent-element position. It uses original parent shape functions after the tetrahedral search; it is not merely linear tetrahedron field interpolation. The native routine exposes parent element, weights, and distance internally, but the plain submodel keyword does not turn a finite-distance attachment into an explicit unavailable point. [Official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `interpolsubmodel.f` (`590655109f3f87351891a5f66a1f391a0fff357999955f9f3cc60893c026b28e`) and `basis.f` (`559a84d544b0b9f567c9efcec74d94b8b77903c3b5fde4bc41ab9faa5cb61464`).

## VTK exact-owner extraction and probing

### What exact extraction preserves

`vtkExtractSelection` cell selection creates `vtkOriginalPointIds` and `vtkOriginalCellIds` from zero-based input dataset indices, then invokes `vtkExtractCells`. Those indices do not become original solver node/element IDs by naming alone. Existing solver-ID arrays require their own verified provenance mapping. [VTK 9.7.0 `vtkExtractSelection.cxx:893–935`](https://github.com/Kitware/VTK/blob/23f0a095621e91bbdbeace8451e22b950c8e5f46/Filters/Extraction/vtkExtractSelection.cxx#L893).

`vtkExtractCells` builds its point map from original point IDs used by the chosen cells, not coordinate proximity; separate nodes at identical coordinates remain separate. It copies point/cell arrays for the chosen indices, and adds `vtkOriginalCellIds` only when an array with that name is not already present. Extraction is not complete reference validation: its input list is sorted/uniquified and invalid indices are processed rather than reported as missing references. A native update succeeding therefore does not prove requested/extracted ID-set equality. [VTK 9.7.0 `vtkExtractCells.cxx:401–447`, `:473–512`, `:654–673`](https://github.com/Kitware/VTK/blob/23f0a095621e91bbdbeace8451e22b950c8e5f46/Filters/Core/vtkExtractCells.cxx#L401).

### What a probe success does and does not mean

The probe interpolates source point arrays using native cell weights, and copies source cell-array values from the selected cell. It initializes `vtkValidPointMask` to zero and sets it to one on accepted probing; unprobed numeric arrays are initialized to zero. A zero displacement without the validity mask is not an available observation. `ComputeTolerance` defaults on; for point-set sources the initial tolerance is 0.1% of a sampled cell diagonal. `SnapToCellWithClosestPoint` defaults off, but enabling it permits an explicit closest-point fallback. [VTK 9.7.0 `vtkProbeFilter.cxx:70–86`, `:303–311`, `:359–370`, `:550–600`, `:624–640`](https://github.com/Kitware/VTK/blob/23f0a095621e91bbdbeace8451e22b950c8e5f46/Filters/Core/vtkProbeFilter.cxx#L70).

`vtkStaticCellLocator::FindCell` returns the first acceptable candidate in its bin, not a set of all independently owned matches. It checks `EvaluatePosition` status is not -1 and distance squared is within the requested tolerance; status need not equal strict inside. It has no owner identity beyond the dataset supplied to it. A mixed coincident-body dataset can therefore return a geometrically valid but wrong owner. [VTK 9.7.0 `vtkStaticCellLocator.cxx:482–524`](https://github.com/Kitware/VTK/blob/23f0a095621e91bbdbeace8451e22b950c8e5f46/Common/DataModel/vtkStaticCellLocator.cxx#L482).

Even zero explicit probe tolerance is insufficient to rule out extrapolation. `vtkTetra::EvaluatePosition` accepts barycentric values down to -0.001 and up to 1.001, returns status 1 and zero distance for that parametric margin, and leaves potentially negative interpolation weights. Its native `GetParametricDistance` can expose departure from the actual parametric domain. Exact face points also have floating-point residuals; any admissibility tolerance must be justified separately from engineering overclosure/slip limits. Other cell types require their own native qualification rather than importing this tetrahedron-specific margin as a universal rule. [VTK 9.7.0 `vtkTetra.cxx:127–183`, `:1050–1075`](https://github.com/Kitware/VTK/blob/23f0a095621e91bbdbeace8451e22b950c8e5f46/Common/DataModel/vtkTetra.cxx#L127).

### Limited native synthetic check

A private Python experiment used only the installed VTK 9.7.0 library, two disconnected tetrahedra with exactly coincident coordinates, explicit synthetic solver-ID arrays, and distinct affine displacement fields. It did not import FreeCAD or read project geometry. Producer SHA-256: `e0a517221331649777614fa2d2a805cbbbc04c40e426a30f4bd89f4b43a570ab`.

| Native observation | Result |
|---|---|
| Extract both owner cells | 2 cells, 8 distinct point IDs retained |
| Extract owner 0 / owner 1 independently | 1 cell and 4 points each; original indices and synthetic element IDs stayed distinct |
| Probe `(0.2,0.2,0.2)` independently | Owner fields `(1.2,0.2,0.2)` and `(101.2,100.2,100.2)`, mask 1 |
| Probe outside `(5,5,5)` | Mask 0; returned numeric arrays zero, not an observation |
| Probe `(0.4,0.4,0.20001)` just outside `x+y+z≤1` | Mask 1 and affine extrapolation even with automatic tolerance off, explicit tolerance zero, and snapping off |
| Native parametric distance at that outside point | `1.0000000000037756e-5`, despite status 1 and zero distance squared |
| Native parametric distance at exact face `(0.4,0.4,0.2)` | `5.551115123125783e-17` floating-point residual |
| Invalid extraction indices `[-1,0,999]` for 2 cells | Returned both source cells; request validity cannot be inferred from successful Update |

This demonstrates a native owner-separation capability and concrete permissive failure cases. It does not establish an editable FreeCAD operation, topology-to-result ownership, supported quadratic-cell behavior, result/frame/unit identity, cold provenance, ambiguity rejection, or availability at any of the retained collector's required points. No native contact quantity, interpolated value, or synthetic software result in this note constitutes movement, equilibrium, whole-house, R30, or BIM acceptance.

## Existing FreeCAD source seam, inspected after reproduction

At repository commit `e87804280680a916ac431fdfbd0c06a57345c527`, `FemPostObject.getDataSet()` exposes a native dataset when VTK Python support is enabled; `PropertyPostDataObject` accepts and deep-copies native VTK data. The registered `Fem::PostFilterPython` object and its `addFilterPipeline` API can host native algorithms. These are existing extension seams, not an already-qualified owner-specific reporting feature. Sources: [`FemPostObjectPyImp.cpp`](../../src/Mod/Fem/App/FemPostObjectPyImp.cpp), [`PropertyPostDataObject.cpp`](../../src/Mod/Fem/App/PropertyPostDataObject.cpp), [`FemPostFilterPyImp.cpp`](../../src/Mod/Fem/App/FemPostFilterPyImp.cpp).

Existing DataAtPoint sets manual probe tolerance `0.01`; its exposed `PointData` reduces vector arrays to magnitudes and does not consult its `ValidPointArray` mask before copying field values. An owner-extracted dataset feeding that filter would therefore not by itself expose a qualified side-specific displacement vector or explicit unavailable state. Source: [`FemPostFilter.cpp:565–674`](../../src/Mod/Fem/App/FemPostFilter.cpp).

The result-to-VTK path inserts points at mesh node ID minus one, uses default `vtkPoints` precision, and appends highest-dimension cells in native iterator order without adding an original element-ID array. It does not establish `VTK cell index = solver element ID minus one`. Displacement vectors are scaled by `0.001` into metres, while the mesh export default coordinate scale is `1.0`; coordinate and displacement numbers therefore need separately verified units. Source: [`FemVTKTools.cpp:630–717`, `:1201–1270`](../../src/Mod/Fem/App/FemVTKTools.cpp) and [`FemVTKTools.h`](../../src/Mod/Fem/App/FemVTKTools.h).

The smallest candidate seam is native exact-owner extraction followed by native cell-location/probe interpolation with full vector access, together with reference, parametric-domain, residual, unavailable/ambiguity, frame/unit, and source/save/cold guards. That adds no project-side numerical interpolation formula or geometric matcher. This is an implementation candidate only: it still needs actual retained owner/topology/result applicability and native software proof before it can be called a supported route.
