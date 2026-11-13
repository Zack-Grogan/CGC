"""Explicit native compute budgets; no profile guarantees subjective quality."""
from copy import deepcopy

# Published Qwen 2.1 canvas presets. Keeping the area close to the published
# 2048px square avoids claiming arbitrary larger canvases are qualified.
QWEN_CANVASES={(2048,2048),(2400,1792),(1792,2400),(2528,1696),(1696,2528),(2752,1536),(1536,2752)}

PROFILES = {
    'qwen-image-2.1': {'draft': {'steps':20}, 'standard': {'steps':40}, 'detail': {'steps':40}},
    'qwen-image-2.1-turbo': {'draft': {'steps':8}, 'standard': {'steps':8}, 'detail': {'steps':8}},
    'trellis2': {
        'draft': {'resolution':'512','texture_size':1024,'decimation_target':50000},
        'standard': {'resolution':'1024','texture_size':2048,'decimation_target':100000},
        'detail': {'resolution':'1024','texture_size':2048,'decimation_target':300000,'save_latents':True}},
    'moss-sfx-v2': {'draft': {'steps':50}, 'standard': {'steps':100}, 'detail': {'steps':100}},
    'ace-step-1.5-base': {'draft': {'steps':32}, 'standard': {'steps':32}, 'detail': {'steps':64}},
    'ace-step-1.5-turbo': {'draft': {'steps':8}, 'standard': {'steps':8}, 'detail': {'steps':8}},
    'voxcpm2': {'draft': {'steps':6}, 'standard': {'steps':10}, 'detail': {'steps':10}},
    'kimodo-soma-rp-v1.2': {'draft': {'steps':50}, 'standard': {'steps':100}, 'detail': {'steps':100}},
    'holopart': {'draft': {'steps':25,'octree_depth':6}, 'standard': {'steps':50,'octree_depth':7}, 'detail': {'steps':50,'octree_depth':8}},
    'tokenrig': {'draft': {'num_beams':4}, 'standard': {'num_beams':10}, 'detail': {'num_beams':10}},
}


def resolve(model, options, operation=None):
    """Fill only unspecified controls and retain exact explicit user choices."""
    name=options.get('quality')
    result=dict(options)
    if name is None:return result,None
    if name not in ('draft','standard','detail'):raise ValueError('Quality must be draft, standard, or detail')
    if model not in PROFILES:raise ValueError('This execution profile has no generation quality budget: '+model)
    settings=deepcopy(PROFILES[model][name]);applied={};overrides={}
    if model=='trellis2' and options.get('from_latents'):
        settings.pop('resolution',None);settings.pop('save_latents',None)
    if operation=='model.texture':
        settings.pop('decimation_target',None);settings.pop('save_latents',None)
    for key,value in settings.items():
        unspecified=result.get(key) is None
        if unspecified:result[key]=value;applied[key]=value
        else:overrides[key]=result[key]
    return result,{'name':name,'defaults':settings,'applied':applied,'explicit_overrides':overrides,
                   'basis':'Native controls and recorded adapter budgets; no comparative visual-quality benchmark',
                   'guarantees_quality':False}
