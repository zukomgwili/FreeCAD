"""Read-only authored source/style gates. No native/app/build or installation."""
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parents[1]
REPO = Path('/Users/zukomgwili/src/FreeCAD')
sys.path.insert(0, str(TASK))
from process_control import assert_serial, run_bounded

FILES = [
    'femtools/force_accounting.py', 'femtools/ccxtools.py', 'femtools/elastic_connector.py',
    'femsolver/calculix/writer.py', 'femsolver/calculix/write_constraint_elastic_connector.py',
    'femsolver/calculix/write_constraint_rigidbody.py', 'femtest/app/test_elastic_connector.py',
    'femtest/app/test_force_accounting.py', 'femtest/app/test_movement_provenance.py',
    'femtest/app/coupled_port_fixture.py', 'femtest/app/coupled_port_audit.py',
    'femtest/app/test_moving_port_capacity_native.py',
]
PYTHON = '/Users/zukomgwili/.cache/pre-commit/repo02tpbrpu/py_env-python3.13/bin/python'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    assert len(sys.argv) == 2
    output = Path(sys.argv[1]).resolve()
    assert output.parent == TASK / 'native-qa' and not output.exists()
    assert not sys.flags.optimize
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    assert sha(TASK / 'process_control.py') == '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d'
    paths = [REPO / 'src/Mod/Fem' / name for name in FILES]
    paths += [REPO / 'src/Mod/Fem/CMakeLists.txt']
    paths += [REPO / 'src/Mod/Fem/femtest/data/calculix' / name for name in (
        'coupled_port_capacity_fixture.json', 'coupled_port_capacity_oracle.json')]
    paths += [REPO / 'package/calculix/force-accounting' / name for name in (
        'forceaccounting.c', 'hooks.patch', 'contract.json')]
    paths += [Path(__file__), TASK / 'process_control.py']
    before = {str(path): sha(path) for path in paths}
    output.mkdir()
    commands = [
        [PYTHON, '-B', '-m', 'black', '--version'],
        [PYTHON, '-B', '-m', 'black', '--check', '--no-cache', '--line-length', '100',
         *[str(REPO / 'src/Mod/Fem' / name) for name in FILES]],
        ['/opt/anaconda3/bin/flake8', '--version'],
        ['/opt/anaconda3/bin/flake8', '--ignore=E266,W503', '--max-line-length=100',
         *[str(REPO / 'src/Mod/Fem' / name) for name in FILES]],
        ['git', 'diff', '--check'],
    ]
    results = []
    for index, command in enumerate(commands):
        row = run_bounded(command, cwd=REPO, log=output / f'check-{index}.log', timeout=60)
        row.update(command=command, log_sha256=sha(output / f'check-{index}.log'))
        results.append(row)
    for path in paths:
        if path.suffix == '.json':
            json.loads(path.read_text())
        elif path.suffix == '.py':
            compile(path.read_bytes(), str(path), 'exec')
    after = {str(path): sha(path) for path in paths}
    passed = before == after and all(row['returncode'] == 0 and not row['timed_out']
        and row['child_reaped'] and row['process_group_gone'] for row in results)
    receipt = {'passed': passed, 'commands': results, 'inputs_before': before,
        'inputs_after': after, 'inputs_unchanged': before == after,
        'JSON_parsed_and_Python_compiled_without_execution': True,
        'native_or_application_launched': False, 'installation_performed': False}
    with (output / 'execution.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': passed, 'receipt': str(output / 'execution.json')}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
