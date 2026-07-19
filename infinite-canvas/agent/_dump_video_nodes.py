import json
import comfy_client as cc

nodes = [
    "WanTextToVideo", "WanImageToVideo", "WanVideoModelLoader",
    "WanVideoVAELoader", "WanVideoClipLoader", "WanVideoTextEncode",
    "WanVideoSampler", "WanVideoDecode", "VHS_VideoCombine",
]
info = cc.get_object_info()  # 一次性排查脚本：不强制刷新缓存
for n in nodes:
    spec = info.get(n)
    if not spec:
        print(n, "== MISSING ==")
        continue
    print("====", n, "====")
    inp = spec.get("input", {})
    req = inp.get("required", {})
    opt = inp.get("optional", {})
    for section, d in (("required", req), ("optional", opt)):
        print(f"  -- {section} --")
        for k, v in d.items():
            print(f"    {k}: {v}")
    out = spec.get("output", [])
    print("  -- output --", out)
    print()
