import sys
sys.dont_write_bytecode = True
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import FreeCAD as App
spec = importlib.util.spec_from_file_location('native_source', '/Users/zukomgwili/src/FreeCAD/src/Mod/Fem/femtest/app/test_staged_selfweight_native.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TestStagedSelfweightNative = module.TestStagedSelfweightNative

def setUpModule():
    import importlib
    repo=Path('/Users/zukomgwili/src/FreeCAD')
    origins={}
    for name, relative in {
        'femobjects.solver_calculix':'femobjects/solver_calculix.py',
        'femsolver.calculix.write_step_equation':'femsolver/calculix/write_step_equation.py',
        'femsolver.calculix.write_amplitude':'femsolver/calculix/write_amplitude.py',
        'femtools.force_accounting':'femtools/force_accounting.py',
        'femtools.contact_state':'femtools/contact_state.py',
    }.items():
        actual=Path(importlib.import_module(name).__file__).resolve()
        expected=repo/'build/release/Mod/Fem'/relative
        assert actual==expected,(name,actual,expected)
        assert actual.read_bytes()==(repo/'src/Mod/Fem'/relative).read_bytes(),name
        origins[name]={'path':str(actual),'sha256':hashlib.sha256(actual.read_bytes()).hexdigest()}
    native=Path(App.ConfigGet('AppHomePath'))/'data/NativeSolvers/ccx-force-accounting'
    candidate=json.loads((Path(__file__).parent/'candidate-binary.json').read_text())
    assert hashlib.sha256(native.read_bytes()).hexdigest()==candidate['sha256']
    (Path(os.environ['E4K_RUN'])/'origins.json').write_text(json.dumps({'modules':origins,'native':str(native),'native_sha256':candidate['sha256']},indent=2)+'\n')
