"""Launch the installed pgAdmin with an isolated project configuration."""
from pathlib import Path
import builtins,os,runpy,sys
phase=Path(__file__).resolve().parents[1]
web=Path(r'D:\PostgreSQL\17\pgAdmin 4\web')
data=phase/'.runtime'/'pgadmin'
data.mkdir(parents=True,exist_ok=True)
os.environ['PGADMIN_SERVER_MODE']='OFF'
builtins.SERVER_MODE=False
sys.path.insert(0,str(web))
import config
config.SERVER_MODE=False
config.DEFAULT_SERVER='127.0.0.1'
config.DEFAULT_SERVER_PORT=5055
config.DATA_DIR=str(data)
config.SQLITE_PATH=str(data/'pgadmin4.db')
config.SESSION_DB_PATH=str(data/'sessions')
config.STORAGE_DIR=str(data/'storage')
config.LOG_FILE=str(data/'pgadmin4.log')
config.MASTER_PASSWORD_REQUIRED=False
config.UPGRADE_CHECK_ENABLED=False
for p in [config.SESSION_DB_PATH,config.STORAGE_DIR]: Path(p).mkdir(exist_ok=True)
runpy.run_path(str(web/'pgAdmin4.py'),run_name='__main__')
