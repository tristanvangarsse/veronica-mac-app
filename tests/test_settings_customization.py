#!/usr/bin/env python3
"""Exercise custom settings through real scan, staging and preset round trips."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from PIL import Image
from fixture_dates import exif_date
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import media_maintenance as mm


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--engine',type=Path,default=ROOT/'veronica.py')
    engine=parser.parse_args().engine.resolve();prefix=[sys.executable,str(engine)] if engine.suffix=='.py' else [str(engine)]
    with tempfile.TemporaryDirectory(prefix='veronica-settings-custom-') as td:
        base=Path(td).resolve();media=base/'Photos';other=base/'Other folder';state=base/'State'
        media.mkdir();other.mkdir();(media/'Original').mkdir()
        photo=media/'2023.07.14_photo.jpg'
        Image.effect_noise((900,700),70).convert('RGB').save(photo,quality=95,exif=exif_date('2023:07:14 10:00:00'))
        Image.new('RGB',(100,100),'blue').save(media/'Original/another.jpg',exif=exif_date())
        video=media/'video.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=1600x900:rate=24','-t','0.8','-c:v','libx264','-preset','ultrafast','-crf','12','-metadata','creation_time=2023-07-14T10:00:00Z',str(video)],check=True,timeout=60)
        before={str(p.relative_to(media)):hashlib.sha256(p.read_bytes()).hexdigest() for p in media.rglob('*') if p.is_file()}
        def run(cmd,*args,ok=True):
            result=subprocess.run([*prefix,cmd,'--state-dir',str(state),*map(str,args)],capture_output=True,text=True,timeout=120)
            assert (result.returncode==0)==ok,result.stdout+result.stderr
            return result
        def payload(folder):return json.loads(run('folder-settings','--folder',folder).stdout)
        def configure(recipe):return json.loads(run('configure-folder','--folder',media,'--recipe-json',json.dumps(recipe)).stdout)
        def analyze():
            run('analyze-all','--run-date','2026-10-26')
            with sqlite3.connect(child/'media-maintenance.sqlite') as con:pid=con.execute('SELECT plan_id FROM plans ORDER BY created_at DESC LIMIT 1').fetchone()[0]
            path=next(child.glob('plan-*-'+pid[:12]+'.json'));return path,json.loads(path.read_text())
        run('configure-folders','--add',media,'--add',other)
        original_other=payload(other)['recipe'];recipe=payload(media)['recipe'];child=Path(payload(media)['state_dir'])
        assert recipe['media_processing']['excluded_directory_names']==[]
        recipe['date_scope']={'mode':'all','start':None,'end':None,'legacy':False}
        recipe['optimization_settings']['recompress_images_below_target']=False
        for style,wanted in [('YYYYMMDD-','20230714-photo.jpg'),('DD-MM-YYYY_','14-07-2023_photo.jpg'),('YYYY.MM.DD_','2023.07.14_photo.jpg'),('DD_MM_YY-','14_07_23-photo.jpg')]:
            recipe['filename_policy']['date_format']=style;configure(recipe);path,plan=analyze()
            item=next(i for i in plan['items'] if i['relpath']==photo.name)
            assert item['operation'] in {'RENAME','SKIP_NO_BENEFIT'},item
            if item['operation']=='RENAME':assert item['target']['final_relpath']==wanted,item
            assert not any(i['operation']=='PRESERVE' for i in plan['items'] if i['relpath'].startswith('Original/'))
            assert mm.canonical_media_filename(wanted,'2023-07-14',None,plan['config_snapshot'])==wanted
        valid=payload(media)['recipe']
        for bad in ['YYYY/MM/DD_','YYYY-MM-DD','YYYY-MM-MM_','%Y-%m-%d_','YYYY-MM-DD_../','custom']:
            changed=json.loads(json.dumps(valid));changed['filename_policy']['date_format']=bad
            run('configure-folder','--folder',media,'--recipe-json',json.dumps(changed),ok=False)
            assert payload(media)['recipe']==valid
        # Both extra controls must affect the actual encoder decision.
        recipe=valid;recipe['filename_policy']['enabled']=False
        recipe['optimization_settings'].update(recompress_images_below_target=True,minimum_saving_percent=90,minimum_saving_mb=1024)
        configure(recipe);path,plan=analyze()
        run('stage','--state-dir',child,'--plan',path,'--max-images','10','--max-videos','0','--max-audio','0')
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            status=con.execute('SELECT status FROM staging_items WHERE relpath=? ORDER BY rowid DESC LIMIT 1',(photo.name,)).fetchone()[0]
        assert status=='KEEP_ORIGINAL',status
        recipe['optimization_settings'].update(minimum_saving_percent=1,minimum_saving_mb=0)
        configure(recipe);path,plan=analyze()
        assert next(i for i in plan['items'] if i['relpath']==photo.name)['operation']=='CONVERT_IMAGE', 'A changed saving target must retry the original.'
        run('stage','--state-dir',child,'--plan',path,'--max-images','10','--max-videos','0','--max-audio','0')
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            status=con.execute('SELECT status FROM staging_items WHERE relpath=? ORDER BY rowid DESC LIMIT 1',(photo.name,)).fetchone()[0]
        assert status=='STAGED_VERIFIED',status
        for edge,expected in [(854,(854,480)),(1000,(1000,562))]:
            recipe['optimization_settings']['video_max_edge']=edge;configure(recipe);path,plan=analyze()
            assert plan['config_snapshot']['video_max_storage_edge']==edge
            run('stage','--state-dir',child,'--plan',path,'--max-images','0','--max-videos','1','--max-audio','0')
            with sqlite3.connect(child/'media-maintenance.sqlite') as con:
                output,ver=con.execute('SELECT output_path,verification_json FROM staging_items WHERE relpath=? ORDER BY rowid DESC LIMIT 1',(video.name,)).fetchone()
            verification=json.loads(ver)
            assert tuple(verification['output_dimensions'])==expected,(edge,verification)
        preset=json.loads(run('save-preset','--name','My custom settings','--recipe-json',json.dumps(recipe)).stdout)
        assert preset['recipe']==payload(media)['recipe']
        assert payload(other)['recipe']==original_other
        for name,sha in before.items():assert hashlib.sha256((media/name).read_bytes()).hexdigest()==sha
        # The former automatic list is cleared once. A newly chosen list is retained.
        settings=mm.load_product_settings(child);old=['RAW','Capture','CaptureOne','Photoshop','Original','Retouch','Assets','Unused','Masters','Master','Source','Working','Negatives']
        settings['folder_recipe']['media_processing']['excluded_directory_names']=old
        for key in ['recompress_images_below_target','minimum_saving_percent','minimum_saving_mb']:
            settings.pop(key,None);settings['folder_recipe']['optimization_settings'].pop(key,None)
        (child/'settings.json').write_text(json.dumps(settings))
        migrated=payload(media)['recipe'];assert migrated['media_processing']['excluded_directory_names']==[]
        migrated['media_processing']['excluded_directory_names']=old
        configure(migrated);assert payload(media)['recipe']['media_processing']['excluded_directory_names']==old
    print('Custom date styles, prefix deduplication, empty exclusions, 480p/custom video staging, real saving targets, retry after changed settings and preset isolation: PASS')
if __name__=='__main__':main()
