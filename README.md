# MiniMax-H3 Context-IR Agent

An independent Codex SDK project that uses GLM as the agent LLM, compiles multimodal requests into validated Context-IR, and packages the result for MiniMax-H3.

## Project layout

```text
backend/     Python Agent, perception providers, Context-IR compiler, Web API
frontend/    Independent browser interface
assets/      Uploaded/request media grouped by case
skills/      Official MiniMax-H3 Skills
deploy/      Container launchers and local environment templates
outputs/     Generated Context-IR, H3 Prompt, audit, and request files
```

The root `agent.py`, `context_ir.py`, and `perception.py` files remain as
backward-compatible entry points; active implementations live in `backend/`.

## Architecture

```text
user intent + asset manifest + optional media_analysis.v1
                         |
                    Codex SDK
                         |
              GLM Responses provider
                         |
       official MiniMax-H3 SkillInput(s)
                         |
                   Context-IR JSON
                         |
     task adapter + deterministic prompt audit
                         |
           H3 prompt + service request JSON
```

The default perception provider is Gitee's OpenAI-compatible
`Qwen3-VL-32B-Instruct`. It analyzes images and videos through the local
observations from videos into `media_analysis.v1`. Audio assets are explicitly
marked unsupported by the visual provider and remain available for a later
audio-analysis provider. Supplying an existing `perception` object skips the
VLM call, so the provider remains replaceable.

## Run

Put each request's media under `assets/case_NNN/` using the `images`, `videos`,
and `audio` subfolders. Start from `assets/case_001/request.json`; media paths
must use the absolute `/home/mx/shenxing/minimax-H3-context-IR/assets/...`
form so they resolve identically on the host and in the container.

Prepare an input JSON from `examples/request.example.json`, then run:

```bash
cd /home/mx/shenxing/minimax-H3-context-IR
bash deploy/run.sh examples/request.example.json
```

For the included case template:

```bash
bash deploy/run.sh assets/case_001/request.json
```

## Web studio

Start the independent frontend and upload API from the same project folder:

```bash
bash deploy/web.sh
```

Then open `http://<aigc-host>:38080`. The interface accepts natural-language
requirements and drag-and-drop media, assigns image/video/audio numbers,
captures each asset's intended role, creates a new `assets/case_NNN`, and runs
the same Codex Agent pipeline. Generated files remain under `outputs/` and are
available in Context-IR, H3 Prompt, and audit tabs.

The interface is an independent implementation inspired by the interaction
patterns of the MIT-licensed `ComfyUI-MiniMaxH3-Prompt-Writer`; it does not
depend on ComfyUI or copy its runtime integration.

Results are written to a timestamped folder under `outputs/` unless `--output-dir` is provided.
The normalized visual evidence is saved as `media_analysis.json`; model
reasoning text and Base64 image payloads are never written to outputs.
Each successful run now includes `h3_prompt_audit.json`. Base tasks
(`T2VA/I2VA/FL2VA/L2VA`) use the official three-section structure, while
`Ref2VA` uses the official six-section structure. H3 reference labels are
derived deterministically from final condition order.

Check the Codex runtime and GLM gateway without running an Agent turn:

```bash
bash deploy/run.sh --preflight-only
```

Use an official style Skill when relevant:

```bash
bash deploy/run.sh request.json --style-skill minimalist-product-ad-generator
```

Validate without calling GLM:

```bash
bash deploy/run.sh --validate-only outputs/<run>/context_ir.json
```

## Runtime configuration

Visual perception defaults to the locally deployed Qwen3-VL-32B FIFO service:

- `CONTEXT_IR_VLM_PROVIDER`: default `local-qwen3-vl-32b`
- `YIWU_VLM_BASE_URL`: default `http://127.0.0.1:9012`
- `YIWU_VLM_MODEL`: default `Qwen3-VL-32B-Instruct`
- `CONTEXT_IR_VIDEO_FPS`: default `2`
- `CONTEXT_IR_VIDEO_MAX_FRAMES`: default `256`
- `CONTEXT_IR_VLM_TIMEOUT_SECONDS`: default `1800`

As with the `yiwu_codex` launcher, runtime values may be kept in a local env
file. Copy `deploy/context_ir.env.example` to `deploy/context_ir.env`, add the
key there, and keep that file uncommitted. An already exported environment
variable takes precedence over the file.

Local image and video absolute paths are submitted directly to the service.
The service copies each input into its FIFO task directory and uses Qwen's
native video utility to decode chronological frames; audio tracks are not
analyzed. The previous `gitee-qwen3-vl` contact-sheet adapter remains available
as an explicit provider fallback.

The Codex Agent uses GLM-5.2 through the remote LiteLLM Responses API:

- `GLM_MODEL` default: `GLM-5.2`
- `GLM_PROVIDER_ID` default: `glm`
- `GLM_RESPONSES_BASE_URL` default: `http://127.0.0.1:38041/v1`
- `GLM_HTTP_HOST` default: `litellm-poc.pgw.metax-tech.com`
- `OPENAI_API_KEY`: required LiteLLM bearer key
- wire API: `responses`

Keep the real LiteLLM key only in the ignored `deploy/context_ir.env` file.
Because `aigc` cannot resolve the LiteLLM intranet hostname, Windows supplies
network access through an SSH reverse tunnel:

```powershell
Start-Process ssh -ArgumentList @(
  "-N", "-T",
  "-o", "ExitOnForwardFailure=yes",
  "-o", "ServerAliveInterval=30",
  "-o", "ServerAliveCountMax=3",
  "-R", "38041:litellm-poc.pgw.metax-tech.com:80",
  "aigc"
) -WindowStyle Hidden
```

`GLM_HTTP_HOST` preserves the original virtual-host routing while Codex calls
the tunnel through `127.0.0.1:38041`.

The Docker **container** is named `minimax_h3_context_ir`. By default the
launcher reuses the existing **image** `yiwu_codex:latest` only as the Codex
SDK runtime; these are deliberately different concepts. Override the image
with `CONTEXT_IR_IMAGE`, for example:

```bash
CONTEXT_IR_IMAGE=minimax-h3-context-ir:latest bash deploy/run.sh request.json
```

The mounted project remains independent and does not depend on
`/home/mx/shenxing/yiwu_codex`.

The LiteLLM Responses gateway is an external prerequisite. The runner does not
start or manage it.
