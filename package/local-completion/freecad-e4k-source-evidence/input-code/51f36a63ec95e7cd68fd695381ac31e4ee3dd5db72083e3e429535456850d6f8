"""Use the existing pinned serial/profile-custody gate for e4k source checks."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
path = REPO/'package/local-completion/freecad-8rk-installation-evidence/run_gate.py'
spec = importlib.util.spec_from_file_location('e4k_build_guard', path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
guard.ROOT=ROOT
guard.SOURCE_FILES=(
    'src/Mod/Fem/femobjects/solver_calculix.py',
    'src/Mod/Fem/femsolver/calculix/write_step_equation.py',
    'src/Mod/Fem/femsolver/calculix/write_amplitude.py',
    'src/Mod/Fem/femtest/app/test_static_step_amplitude.py',
    'src/Mod/Fem/femtest/app/test_staged_selfweight_native.py',
    'package/calculix/force-accounting/forceaccounting.c',
    'package/calculix/force-accounting/hooks.patch',
    'package/calculix/force-accounting/contactstate.c',
    'src/Mod/Fem/femtools/contact_state.py',
    'src/Mod/Fem/femtest/app/test_contact_state_catalogue.py',
    str(ROOT/'build.py'), str(ROOT/'candidate-binary.json'),
)
guard.COMMANDS['configure']=['pixi','run','--frozen','cmake','-S',str(REPO),'-B',str(REPO/'build/release'),'-DFREECAD_NATIVE_CCX_ACCOUNTING='+json.loads((ROOT/'candidate-binary.json').read_text())['path']]
guard.COMMANDS['guard-compile']=['clang','-std=c11','-Wall','-Wextra','-Werror','-O2',str(ROOT/'spc_guard_test.c'),'-o',str(ROOT/'spc_guard_test')]
guard.COMMANDS['guard-test']=[str(ROOT/'spc_guard_test')]
if __name__ == '__main__':
    raise SystemExit(guard.main())
