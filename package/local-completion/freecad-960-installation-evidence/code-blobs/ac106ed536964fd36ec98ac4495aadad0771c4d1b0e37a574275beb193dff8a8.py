"""Fresh commands over the frozen bounded DESTDIR/stage/swap supervisor."""
import hashlib
import importlib.util
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
original=Path('/Users/zukomgwili/src/FreeCAD/package/local-completion/freecad-8rk-installation-evidence/run_step.py')
assert hashlib.sha256(original.read_bytes()).hexdigest()=='612141eb6c5f8693dd33d9dd8d5012a99d8571b16d17654043d187c7fca8bbb3'
spec=importlib.util.spec_from_file_location('_960_step_guard',original)
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
core.ROOT=ROOT
prefix=['/opt/homebrew/bin/pixi','run','--frozen']
core.COMMANDS={
 'capture':prefix+['python','-B','-c','import sys;sys.path.insert(0,'+repr(str(ROOT))+');import critical_pins;critical_pins.capture()'],
 'payload':prefix+['cmake','--install','build/release'],
 'audit-payload':prefix+['python','-B',str(ROOT/'audit_payload_stage.py'),'payload'],
 'stage':prefix+['python','-B',str(ROOT/'stage_install.py'),'stage'],
 'audit-stage':prefix+['python','-B',str(ROOT/'audit_payload_stage.py'),'stage'],
 'audit-custody':prefix+['python','-B',str(ROOT/'audit_payload_stage.py'),'custody'],
 'swap':prefix+['python','-B',str(ROOT/'stage_install.py'),'swap'],
}
if __name__=='__main__':raise SystemExit(core.main())
