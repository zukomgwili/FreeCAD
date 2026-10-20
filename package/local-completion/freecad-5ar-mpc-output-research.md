# Native MPC tie force and movement outputs

FreeCAD-5ar needs both independently owned displacement observations and a force ledger that distinguishes applied loads, support reactions, contact forces, and Tie transfers. CalculiX 2.23 has a native output route worth qualifying before extending the solver, but its combined `RF` output is not itself that separated ledger.

## Documented CalculiX 2.23 outputs

Ordinary `*TIE` creates multiple point constraints connecting slave nodes to master faces. Connected slave positions are adjusted unless `ADJUST=NO`. A position tolerance below `1e-10` selects a default tolerance, not exact zero. [Manual section 7.133, printed pages 620–621](https://dhondt.de/ccx_2.23.pdf#page=620).

`RF` combines reaction and applied concentrated/distributed forces; it is not generally a reaction-only output. `*NODE PRINT` supports selected node sets and `GLOBAL=YES`. [Manual section 7.99, printed pages 567–569](https://dhondt.de/ccx_2.23.pdf#page=567).

`SOF` and `SOM` integrate extrapolated/interpolated stresses. The selected element side determines the sign; material-interface stress jumps reduce accuracy. These quantities are not a direct MPC-transfer ledger. [Manual section 7.115, printed pages 591–592](https://dhondt.de/ccx_2.23.pdf#page=591).

`CF`, `CFN`, and `CFS` report selected face-to-face penalty-contact forces and origin moments, not ordinary Tie forces. [Manual section 7.23, printed pages 440–441](https://dhondt.de/ccx_2.23.pdf#page=440).

`U` is nodal displacement output. [Manual sections 7.97 and 7.99](https://dhondt.de/ccx_2.23.pdf#page=563).

## Release source details that affect interpretation

Use the official 2.23 release archive, not an unverified GitHub `master` snapshot. In `src/resultsforc.c` lines 34–119, MPC contributions are removed while forming reduced-system forces, then restored to `fn` for structural nodes. The routine computes its intermediate MPC scalar from the dependent `fn` and coefficient, without subtracting a separately supplied applied-load vector. [Official 2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2).

`src/printoutnode.f` lines 36–49 prints `U` using the requested node identity; lines 94–111 prints `RF` from `fn`. `src/resultsini.c` lines 226–310 reconstructs dependent displacements from MPC coefficients. Coincident coordinates alone therefore need not merge the two node identities. [Official 2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2).

`src/resultsmech.f` lines 371–453 also assembles contact-spring contributions into `fn`. Consequently, output interpretation must account for contact rather than treating every value at a Tie participant as pure Tie transfer. [Official 2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2).

The archive SHA-256 is `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7`.

## Derived qualification proposal

The smallest candidate native route is per-node `U` and `RF` on separately owned Tie-side node sets, using `GLOBAL=YES`, with immutable original coordinates and an explicit origin. It is a candidate, not a claim that native output already satisfies the complete FreeCAD ledger contract.

A loaded dependent Tie node is decisive: the combined value must not be attributed wholly to Tie transfer. The same distinction applies where a support or contact acts at a participating node. A valid decomposition must reproduce the combined force without counting any contribution twice; each reported moment must use the corresponding force and the same original-coordinate lever arm.

For a body with no cut, the proposed ledger check is the vector sum of its separately attributed applied, support, contact, and MPC forces, and the corresponding sum of original-origin moments. A cut introduces a separately identified section contribution. Neither reduced-coordinate force projection nor a stress-integrated section output should be renamed as direct physical Tie transfer.

## Runtime qualification boundary

Closure requires native demonstrations of owner-specific `U`, force and moment accounting, applied loads at dependent nodes, mixed contact and Tie participation, and unchanged existing accounting behavior. The documentary/source findings above do not establish those runtime results or accept any engineering fixture. A solver extension is justified only if the demonstrated existing native route cannot supply the required separated outputs.
