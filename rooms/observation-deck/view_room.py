"""Open the real ship runtime in an isolated, interactive desktop viewer.

Named view_room.py (formerly inspect.py) so it cannot shadow the standard-library
inspect module when this folder is first on sys.path.
"""
from pathlib import Path
import argparse, os, shutil, subprocess
parser=argparse.ArgumentParser()
parser.add_argument('--smoke-check',action='store_true',help='Run a hidden, bounded startup check')
options=parser.parse_args()
HERE=Path(__file__).resolve().parent
ROOT = HERE.parents[1]
stage=ROOT/'.local/starship-inspect'
stage.mkdir(parents=True,exist_ok=True)
source=HERE.parents[1] / 'app/starship'
shutil.copytree(source,stage/'starship',dirs_exist_ok=True)
# Drop stage copies of files the runtime package no longer has (renamed or removed groups).
for stale in [p for p in (stage/'starship').iterdir() if p.is_file() and not (source/p.name).exists()]:
    stale.unlink()
shutil.copyfile(HERE/'inspect.gd',stage/'inspect.gd')  # the viewer scene script keeps its name
(stage/'project.godot').write_text('config_version=5\n[application]\nconfig/name="Observation Deck inspection"\nconfig/use_custom_user_dir=true\nconfig/custom_user_dir_name="s"\n[rendering]\nrenderer/rendering_method="mobile"\n')
godot=ROOT/'.local/deps/godot-4.7.2/Godot_v4.7.2-stable_win64.exe'
command=[str(godot),'--path',str(stage),'--xr-mode','off','--audio-driver','Dummy','--resolution','1600x1000',
         '--script','res://inspect.gd']
startup=None
if options.smoke_check:
    log=HERE/'verification/inspector.log'
    command += ['--quit-after','12','--log-file',str(log),'--position','-10000,-10000']
    startup=subprocess.STARTUPINFO();startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
subprocess.run(command,env=dict(os.environ,APPDATA=str(stage/'user-data')),startupinfo=startup,
               creationflags=subprocess.CREATE_NO_WINDOW if options.smoke_check else 0,check=True)
if options.smoke_check:
    text=log.read_text(errors='replace')
    assert 'ERROR:' not in text,text
    print('INSPECTOR_STARTUP_OK')
