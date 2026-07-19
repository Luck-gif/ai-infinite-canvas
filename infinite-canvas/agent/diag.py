"""诊断原生 ComfyUI 连通性（独立脚本，避开 PowerShell 解析问题）。"""
import json
import time
import urllib.request

URL = "http://127.0.0.1:8188"


def try_get(ep: str, tries: int = 3):
    for i in range(tries):
        try:
            d = json.load(urllib.request.urlopen(URL + ep, timeout=20))
            n = len(d) if isinstance(d, dict) else "?"
            print(f"{ep}: OK ({n})")
            return d
        except Exception as e:  # noqa: BLE001
            print(f"{ep}: try {i+1} ERR {e!r}")
            time.sleep(3)
    return None


if __name__ == "__main__":
    try_get("/system_stats")
    try_get("/object_info")
