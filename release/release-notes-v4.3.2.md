SHTUCodeProxy v4.3.2

Model-level multimodal capability guard release.

Fixes:
1. Added per-model `supports_image`, `supports_audio`, and `supports_video` capability flags in GUI, saved config, and headless Linux config files.
2. GPT-5.5 and qwen-instruct default to image-capable. GLM and DeepSeek chat routes default to text-only.
3. Incompatible models now return a normal assistant message when users send unsupported image, audio, or video input instead of forwarding the request upstream and risking a broken app conversation.
4. The guard works for both Anthropic Messages (`/v1/messages`) and OpenAI Responses (`/v1/responses`), including streaming and non-streaming requests.
5. Image-capable routes continue to pass image content through to compatible upstreams. File/document passthrough keeps the existing behavior and is not gated by these switches.
6. Manually edited boolean config values such as `"supports_image": "false"` now parse correctly. Older `supports_multimodal` configs are read as a backward-compatible image-support hint.
7. Fixed a Codex Responses regression where the final modality sanitizer inspected ordinary tool JSON Schema `type` values and returned HTTP 500, causing repeated `Reconnecting...` failures.
8. Historical unsupported image/audio/video parts are stripped before upstream calls, while the current text-only turn remains usable.
9. Responses streams that only provide final text in `response.completed.output` are converted back into Anthropic text events for Claude Code compatibility.

Validation:
- `python -m json.tool headless-config.example.json`
- `python -m py_compile config_store.py proxy.py pyqt_gui.py smoke_test.py`
- `python smoke_test.py`
- Real upstream qwen-instruct image URL and base64 image probes through `/v1/messages`
- Real upstream qwen-instruct base64 image probe through `/v1/responses`
- Real upstream GLM text request after blocked multimodal requests
- Real `codex exec` against the rebuilt Windows EXE for `glm-chat`, `deepseek-chat`, and `qwen-instruct`
- Real `claude -p` against `/v1/messages` for `glm-chat`, `deepseek-chat`, and `qwen-instruct`
- Direct `/v1/messages` and `/v1/responses` tests for blocked image input followed by a clean text-only turn

Large assets:
Windows EXE/ZIP, Linux binaries, headless CLI zip, python-launcher tar.xz, source package, README, and checksums are attached to the GitHub Release.
