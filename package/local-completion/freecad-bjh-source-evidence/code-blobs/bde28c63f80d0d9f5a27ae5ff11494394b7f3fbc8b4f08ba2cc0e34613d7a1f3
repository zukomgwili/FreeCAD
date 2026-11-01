"""Exact ordinary-field comparison on unchanged, stock-written input."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fields(path):
    return [line for line in Path(path).read_bytes().splitlines()
            if line[4:10] not in (b'1UDATE',b'1UTIME')
            and not line.startswith(b'    1UCOMPILETIME')]


def main():
    source=Path(os.environ['BJH_COMPONENT_SOURCE'])
    data=json.loads((source/'section-data.json').read_text())
    observed=Path(data['provenance']['frd']['path'])
    stock=Path(data['provenance']['deck'])
    original=stock.read_bytes()
    assert sha(observed)==data['provenance']['frd']['sha256']
    assert sha(stock)==data['provenance']['deck_sha256']
    directory=Path(os.environ['BJH_CASE_ROOT']);directory.mkdir()
    environment={key:value for key,value in os.environ.items()
                 if key not in {'CCX_BEAM_SECTION_REQUEST','CCX_FORCE_ACCOUNTING_REQUEST',
                                'CCX_CONTACT_STATE_REQUEST','CCX_9ZT_DIAGNOSTIC'}}
    environment['OMP_NUM_THREADS']=str(multiprocessing.cpu_count())
    reports={}
    for label,binary in (('candidate_inactive',os.environ['BJH_TEST_SOLVER']),
                         ('previous_inactive',os.environ['BJH_BASELINE_SOLVER'])):
        destination=directory/label;destination.mkdir()
        deck=destination/stock.name;deck.write_bytes(original)
        done=subprocess.run([binary,'-i',deck.stem],cwd=destination,env=environment,
                            capture_output=True,timeout=120)
        (destination/'stdout.txt').write_bytes(done.stdout)
        (destination/'stderr.txt').write_bytes(done.stderr)
        assert done.returncode==0,(done.returncode,done.stdout,done.stderr)
        assert deck.read_bytes()==original
        assert fields(deck.with_suffix('.frd'))==fields(observed),label
        reports[label]={'binary':str(Path(binary).resolve()),'binary_sha256':sha(binary),
                        'deck_sha256':sha(deck),'frd_sha256':sha(deck.with_suffix('.frd')),
                        'literal_native_mesh_and_fields_equal':True}
    assert stock.read_bytes()==original
    (directory/'mechanics-equivalence.json').write_text(json.dumps({
        'observed_frd_sha256':sha(observed),'observed_native_binary_sha256':data['provenance']['binary_sha256'],
        'exclusions_only':['1UDATE','1UTIME','1UCOMPILETIME'],'cases':reports},indent=2))


if __name__=='__main__':main()
