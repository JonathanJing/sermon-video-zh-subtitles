"""Read-only local interpreter, distribution and media-tool admission identity."""
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys


def _hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot():
    tools={}
    for name in ('ffmpeg','ffprobe'):
        path=shutil.which(name)
        if not path:
            raise ValueError('runtime_media_tool_missing')
        output=subprocess.run([path,'-version'],capture_output=True,check=True,timeout=15).stdout
        tools[name]={'binarySha256':_hash(Path(path).resolve()),'versionSha256':hashlib.sha256(output).hexdigest()}
        if name=='ffmpeg':
            for capability in ('decoders','encoders'):
                result=subprocess.run([path,'-hide_banner','-'+capability],capture_output=True,check=True,timeout=15)
                tools[name][capability+'Sha256']=hashlib.sha256(result.stdout).hexdigest()
    return {'schemaVersion':'sermon-local-runtime-identity-v1',
            'python':{'binarySha256':_hash(Path(sys.executable).resolve()),'version':sys.version},
            'distributions':sorted((dist.metadata['Name'],dist.version) for dist in importlib.metadata.distributions()
                                   if dist.metadata.get('Name')),'tools':tools}
