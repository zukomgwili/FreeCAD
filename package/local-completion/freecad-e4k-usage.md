# Staged volumetric self-weight in one native static step

Select the CalculiX solver and set **Static Step Amplitude** (`StaticStepAmplitude`,
in the TimeIncrement property group) to **Step**. This applies unamplified loads,
including genuine material-density-based self-weight, at full value from the
first converged increment. It applies to every unamplified loading card in that
static step. Give the variable Force or Pressure its own enabled amplitude to
delay and reverse it independently. **Ramp** remains the default and writes the
same input as older versions.

For example, use a 1 s static period with 0.1 s increments, actual material
densities and an ordinary Self Weight constraint. On the variable load, enable
amplitude and enter these native time/factor rows, with time in seconds:

```text
0, 0, 0.2, 0
0.4, 1, 0.6, 0, 0.8, -1, 1, 0
```

Gravity is established before Q starts after 0.2 s. Q then reaches its positive
reference at 0.4 s, returns to zero, reverses at 0.8 s and returns to zero at
1 s. This route uses the stock writer's volumetric `GRAV`, actual element
materials and the solver's normal contact history. It does not replace gravity
with face or nodal forces. The native default and explicit-amplitude precedence
are documented in the [CalculiX 2.23 manual](https://www.dhondt.de/ccx_2.23.pdf),
printed p607; the examined PDF SHA256 is
`a0bf3fc03f374912ff2bf28da3f7dfb6a61428dd7f41b281a2e7e1fdb318f330`.

Enabled amplitude tables must contain finite, strictly increasing time/value
pairs, with one to four pairs per row. Signed factors, negative prehistory,
Fortran D exponents and native trailing comma padding remain readable without
changing their saved literal form. Missing, malformed, duplicate-time and
nonfinite tables fail export. Disabled tables remain ignored. An invalid
static-step choice, or choosing Step for a non-static analysis, also fails
export instead of silently changing the setting. Existing saved solvers gain
the Ramp default; saved Step selections and load histories survive reopening.

For native equilibrium accounting, enable `NativeForceAccounting`, select
physical external supports and author explicit one-sided equilibrium cuts.
Select the contact in `NativeContactOutputs` to retain its native state and
frame identities. The bundled solver recognizes its own implicit STEP table on
an exactly zero original Fixed boundary. Explicit support amplitudes, moving
supports, RBE helper SPCs and altered or impersonated default tables remain
outside that allowance. The existing support and cut ownership rules apply.

Accounting is a **final-state observation**. To request another current state,
set the static period to that physical endpoint and run normally from time
zero, keeping the full original amplitude rows unchanged. Each run reproduces
the same history prefix. This feature adds neither multiple-step accounting nor
an intermediate-frame accounting selector. Native contact output retains its
own frames; a current accounting result must match the requested endpoint and
the contact result's final native step, increment and time.

Contact diagnostics keep each retained frame's actual face and sampling-point
catalogue when CalculiX regenerates quadrature points. Point labels identify
that frame; they do not establish material-point trajectories across frames.
The output explicitly marks this scope and retains exact final-frame aliases.
Older constant-catalogue V1 output remains readable. Missing samples, altered
owners, incomplete catalogues and inconsistent aliases remain refused.

Physical edits withdraw Current availability and preserve historical literals.
After saving and cold reopening, rerun normally to establish Current output.
Reopening does not recreate successful solver-process ownership.

The small qualification fixture checks held G, positive/negative Q, three
material owners, both cut sides, physical support, global force and original
global-origin moments against independently frozen 1% references. Early native
contact totals distinguish Step from Ramp within the full-length run. The
normal-source fixture uses nonzero friction and actual native STICK state; it
does not qualify sliding, separation or general tangential loading. The tests
observe the lower cut body's contact action as both native slave and
native master in separate runs. They add no simultaneous independent base-side
contact measurement. These checks do not accept Oomakhi, establish a universal mesh-accuracy tolerance or
discharge its separate 5% sensitivity duty.
