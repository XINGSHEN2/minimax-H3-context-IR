# GLM 5.3 two-stage case1.1 experiment

## Configuration

- Model: `sha/GLM-5.3`
- Endpoint: LiteLLM gateway Chat Completions
- Transport: streaming SSE with usage capture
- Per-call maximum: 16,384 tokens
- Proposed stages: frozen shot plan, then H3 prompt compilation
- Dataset: `1.1 品牌大片与影视内容`, case1 through case5

## Result

The gateway accepted streaming requests and returned reasoning deltas, but the
planner produced no answer text before exhausting the per-call limit.

- Case 2, thinking enabled: 16,385 reasoning tokens, 0 text tokens,
  `finish_reason=length`, 725.1 seconds.
- Case 1, thinking disabled: 16,385 reasoning tokens, 0 text tokens,
  `finish_reason=length`, 623.6 seconds.
- Case 2, thinking disabled and JSON response format omitted: 16,384 reasoning
  tokens, 0 text tokens, `finish_reason=length`, 747.7 seconds.

The five-case batch was stopped after reproducing the same gateway behavior so
that it would not spend roughly another hour generating no usable text.

## Conclusion

Splitting planning and H3 compilation gives each answer an independent output
budget, but it cannot help when the model spends the entire budget on hidden
reasoning before producing the first answer token. The current gateway does not
honor `thinking: {"type":"disabled"}` for these complex requests, although a
minimal `只回复 OK` probe succeeds with that option.

Before continuing the five-case quality comparison, use one of:

1. a gateway/model setting that enforces non-thinking mode;
2. a separate reasoning-token budget below the 16,384 completion limit; or
3. much smaller planning subtasks, verified first on one case.

Failed outputs and usage evidence are retained under the corresponding
`glm53_two_stage_*` output directories.
