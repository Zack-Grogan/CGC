"""An expressive local-first CLI with a dependency-free control layer."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from . import __version__
from .catalog import ASPECTS, MODELS, STYLES
from .planning import ROOT, UserError, build_plan
from .runtime import doctor, history, run, setup, setup_commands

CLI_ERRORS=(UserError,OSError,ValueError,RuntimeError,subprocess.SubprocessError)

def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def accent(text):
    return f"\033[1;36m{text}\033[0m" if sys.stdout.isatty() and "NO_COLOR" not in os.environ else text


def command_tree(value):
    for action in value._actions:
        if isinstance(action,argparse._SubParsersAction):
            return {name:command_tree(child) for name,child in action.choices.items()}
    return {}


def show_plan(plan):
    if plan.backend == "remote":
        print(f"{plan.operation} / {plan.model} / Beam -> {plan.output}")
        for warning in plan.warnings:print(f"  Note      {warning}")
        quality=plan.parameters.get('quality_profile')
        if quality:print('  Quality   '+json.dumps(quality,ensure_ascii=False))
        return
    name = MODELS[plan.model].name
    if plan.backend == "beam":
        name = f"{plan.model} · Beam {plan.parameters['remote_precision']}"
    print(accent(f"{plan.operation}  /  {name}"))
    print(f"  Output    {plan.output}")
    print(f"  Seed      {plan.seed if plan.seed is not None else 'not exposed by audio backend'}")
    print(f"  Backend   {'Beam remote (paid usage)' if plan.backend == 'beam' else 'local MLX'}")
    print(f"  Network   {'Sends speech inputs to Beam; public model downloads occur remotely' if plan.backend == 'beam' else 'Model downloads allowed; inference remains local' if plan.download else 'Hugging Face offline mode; auxiliary libraries may have separate downloads'}")
    for warning in plan.warnings:
        print(f"  Note      {warning}")
    print("\n" + shlex.join(plan.command))


def parser():
    from .remote import CATALOG as remote_catalog
    model_choices=list(dict.fromkeys([*MODELS,*remote_catalog]))
    p = argparse.ArgumentParser(prog="cgc", description="CGC · Creative Generation Control\nRemote image, mesh, speech, SFX and music generation with a durable local queue.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Start: cgc capabilities --json → cgc setup beam → cgc image generate 'your idea' --dry-run\nGeneration runs on Beam; --enqueue returns job IDs. Use local file paths for inputs and outputs.\nCore CLI needs Python 3.11+; isolated Beam client uses Python 3.12.")
    p.add_argument("--version", action="version", version=f"CGC {__version__}")
    subs = p.add_subparsers(dest="command", required=True)
    from . import standards
    standards.add_parser(subs)
    from . import game_assets
    game_assets.add_parser(subs)
    from . import media_quality
    media_quality.add_parser(subs)
    from . import animation_assets
    animation_assets.add_parser(subs)
    for family in ('queue', 'jobs'):
        group = subs.add_parser(family)
        actions = group.add_subparsers(dest='action', required=True)
        for action in (('start', 'pause', 'resume', 'add', 'configure', 'cool') if family == 'queue' else ('list', 'show', 'wait', 'cancel', 'collect', 'retry')):
            sub = actions.add_parser(action)
            sub.add_argument('--json', action='store_true')
            if action == 'configure':
                sub.add_argument('--keep-warm-seconds',type=int,required=True)
            elif action == 'add':
                sub.add_argument('file', type=Path)
                sub.add_argument('--accept-license', action='store_true')
                sub.add_argument('--consent', action='store_true')
            elif action == 'list':
                sub.add_argument('--limit', type=int, default=100)
            elif family == 'jobs':
                sub.add_argument('ids', nargs='+' if action == 'wait' else 1)
    capabilities = subs.add_parser("capabilities", help="Show remote operations and execution profiles")
    capabilities.add_argument("--json", action="store_true")
    models = subs.add_parser("models", help="Browse the curated, license-labeled model catalog")
    models.add_argument("model", nargs="?", choices=model_choices)
    models.add_argument("--local", action="store_true", help="Show the legacy local adapter catalog")
    models.add_argument("--kind", choices=("image", "audio", "model", "motion"))
    models.add_argument("--json", action="store_true")
    styles = subs.add_parser("styles", help="Show reusable visual art-direction presets")
    styles.add_argument("--json", action="store_true")
    doc = subs.add_parser("doctor", help="Check host, disk and backend packages without loading models")
    doc.add_argument("--json", action="store_true")
    install = subs.add_parser("setup", help="Install pinned backend packages, never model weights")
    install.add_argument("backend", choices=("image", "audio", "kokoro", "beam"))
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--json", action="store_true")
    hist = subs.add_parser("history", help="Review receipts in this project's default outputs directory")
    hist.add_argument("--limit", type=int, default=10)
    hist.add_argument("--json", action="store_true")
    batch = subs.add_parser("batch", help="Run a JSON creative brief as sequential, reproducible jobs")
    batch.add_argument("file", type=Path)
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument("--download", action="store_true")
    batch.add_argument("--json", action="store_true")
    batch.add_argument("--backend", choices=("auto", "beam", "local"), default="beam", help="Audio execution target; auto uses Beam for Phonon/VoxCPM2")
    batch.add_argument("--accept-license", action="store_true", help="Confirm restricted model terms permit your intended use")
    batch.add_argument("--consent", action="store_true", help="Authorize your own or consented voices in this batch")
    for media, actions in (("image", ("generate", "edit")), ("audio", ("speak", "clone", "design", "sfx", "music", "face")), ("model", ("generate", "rig", "skin", "segment", "views", "split", "complete", "texture")), ("motion", ("generate", "extract", "convert"))):
        family = subs.add_parser(media, help={'image':'Generate and edit referenced images','audio':'Generate speech, SFX, music and facial weights','model':'Generate, texture, rig and process 3D assets','motion':'Generate, capture and convert body motion'}[media])
        verbs = family.add_subparsers(dest="action", required=True)
        for action in actions:
            cmd = verbs.add_parser(action)
            cmd.add_argument("prompt", nargs="?", default="", help="Generation brief, edit instruction, or words to speak")
            cmd.add_argument("--enqueue", action="store_true", help="Queue in background and return job ID")
            cmd.add_argument("--model", choices=model_choices)
            cmd.add_argument("-o", "--output", help="New output path; the operation defines its file type. Existing files are preserved")
            cmd.add_argument("--dry-run", action="store_true", help="Show exact command with no installs, downloads or execution")
            cmd.add_argument("--accept-license", action="store_true", help="Confirm restricted model terms permit your intended use; does not grant a license")
            cmd.add_argument("--download", action="store_true", help="Allow missing model/auxiliary assets to download from their providers")
            cmd.add_argument("--json", action="store_true", help="Machine-readable plan or final receipt; backend logs are saved to file")
            cmd.add_argument("--count", type=int, default=1)
            cmd.add_argument("--output-dir", type=Path)
            configurable=(media=='image' or media=='model' and action in ('generate','rig','skin','complete','texture') or media=='motion' and action=='generate' or media=='audio' and action in ('design','clone','sfx','music'))
            if configurable:
                cmd.add_argument("--quality",choices=("draft","standard","detail"),help="Resolve native compute settings; visual quality still needs review")
            if media=='image' or media=='model' and action=='complete' or media=='audio' and action in ('design','clone','music'):
                cmd.add_argument("--guidance-scale",type=float,help="Native guidance/CFG control where supported")
            if media == "model" and action == "texture":
                cmd.add_argument("--input",required=True)
                cmd.add_argument("--reference",action="append",required=True)
                cmd.add_argument("--resolution",choices=("512","1024"))
                cmd.add_argument("--texture-size",type=int)
                cmd.add_argument("--seed",type=int)
                cmd.add_argument("--backend",choices=("beam",),default="beam")
                continue
            if media == "model" and action in ("split","complete"):
                cmd.add_argument("--input",required=True)
                cmd.add_argument("--backend",choices=("beam",),default="beam")
                if action == "split":
                    cmd.add_argument("--labels",required=True)
                    cmd.add_argument("--label",type=int,default=1)
                else:
                    cmd.add_argument("--part",required=True)
                    cmd.add_argument("--steps",type=int)
                    cmd.add_argument("--octree-depth",type=int)
                    cmd.add_argument("--seed",type=int)
                continue
            if media == "audio" and action == "face":
                cmd.add_argument("--input",required=True)
                cmd.add_argument("--backend",choices=("beam",),default="beam")
                continue
            if media == "model" and action == "segment":
                cmd.add_argument("--views",required=True)
                group=cmd.add_mutually_exclusive_group(required=True)
                group.add_argument("--points");group.add_argument("--mask")
                cmd.add_argument("--view",type=int,default=0)
                cmd.add_argument("--seed",type=int)
                cmd.add_argument("--backend",choices=("beam",),default="beam")
                continue
            if media == "model" and action in ("rig","skin","views"):
                cmd.add_argument("--input", required=True)
                cmd.add_argument("--seed", type=int)
                if action in ("rig","skin"):cmd.add_argument("--num-beams",type=int)
                cmd.add_argument("--backend", choices=("beam",), default="beam")
                continue
            if media == "motion":
                if action == "convert":
                    cmd.add_argument("--input",required=True)
                    cmd.add_argument("--backend",choices=("beam",),default="beam")
                    continue
                if action == "extract":
                    cmd.add_argument("--input",required=True)
                    cmd.add_argument("--duration",type=float)
                    cmd.add_argument("--camera-mode",choices=("static","background"),default="background")
                    cmd.add_argument("--backend",choices=("beam",),default="beam")
                    continue
                cmd.add_argument("--duration", type=float, default=5)
                cmd.add_argument("--steps", type=int)
                cmd.add_argument("--seed", type=int)
                cmd.add_argument("--backend", choices=("beam",), default="beam")
                continue
            if media == "model":
                cmd.add_argument("--reference", action="append")
                cmd.add_argument("--from-latents")
                cmd.add_argument("--resolution", choices=("512","1024","1536"))
                cmd.add_argument("--texture-size", type=int)
                cmd.add_argument("--decimation-target", type=int)
                cmd.add_argument("--save-latents", action=argparse.BooleanOptionalAction,default=None)
                cmd.add_argument("--seed", type=int)
                cmd.add_argument("--backend", choices=("beam",), default="beam")
                continue
            if action == "music":
                cmd.add_argument("--task", choices=("generate","cover","repaint","extract","layer","complete"), default="generate")
                cmd.add_argument("--input")
                cmd.add_argument("--reference", action="append")
                cmd.add_argument("--start", type=float)
                cmd.add_argument("--end", type=float)
                cmd.add_argument("--track")
                cmd.add_argument("--tracks")
                cmd.add_argument("--bpm", type=int)
                cmd.add_argument("--key")
                cmd.add_argument("--instrumental", action="store_true")
                cmd.add_argument("--lyrics-file")
            if action in ("sfx", "music"):
                cmd.add_argument("--duration", type=float, default=10)
            if action == "sfx":cmd.add_argument("--cfg-scale",type=float)
            if media == "image":
                cmd.add_argument("--backend", choices=("local", "beam"), default="beam")
                cmd.add_argument("--transparent", action="store_true")
                cmd.add_argument("--seed", type=int, help="Reproducible image seed; defaults to a recorded random seed")
                cmd.add_argument("--style", choices=list(STYLES), default="raw")
                cmd.add_argument("--aspect", choices=list(ASPECTS), default="square")
                cmd.add_argument("--size", type=int, default=1024, help="Long edge: 512/768/1024/1536/2048; aspect rounded to multiples of 16")
                cmd.add_argument("--width", type=int)
                cmd.add_argument("--height", type=int)
                cmd.add_argument("--steps", type=int)
                cmd.add_argument("--negative-prompt")
                cmd.add_argument("--input", help="Target image to edit")
                cmd.add_argument("--reference", action="append", help="Supporting image; repeat for multiple references")
            else:
                cmd.add_argument("--steps",type=int)
                cmd.add_argument("--seed", type=int)
                cmd.add_argument("--text-file")
                cmd.add_argument("--backend", choices=("auto", "beam", "local"), default="auto", help="auto: remote operations use Beam, legacy adapters use local execution; local: require a supported local adapter")
                cmd.add_argument("--metrics", action="store_true", help="Record timing and memory metrics; Beam reports remote stages in the receipt")
                cmd.add_argument("--language", help="English, Spanish, etc.; Kokoro uses codes such as a (American English)")
                cmd.add_argument("--voice", help="Preset voice: Qwen Ryan, Aiden, Vivian, etc.; Kokoro af_heart, etc.")
                cmd.add_argument("--direction", help="Natural-language delivery/voice direction for supported models")
                cmd.add_argument("--speed", type=float, help="Kokoro only, 0.5 to 2.0")
                if action == "clone":
                    cmd.add_argument("--reference", required=True, help="Clean reference recording of an authorized speaker")
                    cmd.add_argument("--transcript-file")
                    cmd.add_argument("--transcript", help="Exact words in reference; avoids automatic ASR download")
                    cmd.add_argument("--consent", action="store_true", help="Confirm you own this voice or the speaker has authorized its use")
    return p


def batch_plans(args):
    try:
        data = json.loads(args.file.read_text())
    except (OSError, ValueError) as exc:
        raise UserError(f"Cannot read batch JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("jobs"), list):
        raise UserError("Batch must be an object with version: 1 and jobs: [...]. See examples/creative-brief.json.")
    if not 1 <= len(data["jobs"]) <= 50:
        raise UserError("A batch must contain 1 to 50 jobs, executed sequentially.")
    plans, outputs = [], set()
    allowed = {"operation", "prompt", "model", "output", "seed", "style", "aspect", "size", "width", "height",
               "steps", "reference", "transcript", "language", "voice", "direction", "speed", "metrics"}
    for index, row in enumerate(data["jobs"], 1):
        if not isinstance(row, dict) or set(row) - allowed:
            raise UserError(f"Job {index}: invalid fields. Jobs cannot grant downloads, consent, or execute arbitrary commands.")
        options = {**row, "download": args.download, "consent": args.consent, "accept_license": args.accept_license,
                   "backend": args.backend}
        try:
            plan = build_plan(row.get("operation", ""), options)
        except (UserError, TypeError, AttributeError) as exc:
            raise UserError(f"Job {index}: {exc}") from exc
        if plan.output in outputs:
            raise UserError(f"Job {index}: duplicate output path {plan.output}")
        outputs.add(plan.output)
        plans.append(plan)
    return plans


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv)>2 and argv[:2]==['audio','music'] and argv[2] in ('generate','cover','repaint','extract','layer','complete'):
        task=argv.pop(2)
        argv += ['--task',task]
    args = parser().parse_args(argv)
    try:
        if args.command == "animation":
            from .animation_assets import handle
            result=handle(args);emit(result)
            return 2 if result.get('status')=='failed' else 0
        elif args.command == "media":
            from .media_quality import handle
            result=handle(args);emit(result)
            return 2 if result.get('status')=='failed' else 0
        elif args.command == "asset":
            from .game_assets import handle
            result=handle(args);emit(result)
            return 2 if result.get('status')=='failed' else 0
        elif args.command == "validate":
            from .standards import handle
            result=handle(args);emit(result)
            return 2 if result.get('status')=='failed' else 0
        elif args.command == "capabilities":
            from .remote import PROFILES
            emit({"profiles":PROFILES,"commands":command_tree(parser()),"inputs":"local paths","outputs":"local paths","provider":"beam","hosting":"On-demand, finite warm retention, zero minimum GPU containers"})
        elif args.command in ("queue", "jobs"):
            from .queue import cli as queue_cli
            answer=queue_cli(args)
            emit(answer)
            if args.command=="jobs" and args.action=="wait" and any(r["state"]!="completed" for r in answer):
                return 2
        elif args.command == "models":
            from .remote import catalog
            if args.local or (args.model and args.model not in {m['id'] for m in catalog()}):
                selected = [MODELS[args.model].to_dict()] if args.model else [m.to_dict() for m in MODELS.values() if not args.kind or m.backend==args.kind]
            else:
                selected=[m for m in catalog() if (not args.model or m['id']==args.model) and (not args.kind or any(op.startswith(args.kind+'.') for op in m['capabilities']))]
            if args.json:
                emit(selected)
            else:
                for model in selected:
                    print(f"{model['id']} · {model['backend']} · {', '.join(model['capabilities'])}\n  {model['license']} · {model['source']}")
        elif args.command == "styles":
            if args.json:
                emit(STYLES)
            else:
                for key, value in STYLES.items():
                    print(f"{accent(key):16} {value or 'Your exact prompt, with no style added.'}")
        elif args.command == "doctor":
            result = doctor()
            if args.json:
                emit(result)
            else:
                print(accent("CGC / studio check"))
                print(f"  Host       {result['platform']} {result['architecture']}\n  Disk free  {result['free_disk_gib']} GiB\n  Project    {ROOT}")
                for name, info in result["backends"].items():
                    print(f"  {name:10} {info.get('package_version', 'not installed')} (cgc setup {name})")
                print("  Generation defaults to Beam. Model weights and inference remain remote. Access and model readiness are checked at submission; local adapters require --backend local.")
        elif args.command == "setup":
            commands = setup_commands(args.backend)
            if args.dry_run:
                if args.json:
                    emit({"backend": args.backend, "commands": commands, "downloads_weights": False})
                else:
                    print("Package-only setup. Local model downloads require --download; Beam downloads public weights remotely.\n" + "\n".join(shlex.join(c) for c in commands))
            else:
                if args.json:
                    raise UserError("Use setup --dry-run --json for a plan; installation streams package-manager logs.")
                setup(args.backend)
                print("Backend packages installed. No model weights were requested.")
        elif args.command == "history":
            if args.limit < 1:
                raise UserError("History limit must be positive.")
            rows = history(limit=args.limit)
            if args.json:
                emit(rows)
            elif not rows:
                print("No recorded runs in CGC/outputs yet. Dry runs do not write files.")
            else:
                for r in rows:
                    print(f"{r['status']:10} {r['plan']['operation']:15} {r['plan']['model']:16} {r['plan']['output']}")
        else:
            if args.command == 'batch':
                plans = batch_plans(args)
            else:
                operation=f"{args.command}.{args.action}"
                if operation=='audio.music':
                    operation += '.'+args.task
                options=vars(args).copy()
                if options.get('backend')=='local' and any(options.get(key) is not None for key in ('quality','guidance_scale','negative_prompt','cfg_scale','num_beams')):
                    raise UserError('These quality controls are qualified for Beam; select --backend beam')
                if options.get('backend')=='auto' and options.get('model') in (None,'phonon','voxcpm2'):
                    options['backend']='beam'
                count=options.get('count',1)
                if not 1<=count<=10000:
                    raise UserError('Count must be 1 through 10000; use bulk import for larger queues')
                if count>1 and not args.output_dir:
                    raise UserError('--count requires --output-dir')
                plans=[]
                for index in range(count):
                    row=dict(options)
                    if args.output_dir:
                        suffix='.zip' if operation=='model.views' else '.pt' if operation=='motion.extract' else '.npz' if args.command=='motion' or operation in ('model.segment','audio.face') else '.png' if args.command=='image' else '.glb' if args.command=='model' else '.wav'
                        row['output']=str(args.output_dir/f'{index+1:04d}{suffix}')
                    if row.get('seed') is not None:
                        row['seed']=(row['seed']+index) % 2**32
                    plan=build_plan(operation,row)
                    if plan.backend!='remote' and any(row.get(key) is not None for key in ('quality','guidance_scale','negative_prompt','cfg_scale','num_beams')):
                        raise UserError('These quality controls are qualified for Beam; select --backend beam')
                    plans.append(plan)
            if args.dry_run:
                if args.json:
                    emit([p.to_dict() for p in plans] if args.command == "batch" or len(plans)>1 else plans[0].to_dict())
                else:
                    for plan in plans:
                        show_plan(plan)
                        print()
            else:
                receipts = []
                for job_index, plan in enumerate(plans, 1):
                    if not args.json:
                        show_plan(plan)
                        print()
                    try:
                        if getattr(args, 'enqueue', False) or plan.backend == 'remote':
                            from .queue import enqueue, start
                            receipt = enqueue(plan)
                            start()
                            if not getattr(args,'enqueue',False):
                                from .queue import wait
                                finished=wait([receipt['id']])[0]
                                if finished['state']!='completed':
                                    raise UserError(f"Job {finished['id']}: {finished['error']}")
                                receipt=finished['result']
                        else:
                            receipt = run(plan, quiet=args.json)
                    except CLI_ERRORS as exc:
                        if args.json and args.command == "batch":
                            emit({"status": "failed", "error": str(exc), "failed_job": job_index,
                                  "completed": receipts, "not_run": len(plans) - job_index,
                                  "failed_output": plan.output, "manifest": plan.output + ".json", "log": plan.output + ".log"})
                            return 2
                        raise
                    receipts.append(receipt)
                    if not args.json:
                        print(accent(f"Queued {receipt['id']}" if getattr(args, "enqueue", False) else f"Saved {plan.output}"))
                if args.json:
                    emit(receipts if args.command == "batch" or len(receipts)>1 else receipts[0])
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Check the run receipt. A remote task may still be running; verify Beam task status before retrying.", file=sys.stderr)
        return 130
    except CLI_ERRORS as exc:
        if getattr(args, "json", False):
            emit({"error": str(exc), "status": "failed"})
        else:
            print(f"CGC: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
