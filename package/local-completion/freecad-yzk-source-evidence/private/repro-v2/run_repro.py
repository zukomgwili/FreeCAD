"""Root-reviewed bounded installed reproduction. No action occurs on import.

Usage: pixi run --frozen python -B run_repro.py NEW_LABEL
Separate900s supervisor; fixture/identity/definition bytes equal the original frozen attempt.\nNormal test failure remains a failure; exact native refusal is retained as RED.
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

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/zukomgwili/src/FreeCAD')
APP = Path('/Applications/FreeCAD-27.1.0.app')
CONTROL = ROOT.parent / 'process_control.py'
sys.path.insert(0, str(ROOT.parent))
from process_control import assert_serial, run_bounded


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def inventory(root):
    assert root.is_dir() and not root.is_symlink(), root
    result = {'.': {'kind': 'dir', 'mode': stat.S_IMODE(root.lstat().st_mode)}}
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in sorted(directories + names):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            item = {'mode': stat.S_IMODE(mode)}
            if stat.S_ISLNK(mode):
                item.update(kind='link', target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                item.update(kind='dir')
            else:
                assert stat.S_ISREG(mode), path
                item.update(kind='file', sha256=sha(path))
            result[str(path.relative_to(root))] = item
    return result


def inputs():
    paths = [ROOT / name for name in ('run_repro.py', 'InstalledIdentity.py',
                                     'PortCapacityWitness.py', 'fixture.json')]
    paths += [CONTROL, REPO / 'package/local-completion/freecad-ywu-installation.json',
              REPO / 'package/local-completion/freecad-ywu-installation-evidence/private/installed-endload/identity.json',
              REPO / 'pixi.toml', REPO / 'pixi.lock',
              REPO / '.pixi/envs/default/lib/qt6/plugins/platforms/libqcocoa.dylib',
              REPO / '.pixi/envs/default/bin/ccx']
    original = ROOT.parent / 'repro'
    originals = {
        'InstalledIdentity.py': '13a396f61ba66e1885b111ab73a27186e4dc96d8a9004b86a7db02f26fbe21a1',
        'PortCapacityWitness.py': '16be8acafdfc0bf81beb1a5896d619921f5a5e0bbdb63a137a195e4dedd86a22',
        'fixture.json': 'ea44faba259494b772db6357996c7e543c99bdf5df366b4b17092eaebf90e7b9',
        'run_repro.py': 'c7193b29e24dfaccc99ab4a3ef6806109d3dc108f223f882c8bf9feedb883f1c',
    }
    for name, expected in originals.items():
        assert sha(original / name) == expected, name
        paths.append(original / name)
        if name != 'run_repro.py':
            assert sha(ROOT / name) == expected, name
    return {str(path): sha(path) for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label)
    assert_serial(('gmsh', 'ninja', 'make', 'gmake'))
    assert sha(CONTROL) == '5199c733fdc18a2c6f78d03ea2a3281e236419365219d7b9f33b5ecca0aa733d'
    wrapper = APP / 'Contents/MacOS/FreeCADCmd'
    assert wrapper.is_file() and os.access(wrapper, os.X_OK)
    protected = [APP, Path('/Users/zukomgwili/Library/Application Support/FreeCAD'),
                 Path('/Users/zukomgwili/Library/Application Support/FreeCAD Local'),
                 Path('/Users/zukomgwili/Library/Preferences/FreeCAD')]
    custody = {str(path): inventory(path) for path in protected if path.is_dir()}
    before = inputs()
    run = ROOT / args.label
    run.mkdir()
    write(run / 'private-custody-before.json', custody)
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('FREECAD_', 'CCX_', 'APPQA_', 'YWU_', 'YZK_', 'FIVEAR_')) or key in (
                'PYTHONHOME', 'PYTHONPATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            environment.pop(key)
    for key in ('FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        path = run / key.lower()
        path.mkdir()
        environment[key] = str(path)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='2',
                       TMPDIR=environment['FREECAD_USER_TEMP'], YZK_OUTPUT=str(run))
    command = [str(wrapper), '-u', str(run / 'user.cfg'), '-s', str(run / 'system.cfg'),
               '-P', str(ROOT), '-t', 'InstalledIdentity', '-t', 'PortCapacityWitness']
    report = {'passed': False, 'application': str(APP), 'timeout_seconds': 900,
              'inputs_before': before, 'no_Oomakhi_run': True, 'native_solver_override': False,
              'scope': 'Initial installed stock65-port capacity tracer, not full physical qualification'}
    try:
        report.update(run_bounded(command, cwd=REPO, log=run / 'run.log', timeout=900, environment=environment))
    except BaseException as error:
        report['supervision_error'] = repr(error)
    finally:
        report['inputs_after'] = inputs()
        after = {path: inventory(Path(path)) for path in custody}
        write(run / 'private-custody-after.json', after)
        report['app_and_profiles_unchanged'] = custody == after
        report['inputs_unchanged'] = before == report['inputs_after']
        report['custody_before_sha256'] = sha(run / 'private-custody-before.json')
        report['custody_after_sha256'] = sha(run / 'private-custody-after.json')
        text = (run / 'run.log').read_text(errors='replace')
        counts = re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*$', text, re.M)
        report['unittest_counts'] = counts
        identity_path, probe_path = run / 'identity.json', run / 'witness/probe.json'
        identity = json.loads(identity_path.read_text()) if identity_path.is_file() else {}
        probe = json.loads(probe_path.read_text()) if probe_path.is_file() else {}
        report['identity_passed'] = identity.get('passed') is True
        report['identity_sha256'] = sha(identity_path) if identity else None
        report['probe_sha256'] = sha(probe_path) if probe else None
        report['probe_stage'] = probe.get('stage')
        report['native_returncode'] = probe.get('solver_returncode')
        report['native_diagnostic'] = probe.get('native_diagnostic')
        report['runtime'] = identity.get('runtime')
        complete = (report.get('child_reaped') and report.get('process_group_gone') and not report.get('timed_out')
                    and report['app_and_profiles_unchanged'] and report['inputs_unchanged'] and report['identity_passed'])
        report['native_refusal_RED_observed'] = bool(complete and probe.get('stage') == 'native_run' and
            probe.get('solver_returncode') not in (None, 0) and len(probe.get('actual_PORT_declarations', [])) == 65 and
            probe.get('stock_deck_unchanged') and probe.get('stock_request_unchanged'))
        report['passed'] = bool(complete and report.get('returncode') == 0 and probe.get('passed') and
            len(counts) == 1 and int(counts[0][0]) == 2 and re.search(r'^OK\s*$', text, re.M) and
            not re.search(r'^(FAILED\b|FAIL:|ERROR:|UNEXPECTED SUCCESS:)', text, re.M))
        write(run / 'execution.json', report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('inputs_before', 'inputs_after')}, indent=2), flush=True)
    assert_serial(('gmsh',))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
