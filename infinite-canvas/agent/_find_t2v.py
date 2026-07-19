import comfy_client as cc
info = cc.get_object_info()  # 一次性排查脚本
keys = list(info.keys())
for pat in ["TextToVideo", "TxtToVideo", "T2V", "Text2Video", "ToVideo", "EmptyWan", "WanEmpty"]:
    hits = [k for k in keys if pat.lower() in k.lower()]
    if hits:
        print(pat, "->", hits)
print("---- all *ToVideo* ----")
print([k for k in keys if "ToVideo".lower() in k.lower()])
