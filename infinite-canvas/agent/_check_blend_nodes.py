"""检查 ComfyUI 中可用的融合/混合节点。"""
import comfy_client as cc

info = cc.get_object_info()
# 搜索 blend/merge/mix/composite 相关节点
targets = [k for k in info if any(w in k.lower() for w in ['blend', 'merge', 'mix', 'composite', 'overlay'])]
for n in sorted(targets):
    req = list(info[n]['input']['required'].keys())
    opt = list(info[n]['input'].get('optional', {}).keys()) if info[n]['input'].get('optional') else []
    print(f'{n}: required={req}, optional={opt}')
