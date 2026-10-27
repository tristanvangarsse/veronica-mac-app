"""Permanent file change logs; the delivery queue lives only in session scratch data."""
from pathlib import Path
from functools import lru_cache
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid
import functools
import contextlib
import media_security as security

ERROR = 'Veronica could not update its change log. Temporary records have been kept; free space or check permissions, then try again.'


def destination(state: Path) -> Path:
    state = Path(os.path.abspath(state))
    base = state.parent.parent if state.parent.name == 'folders' and re.fullmatch(r'[0-9a-f]{16}', state.name) else state
    if base.parent.name == 'Sessions.noindex' and re.fullmatch(r'[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}', base.name):
        base = base.parent.parent
    return security.inside(base, 'Change Logs')


def _open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        os.close(fd)
        raise ValueError('The change log must be a regular file.')
    os.fchmod(fd, 0o600)
    return fd


def _write_all(fd, data):
    while data:
        written = os.write(fd, data)
        if not written: raise OSError('The change log could not be written.')
        data = data[written:]


def _line(record):
    if record['operation'] in {'RUN_STARTED','RUN_FINISHED'}:
        group=record['group']; label=KINDS[group['kind']]
        result=record['timestamp']+' — '+label+' '+('started' if record['operation']=='RUN_STARTED' else record.get('outcome','finished'))+'\n'
        if record.get('folders'): result+='  Folders: '+json.dumps(record['folders'],ensure_ascii=False)+'\n'
        if 'changed_files' in record:
            result+='  Completed file changes: '+str(record['changed_files'])+'\n'
            if not record['changed_files']:result+='  No files were changed.\n'
        if record.get('message'): result+='  Details: '+json.dumps(record['message'],ensure_ascii=False)+'\n'
        return result+'\n'
    labels = {'CONVERT_IMAGE':'Optimized photo', 'CONVERT_VIDEO':'Optimized video', 'CONVERT_AUDIO':'Optimized audio',
              'RENAME':'Renamed file', 'SET_EMBEDDED_DATE':'Saved embedded date', 'RESTORE_ORIGINAL':'Restored original',
              'MOVE_ORIGINALS_TO_TRASH':'Moved retained originals to Trash'}
    quoted = lambda value: json.dumps(value, ensure_ascii=False)
    parts = [record['timestamp']+' — '+labels.get(record['operation'], record['operation']),
             'From: '+quoted(record['source']), 'To: '+quoted(record['destination'])]
    for key,label in [('before_bytes','Before'),('after_bytes','After'),('saved_bytes','Saved')]:
        if record.get(key) is not None: parts.append(f'{label}: {record[key]:,} bytes')
    if record.get('output_format'): parts.append('Format: '+record['output_format'])
    if record.get('output_dimensions'): parts.append('Dimensions: '+' × '.join(map(str,record['output_dimensions']))+' px')
    if record.get('output_codec'): parts.append('Codec: '+record['output_codec'])
    if 'date' in record: parts.append('Embedded date: '+quoted(record.get('previous_date'))+' → '+quoted(record['date']))
    if record.get('settings'): parts.append('Settings: '+quoted(record['settings']))
    parts.append('ID: '+record['event_id'])
    return '\n  '.join(parts)+'\n\n'


@lru_cache(maxsize=32)
def _plan_settings(state: str, plan_id: str):
    security.identifier(plan_id,64)
    paths = sorted(Path(state).glob('plan-*-'+plan_id[:12]+'.json'))
    if not paths: return {}
    plan = json.loads(paths[-1].read_text()); cfg = plan.get('config_snapshot',{})
    return {key:cfg[key] for key in ('image_output_format','jpeg_quality','image_max_megapixels','video_max_storage_edge',
            'audio_min_size_mb','filename_date_format','minimum_saving_percent','minimum_saving_bytes') if key in cfg}


def _queue(con, state, key, record):
    record = {'schema_version':1, 'event_id':hashlib.sha256((str(state)+'|'+key).encode()).hexdigest(), **record}
    record.setdefault('group', record_group(state,key,record))
    con.execute('INSERT OR IGNORE INTO change_log_outbox(event_key,payload,status) VALUES(?,?,?)',
                (key,json.dumps(record,ensure_ascii=False,sort_keys=True),'ready'))


def _seed(con, state):
    con.row_factory = sqlite3.Row
    root = Path(con.execute("SELECT value FROM meta WHERE key='root'").fetchone()[0])
    rows = con.execute("SELECT ci.*,c.plan_id,c.completed_at,si.verification_json FROM commit_items ci JOIN commits c USING(commit_id) "
        "LEFT JOIN staging_items si ON si.staging_id=c.staging_id AND si.relpath=ci.relpath "
        "WHERE ci.status IN ('COMMITTED','ROLLED_BACK') AND c.completed_at IS NOT NULL "
        "AND NOT EXISTS(SELECT 1 FROM change_log_outbox o WHERE o.event_key='change:'||ci.commit_id||':'||ci.relpath) "
        "ORDER BY c.completed_at,ci.commit_id").fetchall()
    for row in rows:
        details=json.loads(row['details_json'] or '{}'); verification=json.loads(row['verification_json'] or '{}')
        before=verification.get('source_size',details.get('before_bytes'));after=verification.get('output_size',details.get('after_bytes'))
        if row['operation']=='RENAME':
            planned=con.execute('SELECT source_size FROM plan_items WHERE plan_id=? AND relpath=?',(row['plan_id'],row['relpath'])).fetchone()
            before=after=planned[0] if planned else None
        record={'timestamp':row['completed_at'],'operation':row['operation'],'source':str(root/row['relpath']),
                'destination':row['final_path'],'library':str(root),'commit_id':row['commit_id'],
                'before_sha256':row['source_original_sha256'],'after_sha256':row['final_sha256'],
                'before_bytes':before,'after_bytes':after,'saved_bytes':before-after if row['operation'].startswith('CONVERT_') and before is not None and after is not None else None,
                'settings':_plan_settings(str(state),row['plan_id'])}
        fields={'CONVERT_IMAGE':('image_output_format','jpeg_quality','image_max_megapixels','minimum_saving_percent','minimum_saving_bytes'),
                'CONVERT_VIDEO':('video_max_storage_edge','minimum_saving_percent','minimum_saving_bytes'),
                'CONVERT_AUDIO':('audio_min_size_mb','minimum_saving_percent','minimum_saving_bytes'),
                'RENAME':('filename_date_format',)}.get(row['operation'],())
        record['settings']={k:v for k,v in record['settings'].items() if k in fields}
        if row['operation']=='CONVERT_IMAGE':
            record['output_dimensions']=verification.get('output_dimensions')
            record['output_format']=(verification.get('output_image') or {}).get('format')
        elif row['operation']=='CONVERT_VIDEO':
            record['output_dimensions']=verification.get('output_dimensions')
            record['output_codec']=verification.get('output_video_codec')
        elif row['operation']=='CONVERT_AUDIO':
            record['settings']['bitrate_kbps']=128
        if row['operation']=='SET_EMBEDDED_DATE':
            record.update(date=details.get('date'),previous_date=details.get('previous_date'))
        _queue(con,state,'change:'+row['commit_id']+':'+row['relpath'],record)
    rows=con.execute("SELECT r.rollback_id,COALESCE(r.completed_at,r.started_at) logged_at,ci.* FROM rollbacks r JOIN commit_items ci USING(commit_id) "
        "WHERE r.status='ROLLED_BACK' AND NOT EXISTS(SELECT 1 FROM change_log_outbox o WHERE o.event_key='restore:'||r.rollback_id||':'||ci.relpath) "
        "ORDER BY r.completed_at").fetchall()
    for row in rows:
        details=json.loads(row['details_json'] or '{}')
        _queue(con,state,'restore:'+row['rollback_id']+':'+row['relpath'],
            {'timestamp':row['logged_at'],'operation':'RESTORE_ORIGINAL','source':row['final_path'],
             'destination':str(root/details.get('original_relpath',row['relpath'])),'library':str(root),
             'commit_id':row['commit_id'],'after_sha256':row['source_original_sha256']})


def _repair_tail(fd):
    length=os.lseek(fd,0,os.SEEK_END)
    if not length or os.pread(fd,1,length-1)==b'\n':return False
    # Only an interrupted final record may be removed; earlier entries stay intact.
    offset=length;tail=b''
    while offset:
        count=min(offset,65536);offset-=count;tail=os.pread(fd,count,offset)+tail
        if b'\n' in tail:break
    last=tail.rsplit(b'\n',1)[-1]
    if not (last.startswith(b'{') or b'{'.startswith(last)):
        raise ValueError('The end of the change log is unrecognized; it has been left untouched.')
    os.ftruncate(fd,length-len(last));os.fsync(fd)
    return True


def _records(fd):
    os.lseek(fd,0,os.SEEK_SET)
    with os.fdopen(os.dup(fd),'r',encoding='utf-8') as stream:
        for line in stream:
            record=json.loads(line)
            if record.get('schema_version')!=1 or not re.fullmatch(r'[0-9a-f]{64}',record.get('event_id','')):
                raise ValueError('The change log contains an unrecognized record.')
            yield record


KINDS = {'cleanup':'Smart cleanup', 'manual-date':'Manual date edit', 'restore':'Restore original',
         'file-change':'File change', 'previous':'Earlier changes'}


def _context(state):
    path=security.inside(state,'change-log-run.json')
    return json.loads(path.read_text()) if path.is_file() else {}


def _valid_group(group):
    if not isinstance(group,dict) or group.get('kind') not in KINDS or not re.fullmatch(r'[0-9a-f]{32}',group.get('id','')):
        raise ValueError('Unrecognized change log group')
    dt.datetime.fromisoformat(group['started_at'])
    return group


def record_group(state,key,record):
    context=_context(state)
    if context.get('active'):
        return _valid_group(context['group'])
    kind='manual-date' if record['operation']=='SET_EMBEDDED_DATE' else 'restore' if record['operation']=='RESTORE_ORIGINAL' else 'file-change'
    return {'id':hashlib.sha256((str(state)+'|'+key).encode()).hexdigest()[:32], 'kind':kind,
            'started_at':record['timestamp'], 'folders':[record['library']] if record.get('library') else []}


def last_group(state):
    context=_context(state)
    return _valid_group(context['group']) if context else None


def _previous_group(directory):
    path=security.inside(directory,'.records/previous-group.json')
    if path.exists():return _valid_group(json.loads(path.read_text()))
    return {'id':'0'*32,'kind':'previous','started_at':'1970-01-01T00:00:00+00:00','folders':[]}


def _paths(directory,group):
    group=_valid_group(group)
    if group['kind']=='previous':
        name='Earlier changes - '+group['id'][:8]
    else:
        stamp=dt.datetime.fromisoformat(group['started_at']).astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H.%M.%S UTC')
        name=stamp+' - '+KINDS[group['kind']]+' - '+group['id'][:8]
    return (security.inside(directory,'.records/'+group['id']+'.jsonl'),security.inside(directory,name+'.log'))


@contextlib.contextmanager
def _locked(directory):
    security.private_directory(directory)
    security.private_directory(security.inside(directory,'.records'))
    lock=_open(security.inside(directory,'.lock'),os.O_CREAT|os.O_RDWR)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield
    finally:os.close(lock)


def _deliver(directory,group,pending,writing,delivered):
    data_path,human_path=_paths(directory,group)
    data=_open(data_path,os.O_CREAT|os.O_RDWR|os.O_APPEND)
    try:readable=_open(human_path,os.O_CREAT|os.O_RDWR|os.O_APPEND)
    except BaseException:
        os.close(data)
        raise
    try:
        interrupted=_repair_tail(data)
        known=set()
        if interrupted or any(row[2]=='writing' for row in pending) or (os.fstat(readable).st_size==0 and os.fstat(data).st_size>0):
            os.ftruncate(readable,0)
            for record in _records(data):
                known.add(record['event_id']);_write_all(readable,_line(record).encode())
            os.fsync(readable)
        for key,payload,status in pending:
            record=json.loads(payload)
            if record['event_id'] not in known:
                writing(key)
                _write_all(data,(json.dumps(record,ensure_ascii=False,sort_keys=True)+'\n').encode());os.fsync(data)
                _write_all(readable,_line(record).encode());os.fsync(readable)
                known.add(record['event_id'])
            delivered(key)
        security.sync_directory(directory);security.sync_directory(directory/'.records')
    finally:os.close(data);os.close(readable)


def _lifecycle_locked(state,directory):
    context=_context(state)
    pending=[(entry['key'],json.dumps(entry['record'],ensure_ascii=False,sort_keys=True),entry['status'])
             for entry in context.get('lifecycle',[]) if entry['status']!='delivered']
    if not pending:return
    def mark(key,status):
        for entry in context['lifecycle']:
            if entry['key']==key:entry['status']=status
        security.atomic_json(security.inside(state,'change-log-run.json'),context)
    _deliver(directory,context['group'],pending,lambda key:mark(key,'writing'),lambda key:mark(key,'delivered'))


def flush_state(state: Path, extra=None):
    """Deliver each change to its action's log before acknowledging the queue."""
    state=Path(os.path.abspath(state));db=security.inside(state,'media-maintenance.sqlite')
    if not db.is_file() and not _context(state):return
    directory=destination(state)
    with _locked(directory):
        _lifecycle_locked(state,directory)
        if not db.is_file():return
        with security.database(db) as con:
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'commits','commit_items','rollbacks'} <= tables:return
            con.execute("CREATE TABLE IF NOT EXISTS change_log_outbox(event_key TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('ready','writing','delivered')))")
            _seed(con,state)
            if extra:
                key,record=extra;_queue(con,state,key,record)
            con.commit()
            grouped={}
            for key,payload,status in con.execute("SELECT event_key,payload,status FROM change_log_outbox WHERE status<>'delivered' ORDER BY rowid"):
                record=json.loads(payload);group=record.get('group') or _previous_group(directory)
                bucket=grouped.setdefault(group['id'],(group,[]));bucket[1].append((key,payload,status))
            def mark(key,status):
                con.execute("UPDATE change_log_outbox SET status=? WHERE event_key=?",(status,key));con.commit()
            for group,pending in grouped.values():
                _deliver(directory,group,pending,lambda key:mark(key,'writing'),lambda key:mark(key,'delivered'))


def _lifecycle_record(group,operation,**fields):
    return {'schema_version':1,'event_id':hashlib.sha256((group['id']+'|'+operation).encode()).hexdigest(),
            'timestamp':group['started_at'] if operation=='RUN_STARTED' else dt.datetime.now(dt.timezone.utc).isoformat(),
            'operation':operation,'group':group,'folders':group['folders'],**fields}


def begin_action(args,state,kind,folders,inherited=None):
    # Flush or close a previous interrupted action before replacing its retry
    # marker. Pending changes keep their original run even after cancellation.
    finish_action(state,'interrupted')
    flush_state(state)
    if inherited:
        context={'group':_valid_group(inherited),'active':True,'lifecycle':[]}
    else:
        group={'id':uuid.uuid4().hex,'kind':kind,'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),
               'folders':[str(folder) for folder in folders]}
        context={'group':group,'active':True,'lifecycle':[{'key':'start','record':_lifecycle_record(group,'RUN_STARTED'),'status':'ready'}]}
        args._change_log_owned_state=str(state)
    security.atomic_json(security.inside(state,'change-log-run.json'),context)
    flush_state(state)
    return context['group']


def finish_action(state,outcome,message=None):
    state=Path(state);context=_context(state)
    if not context or not context.get('active'):return
    children=[]
    folder_root=security.inside(state,'folders')
    if folder_root.is_dir():
        children=[child for child in folder_root.iterdir() if re.fullmatch(r'[0-9a-f]{16}',child.name)
                  and _context(child).get('group',{}).get('id')==context['group']['id']]
    for child in children:flush_state(child)
    flush_state(state)
    context=_context(state)
    changed_files=0
    if context.get('lifecycle'):
        directory=destination(state)
        with _locked(directory):
            data,_=_paths(directory,context['group'])
            if data.exists():
                fd=_open(data,os.O_RDONLY)
                try:changed_files=sum(record['operation'] not in {'RUN_STARTED','RUN_FINISHED','MOVE_ORIGINALS_TO_TRASH'} for record in _records(fd))
                finally:os.close(fd)
    context['active']=False
    if context.get('lifecycle'):
        context['lifecycle'].append({'key':'finish','record':_lifecycle_record(context['group'],'RUN_FINISHED',outcome=outcome,message=message,changed_files=changed_files),'status':'ready'})
    security.atomic_json(security.inside(state,'change-log-run.json'),context)
    flush_state(state)
    for child in children:
        other=_context(child);other['active']=False
        security.atomic_json(security.inside(child,'change-log-run.json'),other)


def logged_action(function):
    @functools.wraps(function)
    def wrapped(args,*a,**kw):
        args._change_log_owned_state=None
        try:result=function(args,*a,**kw)
        except BaseException as error:
            if getattr(args,'_change_log_owned_state',None):
                try:finish_action(args._change_log_owned_state,'interrupted' if isinstance(error,(KeyboardInterrupt,SystemExit)) else 'stopped',str(error)[:1000])
                except (OSError,ValueError,RuntimeError,sqlite3.Error):pass
            raise
        if getattr(args,'_change_log_owned_state',None):
            finish_action(args._change_log_owned_state,'completed' if result==0 else 'stopped')
        return result
    return wrapped


def initialize(preferences: Path):
    directory=security.inside(preferences,'Change Logs')
    with _locked(directory):
        old_data=security.inside(directory,'changes.jsonl');old_human=security.inside(directory,'changes.log')
        if old_data.exists() or old_human.exists():
            # Preserve the original combined history, including retry records
            # from the preceding version; new runs never append to this archive.
            raw=old_data.read_bytes() if old_data.exists() else b''
            if not raw and old_human.exists():raw=old_human.read_bytes()
            if raw or (old_human.exists() and old_human.stat().st_size):
                marker=security.inside(directory,'.records/previous-group.json')
                group=_valid_group(json.loads(marker.read_text())) if marker.exists() else {
                    'id':hashlib.sha256(raw).hexdigest()[:32],'kind':'previous','started_at':'1970-01-01T00:00:00+00:00','folders':[]}
                # Persist the archive identity first, so an interrupted migration
                # resumes into the same pair of files and preserves retry IDs.
                security.atomic_json(marker,group)
                data,human=_paths(directory,group)
                for old,target in ((old_data,data),(old_human,human)):
                    if old.exists():
                        if target.exists():
                            if target.read_bytes()!=old.read_bytes():raise ValueError('An earlier log archive already exists with different contents.')
                            old.unlink()
                        else:old.rename(target)
            else:
                for old in (old_data,old_human):
                    if old.exists():old.unlink()
            security.sync_directory(directory)
            security.sync_directory(directory/'.records')
    return {'directory':str(directory),'layout':'One readable log per cleanup run or manual action'}
