"""Check the files Git would publish for local data and obvious secrets."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PRIVATE_DIRS={'downloads','patched','backups','serial_runtime','_runtime','.venv','venv','__pycache__'}
PRIVATE_SUFFIXES={'.zip','.vcl','.lnk','.exe','.dll','.pyd','.pem','.key','.p12','.pfx','.log'}
SENSITIVE=re.compile(r'password|passwd|api_?key|access_?token|refresh_?token|client_?secret|credential',re.I)
KEY_PATTERNS=[
    re.compile(r'\b(?:ghp|github_pat|gho|ghu|ghs)_[A-Za-z0-9_]{20,}\b'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
]


def files():
    result=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,capture_output=True)
    if result.returncode:
        raise RuntimeError('Run git init before checking repository contents.')
    return sorted(set(result.stdout.decode().split('\0'))-{''})


def placeholder(value):
    return value in ('','test','example') or value.startswith('EXAMPLE_')


def json_secrets(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if SENSITIVE.search(key) and isinstance(item,str) and not placeholder(item): return True
            if json_secrets(item): return True
    elif isinstance(value,list):
        return any(json_secrets(item) for item in value)
    return False


def check():
    issues=[]
    candidates=files()
    for name in candidates:
        path=ROOT/name
        private=(any(part in PRIVATE_DIRS for part in Path(name).parts)
                 or path.suffix.lower() in PRIVATE_SUFFIXES
                 or path.name.startswith('.env') or path.name=='.instance.lock'
                 or (path.name.startswith('settings') and path.name.endswith('.json') and path.name!='settings.example.json'))
        if private: issues.append((name,'local or generated file is included'))
        data=path.read_bytes()
        try: text=data.decode('utf-8-sig')
        except UnicodeDecodeError: continue
        if any(pattern.search(text) for pattern in KEY_PATTERNS): issues.append((name,'possible access key or private key'))
        if re.search(r'[A-Za-z]:[\\/]Users[\\/](?!Public\b|Default\b)[^\s"\'<>/\\]+',text,re.I):
            issues.append((name,'personal Windows home path'))
        if path.suffix=='.json' and json_secrets(json.loads(text)):
            issues.append((name,'nonempty credential field'))
        if path.suffix=='.py':
            tree=ast.parse(text,filename=name)
            for node in ast.walk(tree):
                if isinstance(node,(ast.Assign,ast.AnnAssign)):
                    targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                    value=node.value
                    if isinstance(value,ast.Constant) and isinstance(value.value,str) and not placeholder(value.value):
                        if any(isinstance(target,ast.Name) and SENSITIVE.search(target.id) for target in targets):
                            issues.append((name,'literal credential assignment'))
    for name,reason in issues: print(f'{name}: {reason}')
    if issues: return 1
    print(f'Repository check passed: {len(candidates)} files; no local data or obvious credentials found.')
    return 0


if __name__=='__main__':
    try: sys.exit(check())
    except Exception as exc:
        print(f'Repository check failed: {exc}');sys.exit(1)
