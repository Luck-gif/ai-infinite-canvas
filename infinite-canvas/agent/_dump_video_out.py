import comfy_client as cc
info = cc.get_object_info()  # 一次性排查脚本
for n in ["CreateVideo", "VHS_VideoCombine", "WanImageToVideo", "UNETLoader",
          "ModelSamplingSD3", "KSamplerAdvanced", "CLIPLoader", "VAELoader",
          "CLIPTextEncode", "VAEDecode"]:
    spec = info.get(n)
    if not spec:
        print(n, "== MISSING ==")
        continue
    print("====", n, "====")
    inp = spec.get("input", {})
    print("  required:", {k: (v[0] if isinstance(v, list) else v) for k, v in inp.get("required", {}).items()})
    print("  optional:", {k: (v[0] if isinstance(v, list) else v) for k, v in inp.get("optional", {}).items()})
    print("  output:", spec.get("output"))
    print()
