"""Derive a byte-validated attestation of one ALREADY completed native build.

Root alone executes this read-only audit after reading it. It never launches a
solver, compiler, app or capability query, never rewrites original evidence,
and creates only a new, explicitly DERIVED receipt at the requested QA path.
This bridges the earlier root supervisor schema; it is NOT a new build run or
physical/capacity qualification. The old supervisor did not inventory profiles.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
from pathlib import Path

QA = Path(__file__).resolve().parent
TASK = QA.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
RUN = TASK / 'native-capacity-r01'
NATIVE = RUN / 'native'
PRODUCTION = REPO / 'package/calculix/force-accounting'
DRIVER = REPO / 'package/local-completion/calculix-9zt-probe'
RECIPE = Path('/Users/zukomgwili/Library/Caches/rattler/cache/pkgs/calculix-2.23-pl5321hd17ca8b_8/info/recipe')
ARCHIVE = Path('/private/tmp/freecad-5ar-primary.v96dZv/ccx_2.23.src.tar.bz2')
CANDIDATE = NATIVE / 'CalculiX/ccx_2.23/src/ccx_2.23_conda'
C_SHA = '8c51e06abecf4c2b1537b1e6f4ef4606ea8481a4a180d465cbff00d63329f2a4'
HOOKS_SHA = 'e500c46cc9cd26fc4e63508a51375bd09ebdc0973638375df14cffd036c9bfa7'
CONTRACT_OBSERVED_SHA = '4418a41794adfc386143bd94b709794eea0d9991e774ab559e714e2782730ad3'
CANDIDATE_SHA = '6c02452a896727af6cb4578fd3fb6bbfbdd48e3fb887c1c04fa2d8b171976c66'
ARCHIVE_SHA = '9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7'
PINS_SHA = '196b555f58afc8330b6eda97098ebc22cbde3f96eed807aaf6c1dc5dd4dc9dd7'
LOCK_SHA = 'a1535ebfa2395fd505583317f899736433375e12e93ed6887e8b91ac25e81b09'
MANIFEST_SHA = '89e8a507500fc6ab8a094e4a1567082f87db1cb419267b7b64963e08ade59fb3'
CONTROL_SHA = '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d'
EVIDENCE_PINS = {
    RUN / 'execution.json': 'a12387d4bb6f2bff67c4f82312e8d403f23031dfb783913e196883b8da808ab9',
    NATIVE / 'build-receipt.json': 'b899e0035c706fa6d272eee73f2515afd8c89747cea44875f0e0b541fd69a89e',
    RUN / 'run.log': '54ca894ed95bd97af8b6838a3061a7c33ec577929009b24bae4401c35bdaf0f4',
    NATIVE / 'build.log': '1534760e588602722ca14b6bc9472af4dac48c13a33ac30ca0312e98f74d179c',
    NATIVE / 'functional-tests.log': '6a713b172e46519217bc0adb5de6e9d1fe2eb3c0edc55171196d8834115ecaf2',
}
INPUT_PINS = {
    TASK / 'run_builds.py': '14744f41739b0aaefe6332c2d0d17aea45e4ccc253565c9f5e7cc5af0c2ac1ce',
    TASK / 'process_control.py': CONTROL_SHA,
    DRIVER / 'build_probe.py': 'c91d168d9c56b9641deba38f9c08c41ccfe1518fff49e75d753fd53f3f107f61',
    ARCHIVE: ARCHIVE_SHA, DRIVER / 'recipe-pins.json': PINS_SHA,
    DRIVER / 'pixi.toml': MANIFEST_SHA, DRIVER / 'pixi.lock': LOCK_SHA,
    PRODUCTION / 'forceaccounting.c': C_SHA, PRODUCTION / 'hooks.patch': HOOKS_SHA,
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate():
    for path, expected in {**EVIDENCE_PINS, **INPUT_PINS}.items():
        assert sha(path) == expected, str(path)
    outer = json.loads((RUN / 'execution.json').read_text())
    inner = json.loads((NATIVE / 'build-receipt.json').read_text())
    assert outer['passed'] is True and outer['mode'] == 'native'
    assert outer['installed'] is False and outer['returncode'] == 0
    assert outer['timed_out'] is False
    assert all(outer[name] is True for name in ('reaped', 'child_reaped', 'process_group_gone', 'inputs_unchanged'))
    assert outer['pid'] == outer['process_group'] and outer['elapsed_seconds'] < 900
    assert outer['inputs_before'] == outer['inputs_after']
    assert outer['log_sha256'] == EVIDENCE_PINS[RUN / 'run.log']
    assert outer['command'] == ['pixi', 'run', '--frozen', 'python', '-B', str(DRIVER / 'build_probe.py'),
        '--source-archive', str(ARCHIVE), '--recipe', str(RECIPE), '--workdir', str(NATIVE),
        '--patch', str(PRODUCTION / 'hooks.patch'), '--extra-source', str(PRODUCTION / 'forceaccounting.c'),
        '--runtime-prefix', str(REPO / '.pixi/envs/default')]
    pins = json.loads((DRIVER / 'recipe-pins.json').read_text())
    expected_inputs = {str(path): expected for path, expected in INPUT_PINS.items()}
    for relative, expected in pins.items():
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        assert sha(RECIPE / relative) == expected, relative
        expected_inputs[str(RECIPE / relative)] = expected
    assert outer['inputs_before'] == expected_inputs, 'The original execution must cover the complete exact recipe/driver/C/hooks input set'
    for path, expected in expected_inputs.items():
        assert sha(path) == expected, path
    assert inner == {
        'installed': False, 'channel': 'CCX_FORCE_ACCOUNTING_V3', 'baseline': False,
        'source_sha256': ARCHIVE_SHA, 'recipe_pins_sha256': PINS_SHA,
        'probe_patch_sha256': HOOKS_SHA, 'extra_source_sha256': C_SHA,
        'toolchain_lock_sha256': LOCK_SHA, 'binary': str(CANDIDATE),
        'binary_sha256': CANDIDATE_SHA, 'dependency_functional_tests_passed': True,
        'physical_duty_qualified': False}
    assert sha(CANDIDATE) == CANDIDATE_SHA
    assert sha(CANDIDATE.parent / 'forceaccounting.c') == C_SHA
    assert sha(NATIVE / 'pixi.toml') == MANIFEST_SHA
    assert sha(NATIVE / 'pixi.lock') == LOCK_SHA
    assert sha(PRODUCTION / 'contract.json') == CONTRACT_OBSERVED_SHA
    return expected_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert not sys.flags.optimize
    output = args.output.absolute()
    assert output.parent.resolve() == QA and not output.exists()
    assert sha(TASK / 'process_control.py') == CONTROL_SHA
    sys.path.insert(0, str(TASK))
    from process_control import assert_serial
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    inputs = validate()
    monitored = {**inputs, **{str(path): expected for path, expected in EVIDENCE_PINS.items()},
        str(Path(__file__)): sha(__file__), str(CANDIDATE): CANDIDATE_SHA,
        str(CANDIDATE.parent / 'forceaccounting.c'): C_SHA,
        str(NATIVE / 'pixi.toml'): MANIFEST_SHA, str(NATIVE / 'pixi.lock'): LOCK_SHA,
        str(PRODUCTION / 'contract.json'): CONTRACT_OBSERVED_SHA}
    assert all(sha(path) == expected for path, expected in monitored.items())
    report = {
        'schema': 'FreeCAD-yzk-existing-native-build-attestation-v1', 'passed': True,
        'derived_receipt': True, 'mode': 'native', 'new_execution_performed': False,
        'installed': False, 'physical_duty_qualified': False, 'native_capacity_qualified': False,
        'candidate': {'path': str(CANDIDATE), 'sha256': CANDIDATE_SHA},
        'compiled_sources_sha256': {'forceaccounting.c': C_SHA, 'hooks.patch': HOOKS_SHA},
        'native_source_sha256': {'forceaccounting.c': C_SHA, 'hooks.patch': HOOKS_SHA,
                                'contract.json': CONTRACT_OBSERVED_SHA},
        'contract_compilation_claimed': False,
        'contract_scope': 'Currently byte-observed protocol document; absent from the original build supervisor input set and not a compiler input.',
        'original_evidence': {str(path.relative_to(RUN)): {'path': str(path), 'sha256': expected}
                              for path, expected in EVIDENCE_PINS.items()},
        'validated_original_inputs': inputs,
        'validated_current_files': monitored,
        'capability_observed_in_original_driver_receipt': 'CCX_FORCE_ACCOUNTING_V3',
        'dependency_functional_tests_passed_in_original_driver_receipt': True,
        'historical_app_profile_custody_reconstructed': False,
        'scope': 'Exact original successful build receipts, logs, declared immutable inputs, copied C, toolchain lock and candidate bytes. No new execution, physical qualification or retrospective profile-custody claim.'}
    with output.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'derived_receipt': str(output), 'sha256': sha(output),
                      'new_execution_performed': False, 'physical_duty_qualified': False}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
