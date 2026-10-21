"""Run the reviewed native whole-export observation, then enforce frozen work caps.

The observational producer remains unchanged. Its PASS is not the work-budget
verdict: this command exits one on excessive native work, after retaining all
actual output and custody evidence. Root alone executes this composite.
"""
import sys
sys.dont_write_bytecode = True

import hashlib
import importlib.util
import json
from pathlib import Path
import re

TASK = Path(__file__).resolve().parent
QA = TASK / 'proposals'
PINS = {
    'run_tiny_profile.py': 'e685745fe3a73083b1d605c5fbb8a2d23df7ad65663bad023b5cc118d4790c71',
    'Q37WholeExport.py': 'a9a7ee0ec437686c58d30b30493b58ebd1468c529b159fe0946064163156b6c4',
    'Q37Identity.py': '36fb37d7e8f22625e3f2f3e52c5dddf22aaaa9d45b06044625807ee35d423b10',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if sys.flags.optimize or len(sys.argv) != 3 or sys.argv[1] != '--label' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', sys.argv[2]):
        raise RuntimeError('Use unoptimized Python with --label NEW_LABEL')
    label = sys.argv[2]
    own = Path(__file__).read_bytes()
    for name, expected in PINS.items():
        if sha((QA / name).read_bytes()) != expected:
            raise RuntimeError('Reviewed observation changed: ' + name)
    sys.path.insert(0, str(QA))
    spec = importlib.util.spec_from_file_location('Q37FrozenObservationDriver', QA / 'run_tiny_profile.py')
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    result = driver.main()
    run = TASK / label
    if result != 0:
        raise RuntimeError('Native observation/custody failed; not a work-budget RED')
    execution_raw, observation_raw = (run / 'execution.json').read_bytes(), (run / 'observation.json').read_bytes()
    execution, observation = json.loads(execution_raw), json.loads(observation_raw)
    if not execution['passed'] or not observation['passed'] or observation['actual_write_inp_file_calls'] != 1:
        raise RuntimeError('Missing successful actual whole write')
    if execution['produced_outputs']['observation.json']['sha256'] != sha(observation_raw):
        raise RuntimeError('Execution/observation binding differs')
    profile = (run / 'whole-write.prof').read_bytes()
    if sha(profile) != observation['profile_blob']['sha256'] or execution['produced_outputs']['whole-write.prof'] != observation['profile_blob']:
        raise RuntimeError('Actual profiler binding differs')
    elements, groups = observation['element_count'], observation['group_count']
    if elements <= 0 or groups <= 0:
        raise RuntimeError('Required native owned mesh unavailable')
    limits = {'Part.Shape.isValid': 36, 'Fem.FemMesh.getElementNodes': 24 * elements,
              'Fem.FemMesh.getGroupElements': 20 * groups + 64}
    checks = []
    for symbol, limit in limits.items():
        count = observation['native_operations'][symbol]['total_calls']
        if not isinstance(count, int) or count <= 0:
            raise RuntimeError('Required native profiler symbol unavailable: ' + symbol)
        checks.append({'native_operation': symbol, 'actual_calls': count, 'maximum_calls': limit,
                       'passed': count <= limit})
    if Path(__file__).read_bytes() != own or (run / 'execution.json').read_bytes() != execution_raw or (run / 'observation.json').read_bytes() != observation_raw or (run / 'whole-write.prof').read_bytes() != profile:
        raise RuntimeError('Composite inputs/actual evidence changed')
    report = {'schema': 'FreeCAD-3q7-whole-export-work-regression-v1',
              'passed': all(row['passed'] for row in checks), 'actual_public_writes': 1,
              'execution_sha256': sha(execution_raw), 'observation_sha256': sha(observation_raw),
              'profiler_sha256': sha(profile), 'composite_sha256': sha(own), 'producer_pins': PINS,
              'element_count': elements, 'group_count': groups, 'checks': checks,
              'scope': 'Pre-implementation tiny real-owned-mesh whole-export work envelope, not a wall-time SLA, universal scaling proof, guard qualification or physical acceptance.'}
    with (run / 'work-bound.json').open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
