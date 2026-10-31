"""Retain exact historical text inputs without rewriting original gate receipts."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
TEXT = {'.py','.c','.h','.f','.patch','.json','.toml','.lock','.txt','.yaml','.pl','.inp','.ref'}
def sha(data):
    return hashlib.sha256(data).hexdigest()
for label in sys.argv[1:]:
    directory = ROOT / label
    receipt = directory / 'execution.json'
    proof = json.loads(receipt.read_text())
    assert proof['source_inputs_before'] == proof['source_inputs_after']
    target = directory / 'input-snapshots-complete.json'
    if target.exists():
        old = json.loads(target.read_text())
        assert old['execution_sha256'] == sha(receipt.read_bytes())
        continue
    old_path = directory / 'input-snapshots.json'
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    rows = {}
    for name, wanted in proof['source_inputs_before'].items():
        path = Path(name)
        row = {'sha256': wanted}
        current = path.read_bytes() if path.is_file() else None
        if path.suffix in TEXT or path.name in ('Makefile_MT','LICENSE'):
            candidates = sorted((ROOT/'code-blobs').glob(wanted+'.*'))
            if current is not None and sha(current) == wanted:
                data = current
            elif name in old and 'snapshot' in old[name]:
                data = (ROOT/old[name]['snapshot']).read_bytes()
            elif candidates:
                data = candidates[0].read_bytes()
            else:
                raise ValueError('No exact historical source snapshot: '+name)
            assert sha(data) == wanted
            data.decode('utf-8')
            blob = ROOT/'code-blobs'/(wanted+(path.suffix or '.txt'))
            blob.parent.mkdir(exist_ok=True)
            if blob.exists():
                assert blob.read_bytes() == data
            else:
                blob.write_bytes(data)
            row['snapshot'] = str(blob.relative_to(ROOT))
        else:
            assert current is not None and sha(current) == wanted, name
            row['withheld'] = 'Native executable or pinned upstream source archive; not published'
        rows[name] = row
    with target.open('x') as stream:
        json.dump({'schema':'FreeCAD-960-exact-input-snapshots-v2',
                   'execution_sha256':sha(receipt.read_bytes()),
                   'capture_helper_sha256':sha(Path(__file__).read_bytes()),'inputs':rows},stream,indent=2)
        stream.write('\n')
    print(json.dumps({'label':label,'complete_input_snapshots':len(rows)}))
