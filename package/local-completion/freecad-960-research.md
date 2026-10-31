# FreeCAD-960: documented beam-result semantics

Research, 31 October 2026. The initial manual review preceded implementation inspection; the later upstream source qualification is recorded below. No solver was executed and no project was opened for this note. This is evidence for the bead, not an engineering acceptance record.

## Documented solver contract

The [CCX 2.22 manual](https://www.dhondt.de/ccx_2.22.pdf#page=124), §§6.2.33 and 7.51, assigns the beam-node `S` channels as follows:

| Channel name | Physical quantity |
| --- | --- |
| `xx` | Shear along local n1 |
| `yy` | Shear along local n2 |
| `zz` | Axial resultant |
| `xy` | Torsional resultant |
| `xz` | Bending about n2 |
| `yz` | Bending about n1 |

They are not stresses. Consistent N/mm input implies N forces and N·mm moments; CalculiX does not impose a unit system (§3).

`SECTION FORCES` conflicts with `OUTPUT=3D`; ordering decides precedence. `OUTPUT=2D` returns original-node quantities with averaging. `NOE` disables the automatic stress-error output, not averaging. [§7.51](https://www.dhondt.de/ccx_2.22.pdf#page=493)

The integration explanation distinguishes positive-end directions n1/n2/t from opposite-end action directions. It does not establish a unique incident-element identity for each exported nodal value. [§10.3.9](https://www.dhondt.de/ccx_2.22.pdf#page=691)

The beam example recommends B32R and warns that B32 resultants, especially bending, can be inaccurate. [§5.14](https://www.dhondt.de/ccx_2.22.pdf#page=68)

Mixed beam/shell connectivity is documented; shared nodes transmit rotation rigidly. Beam/3D connectivity is described as hinged. A FreeCAD preflight restriction therefore cannot establish a universal solver prohibition. [§6.2.33](https://www.dhondt.de/ccx_2.22.pdf#page=121)

## Documented FRD identity

The [CGX 2.22 manual](https://www.dhondt.de/cgx_2.22.pdf#page=147), §§11.5–11.6, describes parameter records and node-keyed result datasets. Dataset metadata includes numerical value (time/frequency), analysis type, step number, description and format. Component headers name the fields. The tensor-style order shown later is `XX,YY,ZZ,XY,YZ,ZX`; consequently positional assumptions can exchange the bending channels. Identity should retain dataset/frame/step/time and the original node label, rather than time alone. The specification lists an element-at-node result kind as unused; it does not promise independent per-element end rows.

## Independent qualification implications

These are proposed checks, not observed runtime results:

- Use native-created, straight, single-section beam fixtures before joints or mixtures. Confirm the actual emitted element type and local triad; do not silently substitute elements to obtain better agreement.
- A static beam directed along +z with end load +100 N along x and length 1000 mm requires root reaction −100 N along x and −100000 N·mm about y. A positive-face action on the retained root segment at coordinate z has shear +100 N and moment +100(1000−z) N·mm about y. This follows independently from the free-body balance, not from FRD values.
- Positive and negative axial, transverse and torsional loads, rotated axes, reversed connectivity, multiple frames and a shared-node joint should distinguish channel/sign/identity mistakes. A nodal average must never be silently presented as a unique member-end action.
- Separate force and moment dimensions, and prevent von Mises/principal-stress recovery from resultant channels. Retain raw component names and qualified sample provenance through save/cold-reopen.

The manuals alone do not prove how the current bundled binary labels every FRD frame, how it treats coincident joints in this route, or whether current FreeCAD import can preserve these semantics. Those questions require the agreed stock-workflow runtime qualification. No custom recovery or manual deck editing is proposed here.

## Bundled version qualification

The repository's [native solver contract](../calculix/force-accounting/contract.json) pins CalculiX **2.23**, not 2.22. Its [2.23 manual](https://www.dhondt.de/ccx_2.23.pdf#page=498), §7.52, pp. 498–499, retains the channel mapping above and the `OUTPUT=3D` conflict. Section 6.2.33 still describes original-node mapping; §5.14 retains the B32R recommendation. The 2.22 citations are background, not a claim that the bundled executable is 2.22. Frame and joint behavior still need qualification through that executable.

## Upstream source sign and averaging qualification

The [official 2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2) matched the contract's SHA256 `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7`. The relevant member is `CalculiX/ccx_2.23/src/map3dto1d2d.f`, not `beamforces.f`.

That routine constructs section coordinates from `co+vold` (line 328), derives face axes with different first/last-end orientation (334–375), integrates traction and centroid-relative moments (447–488), then averages incident contributions (619–625). `gen3dfrom1d.f` (79–126) establishes the rectangular corner ordering. For a straight undeformed section, combining these definitions gives first-end basis −n1/−n2/−t and outward normal −t; last-end basis and normal are positive. Consequently both traction and basis reverse: raw first-end channels must not simply be negated because physical end actions oppose.

`frd.c` (76, 1017–1026) swaps internal channels 5/6 and writes `SXX,SYY,SZZ,SXY,SYZ,SZX`. `frdheader.c` (36–45) writes dataset/increment/step identities. Native face axes use displaced expanded geometry; reference beam axes are not an exact native output-frame basis.

Source SHA256 pins:

| Archive member | SHA256 |
| --- | --- |
| `map3dto1d2d.f` | `ec0520c711784a4df7def04522c9d0b0b28980f63d8145a71018011f64d3bf87` |
| `frd.c` | `6439bca2ae53c813ab6887c3c560dd15db5947fd8cf9b9f01ada5753d5ed9915` |
| `frdheader.c` | `25eb79d5f71a096ef1cacfe20105cc26d64ca17581a69e21ed2a7424556db5cb` |

These upstream facts do not prove that every packaged patch leaves them unchanged. The retained accounting patch does not target these three files; final production qualification must still bind the actual executable and exported request.
