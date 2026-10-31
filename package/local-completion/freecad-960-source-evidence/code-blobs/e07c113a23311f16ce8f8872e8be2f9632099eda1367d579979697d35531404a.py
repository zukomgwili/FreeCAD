"""Compare unchanged stock-written decks under old/new native executables."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent
OLD = Path('/Applications/FreeCAD-27.1.0.app/Contents/Resources/data/NativeSolvers/ccx-force-accounting')


class TestLegacyBeam(unittest.TestCase):
    def test_disabled_observer_preserves_native_frd_and_dat(self):
        config = json.loads((ROOT/'native-candidate.json').read_text())
        candidate = Path(config['path'])
        self.assertEqual(hashlib.sha256(OLD.read_bytes()).hexdigest(),
                         '0c2a86318df9c7cc9d921e5068ae52f1d53e27b7b16747e00a74ccc8fe37c6cc')
        directory = Path(os.environ['B960_WITNESS_ROOT'])
        environment = {key:value for key,value in os.environ.items()
                       if not key.startswith('CCX_')}
        environment.update(OMP_NUM_THREADS='1', CCX_NPROC_RESULTS='1',
                           CCX_NPROC_STIFFNESS='1', CCX_NPROC_EQUATION_SOLVER='1')
        cases = {
            'axial':'test_axial_tension_root_has_negative_global_end_action',
            'bending':'test_transverse_y_root_has_signed_shear_and_bending_equilibrium',
            'torsion':'test_torsion_couple_preserves_distinct_native_ends_at_a_shared_joint',
        }
        observations = []
        for name, method in cases.items():
            with self.subTest(case=name):
                deck = ROOT/'torsion-matrix-r01'/method/'Mesh.inp'
                before = hashlib.sha256(deck.read_bytes()).hexdigest()
                outputs = []
                for label, binary in [('legacy', OLD), ('candidate', candidate)]:
                    run = directory/(name+'-'+label)
                    run.mkdir()
                    target = run/'Mesh.inp'
                    shutil.copyfile(deck, target)
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)
                    with (run/'solver.log').open('xb') as stream:
                        process = subprocess.Popen([str(binary),'-i','Mesh'], cwd=run,
                            env=environment, stdin=subprocess.DEVNULL,
                            stdout=stream, stderr=subprocess.STDOUT)
                        try:
                            code = process.wait(timeout=60)
                        finally:
                            if process.poll() is None:
                                process.kill()
                                process.wait(timeout=5)
                    self.assertEqual(code, 0)
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)
                    frd = b'\n'.join(line for line in (run/'Mesh.frd').read_bytes().splitlines()
                                     if not line.startswith((b'    1UDATE ', b'    1UTIME ',
                                                             b'    1UCOMPILETIME ')))
                    dat = (run/'Mesh.dat').read_bytes()
                    outputs.append((frd,dat))
                self.assertEqual(outputs[0], outputs[1])
                observations.append({'case':name,'deck_sha256':before,
                    'frd_without_build_and_creation_metadata_sha256':hashlib.sha256(outputs[0][0]).hexdigest(),
                    'dat_sha256':hashlib.sha256(outputs[0][1]).hexdigest(),
                    'bitwise_equal':True})
        (directory/'legacy-equivalence.json').write_text(json.dumps(observations,indent=2)+'\n')
        print('[BEAM960-LEGACY]',json.dumps(observations),flush=True)


def load_tests(loader, _tests, _pattern):
    return loader.loadTestsFromTestCase(TestLegacyBeam)
