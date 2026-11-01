# FreeCAD-e4k independent staged-gravity oracles

These software-method references were frozen before a native candidate solve. They use exact free-body statics for a small stock-authored fixture and supply no Oomakhi design acceptance. Original project equilibrium limits of 1% and the separate 5% sensitivity duty remain unchanged. The machine-readable frozen record is `/private/tmp/freecad-e4k-tsd27fAG/oracles.json`.

The selected proportionate route exposes CalculiX's static default `AMPLITUDE=STEP`. Real density-based volumetric `GRAV` reaches full G at the first positive-time converged increment, while an independently amplitude-controlled Q remains zero through .2s. This does not require a new per-self-weight amplitude, a second step or a multi-frame force-accounting API.

## Real geometry and material ownership

Three 100mm cubes share XY bounds x=-33..67 and y=-73..27mm, giving the translated centroid (17,-23)mm. The bottom occupies z=0..100mm, the lower z=100..200 and the upper z=200..300. The genuine contact at z=100 has separate original node identities. The lower and upper share a real conformal cut at z=200. Their explicit density/material owners remain separate.

| Owner | Density kg/m³ | Volume m³ | Held weight N |
| --- | ---: | ---: | ---: |
| Bottom | 7900 | .001 | 77.472535 |
| Lower | 7800 | .001 | 76.491870 |
| Upper | 8000 | .001 | 78.453200 |

Gravity is the actual authored 9.80665m/s² in global -Z (native 9806.65mm/s²). An ordinary native Fixed supports the bottom exterior z=0 face and is explicitly selected in `NativeAccountingSupports`. Its physical support sums the actual prescribed original-node translational residuals and original-position moments, including bottom volumetric gravity, exactly once. No RBE, extra prescribed guide or hidden stabilization is used. This pre-solve support-mechanism amendment leaves all geometry, sources, references and numerical limits unchanged; the earlier RBE oracle remains byte-identical in `oracle-history/step-default-r01-rbe`.

Use nonzero friction, candidate coefficient .3. Q is a positive reference pressure .001MPa on the real 10000mm² upper top face, giving 10N downward at amplitude1. Its full native absolute-time history is (0,0),(.2,0),(.4,1),(.6,0),(.8,-1),(1,0). Five fresh one-step native runs end at .2,.4,.6,.8 and1s. Each retains that same full Q history; only its endpoint period changes. This checks each final Current state without inventing retained intermediate accounting frames. The negative Q amplitude reverses the external source but leaves positive contact compression.

## Signed independent free bodies

With P positive downward, write Wb,Wl,Wu for the held material weights. On the named physical owner:

| Action | Fz N |
| --- | --- |
| Physical support on bottom | Wb+Wl+Wu+P |
| Gravity LOAD on bottom | -Wb |
| Contact on bottom | -(Wl+Wu+P) |
| Gravity LOAD on lower | -Wl |
| Contact on lower | Wl+Wu+P |
| Cut on lower | -(Wu+P) |
| Total LOAD on upper | -(Wu+P) |
| Contact on upper | 0 |
| Cut on upper | Wu+P |

Every force has zero X/Y components. Its moment about the **original global origin** is `(-23Fz,-17Fz,0)`Nmm. Lower-body cut ownership thus has gravity, upward contact and downward cut; upper-body ownership has downward gravity/Q and upward cut. The cut bodies are disjoint material volumes sharing only their real interface. Neither selected body contains an SPC/MPC. Selecting both as one body would internalize the cut and does not measure the specified action. Actual source/cut/contact labels and orientations must be bound to the stock export, rather than guessed from face ordinals.

At G only, the support/contact-on-lower/cut-on-upper forces are 232.417605,154.945070,78.453200N. At Q=+10N they are 242.417605,164.945070,88.453200N; at Q=-10N they are 222.417605,144.945070,68.453200N. The full exact signed components for all five endpoints are in the frozen JSON.

## Fixed acceptance and history duties

Every independently nonzero physical force/moment component must satisfy 1% relative error at every current endpoint. Expected-zero force components have the fixed absolute budget 1e-6N; expected-zero moment components 1e-4Nmm. Named material, contact-pair, cut-pair and global closures are checked independently: use1% of the independently expected largest physical support/action per nonzero axis, and those explicit near-zero budgets for zero axes. No frame averaging, owner cancellation or result-derived fit is permitted.

Preserve and inspect the actual native contact availability/state; zero tangent demand does not by itself prove STICK. This normal-source fixture qualifies staged history in a frictional contact, without claiming sliding, generic tangential stiffness, separation or contact-law accuracy.

Verify default unamplified behavior, missing/invalid requested amplitudes, dimensional/time consistency and fail-closed Current invalidation on amplitude, density, step, source, cut/contact/support and run-custody changes. Separate-process cold reopening must preserve exact saved controls, material ownership, amplitude history and observation literals/hashes, retaining Historical/Stale availability. It must not rerun, repair paths, rebind cases or promote Current. Retain the untouched stock-generated one-step deck and actual native source hashes.

An earlier unexecuted ramp-G candidate remains unchanged under `/private/tmp/freecad-e4k-oracles-848kfv2w`; it is superseded by this explicitly selected STEP-default candidate, not a numerical failure or a passing qualification.

## Early native history discriminator and default control

This observational amendment is frozen before a native candidate solve. The preceding attempt was refused during generated-support-amplitude validation before launching the solver, so it supplied no solved discrepancy or result-derived fit. All geometry, densities, sources, histories, current wrench references, equilibrium limits and project duties remain unchanged. The earlier fixed-support oracle is preserved in `oracle-history/step-default-r02-fixed`.

Five final-only endpoint runs do not by themselves prove held G during a longer history: RAMP also reaches full gravity at the end of each independently truncated period. Therefore inspect actual early **native integrated CF pair totals** in the full1s run. This is ordinary native `CONTACT PRINT` force output, already integrated inside CalculiX, with no stress recovery, sample-area aggregation, nodal substitute, manual deck edit or new intermediate ForceAccounting API.

Q remains exactly zero through .2s. At both .1s and .2s, STEP must produce contact-force magnitude154.945070N, within1%=1.54945070N, before Q begins. The same successful child's exact retained native contact frame must have nonempty active samples, positive pressure and actual native STICK. Preserve true pair, step, increment, time, case and input/output custody. Missing or repeated requested-time CF blocks or contact frames are ambiguous and must fail, rather than being silently collapsed into a dictionary.

An ancillary unchanged-default RAMP control uses the same full1s source history. Its expected early magnitudes are15.4945070N at .1s (1% budget .154945070N) and30.9890140N at .2s (budget .309890140N). This distinguishes the original native default history from the chosen STEP route. The final1s G1/Q0 equilibrium references coincide in both modes and remain separately checked.

Native CF moments use their legacy deformed-slave-position convention. Retain their literals as such; do not relabel or compare them to the separately qualified original-reference-global-origin moments. The unchanged final Current force-accounting material/cut/support/global and moment checks continue to supply that separate duty.
