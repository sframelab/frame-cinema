"""Pack the ship's baked textures and render an isolated desktop preview.

The default run is stage-only: the bake is packed into .local/starship-preview/
starship and rendered from there; nothing in the app project changes and the
renders go to preview/stage/. Only --install copies the bake outputs into the
app project, regenerates package.json and replaces the menu thumbnail.
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys

HERE=Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJECT=HERE.parents[1] / 'app'
SHIP=PROJECT/'starship'
GODOT = Path(os.environ.get('GODOT', str(ROOT / '.local/deps/godot-4.7.2/Godot_v4.7.2-stable_win64.exe')))
STAGE=ROOT/'.local/starship-preview'
PART_PATTERNS=('*.bin','*-lighting.res','*-albedo.res','deck-mirror.res','deck-wear.res','starship.json')
FAIL_MARKERS=('SCRIPT ERROR','SHADER ERROR','ERROR:')

def run_godot(stage, script, environment, name, headless=False, timeout=1800):
    args=[str(GODOT),'--path',str(stage),'--xr-mode','off','--audio-driver','Dummy',
          '--rendering-method','mobile','--log-file',str(stage/(name+'.log')),'--script',script]
    if headless:args.append('--headless')
    else:args += ['--resolution','64x64','--position','-10000,-10000']
    env=os.environ.copy();env.update(environment)
    env['APPDATA']=str(stage/'user-data')
    startup=subprocess.STARTUPINFO();startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    result=subprocess.run(args,env=env,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW,timeout=timeout)
    log=(stage/(name+'.log')).read_text(errors='replace')
    print(log[-5000:])
    bad=[line for line in log.splitlines() if any(marker in line for marker in FAIL_MARKERS)]
    if result.returncode or bad:
        raise RuntimeError(name+' failed: return code '+str(result.returncode)+'; '+' | '.join(bad[:6]))
    return log

def is_part_file(path):
    return any(path.match(pattern) for pattern in PART_PATTERNS)

def stage_runtime(stage_ship, clean):
    """Copy runtime scripts, shaders and sky maps; optionally drop stale part files."""
    stage_ship.mkdir(parents=True,exist_ok=True)
    for item in SHIP.iterdir():
        if item.is_dir():
            shutil.copytree(item,stage_ship/item.name,dirs_exist_ok=True)
        elif not is_part_file(item):
            shutil.copy2(item,stage_ship/item.name)
    if clean:
        removed=[]
        for pattern in PART_PATTERNS:
            for stale in stage_ship.glob(pattern):
                stale.unlink();removed.append(stale.name)
        print('STAGE_CLEAN removed',len(removed),'part files',flush=True)
    for ambient in [PROJECT/'cinema_ambient.gd']+sorted(PROJECT.glob('cinema_ambient*.gdshader')):
        shutil.copy2(ambient,stage_ship.parent/ambient.name)

def install(stage_ship, bake, metadata):
    names=[p.name for p in stage_ship.iterdir() if p.is_file() and is_part_file(p)]
    for name in names:shutil.copyfile(stage_ship/name,SHIP/name)
    write_package(metadata)
    print('STAGE_INSTALLED',len(names),'files into',SHIP,flush=True)

def write_package(metadata):
    """package.json lists every runtime file with its hash; the build refuses a mismatch. stars.dat and galaxy.res come from prepare_stars.py and pack_earth.gd, so a sky-only change refreshes it with --refresh-package."""
    files={f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(SHIP.iterdir()) if f.is_file() and f.name!='package.json' and not f.name.endswith('.uid')}
    (SHIP/'package.json').write_text(json.dumps({'schema':1,'revision':metadata['revision'],'name':'Observation Deck',
      'status':'development; the room ran on the Frame in 0.5.9 (72 Hz, about 109.5 deg per eye, stand-in timing with nobody wearing it); timing and comfort on the head not measured yet for this package',
      'geometry':'authored metre-scale 3D; no interior panorama','triangles':metadata['triangles'],
      'static_meshes':len(metadata['parts']),'source':'build_interior.py','files':files},indent=2))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--bake',type=Path)
    p.add_argument('--refresh-package',action='store_true',help='Only rewrite package.json from the runtime files in the app project (after prepare_stars.py or a sky pack)')
    p.add_argument('--skip-pack',action='store_true',help='Reuse the textures already packed in the stage (script/shader-only re-render)')
    p.add_argument('--install',action='store_true',help='Copy the packed bake into the app project, refresh package.json and the thumbnail')
    p.add_argument('--output',type=Path,help='Render folder (default preview/stage, or preview with --install)')
    p.add_argument('--no-compare',action='store_true')
    p.add_argument('--stage',type=Path,help='Private stage folder (default .local/starship-preview); keeps parallel look-dev runs apart')
    p.add_argument('--overlay',type=Path,action='append',default=[],help='Folder of work-in-progress runtime files (shaders, scripts, sky maps) copied over the app project copies in the stage; repeatable')
    args=p.parse_args()
    if args.refresh_package:
        write_package(json.loads((SHIP/'starship.json').read_text()))
        print('STAGE_PACKAGE_REFRESHED',SHIP/'package.json',flush=True)
        return
    if args.bake is None:p.error('--bake is required')
    bake=args.bake.resolve();bake.relative_to(ROOT.resolve())
    if args.install and args.skip_pack:
        raise SystemExit('--install needs a fresh pack; drop --skip-pack')
    stage=args.stage.resolve() if args.stage else STAGE
    if args.install and (args.stage or args.overlay):
        raise SystemExit('--install uses the default stage and the app project runtime files only')
    stage.mkdir(parents=True,exist_ok=True)
    stage_ship=stage/'starship'
    output=(args.output.resolve() if args.output else (HERE/'preview' if args.install else HERE/'preview/stage'))
    output.mkdir(parents=True,exist_ok=True)
    (stage/'project.godot').write_text('config_version=5\n[application]\nconfig/name="Observation Deck preview"\nconfig/use_custom_user_dir=true\nconfig/custom_user_dir_name="s"\n[rendering]\nrenderer/rendering_method="mobile"\ntextures/default_filters/use_nearest_mipmap_filter=false\n[display]\nwindow/size/viewport_width=64\nwindow/size/viewport_height=64\n')
    stage_runtime(stage_ship,clean=not args.skip_pack)
    for overlay in args.overlay:
        for item in sorted(overlay.resolve().iterdir()):
            if item.is_file():shutil.copy2(item,stage_ship/item.name)
        print('STAGE_OVERLAY',str(overlay),flush=True)
    metadata=json.loads((bake/'starship.json').read_text())
    if not args.skip_pack:
        shutil.copyfile(HERE/'pack_textures.gd',stage/'pack_textures.gd')
        run_godot(stage,'res://pack_textures.gd',{'STARSHIP_BAKE':str(bake),'STARSHIP_DEST':str(stage_ship)},'pack',True)
        for name in ['starship.json']+[q.name for q in bake.glob('*.bin')]:shutil.copyfile(bake/name,stage_ship/name)
    elif not (stage_ship/'starship.json').exists():
        raise SystemExit('--skip-pack needs a previously packed stage')
    shutil.copyfile(HERE/'preview.gd',stage/'preview.gd')
    if (HERE/'screen-picture.png').exists():shutil.copyfile(HERE/'screen-picture.png',stage/'screen-picture.png')
    # Headset sequences are large (96 frames at 2160 px); they stay out of the repo.
    headset=stage/'headset' if args.output is None else output/'headset'
    headset.mkdir(parents=True,exist_ok=True)
    shots=[s.strip() for s in os.environ.get('STARSHIP_PREVIEW_SHOTS','').split(',') if s.strip()]
    if os.environ.get('STARSHIP_PREVIEW_NO_HEADSET')!='1' and (not shots or 'headset' in shots):
        for old in headset.glob('*.png'):old.unlink()
    run_godot(stage,'res://preview.gd',{'STARSHIP_PREVIEW_OUT':str(output),'STARSHIP_PREVIEW_HEADSET_OUT':str(headset)},'render')
    if args.install:
        install(stage_ship,bake,metadata)
        (PROJECT/'environments').mkdir(exist_ok=True)
        shutil.copyfile(output/'starship-thumb.png',PROJECT/'environments/starship-thumb.png')
    print('STAGE_PREVIEW_OK',str(output),'(installed)' if args.install else '(stage-only; app project untouched)',flush=True)

if __name__=='__main__':main()
