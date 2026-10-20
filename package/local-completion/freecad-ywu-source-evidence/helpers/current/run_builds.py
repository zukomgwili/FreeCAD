"""Owned, bounded native/source build gates for the Ywu prototype; no install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
sys.path.insert(0, str(ROOT))
from process_control import assert_serial, run_bounded


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('mode', choices=('native', 'configure', 'build'))
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args()
    assert args.label.replace('-', '').replace('_', '').isalnum()
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    run = ROOT / args.label
    run.mkdir()
    driver = REPO / 'package/local-completion/calculix-9zt-probe/build_probe.py'
    archive = Path('/private/tmp/freecad-5ar-primary.v96dZv/ccx_2.23.src.tar.bz2')
    recipe = Path('/Users/zukomgwili/Library/Caches/rattler/cache/pkgs/calculix-2.23-pl5321hd17ca8b_8/info/recipe')
    production = REPO / 'package/calculix/force-accounting'
    if args.mode == 'native':
        paths = [driver, archive, *sorted(recipe.rglob('*')),
                 production / 'forceaccounting.c', production / 'hooks.patch',
                 REPO / 'package/local-completion/calculix-9zt-probe/pixi.toml',
                 REPO / 'package/local-completion/calculix-9zt-probe/pixi.lock',
                 REPO / 'package/local-completion/calculix-9zt-probe/recipe-pins.json']
        command = ['pixi', 'run', '--frozen', 'python', '-B', str(driver),
                   '--source-archive', str(archive), '--recipe', str(recipe),
                   '--workdir', str(run / 'native'), '--patch', str(production / 'hooks.patch'),
                   '--extra-source', str(production / 'forceaccounting.c'),
                   '--runtime-prefix', str(REPO / '.pixi/envs/default')]
    else:
        paths = [*sorted((REPO / 'src/Mod/Fem').rglob('*.py')),
                 REPO / 'src/Mod/Fem/CMakeLists.txt', production / 'forceaccounting.c',
                 production / 'hooks.patch', production / 'contract.json', REPO / 'CMakeLists.txt',
                 REPO / 'pixi.toml', REPO / 'pixi.lock']
        if args.mode == 'configure':
            assert args.candidate and args.candidate.is_file()
            paths.append(args.candidate)
            command = ['pixi', 'run', '--frozen', 'cmake', '-S', str(REPO),
                       '-B', str(REPO / 'build/release'),
                       '-DFREECAD_NATIVE_CCX_ACCOUNTING=' + str(args.candidate)]
        else:
            command = ['pixi', 'run', '--frozen', 'cmake', '--build', 'build/release', '--parallel', '8']
    paths = [path for path in [Path(__file__), ROOT / 'process_control.py', *paths] if path.is_file()]
    before = {str(path): sha(path) for path in paths}
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('CCX_', 'YWU_', 'FREECAD_')):
            environment.pop(key)
    report = {'passed': False, 'mode': args.mode, 'installed': False, 'inputs_before': before}
    try:
        report.update(run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=900,
                                  environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        after = {str(path): sha(path) for path in paths}
        report['inputs_after'] = after
        report['inputs_unchanged'] = before == after
        report['passed'] = bool(report.get('returncode') == 0 and not report.get('timed_out')
                                and report.get('child_reaped') and report.get('process_group_gone')
                                and report['inputs_unchanged'])
        with (run / 'execution.json').open('x') as stream:
            stream.write(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('inputs_before', 'inputs_after')}, indent=2))
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
