"""One-time verification of the published PowerShell installer in its own new DB."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, pathlib, platform, re, subprocess, sys, uuid

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=pathlib.Path,required=True)
    p.add_argument('--powershell',required=True)
    p.add_argument('--postgres-bin',type=pathlib.Path,required=True)
    p.add_argument('--port',type=int,default=55432)
    a=p.parse_args()
    sys.path.insert(0,str(a.project/'.runtime'/'python'))
    import psycopg
    project=a.project.resolve(); evidence=project/'evidence'
    database='bookbridge_phase2_psinstall_'+uuid.uuid4().hex[:12]
    tables=['users','addresses','publishers','genres','languages','authors','books','book_authors','book_copies','pickup_slots','loans','loan_proposals','loan_extensions','payments','shipments','notifications','generated_documents','reviews']
    record={'project':'BookBridge','started_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'database':database,'empty_template':'template0','retained_for_inspection':True,'installer':str(project/'scripts'/'install.ps1'),'powershell':a.powershell,'python':sys.version,'psycopg':psycopg.__version__,'platform':platform.platform(),'status':'running'}
    log=[]
    def execute(command,label):
        r=subprocess.run([str(v) for v in command],capture_output=True,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
        log.extend([label,'command: '+subprocess.list2cmdline([str(v) for v in command]),r.stdout,r.stderr,'exit_code: '+str(r.returncode),''])
        return r
    def snapshot():
        dsn=psycopg.conninfo.make_conninfo(host='127.0.0.1',port=a.port,user='bookbridge_admin',dbname=database)
        with psycopg.connect(dsn,autocommit=True) as c:
            scalar=lambda q:c.execute(q).fetchone()[0]
            return {
                'server_version':scalar('SELECT version()'),
                'base_tables':scalar("SELECT count(*) FROM information_schema.tables WHERE table_schema='bookbridge' AND table_type='BASE TABLE'"),
                'base_table_columns':scalar("SELECT count(*) FROM information_schema.columns c JOIN information_schema.tables t USING(table_catalog,table_schema,table_name) WHERE c.table_schema='bookbridge' AND t.table_type='BASE TABLE'"),
                'foreign_keys':scalar("SELECT count(*) FROM pg_constraint pc JOIN pg_namespace n ON n.oid=pc.connamespace WHERE n.nspname='bookbridge' AND pc.contype='f'"),
                'seed_rows':{t:scalar('SELECT count(*) FROM bookbridge.'+t) for t in tables},
                'entity_fingerprints':{t:scalar("SELECT md5(coalesce(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),'')) FROM bookbridge."+t+' t') for t in tables},
                'sequences':c.execute("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='bookbridge' ORDER BY sequencename").fetchall(),
            }
    try:
        created=execute([a.postgres_bin/'createdb.exe','-h','127.0.0.1','-p',str(a.port),'-U','bookbridge_admin','-T','template0',database],'CREATE OWN EMPTY UUID DATABASE')
        if created.returncode: raise RuntimeError('Creation of the new UUID database failed; no existing database was modified.')
        record['created_own_database']=True
        command=[a.powershell,'-NoLogo','-NoProfile','-NonInteractive','-File',project/'scripts'/'install.ps1','-PostgresBin',a.postgres_bin,'-Database',database,'-Port',str(a.port)]
        installed=execute(command,'FIRST INSTALLATION INTO THE NEW EMPTY DATABASE')
        record['first_install_exit_code']=installed.returncode
        if installed.returncode: raise RuntimeError('PowerShell installer failed on the empty database.')
        before=snapshot(); total=sum(before['seed_rows'].values())
        record['installed_snapshot']=before; record['total_seed_rows']=total
        if (before['base_tables'],before['base_table_columns'],before['foreign_keys'],total)!=(18,142,32,1431): raise AssertionError('Unexpected installed structure or row totals.')
        recorded=json.loads((evidence/'wrapper-verification-utf8'/'schema_verification.json').read_text(encoding='utf-8'))
        hashes={s['file']:s['sha256'] for s in recorded['scripts']}
        record['source_hashes']=[{'file':n,'sha256':hashlib.sha256((project/'sql'/n).read_bytes()).hexdigest(),'matches_independent_verification':hashlib.sha256((project/'sql'/n).read_bytes()).hexdigest()==hashes[n]} for n in ['01_schema.sql','02_integrity.sql','03_workflows.sql','04_seed.sql','05_queries.sql','06_access.sql']]
        if not all(s['matches_independent_verification'] for s in record['source_hashes']): raise AssertionError('SQL differs from the separately verified published sources.')
        repeated=execute(command,'REPEAT INSTALLATION MUST REFUSE EXISTING TABLES')
        plain=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',repeated.stdout+repeated.stderr)
        plain=' '.join(plain.split())
        refused=repeated.returncode!=0 and 'already contains BookBridge tables' in plain
        record['repeat_install_exit_code']=repeated.returncode
        record['repeat_refused_existing_tables']=refused
        after=snapshot()
        record['repeat_preserved_all_data_and_sequences']=after==before
        if not refused: raise AssertionError('Repeat installer did not explicitly refuse existing BookBridge tables.')
        if after!=before: raise AssertionError('Repeated installation changed the installed data, structure, or sequences.')
        record['status']='passed'
    except Exception as exc:
        record['status']='failed'; record['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        record['finished_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        (evidence/'installer-console.txt').write_text('\n'.join(log),encoding='utf-8')
        (evidence/'installer_verification.json').write_text(json.dumps(record,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'status':record['status'],'database':database,'base_tables':before['base_tables'],'base_table_columns':before['base_table_columns'],'foreign_keys':before['foreign_keys'],'rows':total,'repeat_refused':refused,'repeat_preserved_all_data_and_sequences':after==before,'sql_hashes_match':all(s['matches_independent_verification'] for s in record['source_hashes'])},indent=2))
if __name__=='__main__': main()
