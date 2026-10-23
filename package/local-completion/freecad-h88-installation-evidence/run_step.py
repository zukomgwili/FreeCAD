"""h88 adapter to the unchanged bounded reversible-deployment step supervisor."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
ORIGINAL = REPO / 'package/local-completion/freecad-8rk-installation-evidence/run_step.py'
assert __debug__ and hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == '612141eb6c5f8693dd33d9dd8d5012a99d8571b16d17654043d187c7fca8bbb3'
spec = importlib.util.spec_from_file_location('_h88_deployment_step_core', ORIGINAL)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
PREFIX = ['/opt/homebrew/bin/pixi', 'run', '--frozen']
core.COMMANDS = {
    'admission-self-test': PREFIX + ['python', '-B', str(ROOT / 'audit_payload_stage.py'), 'admission-self-test'],
    'capture': PREFIX + ['python', '-B', '-c', 'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); import critical_pins; critical_pins.capture()'],
    'payload': PREFIX + ['cmake', '--install', 'build/release'],
    'audit-payload': PREFIX + ['python', '-B', str(ROOT / 'audit_payload_stage.py'), 'payload'],
    'stage': PREFIX + ['python', '-B', str(ROOT / 'stage_install.py'), 'stage'],
    'audit-stage': PREFIX + ['python', '-B', str(ROOT / 'audit_payload_stage.py'), 'stage'],
    'audit-custody': PREFIX + ['python', '-B', str(ROOT / 'audit_payload_stage.py'), 'custody'],
    'swap': PREFIX + ['python', '-B', str(ROOT / 'stage_install.py'), 'swap'],
}

if __name__ == '__main__':
    # Do not repeat the earlier deployment's nonqualifying pre-capture payload.
    # Admission happens before the inherited supervisor can launch CMake.
    if sys.argv[1:2] == ['payload']:
        import critical_pins
        for name in ('baseline-inventory.json', 'profile-inventories.json',
                     'build-identity.json', 'critical-before-DESTDIR.json', 'identity.json'):
            assert (ROOT / name).is_file() and not (ROOT / name).is_symlink(), name
        capture = json.loads((ROOT / 'step-capture/execution.json').read_text())
        assert capture['schema'] == 'FreeCAD-8rk-install-step-v1'
        assert capture['mode'] == 'capture' and capture['source_commit'] == core.install.COMMIT
        assert type(capture['returncode']) is int and capture['returncode'] == 0
        assert capture['timed_out'] is False
        for key in ('passed', 'child_reaped', 'process_group_gone',
                    'inputs_unchanged', 'protected_unchanged'):
            assert capture[key] is True, key
        assert capture['inputs_before'] == capture['inputs_after']
        assert capture['protected_before'] == capture['protected_after']
        assert core.sha(ROOT / 'step-capture/run.log') == capture['log_sha256']
        for name, wanted in capture['inputs_after'].items():
            assert core.sha(name) == wanted, name
        critical_pins.verify()
        core.install.unchanged_original()
    raise SystemExit(core.main())
