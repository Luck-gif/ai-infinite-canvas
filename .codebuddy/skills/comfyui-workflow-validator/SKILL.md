---
name: comfyui-workflow-validator
description: This skill should be used when building, validating, or submitting ComfyUI workflows (the JSON payload POSTed to /prompt) to prevent silent 400 errors from missing required inputs (e.g. SaveImage filename_prefix) or non-existent node class_types. It validates a workflow JSON against a live ComfyUI instance (/object_info schema + required-input check) and optionally submits it. Use it whenever a workflow JSON is generated, before handing it to ComfyUI.
---

# ComfyUI 工作流校验器

## Purpose
Validate a ComfyUI workflow JSON (the `prompt` payload POSTed to `/prompt`) **before** submission, catching two failure classes that otherwise surface only as opaque HTTP errors at runtime:
1. **Unknown node `class_type`** — node type not registered in the running ComfyUI.
2. **Missing required inputs** — e.g. `SaveImage` requiring `filename_prefix` in newer ComfyUI; `CLIPTextEncode` requiring `text`/`clip`. This specific bug (missing `filename_prefix`) caused a real 400 during integration and is now caught statically.

## When to use
- After the agent (or any generator) emits a ComfyUI workflow JSON (txt2img / img2img / video / custom).
- Before calling the live ComfyUI `/prompt` endpoint.
- When a `/prompt` returns 400 and the error body is unclear.

## How to use
The validator is `scripts/validate_workflow.py` (standard library only — no pip dependencies).

Validate a workflow file (static schema + required-input check):
```bash
python scripts/validate_workflow.py path/to/workflow.json
```
Also submit to the live ComfyUI for the definitive end-to-end check:
```bash
python scripts/validate_workflow.py path/to/workflow.json --submit
```

### Configuration
- `COMFYUI_URL` env var overrides the target (default `http://127.0.0.1:8188`, the local native ComfyUI Desktop).
- The script auto-retries `/object_info` (the ComfyUI Desktop manager proxy intermittently returns 502) and, on persistent failure, degrades to a core-node allowlist so validation still runs.

### What it checks
1. Each node's `class_type` exists in the live ComfyUI (`/object_info`).
2. Each node provides all `input.required` fields from the node's schema — catches the `SaveImage`/`filename_prefix` class of bug without needing a submit.
3. With `--submit`: POSTs to `/prompt`; a 400 response body is printed verbatim for diagnosis.

## Reference
- `references/shared_models.md` — local shared model library layout (`C:\ai_comfyui_dd\models`) and pre-installed models, so generators pick correct `ckpt_name` / `unet_name` / `clip_name` values.
- ComfyUI HTTP API: `/object_info` (node schemas), `/prompt` (submit), `/history/{id}` (poll for completion).
