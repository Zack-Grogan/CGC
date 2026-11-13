"""Durable local job ledger. The worker executes plans, never creative decisions."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from .planning import ROOT, Plan


def file_digest(path):
    import hashlib
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def state_dir():
    return Path(os.environ.get('CGC_STATE_DIR', ROOT / '.cgc')).expanduser().resolve()


@contextmanager
def connect():
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'queue.sqlite', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, output TEXT UNIQUE NOT NULL, plan TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, result TEXT, error TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS imports (key TEXT PRIMARY KEY, job TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def enqueue(plan, import_key=None):
    """Snapshot references before admission, and reserve the output transactionally."""
    import hashlib
    import shutil
    from .runtime import preflight
    if import_key:
        with connect() as db:
            existing=db.execute("SELECT job FROM imports WHERE key=?",(import_key,)).fetchone()
        if existing:
            return get(existing[0])
    preflight(plan)
    ident = uuid.uuid4().hex
    folder = state_dir() / 'inputs'
    folder.mkdir(parents=True, exist_ok=True)
    command = list(plan.command)
    params = dict(plan.parameters)
    originals = list(params.get('references', []))
    if params.get('reference'):
        originals.append(params['reference'])
    mapping = {}
    for source in originals:
        path = Path(source)
        digest = file_digest(path)
        target = folder / (digest + path.suffix)
        if target.exists():
            if file_digest(target)!=digest:
                raise ValueError('Input snapshot cache failed its digest check: '+str(target))
        else:
            if shutil.disk_usage(folder).free < path.stat().st_size+256*1024*1024:
                raise ValueError('Insufficient snapshot space; preserve 256 MiB for queue state and recovery')
            temporary = folder / (uuid.uuid4().hex + '.tmp')
            shutil.copyfile(path, temporary)
            if file_digest(temporary) != digest:
                temporary.unlink()
                raise ValueError('Input changed while being queued; submit again.')
            os.replace(temporary, target)
        mapping[source] = str(target)
    command = [mapping.get(arg, arg) for arg in command]
    if 'references' in params:
        params['references'] = [mapping.get(p, p) for p in params['references']]
    if 'reference' in params:
        params['reference'] = mapping.get(params['reference'], params['reference'])
    params['source_paths'] = mapping
    snapshot = replace(plan, command=command, parameters=params)
    try:
        with connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)', (ident, plan.output, json.dumps(snapshot.to_dict()), 'queued', time.time(), time.time(), None, None))
            if import_key:
                db.execute('INSERT INTO imports VALUES (?,?)',(import_key,ident))
    except sqlite3.IntegrityError as exc:
        if import_key:
            with connect() as db:existing=db.execute('SELECT job FROM imports WHERE key=?',(import_key,)).fetchone()
            if existing:return get(existing[0])
        raise ValueError('Output path is already reserved by another job: '+plan.output) from exc
    return get(ident)


def get(ident):
    with connect() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError(f'Unknown job: {ident}')
    return decode(row)


def decode(row):
    result = dict(row)
    result['plan'] = json.loads(result['plan'])
    result['result'] = json.loads(result['result']) if result['result'] else None
    tracking=Path(result['output']+'.remote.json')
    if tracking.exists():
        try:result['provider']=json.loads(tracking.read_text())
        except ValueError:pass
    return result


def listing(limit=100):
    if not 1 <= limit <= 10000:
        raise ValueError('Limit must be between 1 and 10000.')
    with connect() as db:
        return [decode(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT ?', (limit,))]


def update(ident, state, result=None, error=None):
    with connect() as db:
        db.execute('UPDATE jobs SET state=?, updated=?, result=?, error=? WHERE id=?', (state, time.time(), json.dumps(result) if result is not None else None, error, ident))


def paused(value=None):
    with connect() as db:
        if value is not None:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('paused',?)", ('1' if value else '0',))
        settings=dict(db.execute("SELECT key,value FROM settings WHERE key IN ('paused','control_busy')"))
        manually_paused=settings.get('paused')=='1'
        busy=settings.get('control_busy')=='1'
    # A crashed control command must not pause dispatch forever. The file lock,
    # held by the actual command, is authoritative; the setting is only a hint.
    with (state_dir()/'control.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        if busy:
            with connect() as db:db.execute("INSERT OR REPLACE INTO settings VALUES ('control_busy','0')")
    return manually_paused


def start():
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    environment=os.environ.copy();environment['CGC_STATE_DIR']=str(folder)
    with (folder / 'worker.log').open('a') as log:
        subprocess.Popen([sys.executable, '-m', 'cgc.queue'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,env=environment)


def claim_next(last_model):
    """Serialize admission to execution with cancellation/control commands."""
    with (state_dir()/'control.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return None
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            setting=db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            if setting and setting[0]=='1':return None
            db.execute("INSERT OR REPLACE INTO settings VALUES ('control_busy','0')")
            row=db.execute("SELECT * FROM jobs WHERE state IN ('queued','recovering') ORDER BY CASE WHEN json_extract(plan,'$.model')=? THEN 0 ELSE 1 END, created LIMIT 1",(last_model,)).fetchone()
            if row:db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?",(time.time(),row['id']))
            return row


def worker(once=False):
    from .runtime import run
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # A previous process died. A paid remote outcome must never be retried blindly.
        with connect() as db:
            db.execute("UPDATE jobs SET state='recovering', error='Recovering after worker restart' WHERE state='running'")
        with connect() as db:
            for row in db.execute("SELECT id,plan,output FROM jobs WHERE state='recovering'").fetchall():
                if json.loads(row['plan'])['backend']!='remote' or not Path(row['output']+'.remote.json').exists():
                    db.execute("UPDATE jobs SET state='remote_outcome_unknown' WHERE id=?",(row['id'],))
        last_model = None
        served = 0
        service_started = time.monotonic()
        while True:
            if served >= 20 or time.monotonic()-service_started >= 600:
                last_model = None
                served = 0
                service_started = time.monotonic()
            row=claim_next(last_model)
            if row:
                last_model = json.loads(row['plan'])['model']
                served += 1
                attempt_started=time.time()
                try:
                    if row['state']=='recovering' and json.loads(row['plan'])['backend']=='remote':
                        from .remote import run as remote_run
                        result=remote_run(Plan(**json.loads(row['plan'])),recover=True)
                    else:
                        result = run(Plan(**json.loads(row['plan'])), quiet=True)
                    result['queue_job_id']=row['id']
                    result['queue_wait_seconds']=max(0,attempt_started-row['created'])
                    if get(row['id'])['state']!='cancelled':
                        update(row['id'], 'completed', result=result)
                except Exception as exc:
                    state = 'failed'
                    receipt = Path(row['output'] + '.json')
                    if receipt.is_file():
                        try:
                            state = json.loads(receipt.read_text()).get('status', state)
                        except ValueError:
                            pass
                    if get(row['id'])['state']!='cancelled':
                        update(row['id'], state, error=str(exc))
            if once:
                return
            if row is None:
                time.sleep(1)


def wait(ids):
    while True:
        rows = [get(i) for i in ids]
        if all(r['state'] not in ('queued', 'running','recovering') for r in rows):
            return rows
        time.sleep(0.5)


def cli(args):
    if args.command == 'queue':
        if args.action=='configure':
            if not 0<=args.keep_warm_seconds<=3600:
                raise ValueError('Keep-warm seconds must be 0 through 3600')
            config={'keep_warm_seconds':args.keep_warm_seconds}
            state_dir().mkdir(parents=True,exist_ok=True)
            (state_dir()/'config.json').write_text(json.dumps(config,indent=2))
            return config
        if args.action=='cool':
            result=subprocess.run([str(ROOT/'.backends/beam/bin/python'),str(ROOT/'cgc/remote_client.py'),'--cooldown'],capture_output=True,text=True,check=True)
            return json.loads(result.stdout)
        if args.action == 'add':
            from .planning import build_plan
            jobs = []
            with args.file.open() as source:
                for number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    allowed={'operation','prompt','model','output','reference','input','seed','style','aspect','size','width','height','steps','direction','transcript','transcript_file','text_file','duration','instrumental','lyrics_file','bpm','key','language','track','tracks','start','end','from_latents','resolution','texture_size','decimation_target','save_latents','transparent','camera_mode','views','points','mask','view','labels','label','part','octree_depth','quality','negative_prompt','guidance_scale','cfg_scale','num_beams'}
                    if not isinstance(row,dict) or set(row)-allowed:
                        raise ValueError(f'Invalid fields on row {number}')
                    operation = row.pop('operation')
                    row.update(backend='beam', accept_license=args.accept_license, consent=args.consent)
                    import hashlib
                    key=hashlib.sha256((str(args.file.resolve())+':'+str(number)+':'+line).encode()).hexdigest()
                    with connect() as db:
                        known=db.execute('SELECT job FROM imports WHERE key=?',(key,)).fetchone()
                    jobs.append(known[0] if known else enqueue(build_plan(operation,row),import_key=key)['id'])
            start()
            return {'jobs': jobs}
        if args.action == 'start':
            start()
            return {'worker': 'start_requested'}
        if args.action in ('pause', 'resume'):
            paused(args.action == 'pause')
            if args.action == 'resume':
                start()
            return {'paused': paused()}
        raise ValueError('Unsupported queue operation')
    if args.action == 'list':
        return listing(args.limit)
    if args.action == 'show':
        return get(args.ids[0])
    if args.action == 'wait':
        return wait(args.ids)
    if args.action == 'retry':
        job=get(args.ids[0])
        if job['state'] in ('queued','running','recovering'):
            raise ValueError('Retry refused while a local attempt is queued or running')
        record=Path(job['output']+'.remote.json')
        if record.exists():
            probe=subprocess.run([str(ROOT/'.backends/beam/bin/python'),str(ROOT/'cgc/remote_client.py'),'--status-only','--plan',json.dumps(job['plan'])],capture_output=True,text=True,check=True)
            status=json.loads(probe.stdout)['status'].upper()
            if status not in ('ERROR','FAILED','TIMEOUT','CANCELLED','REJECTED'):
                raise ValueError('Retry refused for state '+status+'; collect successful/uncertain work first')
        elif job['state']!='failed':
            raise ValueError('Retry requires a confirmed failed attempt')
        attempt=state_dir()/'attempts'/job['id']/uuid.uuid4().hex
        attempt.mkdir(parents=True)
        output=Path(job['output'])
        if output.exists():
            raise ValueError('Output exists; preserve or collect it rather than retry')
        for suffix in ('.json','.log','.remote.json','.result.json'):
            path=Path(str(output)+suffix)
            if path.exists():
                path.rename(attempt/path.name)
        update(job['id'],'queued')
        start()
        return get(job['id'])
    if args.action == 'collect':
        job = get(args.ids[0])
        if job['plan']['backend'] != 'remote':
            raise ValueError('Collection is available for resident remote jobs only')
        plan = Plan(**job['plan'])
        from .remote import run as recover_run
        result=recover_run(plan,recover=True)
        update(job['id'],'completed',result=result)
        return get(job['id'])
    if args.action == 'cancel':
        with connect() as db:
            changed = db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state='queued'", (time.time(), args.ids[0])).rowcount
        if not changed:
            job = get(args.ids[0])
            if job['state'] in ('completed','cancelled','failed'):
                return job
            tracking = Path(job['output'] + '.remote.json')
            if not tracking.exists():
                raise ValueError('Submission outcome unknown; no provider task ID recorded yet')
            with (state_dir()/'control.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                with connect() as db:
                    db.execute("INSERT OR REPLACE INTO settings VALUES ('control_busy','1')")
                try:
                    response=subprocess.run([str(ROOT/'.backends/beam/bin/python'),str(ROOT/'cgc/remote_client.py'),'--cancel','--plan',json.dumps(job['plan'])],capture_output=True,text=True,check=True)
                    outcome=json.loads(response.stdout)
                    state='collection_pending' if outcome['status'] in ('COMPLETE','COMPLETED') else 'cancelled' if outcome['status']=='CANCELLED' else 'failed'
                    update(job['id'],state)
                finally:
                    with connect() as db:
                        db.execute("INSERT OR REPLACE INTO settings VALUES ('control_busy','0')")
        return get(args.ids[0])
    raise ValueError('Unsupported job operation')


if __name__ == '__main__':
    worker()
