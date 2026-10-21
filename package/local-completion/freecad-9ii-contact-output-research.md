# FreeCAD-9ii: native penalty-contact output contract

Research date: 21 October 2026. Scope: ordinary CalculiX 2.23 node-to-face and face-to-face penalty contact, not mortar, massless contact, an Oomakhi solve, or engineering acceptance. This investigation read official solver documentation and source only; it did not run a solver or inspect FreeCAD production implementation. Statements about the bundled executable still require the separate native qualification.

## Primary-source identity

The [official 2.23 manual](https://www.dhondt.de/ccx_2.23.pdf) identifies version 2.23 and is dated 19 October 2025. This investigation reused the previously retained, untouched official distributions and verified their complete SHA-256 digests:

| Distribution | SHA-256 |
|---|---|
| [Official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2) | `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7` |
| [Official HTML manual archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2) | `ed14b31b51972d5492209a42fcd52a062e36cbc7843bcd358617cb3aee0da736` |
| [Official PDF manual](https://www.dhondt.de/ccx_2.23.pdf) | `a0bf3fc03f374912ff2bf28da3f7dfb6a61428dd7f41b281a2e7e1fdb318f330` |

Source member paths below are relative to `CalculiX/ccx_2.23/src/` in the cited source archive; HTML members are under `CalculiX/ccx_2.23/doc/ccx/` in the cited manual archive. The retained source is `/private/tmp/freecad-927-ccx-research.Trz3MF/CalculiX/ccx_2.23/`. Archive identity, member name, and line numbers identify the inspected primary source without relying on a third-party mirror.

## Request syntax and scope

Inside a step, the native requests are:

```text
*CONTACT PRINT,FREQUENCY=1
CDIS,CSTR
*CONTACT FILE,FREQUENCY=1
CDIS,CSTR
```

`PRINT` writes ASCII `.dat`; `FILE` writes ASCII `.frd`. `*CONTACT OUTPUT` instead selects mixed binary/ASCII FRD. Either `CDIS` or `CSTR` selects the combined six-component FRD `CONTACT` dataset. `FREQUENCY` and `TIME POINTS` are alternatives, affect other output cards too, and selections can persist into following steps. Thus the input deck and actual retained frames must be kept together; a result must not assume every solver increment was saved. [HTML manual archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2), `node247.html:125–171`, `node248.html`, `node250.html:112–153`; [source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `calinput.f:437–450`, `noelfiles.f:590–594`.

Local DAT `CDIS`/`CSTR` requests cover every generated active contact sample: slave nodes for node-to-face, slave-face integration points for face-to-face. `SLAVE`/`MASTER` select a pair for integrated `CF`/`CFN`/`CFS`, **not** for local `CDIS`/`CSTR`: the parser stores a pair identifier only for labels starting `CF`, and the local print loop traverses all generated contact elements. Multiple local print cards therefore do not produce pair-filtered local blocks merely by adding these parameters. [HTML manual archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2), `node250.html:87–109`, `:167–171`; [source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `contactprints.f:200–232`, `printout.f:462–506`.

## Raw DAT record identity

Each block starts with one of these native labels, followed by cumulative time:

| Quantity | Node-to-face label | Face-to-face label |
|---|---|---|
| CDIS | `relative contact displacement (slave node,normal,tang1,tang2)` | `relative contact displacement (slave element+face,normal,tang1,tang2)` |
| CSTR | `contact stress (slave node,press,tang1,tang2)` | `contact stress (slave element+face,press,tang1,tang2)` |

The remainder says `for all contact elements and time`; the time is formatted `e14.7`. A node-to-face data row contains one `i10` slave-node identifier and three `e13.6` values. A face-to-face row contains two `i10` identifiers, slave element and face, then three `e13.6` values. CDIS prints internal components 1–3, CSTR components 4–6, without an output sign change. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `printout.f:395–428`, `printoutelem.f:78–105`.

The face-to-face label is **not** an integration-point identifier. Several native rows legitimately share the same element/face; the local output does not write its internal `igauss`, parametric coordinates, integration weight, corresponding master face, pair identifier, normal, or tangents. Node-to-face rows likewise omit the master face and pair. A row ordinal can preserve file provenance, but cannot be renamed a solver integration-point number. Duplicate labels must not be silently collapsed or averaged. These are direct limitations of the output writes, despite the richer native arrays used by the solver. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `printout.f:480–505`, `printoutelem.f:83–104`, `springforc_f2f.f:83–164`, `gencontelem_f2f.f:704–716`.

DAT contact headers contain cumulative time (`ttime+time`), not step/increment numbers. FRD `1PSTEP` separately writes dataset counter, increment, and step; its `100CL` carries time and stored increment counter. Nonlinear output passes cumulative time to FRD. This allows qualified frame association, but DAT time rounding and repeated/ambiguous blocks must be handled explicitly instead of guessing a frame from list position. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `printout.f:395–428`, `frdheader.c:33–42`, `:92–156`, `nonlingeo.c:3868–3879`.

## Values, directions, and units

For face-to-face contact, the normal value is the current slave integration-point position minus its corresponding master position, projected on the stored master normal, with the native initial-penetration reduction applied when enabled. The source writes this clearance directly; penetration is negative in that formulation. Node-to-face uses the corresponding slave-node/master projection. The PDF's CONTACT PRINT positive-overlap wording differs from CONTACT FILE's negative-penetration description; the actual source path does not negate CDIS for DAT. Therefore sign verification must use the bundled executable and a simple oriented compression/open control, not documentation wording alone. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `springforc_f2f.f:60–164`, `springforc_n2f.f:211–254`, `resultsmech.f:412–437`, `printoutelem.f:83–104`; [HTML manual archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2), `node247.html:94–118`, `node250.html:90–98`.

Native tangent 1 is normalized global X projected onto the master tangent plane, falling back to global Z when the normal is nearly parallel to X; tangent 2 is master normal cross tangent 1. Source switches at `1-abs(normal_x) < 1.5231e-6`. The master normal can be local and history-dependent; the output does not carry that vector. Pressure is force divided by the representative contact area; shear components are local force projections divided by that area. Do not treat the scalars as global XYZ components. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `springforc_f2f.f:245–253`, `:286–305`, `:383–405`, `gencontelem_f2f.f:534–547`; [HTML manual archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2), `node247.html:94–118`.

CalculiX does not attach a unit system to the numbers. CDIS uses the consistent input length unit; CSTR uses force/area. For a verified millimetre/Newton input convention, those are mm and N/mm² (MPa), but the parser must get this convention from the export/run provenance, not infer it from `.dat`. [HTML manual archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2), `node4.html:59–101`; [source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `springforc_f2f.f:152–164`, `:245–253`, `:383–405`.

## Tangential movement is not an irreversible-slip state

The ordinary penalty law retains total tangential relative-displacement history `t`, plastic slip history `tp`, and elastic displacement `te=t-tp` separately. It updates `t` using the tangential relative-displacement increment and exports projections of **t** in CDIS. Thus `CSLIP1/2` include elastic sticking displacement and plastic sliding history; they are neither accumulated irreversible travel distance nor an explicit stick/slip flag. Contact loss resets the relevant internal history, adding another reason not to interpret these channels as lifetime accumulated sliding. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `springforc_f2f.f:316–343`, `:355–421`, `gencontelem_f2f.f:769–780`; node-to-face equivalent `springforc_n2f.f:429–534`.

The internal branch compares elastic trial force with the Coulomb bound, with an additional elastic-calculation override. Neither ordinary CONTACT PRINT's accepted local labels nor the FRD CONTACT record writes that branch/state, plastic increment, or accumulated plastic-slip norm. Reporting `stick` merely because CSLIP is zero/small, or `slip` because it is nonzero, would be invented physics. A derived friction-utilization indicator must be labelled derived and is not a native state flag. Native state is unavailable through these ordinary six-channel requests. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `springforc_f2f.f:355–421`, `contactprints.f:176–192`, `frd.c:1648–1654`, `:1696–1706`; [HTML manual archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2), `node291.html:64–99`.

## Availability, recovery, and pair attribution

An omitted DAT sample is not a measured zero or a measured positive gap. The solver may find no opposite master face, reject an open contact, or retain contact history through a cutback. Face-to-face gap/history generation decisions and node-to-face clearance thresholds differ. A successfully parsed empty contact block, an absent requested block, and a malformed/truncated block therefore need distinct availability outcomes. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `gencontelem_f2f.f:319–334`, `:550–670`, `gencontelem_n2f.f:755–786`, `printout.f:462–506`.

FRD is not an independent raw-IP authority for face-to-face contact: `resultsprint` calls `extrapolatecontact`, which fits/restricts samples to slave nodes, constructs midside values, and averages shared-node contributions. It initializes unfilled values to zero. **It also explicitly interchanges the final two recovered rows before FRD labels them CSHEAR1/CSHEAR2.** Raw DAT preserves components 5/6 in order. Any cross-channel or directional parity claim needs actual bundled-solver controls; no project-side numerical recovery should be introduced to manufacture raw sample coordinates from FRD. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `resultsprint.f:236–256`, `extrapolatecontact.f:94–101`, `:179–400`, `:406–537`, especially `:489–502`, `frd.c:1684–1706`.

`CONTACT ELEMENTS` adds `.cel` visualization connectivities and step/increment/attempt/iteration set names. Face-to-face output writes only contact-volume corner-node connectivity with synthetic element numbering; it does not write the native IP coordinates/index/weight or pair names. It is not a direct localization table for the DAT rows. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `gencontelem_f2f.f:99–145`, `:723–765`; node-to-face connectivity equivalent `gencontelem_n2f.f:825–841`.

Consequently a stock-only consumer can faithfully preserve local DAT rows and their printed source labels. It may attribute a row to a contact only when retained export ownership establishes one unique compatible slave node/face. Overlapping slave ownership must remain ambiguous, not be assigned by coordinates or list order. This is a consumer safety inference from the global request scope and absent pair labels, not a native solver guarantee. Exact sample positions, native IP numbers, master-face identity, and native stick/slip state must remain explicitly unavailable where the native record does not supply them. No missing active output should be zero-filled. [Source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), `contactprints.f:200–232`, `printout.f:462–506`, `printoutelem.f:78–105`.
