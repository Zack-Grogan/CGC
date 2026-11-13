"""Pinned, project-scoped Khronos glTF standards validation."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from .planning import ROOT, UserError

VERSION='2.0.0-dev.3.10'


def setup(root=ROOT):
    npm=shutil.which('npm')
    if not npm:raise UserError('Install Node.js/npm to set up the optional Khronos validator')
    folder=Path(root)/'.backends/gltf-validator'
    folder.mkdir(parents=True,exist_ok=True)
    subprocess.run([npm,'install','--prefix',str(folder),'--ignore-scripts','--no-audit','--no-fund','--save-exact','gltf-validator@'+VERSION],check=True,timeout=300)
    return {'status':'installed','package':'gltf-validator','version':VERSION,'path':str(folder),'downloads_model_weights':False}


def validate(source,output=None,warnings_as_errors=False,max_issues=10000,timeout=120,root=ROOT,resource_root=None):
    source=Path(source).expanduser().resolve()
    if source.suffix.lower() not in ('.glb','.gltf') or not source.is_file():raise UserError('Supply an existing GLB or glTF file')
    if type(max_issues) is not int or not 1<=max_issues<=100000:raise UserError('Issue limit must be 1 through 100000')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:raise UserError('Timeout must be positive and finite')
    target=Path(output).expanduser().resolve() if output else None
    resources=Path(resource_root).expanduser().resolve() if resource_root else source.parent
    if not resources.is_dir() or not source.is_relative_to(resources):raise UserError('The asset must be inside the declared resource root')
    if target and target.exists():raise UserError('Validation report exists; select a new output')
    node=shutil.which('node');module=Path(root)/'.backends/gltf-validator/node_modules/gltf-validator'
    metadata=module/'package.json'
    if not node or not metadata.is_file() or json.loads(metadata.read_text()).get('version')!=VERSION:
        raise UserError('Run cgc validate setup to install the pinned official Khronos validator')
    try:
        result=subprocess.run([node,str(Path(__file__).with_name('validate_gltf.cjs')),str(module),str(source),str(max_issues),str(resources)],capture_output=True,text=True,check=True,timeout=timeout)
        validated=json.loads(result.stdout);report=validated['report']
    except subprocess.CalledProcessError as error:raise UserError('Khronos validation failed to run: '+error.stderr[-1500:]) from error
    except subprocess.TimeoutExpired as error:raise UserError('Khronos validation timed out; the asset has not passed') from error
    issues=report.get('issues',{});complete=not issues.get('truncated',False)
    passed=complete and issues.get('numErrors',0)==0 and (not warnings_as_errors or issues.get('numWarnings',0)==0)
    checksum=hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):checksum.update(block)
    if checksum.hexdigest()!=validated['source_sha256']:raise UserError('The asset changed during validation; rerun against a stable file')
    response={'status':'passed' if passed else 'failed','source':str(source),'sha256':checksum.hexdigest(),'validator':'Khronos glTF Validator',
              'package_version':VERSION,'complete':complete,'warnings_as_errors':bool(warnings_as_errors),'errors':issues.get('numErrors',0),'warnings':issues.get('numWarnings',0),'report':report,'external_resources':validated['resources'],
              'resource_root':str(resources),'scope':'glTF specification checks; engine import, visual quality and gameplay suitability need separate checks'}
    if target:
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x') as stream:json.dump(response,stream,indent=2)
        response['report_path']=str(target)
    return response


def add_parser(subparsers):
    group=subparsers.add_parser('validate',help='Check standards with the official Khronos validator')
    commands=group.add_subparsers(dest='action',required=True)
    install=commands.add_parser('setup');install.add_argument('--json',action='store_true')
    check=commands.add_parser('gltf');check.add_argument('--input',required=True);check.add_argument('-o','--output')
    check.add_argument('--warnings-as-errors',action='store_true');check.add_argument('--max-issues',type=int,default=10000)
    check.add_argument('--timeout',type=float,default=120);check.add_argument('--json',action='store_true')
    check.add_argument('--resource-root',help='Allow referenced resources within this explicit asset/project folder')


def handle(args):
    if args.action=='setup':return setup()
    return validate(args.input,args.output,args.warnings_as_errors,args.max_issues,args.timeout,resource_root=args.resource_root)
