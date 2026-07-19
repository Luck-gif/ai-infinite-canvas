import comfy_client as cc
info = cc.get_object_info()  # 一次性排查脚本
for n in ["LoadWanVideoT5TextEncoder", "WanVideoEmptyEmbeds",
          "WanVideoImageToVideoEncode", "WanVideoImageToVideoMultiTalk"]:
    spec = info.get(n)
    if not spec:
        print(n, "== MISSING ==")
        continue
    print("====", n, "====")
    inp = spec.get("input", {})
    for section, d in (("required", inp.get("required", {})), ("optional", inp.get("optional", {}))):
        print(f"  -- {section} --")
        for k, v in d.items():
            print(f"    {k}: {v}")
    print("  -- output --", spec.get("output", []))
    print()
