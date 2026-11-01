"""Additional reviewed bounded comparison; original exact failures are retained."""
import itertools
import json
import math
import multiprocessing
import os
from pathlib import Path
import subprocess

from BjhMechanics import sha, fields


def reporting(value):
    return 0 if value == 0 else 0.5 * 10 ** (math.floor(math.log10(abs(value))) - 5) + abs(value) * 2 ** -24


def compare(first, second):
    a, b = fields(first), fields(second)
    assert len(a) == len(b)
    dataset = None
    maxima = {'DISP': [0.] * 3, 'STRESS': [0.] * 6}
    used = {'DISP': [0.] * 3, 'STRESS': [0.] * 6}
    for x, y in zip(a, b):
        if x.startswith(b' -4'):
            dataset = x.split()[1].decode()
            assert dataset in maxima
        if x.startswith(b' -3'):
            dataset = None
        if dataset and x.startswith(b' -1'):
            assert x[:13] == y[:13]
            count = 3 if dataset == 'DISP' else 6
            assert len(x) == len(y) == 13 + 12 * count
            for i in range(count):
                v = float(x[13 + 12*i:25 + 12*i])
                w = float(y[13 + 12*i:25 + 12*i])
                assert math.isfinite(v) and math.isfinite(w)
                base = 1e-7 if dataset == 'DISP' else 1e-6 if i < 3 else 1e-4
                difference = abs(v - w)
                budget = base + reporting(v) + reporting(w)
                assert difference <= budget, (dataset, i, v, w, budget)
                maxima[dataset][i] = max(maxima[dataset][i], difference)
                used[dataset][i] = max(used[dataset][i], difference / budget)
        else:
            assert x == y, (x, y)
    return {'maximum_component_difference': maxima, 'maximum_budget_fraction': used,
            'literal_native_mesh_and_fields_equal': a == b}


def main():
    source = Path(os.environ['BJH_COMPONENT_SOURCE'])
    data = json.loads((source/'section-data.json').read_text())
    observed = Path(data['provenance']['frd']['path'])
    stock = Path(data['provenance']['deck'])
    original = stock.read_bytes()
    assert sha(observed) == data['provenance']['frd']['sha256']
    assert sha(stock) == data['provenance']['deck_sha256']
    directory = Path(os.environ['BJH_CASE_ROOT']);directory.mkdir()
    environment = {key:value for key,value in os.environ.items()
                   if key not in {'CCX_BEAM_SECTION_REQUEST','CCX_FORCE_ACCOUNTING_REQUEST',
                                  'CCX_CONTACT_STATE_REQUEST','CCX_9ZT_DIAGNOSTIC'}}
    environment['OMP_NUM_THREADS'] = str(multiprocessing.cpu_count())
    reports = {}; frds = {'observed': observed}
    for label, binary in (
        ('candidate_inactive_1',os.environ['BJH_TEST_SOLVER']),
        ('candidate_inactive_2',os.environ['BJH_TEST_SOLVER']),
        ('previous_inactive',os.environ['BJH_BASELINE_SOLVER']),
    ):
        destination=directory/label;destination.mkdir()
        deck=destination/stock.name;deck.write_bytes(original)
        done=subprocess.run([binary,'-i',deck.stem],cwd=destination,env=environment,
                            capture_output=True,timeout=120)
        (destination/'stdout.txt').write_bytes(done.stdout)
        (destination/'stderr.txt').write_bytes(done.stderr)
        assert done.returncode == 0,(done.returncode,done.stdout,done.stderr)
        assert deck.read_bytes() == original
        frds[label]=deck.with_suffix('.frd')
        reports[label]={'binary':str(Path(binary).resolve()),'binary_sha256':sha(binary),
                        'deck_sha256':sha(deck),'frd_sha256':sha(frds[label])}
    comparisons = {a+'__'+b:compare(frds[a],frds[b])
                   for a,b in itertools.combinations(frds,2)}
    assert stock.read_bytes() == original
    (directory/'mechanics-equivalence.json').write_text(json.dumps({
        'type':'ADDITIONAL_BOUNDED_COMPARISON_NOT_EXACT_QUALIFICATION',
        'observed_frd_sha256':sha(observed),
        'observed_native_binary_sha256':data['provenance']['binary_sha256'],
        'OMP_NUM_THREADS':environment['OMP_NUM_THREADS'],
        'exclusions_only':['1UDATE','1UTIME','1UCOMPILETIME'],
        'runs':reports,'comparisons':comparisons},indent=2)+'\n')


if __name__ == '__main__':
    main()
