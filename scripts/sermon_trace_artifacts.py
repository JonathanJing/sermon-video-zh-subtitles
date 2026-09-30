"""Private atomic derived artifacts; raw ledger writes belong to the collector."""
import os
from pathlib import Path
import uuid
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path


def new_directory(path):
    path=_safe_path(path)
    path.mkdir(parents=True,exist_ok=False,mode=0o700)
    jobs._sync_directory_ancestry(path)
    return path


def write(path,content):
    path=Path(path);root=jobs._directory_fd(path.parent);temp='.'+uuid.uuid4().hex
    try:
        jobs._reject_link(path,directory=False)
        fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=root)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path.name,src_dir_fd=root,dst_dir_fd=root);os.fsync(root)
    finally:
        try:os.unlink(temp,dir_fd=root)
        except FileNotFoundError:pass
        os.close(root)
