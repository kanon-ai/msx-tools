"""Verify the generated SCREEN 2 preview ROM in an isolated native openMSX."""
from pathlib import Path
import os,subprocess,tempfile,shutil,json,hashlib
R=Path(__file__).resolve().parent
exe=Path(os.environ.get('OPENMSX_EXE','C:/Program Files/openMSX/openmsx.exe'))
(R/'work').mkdir(exist_ok=True);w=Path(tempfile.mkdtemp(prefix='verify-',dir=R/'work'));(w/'home').mkdir()
art=R/'outputs/ai-tms-screen2'
script='''set save_settings_on_exit false
set power on
set pause off
set throttle true
set minframeskip 0
set maxframeskip 0
set scale_factor 3
set blur 0
set scanline 0
set VDP.vram_access_mode real
set ::violations 0
proc violation {} {incr ::violations}
set VDP.too_fast_vram_access_callback violation
after time 12 {
 openmsx::internal_screenshot -raw ./screen.png
 set f [open vram.bin wb];puts -nonewline $f [debug read_block VRAM 0 16384];close $f
 set f [open result.txt w];puts $f "$::violations [debug size {Main RAM}]";close $f
 exit
}
'''
(w/'run.tcl').write_text(script)
(w/'settings.xml').write_text('<!DOCTYPE settings SYSTEM "settings.dtd"><settings><settings/><bindings/><shortcuts/></settings>')
env=dict(os.environ);env.update(OPENMSX_SYSTEM_DATA=str(exe.parent/'share'),OPENMSX_HOME=str(w/'home'),OPENMSX_USER_DATA=str(Path.home()/'Documents/openMSX/share'))
print(w,flush=True)
subprocess.run([str(exe),'-machine','Sony_HB-101','-cart',str(art/'preview-msx1.rom'),'-setting',str(w/'settings.xml'),'-script',str(w/'run.tcl')],cwd=w,env=env,check=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
v=(w/'vram.bin').read_bytes()
assert v[:6144]==(art/'patterns.bin').read_bytes()
assert v[0x2000:0x3800]==(art/'colors.bin').read_bytes()
assert v[0x1800:0x1b00]==(art/'names.bin').read_bytes()
assert v[0x1b00]==208
violations,ram=map(int,(w/'result.txt').read_text().split());assert violations==0
shutil.copy2(w/'screen.png',R/'outputs/native-screen2.png')
report={'machine':'Sony_HB-101 / MSX1 / TMS9118','ram_bytes':ram,'pattern_color_names_match':True,'strict_vram_timing_violations':violations,'rom_sha256':hashlib.sha256((art/'preview-msx1.rom').read_bytes()).hexdigest(),'physical_hardware_tested':False}
(R/'outputs/native-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
