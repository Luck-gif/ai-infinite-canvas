"""检查 ComfyUI 中 IPAdapter 相关节点的接口定义。"""
import json
import comfy_client as cc

info = cc.get_object_info()
targets = [
    'IPAdapterFaceID', 'IPAdapterUnifiedLoaderFaceID', 'IPAdapterInsightFaceLoader',
    'IPAdapterUnifiedLoader', 'IPAdapterModelLoader', 'CLIPVisionLoader',
    'IPAdapterAdvanced', 'IPAdapter',
    'LoadImage', 'CheckpointLoaderSimple', 'CLIPTextEncode',
    'KSampler', 'VAEDecode', 'SaveImage',
    'ImageBlend',
]

for name in targets:
    if name in info:
        node = info[name]
        req = list(node.get('input', {}).get('required', {}).keys())
        opt = list(node.get('input', {}).get('optional', {}).keys()) if node.get('input', {}).get('optional') else []
        print(f'{name}: required={req}, optional={opt}')
    else:
        print(f'{name}: NOT FOUND')
