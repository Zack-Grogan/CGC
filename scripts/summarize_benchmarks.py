"""Summarize existing local receipts and QA. Does not run models or fetch assets."""
from pathlib import Path
import json,re,shutil,sys
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from cgc.runtime import artifact_info,cached_model_identity
out=root/'outputs'
entries=[
 ('flux3_generate','benchmark-flux3-generate-512.png',54.0,3.60,100.0),
 ('flux3_generate_1024_cold_cached','benchmark-flux3-generate-1024.png',None,None,0),
 ('flux3_background_edit','benchmark-flux3-edit-background-512.png',104.0,4.23,0),
 ('fibo2_color_edit','benchmark-fibo2-edit-color-512.png',55.0,5.37,135.0),
 ('flux3_color_edit','benchmark-flux3-edit-color-512.png',None,None,0),
 ('phonon_speech','benchmark-phonon-speech-retry.wav',None,None,0),
 ('voxcpm2_design','benchmark-voxcpm2-design.wav',None,None,40.0),
 ('voxcpm2_synthetic_clone','benchmark-voxcpm2-clone.wav',13.29,3.46,0),
]
result={'date':'2026-11-08','machine':'Apple M4 Mac mini, 16 GB unified memory','heavy_jobs':'sequential',
        'free_disk_gib':round(shutil.disk_usage(root).free/2**30,2),'runs':[],
        'limitations':['Small illustrative samples, not a model leaderboard.','Peak MLX memory is backend-reported, not whole-system memory.','Transcription QA does not measure naturalness or speaker similarity.','Licensing scope is not independently verified.','No human voice was cloned.']}
for label,name,model_seconds,peak,download in entries:
    file=out/name
    receipt_path=Path(str(file)+'.json')
    if not file.exists() or not receipt_path.exists():continue
    receipt=json.loads(receipt_path.read_text())
    log_path=Path(str(file)+'.log')
    log=log_path.read_text(errors='replace') if log_path.exists() else ''
    peak_match=re.findall(r'Peak (?:MLX memory|memory usage):\s*([0-9.]+)\s*GB',log)
    if peak_match:peak=float(peak_match[-1])
    progress=re.findall(r'100%.*?\[(\d+):(\d+)<',log)
    if file.suffix=='.png' and progress:
        minutes,seconds=progress[-1];model_seconds=int(minutes)*60+int(seconds)
    row={'test':label,'status':receipt['status'],'model':receipt['plan']['model'],'elapsed_seconds':receipt['elapsed_seconds'],
         'first_download_seconds_approx':download,'model_processing_seconds':model_seconds,'backend_peak_mlx_gb':peak,
         'artifact':artifact_info(file),'model_snapshot':cached_model_identity(receipt['plan']['model']),
         'receipt':str(receipt_path)}
    qa_name={'phonon_speech':'qa-phonon','voxcpm2_design':'qa-voxcpm2-design','voxcpm2_synthetic_clone':'qa-voxcpm2-clone'}.get(label)
    if qa_name:
        qa=json.loads((out/(qa_name+'.json')).read_text())
        expected=re.findall(r"[a-z0-9']+",receipt['plan']['prompt'].lower())
        actual=re.findall(r"[a-z0-9']+",qa['text'].lower())
        row['transcription_qa']={'model':'mlx-community/whisper-tiny-asr-fp16','normalized_words_match':expected==actual,'expected_words':len(expected),'actual_words':len(actual),'transcript':qa['text'].strip(),'scope':'intelligibility smoke test only'}
    result['runs'].append(row)
blender=out/'benchmark-blender-eevee.report.json'
if blender.exists():
    result['blender']=json.loads(blender.read_text());result['blender']['process_wall_seconds']=6.94
    result['blender']['artifact']=artifact_info(out/'benchmark-blender-eevee.png')
motion=out/'benchmark-blender-motion.report.json'
if motion.exists():
    result['blender_motion']=json.loads(motion.read_text())
    result['blender_motion']['artifact']=artifact_info(out/'benchmark-blender-motion.mp4')
    probe=out/'benchmark-blender-motion.ffprobe.json'
    if probe.exists():result['blender_motion']['ffprobe']=json.loads(probe.read_text())
blocked=out/'qwen-storage-preflight.json'
if blocked.exists():result['blocked']=json.loads(blocked.read_text())
(root/'docs'/'BENCHMARK_RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
