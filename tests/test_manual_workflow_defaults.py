"""Manual recipe survives reset, folder inheritance, planning and actual image encoding."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import media_audit as audit
import media_maintenance as mm

with tempfile.TemporaryDirectory(prefix='veronica-manual-defaults-') as td:
    base = Path(td).resolve()
    state = base/'State'
    media = base/'Media'
    media.mkdir()
    mm.save_product_settings(state, {'scan_folders':[str(media)], 'jpeg_quality':76,
        'process_images':False, 'process_audio':False, 'date_scope_mode':'all',
        'filename_date_format':'YYYY-MM-DD_', 'filename_max_bytes':180, 'custom_marker':'keep'})
    mm.cmd_restore_manual_defaults(argparse.Namespace(state_dir=str(state)))
    saved = mm.load_product_settings(state)
    assert saved['custom_marker']=='keep' and saved['scan_folders']==[str(media)]
    assert saved['jpeg_quality']==70 and saved['process_images'] and saved['process_audio']
    assert '.gif' not in saved['process_image_extensions']
    child = mm.prepare_scan_folder_state(state,media)
    cfg = mm.apply_product_settings(mm.load_config(None),child,dt.date(2026,10,16))
    assert cfg['image_max_megapixels']==20 and cfg['streams_image_max_megapixels']==20 and cfg['photo_library_max_megapixels']==20
    assert cfg['streams_jpeg_quality']==cfg['photo_library_jpeg_quality']==70
    assert cfg['date_scope']['mode']=='older_than_two_years'
    assert cfg['date_scope']['end']=='2024-10-15'
    a = audit.Auditor(media,cfg,dt.date(2026,10,16),child,False,False)
    def row(rel,mp=19,ext='.jpg',alpha=False):
        return {'relpath':rel,'name':Path(rel).name,'detected_kind':'image','extension_kind':'image',
            'extension':ext,'tags':[],'is_symlink':False,'best_date':'2023-01-01',
            'date_confidence':'HIGH','size':100000,'animated':False,'action':'CANDIDATE',
            'megapixels':mp,'has_alpha':alpha}
    for rel,mp,target in [('Streams/Image/a.jpg',19,20),('Photo_Library/a.jpg',19,20),('Photo_Library/b.jpg',21,20)]:
        item=mm.make_item(row(rel,mp),1,cfg)
        assert item['operation']=='CONVERT_IMAGE',item
        assert item['target']['max_megapixels']==target,item
    assert mm.make_item(row('Photo_Library/small.png',2,'.png',True),2,cfg)['target']['format']=='png'
    assert mm.make_item(row('Streams/small.png',2,'.png'),3,cfg)['target']['format']=='jpeg'
    assert a.decide(row('Streams/a.gif',1,'.gif')).action=='PRESERVE'
    for date,action in [('2024-10-15','CANDIDATE'),('2024-10-16','SKIP')]:
        r={**row('Streams/a.jpg'),'best_date':date}
        decision=a.decide(r)
        assert decision.action==action
        if action=='SKIP':
            r.update(action=decision.action, reason=decision.reason)
            item=mm.apply_filename_policy(mm.make_item(r,9,cfg),r,cfg)
            assert not item['executable'],item
    assert a.decide({**row('Streams/a.jpg'),'tags':['compressed-v2']}).action=='SKIP'
    nested=base/'Photo_Library'/'2023';nested.mkdir(parents=True)
    nested_cfg={**cfg,'scan_root':str(nested)}
    assert mm.make_item(row('a.jpg'),4,nested_cfg)['target']['max_megapixels']==20
    nested_a=audit.Auditor(nested,cfg,dt.date(2026,10,16),child,False,False)
    assert not nested_a.protected_photo_path(Path('Original/a.jpg'))  # No subfolder names are skipped by default.
    protected=audit.Auditor(nested,{**cfg,'excluded_directory_names':['Original']},dt.date(2026,10,16),child,False,False)
    assert protected.protected_photo_path(Path('Original/a.jpg'))
    name=mm.canonical_media_filename('2023-01-01_Café _ summer.. photo!.jpg','2023-01-01',None,cfg)
    assert name=='230101-Cafe-summer-photo.jpg',name
    assert mm.canonical_media_filename(name,'2023-01-01',None,cfg)==name
    assert len(mm.canonical_media_filename('x'*200+'.jpg','2023-01-01',None,cfg))<=60
    # Real isolated encoder: images below 10 MP keep their dimensions, JPEG uses
    # the chosen quality and progressive coding, and PNG transparency survives.
    source=base/'source.png';Image.new('RGB',(80,60),'orange').save(source)
    item=mm.make_item(row('Streams/source.png',.0048,'.png'),5,cfg)
    result=mm.convert_image_stage(source,base/'out.jpg',item,cfg)
    with Image.open(result['output_path']) as im:
        assert im.size==(80,60) and im.format=='JPEG' and im.info.get('progressive')
        expected=base/'expected.jpg';Image.new('RGB',(80,60),'orange').save(expected,quality=70)
        with Image.open(expected) as reference: assert im.quantization==reference.quantization
    alpha=base/'alpha.png';Image.new('RGBA',(80,60),(100,50,20,120)).save(alpha)
    item=mm.make_item(row('Streams/alpha.png',.0048,'.png',True),6,cfg)
    result=mm.convert_image_stage(alpha,base/'alpha-output.png',item,cfg)
    with Image.open(result['output_path']) as im:
        assert im.format=='PNG' and im.getpixel((0,0))[3]==120
print('Manual workflow defaults, reset, folder policies and isolated encoding: PASS')
