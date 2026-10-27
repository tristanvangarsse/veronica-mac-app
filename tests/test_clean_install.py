#!/usr/bin/env python3
"""Exercise an offline first launch and actual media work with developer paths denied."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from PIL import Image
from fixture_dates import exif_date
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--engine',type=Path,default=ROOT/'macos/Veronica/Resources/VeronicaEngine/veronica-engine');args=p.parse_args()
with tempfile.TemporaryDirectory(prefix='veronica-clean-install-') as td:
    base=Path(td).resolve();runtime=base/'App moved to a new folder with spaces'/'VeronicaEngine'
    shutil.copytree(args.engine.resolve().parent,runtime,symlinks=True)
    engine=runtime/'veronica-engine';internal=runtime/'_internal';state=base/'Preferences';media=base/'Media';media.mkdir()
    env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(base),'TMPDIR':str(base)+'/', 'LANG':'en_US.UTF-8'}
    profile='(version 1) (allow default) (deny network*) '+''.join(
        '(deny file-read* process-exec (subpath '+json.dumps(path)+'))'
        for path in ('/opt/homebrew','/usr/local',str(ROOT)))
    def command(executable,*arguments,ok=True,confined=True):
        prefix=['/usr/bin/sandbox-exec','-p',profile] if confined else []
        r=subprocess.run([*prefix,str(executable),*map(str,arguments)],env=env,cwd=base,capture_output=True,text=True,timeout=180)
        assert (r.returncode==0)==ok,r.stdout+r.stderr
        return r
    # macOS does not allow sandbox-exec to install a second sandbox in an
    # already sandboxed process. The coordinator starts each real media helper
    # in its own stricter production sandbox, which denies developer locations.
    def run(name,*arguments,ok=True):return command(engine,name,'--state-dir',state,*arguments,ok=ok,confined=False)
    clean_snapshot=json.loads(command(engine,'ui-snapshot','--state-dir',state).stdout)
    assert all(t['available'] for t in clean_snapshot['preflight']['tools'].values())
    setup=json.loads(run('prepare-runtime').stdout);assert setup['ready'] and setup['prepared_now']
    assert all(t['available'] for t in setup['components']['tools'].values())
    for name in ('ffmpeg','ffprobe','HandBrakeCLI'):
        assert Path(setup['components']['tools'][name]['path']).is_relative_to(internal/'MediaTools')
    receipt=(state/'runtime-setup.json').read_bytes()
    assert not json.loads(run('prepare-runtime').stdout)['prepared_now']
    assert (state/'runtime-setup.json').read_bytes()==receipt
    assert json.loads(command(engine,'prepare-runtime','--state-dir',state).stdout)['ready']
    ffmpeg=internal/'MediaTools/bin/ffmpeg';ffprobe=internal/'MediaTools/bin/ffprobe'
    Image.effect_noise((2000,1500),60).convert('RGB').save(media/'photo.png',exif=exif_date())
    Image.new('RGB',(200,150),'orange').save(media/'undated.jpg')
    command(ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=1600x900:rate=24','-t','1','-c:v','libx264','-preset','ultrafast','-crf','12','-metadata','creation_time=2023-01-01T12:00:00Z',media/'video.mov')
    command(ffmpeg,'-v','error','-f','lavfi','-i','sine=frequency=400:sample_rate=48000','-t','7','-ac','2','-c:a','pcm_s16le','-metadata','date=2023-01-01T12:00:00Z',media/'audio.wav')
    run('configure-folders','--add',media)
    folder=json.loads(run('folder-settings','--folder',media).stdout);recipe=folder['recipe']
    recipe['date_scope']={'mode':'all','start':None,'end':None,'legacy':False}
    recipe['optimization_settings'].update(image_max_megapixels=1,video_max_edge=854,audio_min_size_mb=1,minimum_saving_percent=1,minimum_saving_mb=0)
    run('configure-folder','--folder',media,'--recipe-json',json.dumps(recipe))
    session=state/'Sessions.noindex'/str(uuid.uuid4())
    run('analyze-all','--session-dir',session)
    run('annual-all','--session-dir',session,'--yes')
    records=[json.loads(line) for path in (state/'Change Logs/.records').glob('*.jsonl') for line in path.read_text().splitlines()]
    assert {'CONVERT_IMAGE','CONVERT_VIDEO','CONVERT_AUDIO'} <= {e['operation'] for e in records},records
    for record in records:
        if record['operation']=='CONVERT_IMAGE':
            with Image.open(record['destination']) as im:assert im.format=='JPEG' and im.width*im.height<=1_020_000
        elif record['operation']=='CONVERT_VIDEO':
            probe=json.loads(command(ffprobe,'-v','error','-show_streams','-of','json',record['destination']).stdout)
            video=next(s for s in probe['streams'] if s['codec_type']=='video');assert (video['width'],video['height'])==(854,480)
        elif record['operation']=='CONVERT_AUDIO':
            probe=json.loads(command(ffprobe,'-v','error','-show_streams','-of','json',record['destination']).stdout)
            audio=next(s for s in probe['streams'] if s['codec_type']=='audio');assert audio['codec_name']=='mp3' and int(audio['bit_rate'])==128000
    page=json.loads(run('scan-results','--session-dir',session).stdout)
    missing=next(i for i in page['items'] if i['relpath']=='undated.jpg')
    run('set-file-date','--state-dir',missing['state_dir'],'--plan',missing['plan_path'],'--relpath','undated.jpg','--date','2020-02-03','--yes')
    # No fallback to an installed executable, even if one happens to exist.
    manifest=json.loads((internal/'security-manifest.json').read_text())
    targets=[ffmpeg,internal/next(iter(manifest['tools']['ffmpeg']['libraries']))]
    for target in targets:
        held=target.with_name(target.name+'.held');target.rename(held)
        try:
            failed=run('prepare-runtime',ok=False)
            assert 'Reinstall' in failed.stderr and (state/'runtime-setup.json').read_bytes()==receipt
        finally:held.rename(target)
        assert json.loads(run('prepare-runtime').stdout)['ready']
print('Clean startup and helpers with external paths/network denied; offline setup, relocation, real image/video/audio conversion, date editing and missing-component refusal: PASS')
