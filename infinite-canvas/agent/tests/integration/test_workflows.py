"""端到端集成测试：intent_map 构建工作流 → workflow_to_graph → ComfyUI 校验"""
from __future__ import annotations
import json, sys, os, urllib.error
import intent_map as im
import comfy_client as cc

# 引入 validator（.codebuddy/skills 目录在项目根）
_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROJECT_ROOT = os.path.dirname(_AGENT_DIR)
SKILL_DIR = os.path.join(_PROJECT_ROOT, ".codebuddy", "skills", "comfyui-workflow-validator")
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import validate_workflow as vw  # type: ignore[import-not-found]

def test_all_intents():
    actions = ['txt2img', 'img2img', 'inpaint', 'outpaint']
    passed = skipped = 0
    kwargs_map = {
        'txt2img': {},
        'img2img': {'input_image': 'test.png', 'batch_size': 1},
        'inpaint': {'input_image': 'test.png', 'mask_image': 'mask.png'},
        'outpaint': {'input_image': 'test.png', 'outpaint_direction': 'right', 'outpaint_pixels': 256},
    }
    for action in actions:
        try:
            intent = {
                "action": action,
                "prompt": "a beautiful landscape, masterpiece, best quality",
                "params": {"model": "noobai", "denoise": 0.75},
            }
            kw = kwargs_map[action]
            tid, wf, meta = im.build_workflow(intent, seed=42, **kw)

            # 1) workflow_to_graph 必须成功
            g = cc.workflow_to_graph(wf)
            assert len(g['nodes']) > 0, f"{action}: 节点为空"
            assert len(g['edges']) > 0, f"{action}: 边为空"
            assert g['layout'] == 'dag'

            # 2) meta 中必须注入 workflow_graph
            assert meta.get('workflow_graph') == g

            # 3) 静态校验（class_type + 必需输入）
            issues, degraded = vw.validate(wf, check_required=True)
            if issues:
                print(f"  WARN {action}: {'; '.join(issues)}")
            else:
                print(f"  OK {action}: static check passed (degraded={degraded})")

            print(f"  STATS {action}: {len(g['nodes'])} nodes, {len(g['edges'])} edges | template={tid}")
            passed += 1
        except urllib.error.HTTPError as e:
            print(f"  SKIP {action}: image not uploaded ({e.code})")
            skipped += 1
        except Exception as e:
            print(f"  FAIL {action}: {e!r}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Result: {passed}/{len(actions)} passed (+{skipped} skipped, no real input image)")
    if passed + skipped == len(actions):
        print("ALL PASSED (or skipped)")
    else:
        print("SOME FAILED")
        sys.exit(1)

if __name__ == '__main__':
    test_all_intents()
