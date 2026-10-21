import copy, gzip, hashlib, importlib.util, io, json
from pathlib import Path
import shutil, tarfile
import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
def module(name):
    spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
G=module('github_trace_backup_guard');B=module('bundle_traces')

@pytest.fixture
def case(tmp_path):
    base=tmp_path/'run';arc=base/'trace-archives';arc.mkdir(parents=True);(base/'drive-offload').mkdir()
    raw=gzip.compress(json.dumps({'body':{'input':'A public Spotify review'}}).encode())
    member={'path':'run/handoffs/abc.request.json.gz','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w') as tar:
        for name,body in [(member['path'],raw),('manifest.json',json.dumps([member]).encode())]:
            info=tarfile.TarInfo(name);info.size=len(body);tar.addfile(info,io.BytesIO(body))
    content=buffer.getvalue();sha=hashlib.sha256(content).hexdigest();p=arc/(sha+'.tar');p.write_bytes(content)
    G.atomic_json(p.with_suffix('.json'),{'archive':str(p),'sha256':sha,'members':[member],'local_readback_verified':True,'remote_verified':False})
    r=B.bundle(base);rp=Path(r['file']).with_suffix('.receipt.json')
    env=tmp_path/'.env';env.write_text('API_KEY=known-secret-value-for-tests\n')
    config={'env_file':str(env),'scratch_dir':str(tmp_path),'release_tag':'hero-private-trace-backups','release_id':'release','repository':'owner/repo','account':'owner'}
    return base,rp,p,config

class FakeGitHub:
    def __init__(self, config):
        self.config=config;self.uploads=0;self.corrupt=False;self.fail_download=False;self.payload=None
        self.meta={'id':'release','url':'https://github.com/owner/repo/releases/tag/draft','isDraft':True,'assets':[]}
    def state(self):
        if not self.meta['isDraft']:raise G.UnsafeBackup('Release is public')
        return copy.deepcopy(self.meta)
    def upload(self,p):
        self.uploads+=1;self.payload=p.read_bytes();sha=hashlib.sha256(self.payload).hexdigest()
        self.meta['assets']=[{'name':p.name,'size':len(self.payload),'digest':'sha256:'+sha,'state':'uploaded','id':'asset','apiUrl':'https://api.github.com/asset','url':'https://github.com/asset'}]
    def download(self,p,d):
        if self.fail_download:raise G.DeferredBackup('Transient download failure')
        (d/p.name).write_bytes(b'bad' if self.corrupt else self.payload)

@pytest.mark.parametrize('payload',[b'{"body":"sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"}',b'{"body":"known-secret-value-for-tests"}',b'{"authorization":"anything"}',b'{"body":"known-secret-value-for-te\\u0073ts"}'])
def test_secret_detection(payload):
    with pytest.raises(G.UnsafeBackup):G.scan_json(payload,[b'known-secret-value-for-tests'])

@pytest.mark.parametrize('payload', [b'{"known-secret-value-for-te\\u0073ts":"x"}', b'{"x":"known-secret-value-for-te\\u0073ts","x":"fine"}'])
def test_secret_in_decoded_key_or_shadowed_duplicate(payload):
    with pytest.raises(G.UnsafeBackup):G.scan_json(payload, [b'known-secret-value-for-tests'])

def test_scan_and_success(case):
    base,rp,archive,c=case;gh=FakeGitHub(c)
    report=G.backup_one(rp,base,c,gh)
    assert report['archive_count']==1 and report['state']=='local_reclamation_completed'
    assert not archive.exists() and archive.with_suffix('.json').exists()
    assert json.loads(rp.read_text())['remote_backup']['destination']=='github_draft'
    assert gh.uploads==1 and gh.meta['isDraft']

def test_bad_remote_sha_keeps_all_sources(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);gh.corrupt=True
    with pytest.raises(G.UnsafeBackup):G.backup_one(rp,base,c,gh)
    assert archive.exists() and Path(json.loads(rp.read_text())['file']).exists()
    assert not json.loads(rp.read_text())['remote_verified']

def test_retry_reuses_uploaded_asset(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);gh.fail_download=True
    with pytest.raises(G.DeferredBackup):G.backup_one(rp,base,c,gh)
    assert archive.exists();gh.fail_download=False
    G.backup_one(rp,base,c,gh)
    assert gh.uploads==1 and not archive.exists()

def test_public_release_rejected(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);gh.meta['isDraft']=False
    with pytest.raises(G.UnsafeBackup):G.backup_one(rp,base,c,gh)
    assert gh.uploads==0 and archive.exists()

def test_wrong_account_and_identity(case,monkeypatch):
    _,_,_,c=case;gh=G.GitHub(c)
    monkeypatch.setattr(gh,'run',lambda args:'wrong' if args[0]=='api' else '{}')
    with pytest.raises(G.UnsafeBackup,match='account'):gh.state()
    monkeypatch.setattr(gh,'run',lambda args:'owner' if args[0]=='api' else json.dumps({'isDraft':True,'id':'other','url':'https://github.com/owner/repo/releases/tag/draft'}))
    with pytest.raises(G.UnsafeBackup,match='identity'):gh.state()

@pytest.mark.parametrize('owner',[G,B])
def test_silent_short_read_fails_closed(tmp_path,monkeypatch,owner):
    p=tmp_path/'bytes';p.write_bytes(b'not empty')
    original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda path:b'' if path==p else original(path))
    with pytest.raises((G.DeferredBackup,RuntimeError),match='Short'):owner.checked_bytes(p)

def test_changed_tar_fails_before_upload(case):
    base,rp,archive,c=case;archive.write_bytes(b'changed');gh=FakeGitHub(c)
    with pytest.raises(G.UnsafeBackup):G.backup_one(rp,base,c,gh)
    assert gh.uploads==0 and archive.exists()

def test_existing_conflicting_asset_never_clobbered(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);bundle=Path(json.loads(rp.read_text())['file']);gh.upload(bundle);gh.meta['assets'][0]['digest']='sha256:wrong'
    with pytest.raises(G.UnsafeBackup):G.backup_one(rp,base,c,gh)
    assert gh.uploads==1 and archive.exists()

def test_partial_reclamation_retry(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);bundle=Path(json.loads(rp.read_text())['file']);gh.upload(bundle);archive.unlink()
    G.backup_one(rp,base,c,gh)
    assert gh.uploads==1 and not bundle.exists() and archive.with_suffix('.json').exists()

def test_release_published_after_readback_keeps_sources(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);original=gh.download
    def download(p,d):
        original(p,d);gh.meta['isDraft']=False
    gh.download=download
    with pytest.raises(G.UnsafeBackup):G.backup_one(rp,base,c,gh)
    assert archive.exists() and not json.loads(rp.read_text())['remote_verified']

def test_remote_asset_changed_after_readback_keeps_sources(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);original=gh.download
    def download(p,d):
        original(p,d);gh.meta['assets'][0]['id']='different'
    gh.download=download
    with pytest.raises(G.UnsafeBackup):G.backup_one(rp,base,c,gh)
    assert archive.exists() and not json.loads(rp.read_text())['remote_verified']

def test_receipt_write_failure_keeps_sources(case,monkeypatch):
    base,rp,archive,c=case;gh=FakeGitHub(c);original=G.atomic_json
    def write(path,value):
        if path==rp:raise OSError('simulated disk full')
        original(path,value)
    monkeypatch.setattr(G,'atomic_json',write)
    with pytest.raises(OSError):G.backup_one(rp,base,c,gh)
    assert archive.exists() and Path(json.loads(rp.read_text())['file']).exists()

def test_post_scan_tar_change_preserved(case):
    base,rp,archive,c=case;gh=FakeGitHub(c);original=gh.download
    def download(p,d):
        original(p,d);archive.write_bytes(b'changed during remote request')
    gh.download=download
    with pytest.raises(G.UnsafeBackup):G.backup_one(rp,base,c,gh)
    assert archive.read_bytes()==b'changed during remote request'

def test_exclusive_process_lock(case,tmp_path):
    import fcntl,subprocess,sys
    base,_,_,c=case;c.update(base=str(base),enabled=True)
    config=tmp_path/'config.json';config.write_text(json.dumps(c))
    with (base/'github-trace-backup.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=subprocess.run([sys.executable,str(TOOLS/'github_trace_backup_guard.py'),'--config',str(config),'--once'],capture_output=True,text=True,timeout=10)
    assert result.returncode and 'Another trace backup guard owns the lock' in result.stderr

def test_deferred_old_bundle_does_not_starve_cycle(case,monkeypatch):
    import logging
    base,rp,archive,c=case;c.update(base=str(base),pending_threshold_bytes=10**12,free_threshold_bytes=0)
    def deferred(*args,**kwargs):raise G.DeferredBackup('old bundle needs hydration')
    monkeypatch.setattr(G,'backup_one',deferred)
    result=G.cycle(c,logging.getLogger('test'))
    assert result['deferred_bundles']==[Path(json.loads(rp.read_text())['file']).name]
    assert archive.exists() and result['disk_free']>0
