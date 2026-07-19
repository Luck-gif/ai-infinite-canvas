# 本地共享模型库（ComfyUI Desktop）

本机已装**原生 ComfyUI Desktop**（`comfyui 0.28.0` / PyTorch `2.10.0+cu130`，已支持 RTX 5080 Blackwell `sm_120`），运行于 `http://127.0.0.1:8188`，并通过 `--extra-model-paths-config` 挂载**共享模型库**：

- 默认 base_path：`C:\ai_comfyui_dd\models`（见 `C:\Users\17660\AppData\Roaming\Comfy Desktop\shared_model_paths.yaml` 中 `comfy.desktop_0`）
- 第二路径：`C:\Users\17660\AppData\Local\Comfy-Desktop\ComfyUI-Shared\models`

## 目录结构（生成工作流时按节点类型选对字段）
- `checkpoints/` — SDXL / FLUX / NoobAI 等整包模型（`CheckpointLoaderSimple.ckpt_name`）
- `unet/` — 分离 UNet（`UNETLoader.unet_name`，如 Wan2.2-i2v 14B）
- `text_encoders/` — **FLUX.2 [klein] 的 Qwen3-4B 文本编码器 `qwen_3_4b.safetensors` 必须置于此**（非 `clip/`）；还有 `qwen3vl_4b_fp8`、`gemma3_12B` 等
- `diffusion_models/` — FLUX.1-kontext-dev、Krea2、Ideogram4、Wan2.2（HIGH/LOW fp8 + Q4–Q8 GGUF）、LTX-2、Anima 等
- `clip/` `vae/` `loras/` `controlnet/` `upscale_models/` `ipadapter/`

## 已预装（无需下载）
- 文生图：FLUX.1-kontext-dev、NoobAI-XL-Vpred-v1.0、Krea2、Ideogram4、LTX-2、Anima
- 视频：Wan2.2 14B（HIGH/LOW fp8 + Q4–Q8 GGUF）、Wan2.2-i2v 14B、Wan2.1 14B
- 图像：Qwen-Image 2512、Qwen-Image-Edit
- 文本编码器：qwen3vl_4b_fp8、qwen3vl_8b、qwen_2.5_vl_7b、gemma3-12B
- 配套：VAE×12、LoRA×36、IP-Adapter×37

> 工作流校验器（`validate_workflow.py`）只校验节点结构；模型文件名请对照本表，确保 `ckpt_name` / `unet_name` / `clip_name` 与库中实际文件一致。
