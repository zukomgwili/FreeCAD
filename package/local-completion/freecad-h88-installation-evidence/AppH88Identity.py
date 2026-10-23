"""Literal h88 bundle identity and public BIM/private-copy regression suite."""
import sys

sys.dont_write_bytecode = True

import ctypes
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import unittest

import FreeCAD as App

REPOSITORY = Path('/Users/zukomgwili/src/FreeCAD')
MANIFEST_PATH = Path(os.environ['H88_INSTALL_MANIFEST'])
MANIFEST_BYTES = MANIFEST_PATH.read_bytes()
MANIFEST = json.loads(MANIFEST_BYTES)
RESULTS = {}
PUBLIC_PREFIX = 'bimtests.TestArchShapeCleanup.TestArchShapeCleanup.'
PUBLIC_TEST_IDS = sorted(PUBLIC_PREFIX + name for name in (
    'test_box_material_is_preserved', 'test_bore_material_and_void_are_preserved',
    'test_compound_preserves_both_disconnected_solids',
    'test_notched_channels_keep_valid_material',
    'test_placed_bore_keeps_material_in_the_global_frame',
    'test_saved_bases_preserve_base_and_material_links',
    'test_successful_cleanup_still_removes_splitters'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_origins():
    resources = Path(MANIFEST['application']) / 'Contents/Resources'
    origins = {}
    for entry in sys.path:
        actual = Path(entry or os.getcwd()).resolve()
        assert not any(actual.is_relative_to(REPOSITORY / part) for part in ('src', 'build')), actual
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, '__file__', None)
        if not origin:
            continue
        actual = Path(origin).resolve()
        assert not any(actual.is_relative_to(REPOSITORY / part) for part in ('src', 'build')), (name, actual)
        if name.startswith(('Arch', 'bimtests', 'Bim')) or name == 'TestArch':
            assert actual.is_relative_to(resources / 'Mod/BIM'), (name, actual)
            origins[name] = {'path': str(actual), 'sha256': sha(actual)}
    return origins


class AppH88Identity(unittest.TestCase):
    def test_exact_application_identity_and_loaded_native_origins(self):
        application = Path(MANIFEST['application'])
        resources = application / 'Contents/Resources'
        self.assertEqual(application.resolve(strict=True), application)
        self.assertFalse(application.is_symlink())
        runtime = App.Version()
        self.assertEqual(runtime[:3], ['27', '1', '0'])
        self.assertEqual(runtime[3], MANIFEST['revision'])
        self.assertEqual(runtime[-1], MANIFEST['commit'])
        self.assertEqual(bool(App.GuiUp), MANIFEST['gui'])
        self.assertEqual(Path(App.getHomePath()).resolve(), resources)
        self.assertTrue(sys.dont_write_bytecode)
        self.assertNotIn('FREECAD_CONTACT_STATE_SOLVER', os.environ)
        expected = MANIFEST['expected_native_files']
        for filename, wanted in expected.items():
            path = Path(filename)
            self.assertEqual(path.resolve(strict=True), path)
            self.assertTrue(path.is_relative_to(resources))
            self.assertFalse(path.is_symlink())
            self.assertEqual(sha(path), wanted)
        for relative, wanted in MANIFEST['expected_source_files'].items():
            path = resources / relative
            self.assertEqual(path.resolve(strict=True), path)
            self.assertFalse(path.is_symlink())
            self.assertEqual(sha(path), wanted, relative)
        dyld = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
        dyld._NSGetExecutablePath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        dyld._NSGetExecutablePath.restype = ctypes.c_int
        size = ctypes.c_uint32(4096)
        buffer = ctypes.create_string_buffer(size.value)
        self.assertEqual(dyld._NSGetExecutablePath(buffer, ctypes.byref(size)), 0)
        executable = Path(os.fsdecode(buffer.value)).resolve()
        self.assertEqual(executable, resources / 'bin' / ('FreeCAD' if App.GuiUp else 'FreeCADCmd'))
        self.assertEqual(sha(executable), expected[str(executable)])
        modules = {name: importlib.import_module(name) for name in ('Part', 'Fem', 'Materials')}
        modules['FreeCAD'] = App
        if App.GuiUp:
            modules.update({name: importlib.import_module(name) for name in ('FreeCADGui', 'FemGui')})
        dyld._dyld_image_count.restype = ctypes.c_uint32
        dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        dyld._dyld_get_image_name.restype = ctypes.c_char_p
        images = [Path(os.fsdecode(dyld._dyld_get_image_name(index))).resolve()
                  for index in range(dyld._dyld_image_count())]
        loaded = {}
        libraries = ['libFreeCADBase.dylib', 'libFreeCADApp.dylib']
        if App.GuiUp:
            libraries.append('libFreeCADGui.dylib')
        for name in libraries:
            wanted = resources / 'lib' / name
            self.assertEqual([path for path in images if path.name == name], [wanted])
            self.assertEqual(sha(wanted), expected[str(wanted)])
            loaded[name] = {'path': str(wanted), 'sha256': sha(wanted)}
        for name, module in modules.items():
            wanted = resources / 'lib' / (name + '.so')
            origin = getattr(module, '__file__', None)
            matching = [path for path in images if path.name == wanted.name]
            if origin:
                self.assertEqual(Path(origin).resolve(), wanted)
                self.assertEqual(matching, [wanted])
                self.assertEqual(sha(wanted), expected[str(wanted)])
                loaded[name] = {'path': str(wanted), 'sha256': sha(wanted)}
            else:
                self.assertIn(name, ('FreeCAD', 'FreeCADGui'))
                self.assertTrue(inspect.isbuiltin(App.Version if name == 'FreeCAD' else module.updateGui))
                self.assertIn(matching, ([], [wanted]))
                loaded[name] = {'embedded_native_binding': True, 'standalone_loaded': bool(matching)}
        from H88OriginalCheckpoint import module_origins
        bim = module_origins()
        from femtools import force_accounting
        import ObjectsFem
        doc = App.newDocument('H88LiteralBundleDefaultSolverIdentity')
        try:
            solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
            self.assertEqual(solver.NativeAccountingSolver, '')
            candidate = Path(force_accounting.solver_binary(solver))
            self.assertEqual(candidate, resources / 'data/NativeSolvers/ccx-force-accounting')
            self.assertEqual(sha(candidate), MANIFEST['native_sha256'])
            capabilities = {}
            for option, wanted in (('--freecad-force-accounting-version', 'CCX_FORCE_ACCOUNTING_V3'),
                                   ('--freecad-contact-state-version', 'CCX_CONTACT_STATE_V1')):
                child = subprocess.run([str(candidate), option], cwd=MANIFEST['working_directory'],
                                       stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                                       text=True, check=False)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(child.stdout.strip(), wanted)
                capabilities[option] = child.stdout.strip()
        finally:
            App.closeDocument(doc.Name)
        if App.GuiUp:
            import FreeCADGui as Gui
            Gui.updateGui()
            self.assertIsNotNone(Gui.getMainWindow())
        RESULTS['identity'] = {
            'runtime': runtime, 'home_path': App.getHomePath(), 'native_origins': loaded,
            'process_executable': {'path': str(executable), 'sha256': sha(executable)},
            'candidate': {'path': str(candidate), 'sha256': sha(candidate),
                          'override': False, 'capabilities': capabilities},
            'source_or_build_import_override': False, 'BIM_origins': bim,
            'initial_module_origins': source_origins(), 'GuiUp': bool(App.GuiUp),
        }


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


class VerifiedSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        ids = [test.id() for test in flatten(self)]
        public = sorted(name for name in ids if name.startswith(PUBLIC_PREFIX))
        assert len(ids) == MANIFEST['expected_tests'] and len(set(ids)) == len(ids), ids
        assert public == (PUBLIC_TEST_IDS if MANIFEST['mode'] in ('cmd', 'gui') else []), public
        super().run(result, debug=debug)
        if result.wasSuccessful() and not result.skipped and result.testsRun == len(ids):
            assert MANIFEST_PATH.read_bytes() == MANIFEST_BYTES
            assert set(RESULTS) == {'identity'}
            report = {
                'schema': 'FreeCAD-h88-installation-regression-v1', 'passed': True,
                'application': MANIFEST['application'], 'location': MANIFEST['location'],
                'mode': MANIFEST['mode'], 'gui': MANIFEST['gui'],
                'commit': MANIFEST['commit'], 'revision': MANIFEST['revision'],
                'native_sha256': MANIFEST['native_sha256'], 'test_count': len(ids),
                'selected_test_ids': ids, 'public_test_ids': public,
                'manifest_sha256': hashlib.sha256(MANIFEST_BYTES).hexdigest(),
                'module_sha256': sha(__file__), 'final_module_origins': source_origins(),
                'only_public_native_interfaces': True,
                'source_or_build_import_override': False, 'no_mesh_or_solve': True,
                'original_project_mutated': False, **RESULTS,
            }
            if MANIFEST['mode'] in ('save', 'cold'):
                saved = Path(MANIFEST['save_directory']) / 'private-checkpoint.FCStd'
                cold = Path(MANIFEST['working_directory']) / 'cold-observation.json'
                observation = json.loads(cold.read_text())
                assert observation['passed'] is True and observation['input_unchanged'] is True
                assert observation['no_mesh_or_solve'] is True
                assert observation['original_project_mutated'] is False
                assert observation['phase'] == ('save' if MANIFEST['mode'] == 'save' else 'cold-reopen')
                report.update(private_checkpoint={'path': str(saved), 'sha256': sha(saved)},
                              original_sha256=sha(MANIFEST['original_source']),
                              cold_report={'path': str(cold), 'sha256': sha(cold),
                                           'observation': observation})
                assert report['original_sha256'] == '570e7ffd62c4dfb95c7b0bcbb1eafab69f11c5d54152bf9fd840ad0464402a33'
                if MANIFEST['mode'] == 'save':
                    original = Path(MANIFEST['working_directory']) / 'observation.json'
                    data = json.loads(original.read_text())
                    assert data['passed'] is True and data['source_unchanged'] is True
                    report['original_report'] = {'path': str(original), 'sha256': sha(original)}
            with Path(MANIFEST['report_path']).open('x') as stream:
                json.dump(report, stream, indent=2, sort_keys=True)
                stream.write('\n')
        return result


def load_tests(loader, _tests, _pattern):
    suite = VerifiedSuite([AppH88Identity('test_exact_application_identity_and_loaded_native_origins')])
    mode = MANIFEST['mode']
    if mode in ('cmd', 'gui'):
        suite.addTests(loader.loadTestsFromName('H88Suite'))
    else:
        if mode == 'save':
            suite.addTests(loader.loadTestsFromName('H88OriginalCheckpoint'))
        suite.addTests(loader.loadTestsFromName('H88ColdCheckpoint'))
    return suite
