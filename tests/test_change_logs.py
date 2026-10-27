#!/usr/bin/env python3
"""Change records are immediate, recoverable, private and survive session disposal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from PIL import Image
from fixture_dates import exif_date
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import media_maintenance as mm
import media_security as security
import media_change_log as change_log


def check_interrupted_lifecycle_and_migration(base):
    from unittest.mock import patch
    state=base/'Interrupted logs';state.mkdir()
    original_write=change_log._write_all
    writes=0
    def interrupted_write(fd,data):
        nonlocal writes
        writes+=1
        if writes==2:raise OSError('simulated interrupted readable write')
        original_write(fd,data)
    args=argparse.Namespace()
    with patch.object(change_log,'_write_all',side_effect=interrupted_write):
        try:change_log.begin_action(args,state,'cleanup',[base/'Photos'])
        except OSError:pass
        else:raise AssertionError('Expected an interrupted log write')
    # Recovery must also deliver lifecycle records when no scan DB exists yet.
    security.recover_transactions(state)
    change_log.finish_action(state,'interrupted')
    directory=change_log.destination(state)
    records=[json.loads(line) for p in (directory/'.records').glob('*.jsonl') for line in p.read_text().splitlines()]
    assert [r['operation'] for r in records]==['RUN_STARTED','RUN_FINISHED']
    assert records[-1]['outcome']=='interrupted' and records[-1]['changed_files']==0
    assert len({r['event_id'] for r in records})==2
    change_log.begin_action(argparse.Namespace(),state,'cleanup',[base/'Photos'])
    change_log.begin_action(argparse.Namespace(),state,'cleanup',[base/'Photos'])
    change_log.finish_action(state,'completed')
    assert len(list(directory.glob('*.log')))==3
    records=[json.loads(line) for p in (directory/'.records').glob('*.jsonl') for line in p.read_text().splitlines()]
    assert sum(r.get('outcome')=='interrupted' for r in records)==2

    old=base/'Earlier version';old.mkdir()
    old_directory=old/'Change Logs';old_directory.mkdir()
    record={'schema_version':1,'event_id':'d'*64,'timestamp':'2026-10-25T12:00:00+00:00',
            'operation':'RENAME','source':'old name.jpg','destination':'new name.jpg'}
    data=(json.dumps(record)+'\n').encode();human=change_log._line(record).encode()
    old_data=old_directory/'changes.jsonl';old_human=old_directory/'changes.log'
    old_data.write_bytes(data);old_human.write_bytes(human)
    con=mm.init_db(old/'media-maintenance.sqlite',base/'Photos')
    con.execute("CREATE TABLE change_log_outbox(event_key TEXT PRIMARY KEY,payload TEXT,status TEXT)")
    con.execute("INSERT INTO change_log_outbox VALUES(?,?,?)",('old-retry',json.dumps(record),'writing'))
    con.commit();con.close()
    # A crash between the two archive renames must retain their shared identity.
    original_rename=Path.rename
    def interrupted_rename(path,target):
        if path==old_human:raise OSError('simulated migration interruption')
        return original_rename(path,target)
    with patch.object(Path,'rename',interrupted_rename):
        try:change_log.initialize(old)
        except OSError:pass
        else:raise AssertionError('Expected interrupted migration')
    change_log.initialize(old);change_log.flush_state(old);change_log.initialize(old)
    assert not old_data.exists() and not old_human.exists()
    archives=list(old_directory.glob('Earlier changes*.log'))
    assert len(archives)==1 and archives[0].read_bytes()==human
    structured=list((old_directory/'.records').glob('*.jsonl'))
    assert len(structured)==1 and structured[0].read_bytes()==data


def main():
    p=argparse.ArgumentParser();p.add_argument('--engine',type=Path,default=ROOT/'veronica.py');engine=p.parse_args().engine.resolve()
    prefix=[sys.executable,str(engine)] if engine.suffix=='.py' else [str(engine)]
    with tempfile.TemporaryDirectory(prefix='veronica-permanent-log-') as td:
        base=Path(td).resolve();prefs=base/'Preferences';media=base/'Photos';media.mkdir()
        check_interrupted_lifecycle_and_migration(base)
        Image.effect_noise((1600,1200),70).convert('RGB').save(media/'large.png',exif=exif_date())
        Image.new('RGB',(100,80),'blue').save(media/'small.jpg',exif=exif_date())
        Image.new('RGB',(100,80),'orange').save(media/'missing.jpg')
        other=base/'Other photos';other.mkdir()
        Image.new('RGB',(100,80),'green').save(other/'other.jpg',exif=exif_date())
        session=prefs/'Sessions.noindex'/str(uuid.uuid4())
        def run(cmd,*args,session_arg=None,ok=True):
            command=[*prefix,cmd,'--state-dir',str(prefs),*map(str,args)]
            if session_arg:command+=['--session-dir',str(session_arg)]
            r=subprocess.run(command,capture_output=True,text=True,timeout=120)
            assert (r.returncode==0)==ok,r.stdout+r.stderr
            return r
        run('configure-folders','--add',media)
        recipe=json.loads(run('folder-settings','--folder',media).stdout)['recipe']
        recipe['date_scope']={'mode':'all','start':None,'end':None,'legacy':False}
        recipe['optimization_settings'].update(image_max_megapixels=1,recompress_images_below_target=False)
        run('configure-folder','--folder',media,'--recipe-json',json.dumps(recipe))
        run('configure-folders','--add',other)
        run('configure-folder','--folder',other,'--recipe-json',json.dumps(recipe))
        run('change-log-status')
        run('analyze-all',session_arg=session)
        snap=json.loads(run('ui-snapshot',session_arg=session).stdout);child=Path(next(f['state_dir'] for f in snap['folder_settings'] if f['folder']==str(media)))
        page=json.loads(run('scan-results',session_arg=session).stdout)
        missing=next(i for i in page['items'] if i['relpath']=='missing.jpg')
        run('set-file-date','--state-dir',child,'--plan',missing['plan_path'],'--relpath','missing.jpg','--date','2022-06-15','--yes')
        directory=prefs/'Change Logs'
        def events():return [json.loads(line) for path in sorted((directory/'.records').glob('*.jsonl')) for line in path.read_text().splitlines()]
        def changes():return [e for e in events() if e['operation'] not in {'RUN_STARTED','RUN_FINISHED'}]
        def saved():return {str(p.relative_to(directory)):p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        data,human=change_log._paths(directory,changes()[0]['group'])
        assert len(list(directory.glob('*.log')))==1 and 'Manual date edit' in human.name
        assert len(changes())==1 and changes()[0]['operation']=='SET_EMBEDDED_DATE'
        assert changes()[0]['date']=='2022-06-15' and changes()[0]['previous_date'] is None
        assert 'Saved embedded date' in human.read_text()
        # A full disk during post-commit logging must retain the pending journal,
        # not roll back an already verified replacement or report a false change.
        if engine.suffix=='.py':
            from unittest.mock import patch
            with sqlite3.connect(child/'media-maintenance.sqlite') as con:pid=con.execute('SELECT plan_id FROM plans ORDER BY created_at DESC LIMIT 1').fetchone()[0]
            frozen=next(child.glob('plan-*-'+pid[:12]+'.json'))
            run('stage','--state-dir',child,'--plan',frozen,'--max-images','1','--max-videos','0','--max-audio','0')
            with sqlite3.connect(child/'media-maintenance.sqlite') as con:sid=con.execute("SELECT staging_id FROM staging_items WHERE status='STAGED_VERIFIED'").fetchone()[0]
            with patch.object(change_log,'_write_all',side_effect=OSError('simulated full disk')):
                result=mm.commit_one(argparse.Namespace(state_dir=str(child),staging_id=sid,relpath='large.png',yes=True),quiet=True)
            assert result['status']=='COMMITTED'
            assert list((child/'transactions').glob('*.json'))
            assert len(changes())==1
            security.recover_transactions(child)
            assert not list((child/'transactions').glob('*.json'))
            assert len(changes())==2
        run('annual-all','--yes',session_arg=session)
        entries=events();operations=[e['operation'] for e in entries]
        assert operations.count('CONVERT_IMAGE')==1,operations
        assert operations.count('RENAME')==3,operations
        cleanup_files=list(directory.glob('*Smart cleanup*.log'))
        assert len(cleanup_files)==1
        cleanup_group=next(e['group'] for e in entries if e['operation']=='RUN_STARTED' and e['group']['kind']=='cleanup')
        assert set(cleanup_group['folders'])=={str(media),str(other)}
        assert {e.get('library') for e in entries if e['operation']=='RENAME'}=={str(media),str(other)}
        assert all(e['group']['id']==cleanup_group['id'] for e in entries if e['operation']=='RENAME')
        run('annual-all','--yes',session_arg=session)
        assert len(list(directory.glob('*Smart cleanup*.log')))==2
        empty=next(e for e in events() if e['operation']=='RUN_FINISHED' and e['group']['kind']=='cleanup' and e['changed_files']==0)
        assert 'No files were changed' in change_log._paths(directory,empty['group'])[1].read_text()
        conversion=next(e for e in entries if e['operation']=='CONVERT_IMAGE')
        assert conversion['before_bytes']>conversion['after_bytes']
        assert conversion['settings']['jpeg_quality']==70
        assert conversion['output_dimensions']
        assert hashlib.sha256(Path(conversion['destination']).read_bytes()).hexdigest()==conversion['after_sha256']
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:cid=con.execute("SELECT commit_id FROM commit_items WHERE operation='CONVERT_IMAGE'").fetchone()[0]
        run('rollback','--state-dir',child,'--commit-id',cid,'--yes')
        restored=next(e for e in changes() if e['operation']=='RESTORE_ORIGINAL')
        data,human=change_log._paths(directory,restored['group'])
        assert 'Restore original' in human.name
        assert hashlib.sha256((media/'large.png').read_bytes()).hexdigest()==conversion['before_sha256']
        before=data.read_bytes();change_log.flush_state(child);change_log.flush_state(child)
        assert data.read_bytes()==before,'Recovery must not duplicate a delivered event'
        # A crash after a complete append but before acknowledgement must also
        # avoid duplicates and reconstruct a missing readable log.
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            con.execute("UPDATE change_log_outbox SET status='writing' WHERE rowid=(SELECT MAX(rowid) FROM change_log_outbox)")
        human.write_text('interrupted readable log')
        change_log.flush_state(child)
        assert data.read_bytes()==before and 'Restored original' in human.read_text()
        # Retry a partially written final JSON record, preserving every complete
        # earlier record and producing exactly one complete entry for the retry.
        payload={'schema_version':1,'event_id':'e'*64,'timestamp':'2026-10-26T12:00:00+00:00','operation':'RENAME','source':'test "quoted"\nname','destination':'test renamed','group':restored['group']}
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            con.execute("INSERT INTO change_log_outbox VALUES(?,?,?)",('interrupted-test',json.dumps(payload),'writing'))
        with data.open('ab') as f:f.write(json.dumps(payload)[:50].encode());f.flush();os.fsync(f.fileno())
        change_log.flush_state(child)
        assert data.read_bytes().startswith(before)
        assert sum(e['event_id']=='e'*64 for e in events())==1
        assert '\\nname' in human.read_text()
        # Never follow a log directory symlink or discard scratch records while
        # log delivery cannot be verified.
        held=prefs/'Saved logs';directory.rename(held);outside=base/'Outside';outside.mkdir();directory.symlink_to(outside)
        run('desktop-session','--discard',session_arg=session,ok=False)
        assert session.exists() and not list(outside.iterdir())
        directory.unlink();held.rename(directory)
        release=json.loads(run('desktop-session',session_arg=session).stdout)
        trash=base/'Test Trash';trash.mkdir()
        for index,path in enumerate(release['original_folders']):
            source=Path(path);target=trash/(str(index)+'-'+source.name);source.rename(target)
            run('record-trash','--session-dir',session,'--source',source,'--destination',target)
            run('record-trash','--session-dir',session,'--source',source,'--destination',target)
        assert [e['operation'] for e in events()].count('MOVE_ORIGINALS_TO_TRASH')==len(release['original_folders'])
        assert len({e['event_id'] for e in events()})==len(events())
        permanent=saved();run('desktop-session','--discard',session_arg=session)
        assert not session.exists() and saved()==permanent
        next_session=prefs/'Sessions.noindex'/str(uuid.uuid4())
        fresh=json.loads(run('ui-snapshot',session_arg=next_session).stdout)
        assert fresh['active_assets']==0 and fresh['latest_plan'] is None
        assert saved()==permanent
        assert directory.stat().st_mode&0o777==0o700
        assert data.stat().st_mode&0o777==0o600 and human.stat().st_mode&0o777==0o600
        group=change_log.begin_action(argparse.Namespace(),next_session,'cleanup',[media,other])
        run('desktop-session','--discard',session_arg=next_session)
        recovered=[e for e in events() if e['group']['id']==group['id']]
        assert len(recovered)==2 and recovered[-1]['outcome']=='interrupted'
    print('Per-run logs across folders, empty runs, manual dates, restore, Trash, crash retries, failed-write retention and fresh-launch persistence: PASS')
if __name__=='__main__':main()
