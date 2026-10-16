# FreeCAD-n1h: CalculiX 2.23 solver contract

Research evidence, 16 October 2026; no FreeCAD implementation inspected for this note.
Source: Guido Dhondt's official [CalculiX 2.23 manual](https://www.dhondt.de/ccx_2.23.pdf), linked by the [author's download page](https://www.dhondt.de/).
Downloaded PDF SHA-256: `a0bf3fc03f374912ff2bf28da3f7dfb6a61428dd7f41b281a2e7e1fdb318f330`.
Page numbers below are printed manual pages, also matching PDF page numbers.
Follow-up source verification used the author's [2.23 source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), SHA-256 `9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7`.

## Documented contract

- Engineering constants use the eight-plus-two field layout below. `TYPE=ORTHO` instead expects stiffness coefficients, not engineering constants. Temperature-dependent definitions repeat the pair. [§7.47, pp485–487](https://www.dhondt.de/ccx_2.23.pdf#page=485).
- Rectangular orientation uses a nonzero point on local axis 1 and a noncollinear point in the local 1–2 plane, with origin at global zero and right-handed axes. Optional third-line rotation is axis number, angle in degrees. Cylindrical orientation has different semantics. [§7.103, pp572–574, Fig164](https://www.dhondt.de/ccx_2.23.pdf#page=573).
- Attach the orientation name to the material's element-set section; declaring it alone does not establish that assignment. [§7.119, p596](https://www.dhondt.de/ccx_2.23.pdf#page=596).
- Units must be consistent: mm/N/s implies moduli in N/mm² (MPa); Poisson ratios are dimensionless. [§3, p15](https://www.dhondt.de/ccx_2.23.pdf#page=15).
- Linear elasticity uses Lagrange strain/PK2 stress; it is not a general finite-strain constitutive model. Orthotropic plasticity has separate infinitesimal-strain/linear-hardening restrictions. [§6.8.1, p259](https://www.dhondt.de/ccx_2.23.pdf#page=259), [§7.106, p576](https://www.dhondt.de/ccx_2.23.pdf#page=576).
- Shell axes are projected onto the shell, with its normal fixing axis 3; composites require S8R/S6. Beam section orientation and cross-section direction are distinct. [§6.2.14, pp110–111](https://www.dhondt.de/ccx_2.23.pdf#page=110), [§7.118, pp594–596](https://www.dhondt.de/ccx_2.23.pdf#page=595), [§7.3, pp410–411](https://www.dhondt.de/ccx_2.23.pdf#page=410).

## Recommended solid-element output

Symbolic layout (replace symbols with numeric values; temperature may be omitted when unnecessary):

```text
*MATERIAL,NAME=<material-name>
*ELASTIC,TYPE=ENGINEERING CONSTANTS
E1,E2,E3,nu12,nu13,nu23,G12,G13
G23,temperature
*ORIENTATION,NAME=<orientation-name>,SYSTEM=RECTANGULAR
a1,a2,a3,b1,b2,b3
*SOLID SECTION,ELSET=<assigned-element-set>,MATERIAL=<material-name>,ORIENTATION=<orientation-name>
```

For explicit unit direction vectors, choose `a=e1` and `b=e2`. Orthogonalize
input vectors and reject zero/parallel/non-finite vectors before writing them;
these are recommended exporter guards, not claims about automatic solver repair.
An orientation assignment must follow the same element ownership as the material.
Do not substitute a beam's cross-section direction for its material orientation,
or promise shell behavior from a solid-only regression.

## Proposed analytic verification (derived here, not executed)

Use a unit cube, small-displacement static analysis, linear solid elements,
traction `sigma_xx=1 N/mm²` on `x=1`, and symmetry conditions `ux=0` at `x=0`,
`uy=0` at `y=0`, `uz=0` at `z=0`. Leave the remaining faces unloaded.
For a face-pressure convention positive inward, this is outward pressure `-1`
on the positive-x face. Choose deliberately unequal constants:

```text
*ELASTIC,TYPE=ENGINEERING CONSTANTS
12000,3000,1500,0,0,0,700,500
300
*ORIENTATION,NAME=ROTATED,SYSTEM=RECTANGULAR
0,1,0,-1,0,0
```

Here local axes are `e1=+Y`, `e2=-X`, `e3=+Z`. Since all Poisson ratios are
zero, the exact affine solution is `ux=x/3000 mm`, `uy=uz=0`, uniform global
`sigma_xx=1 MPa`, and total support reaction `Fx=-1 N`. The same cube with
identity axes gives `ux=x/12000 mm`: a factor-four change. A missing orientation
or swapped E1/E2 is therefore observable independently of input text inspection.
This case intentionally avoids ambiguous interpretation of nonzero Poisson
subscripts; it does not by itself verify reciprocal coupling. The source-verified
nonzero-Poisson case below provides that additional check.

For a separate shear-order check, apply an affine engineering shear strain
`gamma_xz=0.001` with identity axes: `tau_xz=G13*gamma_xz=0.5 MPa`.
Repeat with the above rotation: global XZ shear becomes local 23 shear, so
`tau_xz=G23*gamma_xz=0.3 MPa`. Prescribing the exact affine displacement on
all boundary nodes and inspecting reaction/stress avoids end-effect assumptions.

## Source-verified Poisson convention and coupling patch

In `CalculiX/ccx_2.23/src/elastics.f`, lines202–219 of the
[official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2), the parser
reads the three entered ratios as `un12`, `un13`, `un23` and obtains their
reciprocals using `un21=un12*e2/e1`, `un31=un13*e3/e1`,
`un32=un23*e3/e2` before converting to stiffness. Therefore the compliance
convention is **not transposed**:

```text
nu_ij = -epsilon_j/epsilon_i under uniaxial stress in direction i
nu21 = nu12*E2/E1; nu31 = nu13*E3/E1; nu32 = nu23*E3/E2

[epsilon11]   [ 1/E1       -nu12/E1  -nu13/E1 ] [sigma11]
[epsilon22] = [-nu12/E1     1/E2     -nu23/E2 ] [sigma22]
[epsilon33]   [-nu13/E1    -nu23/E2   1/E3    ] [sigma33]

gamma12=tau12/G12; gamma13=tau13/G13; gamma23=tau23/G23
```

The matrix's positive definiteness is the relevant elastic stability guard;
applying the isotropic `nu<0.5` rule to every orthotropic input would not be a
general validity test. This is a mathematical consequence of the compliance
matrix, not a claim that the solver validates every invalid input itself.

Repeat the unit-cube traction patch above with
`E=(12000,3000,1500) MPa`, `nu=(0.25,0.1,0.2)`, and the same positive shear
moduli. These constants have `nu21=0.0625`, `nu31=0.0125`, `nu32=0.1`.
The exact global normal strains under `sigma_xx=1 MPa` are:

| Axes | epsilon_xx | epsilon_yy | epsilon_zz |
|---|---:|---:|---:|
| Identity | 1/12000 | -0.25/12000 | -0.1/12000 |
| e1=+Y, e2=-X, e3=+Z | 1/3000 | -0.25/12000 | -0.2/3000 |

Displacements are the respective strain component times x, y, or z. The same
three symmetry-plane displacement conditions remain compatible with the affine
solution. In the rotated case, a mistaken `S12=-nu12/E2` yields transverse
`epsilon_yy=-0.25/3000`, four times the correct contraction. Check this
transverse displacement explicitly, rather than only checking axial compliance.

## Basic shell patch and orientation boundaries

Use a unit square S8R shell in global XY, with positive-Z normal, thickness 1 mm,
the zero-Poisson constants above, and these section data:

```text
*SHELL SECTION,ELSET=<plate-set>,MATERIAL=<material-name>,ORIENTATION=ROTATED
1
```

Prescribe the affine membrane displacement `ux=0.001*x`, `uy=uz=0` on every
shell node and zero all rotations. Expected uniform global `sigma_xx` is 12 MPa
with identity orientation and 3 MPa with the rotated orientation; sum the global
x reactions on the x=1 edge for 12 N and 3 N respectively. This tests the shell
section assignment and in-plane axis projection without relying on a shell edge
load convention. It does not qualify bending, transverse shear, curved shells,
normal reversal, or composites.

Use `*EL PRINT,...,GLOBAL=YES` when comparing the above global stress components:
the documented print-output default is local. [§7.53, p502](https://www.dhondt.de/ccx_2.23.pdf#page=502).
Orientation is optional for solid and shell section cards. Omission means no
named material orientation; shells still construct/project their local frame.
An explicitly supplied name must exist (`solidsections.f` lines109–126 and
`shellsections.f` lines110–126 in the
[official source archive](https://www.dhondt.de/ccx_2.23.src.tar.bz2)). `GLOBAL`
is not a substitute for defining an orientation with that name. Rectangular
`a,b` components are global-coordinate directions, not object-local placement
coordinates: `transformatrix.f` normalizes a, removes its component from b,
normalizes the result, and obtains axis 3 by the right-handed cross product.

These are software patch tests, not material qualification or building-design
acceptance. Keep nonlinear, shell, beam, and nonzero-Poisson support claims
separate unless they receive their own evidence.
