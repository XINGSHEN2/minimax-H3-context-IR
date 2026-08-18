# Input assets

Create one folder per generation request:

```text
assets/case_001/
├── images/
├── videos/
├── audio/
└── request.json
```

Put real media files in the matching folders, then update `request.json` so
every `uri` is the absolute host path under
`/home/mx/shenxing/minimax-H3-context-IR/assets/`. The project directory is
mounted at the same absolute path inside the runtime container.

Do not commit merchant media, API keys, or generated outputs.
