"""Root-reviewed bounded native/configure/source build gates; NEVER install.

Usage: pixi run --frozen python -B run_builds.py NEW_LABEL {build,native,configure}
Configure additionally requires --candidate and --candidate-sha. Every input,
app, profile and selected dependency is fenced. Native builds use the pinned
2.23 archive/conda build8 recipe and their own fresh private toolchain workdir.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parent
TASK = ROOT.parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
BUILD = REPO / 'build/release'
APP = Path('/Applications/FreeCAD-27.1.0.app')
PREFIX = REPO / '.pixi/envs/default'
CONTROL = TASK / 'process_control.py'
sys.path.insert(0, str(TASK))
from process_control import assert_serial, run_bounded


FEM_CMAKE_COPY_LIST_SHA = '992bd5fe07b6539d1931e142d4173a210677d4a1e9f76a55a31ed7de7273d193'
UNLISTED_FEM_PYTHON = {
    'femtest/function_tests/__init__.py',
    'femtest/function_tests/test_support_utils.py',
    'femexamples/meshes/mesh_thermomech_flow1d_seg3.py',
    'femexamples/meshes/mesh_thermomech_spine_tetra10.py',
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def inventory(root):
    assert root.is_dir() and not root.is_symlink(), root
    result = {'.': {'kind': 'dir', 'mode': stat.S_IMODE(root.lstat().st_mode)}}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            row = {'mode': stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                row.update(kind='link', target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                row.update(kind='dir')
            else:
                assert stat.S_ISREG(mode), path
                row.update(kind='file', sha256=sha(path))
            result[str(path.relative_to(root))] = row
    return result


def custody():
    paths = [APP, Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
             Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
             Path('/Users/zukomgwili/Library/Preferences/FreeCAD')]
    return {str(path): inventory(path) for path in paths if path.is_dir()}


def critical():
    paths = [REPO / 'pixi.toml', REPO / 'pixi.lock', PREFIX / 'bin/ccx',
             PREFIX / 'lib/qt6/plugins/platforms/libqcocoa.dylib']
    paths += [PREFIX / 'lib/python3.13/site-packages/freecad' / name for name in (
        'UiTools.py', '__init__.py', 'deprecation.py', 'freecad_doc.py', 'module_io.py',
        'part.py', 'partdesign.py', 'project_utility.py', 'sketcher.py', 'utils.py', 'utils_zip.py')]
    result = {}
    for path in paths:
        info = path.lstat()
        result[str(path)] = {'sha256': sha(path), 'mode': info.st_mode,
                            'size': info.st_size, 'mtime_ns': info.st_mtime_ns,
                            'target': os.readlink(path) if path.is_symlink() else None}
    return result


def source_snapshot(extra=()):
    paths = [Path(__file__), CONTROL, REPO / 'CMakeLists.txt', REPO / 'src/Mod/Fem/CMakeLists.txt',
             REPO / 'pixi.toml', REPO / 'pixi.lock']
    paths += sorted((REPO / 'src/Mod/Fem').rglob('*.py'))
    paths += [REPO / 'package/calculix/force-accounting' / name
              for name in ('forceaccounting.c', 'hooks.patch', 'contract.json', 'COPYING')]
    paths += list(extra)
    head = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True, timeout=10).strip()
    assert all(Path(path).is_file() for path in paths), 'Required source/input missing'
    return {'git_head': head, 'files': {str(path): sha(path) for path in paths}}


def fem_python_copy_plan():
    """The checked GUI/VTK CMake list, not every incidental source-tree .py.

    The reviewed CMake file feeds its explicit Fem* script lists into the two
    fc_copy_sources targets at lines699 and904. This intentionally demands the
    GUI/VTK Python superset used by this source-build QA. A different CMake file
    or source-list omission fails closed instead of silently expanding exclusions.
    """
    cmake = REPO / 'src/Mod/Fem/CMakeLists.txt'
    assert sha(cmake) == FEM_CMAKE_COPY_LIST_SHA, 'Review a changed CMake copy list before using this private gate'
    text = cmake.read_text()
    assert 'fc_copy_sources(FemScriptsTarget "${CMAKE_BINARY_DIR}/Mod/Fem" ${FemAllScripts})' in text
    assert 'fc_copy_sources(FemGuiScriptsTarget "${CMAKE_BINARY_DIR}/Mod/Fem" ${FemAllGuiScripts})' in text
    listed = set(re.findall(r'^\s+([A-Za-z0-9_/.-]+\.py)\s*$', text, re.M))
    source_root = REPO / 'src/Mod/Fem'
    actual = {str(path.relative_to(source_root)) for path in source_root.rglob('*.py')}
    assert listed and listed <= actual, 'A CMake-listed source is missing'
    assert actual - listed == UNLISTED_FEM_PYTHON, 'Unreviewed CMake-copy omission or exclusion change'
    return {'cmake': str(cmake), 'cmake_sha256': FEM_CMAKE_COPY_LIST_SHA,
            'scope': 'Checked explicit GUI/VTK CMake Python copy-list superset',
            'required': sorted(listed), 'excluded_unlisted_source_only': sorted(UNLISTED_FEM_PYTHON)}


def fem_python_copy_parity(plan):
    source_root, build_root = REPO / 'src/Mod/Fem', BUILD / 'Mod/Fem'
    missing = [name for name in plan['required'] if not (build_root / name).is_file()]
    mismatched = [name for name in plan['required'] if (build_root / name).is_file()
                  and sha(source_root / name) != sha(build_root / name)]
    return {'passed': not missing and not mismatched, 'missing': missing, 'mismatched': mismatched}


def build_snapshot():
    paths = [BUILD / 'src/Build/Version.h', BUILD / 'bin/FreeCADCmd', BUILD / 'bin/FreeCAD',
             BUILD / 'lib/libFreeCADApp.dylib', BUILD / 'Mod/Fem/Fem.so', BUILD / 'Mod/Fem/FemGui.so',
             BUILD / 'data/NativeSolvers/ccx-force-accounting', BUILD / 'CMakeCache.txt']
    plan = fem_python_copy_plan()
    paths += [BUILD / 'Mod/Fem' / name for name in plan['required']]
    header = BUILD / 'src/Build/Version.h'
    macros = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', header.read_text(), re.M)) if header.is_file() else {}
    return {'files': {str(path): sha(path) for path in paths if path.is_file()},
            'version_header': macros, 'fem_python_copy_plan': plan,
            'fem_python_copy_parity': fem_python_copy_parity(plan)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('mode', choices=('build', 'native', 'configure'))
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--candidate-sha')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert not sys.flags.optimize
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    assert sha(CONTROL) == '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d'
    run = ROOT / args.label
    assert not run.exists()
    production = REPO / 'package/calculix/force-accounting'
    extra = []
    if args.mode == 'native':
        driver = REPO / 'package/local-completion/calculix-9zt-probe/build_probe.py'
        archive = Path('/private/tmp/freecad-5ar-primary.v96dZv/ccx_2.23.src.tar.bz2')
        recipe = Path('/Users/zukomgwili/Library/Caches/rattler/cache/pkgs/calculix-2.23-pl5321hd17ca8b_8/info/recipe')
        pins_path = driver.parent / 'recipe-pins.json'
        pins = json.loads(pins_path.read_text())
        assert sha(archive) == '9c88385c10fb04f5dc6c4e98027a51bebdd8aee3920e05190d6c1dd08357d6e7'
        for relative, expected in pins.items():
            assert sha(recipe / relative) == expected, relative
        extra = [driver, archive, pins_path, driver.parent / 'pixi.toml', driver.parent / 'pixi.lock']
        extra += [recipe / relative for relative in pins]
        command = ['pixi', 'run', '--frozen', 'python', '-B', str(driver),
                   '--source-archive', str(archive), '--recipe', str(recipe),
                   '--workdir', str(run / 'native'), '--patch', str(production / 'hooks.patch'),
                   '--extra-source', str(production / 'forceaccounting.c'), '--runtime-prefix', str(PREFIX)]
    elif args.mode == 'configure':
        assert args.candidate and args.candidate_sha and args.candidate.is_file()
        assert sha(args.candidate) == args.candidate_sha
        extra = [args.candidate]
        command = ['pixi', 'run', '--frozen', 'cmake', '-S', str(REPO), '-B', str(BUILD),
                   '-DFREECAD_NATIVE_CCX_ACCOUNTING=' + str(args.candidate.resolve())]
    else:
        command = ['pixi', 'run', '--frozen', 'cmake', '--build', str(BUILD), '--parallel', '8']
    before, protected, dependencies = source_snapshot(extra), custody(), critical()
    initial_build = build_snapshot()
    run.mkdir()
    write(run / 'private-custody-before.json', protected)
    write(run / 'private-critical-before.json', dependencies)
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'FIVEAR_')) or key in ('PYTHONHOME', 'PYTHONPATH', 'DESTDIR'):
            environment.pop(key)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2')
    report = {'passed': False, 'mode': args.mode, 'installation_performed': False,
              'native_capacity_qualification_performed': False, 'source_before': before, 'build_before': initial_build,
              'timeout_seconds': 900, 'selected_dependency_scope': '15 selected inputs; CMakeCache observed as build state, not immutable dependency'}
    try:
        report.update(run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=900, environment=environment))
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        report['source_after'], report['build_after'] = source_snapshot(extra), build_snapshot()
        report['source_and_supervisor_unchanged'] = before == report['source_after']
        after, dependencies_after = custody(), critical()
        write(run / 'private-custody-after.json', after)
        write(run / 'private-critical-after.json', dependencies_after)
        report['app_and_profiles_unchanged'] = protected == after
        report['selected_critical_dependencies_unchanged'] = dependencies == dependencies_after
        report['native_source_sha256'] = {name: sha(production / name) for name in ('forceaccounting.c', 'hooks.patch', 'contract.json')}
        if args.mode == 'native':
            candidate = run / 'native/CalculiX/ccx_2.23/src/ccx_2.23_conda'
            report['candidate'] = {'path': str(candidate), 'sha256': sha(candidate)} if candidate.is_file() else None
        if args.mode in ('build', 'configure') and report.get('returncode') == 0:
            report['Fem_python_source_build_parity'] = report['build_after']['fem_python_copy_parity']['passed']
        report['passed'] = bool(report.get('returncode') == 0 and not report.get('timed_out') and
            report.get('child_reaped') and report.get('process_group_gone') and
            report['source_and_supervisor_unchanged'] and report['app_and_profiles_unchanged'] and
            report['selected_critical_dependencies_unchanged'] and report.get('Fem_python_source_build_parity', True))
        report['exit_code'] = report.get('returncode')
        for kind in ('custody', 'critical'):
            for when in ('before', 'after'):
                report[f'private_{kind}_{when}_sha256'] = sha(run / f'private-{kind}-{when}.json')
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('source_before', 'source_after', 'build_before', 'build_after')}, indent=2), flush=True)
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
