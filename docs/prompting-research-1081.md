# #1081 — how to use system prompts and local LLMs for the crystal, and what changed

Request (2026-09-08): *"do an online investigation into how i can best use system prompts and LLMs
to accomplish my goal and adjust system2 to properly utilize the available LLMs to get the desired
result."* The goal, in your words across the night: every line through the crystal as a rap bar —
dense rhyme, the writer's own lexicon, meaning kept exactly, nothing repeated inside an hour — graded
by the deterministic evaluator and re-asked with its faults. Models: gemma4:31b (deep, one runner)
and gemma4:e2b (fast) on Ollama; one real tint prompt is ~16,000 characters.

## What the research says, and what was done with it

| finding | source | what it means here | done |
|---|---|---|---|
| **The runner reuses its KV cache only for an identical prompt prefix.** llama-server matches a new request to a slot by prefix similarity (default 50 %) and re-processes only the tokens after the shared part; a repeated request drops from a full prompt evaluation to "1 token". A prefix that changes at its start forces a full re-evaluation. | [llama.cpp discussion #13606, KV cache reuse tutorial](https://github.com/ggml-org/llama.cpp/discussions/13606); [llama.cpp discussion #8860](https://github.com/ggml-org/llama.cpp/discussions/8860); Ollama's cache is strictly prefix-based ([Ollama in Action, prompt caching](https://leanpub.com/read/ollama/prompt-caching)) | The tint's frame put the road line *before* the world and the passages, and the five passages were **re-sampled on every ask** (`crystal_material`, random by design), so no two asks shared a prefix and the 31b runner re-read ~4k tokens of world and passages each time. | **Yes.** `crystal_prompts._frame` now orders rules → strength → contract rules → world → passages → road → register → per-line evidence; `crystal_material(stable=True)` holds one passage sample for 20 minutes (`CRYSTAL_MATERIAL_WINDOW`). `frame_prefix()` names the shared part; tests pin that it is identical across roads and lines. Measure: `prompt_eval_ms` vs `eval_ms` in `data/model_calls.jsonl`. |
| **Two decode slots raise total throughput.** Single-stream decode is memory-bandwidth bound; batched decode shares one weight read across sequences. Memory scales with slots × context (four slots at 32k reserve KV as if one 128k sequence). | [Ollama parallel requests](https://www.glukhov.org/llm-performance/ollama/how-ollama-handles-parallel-requests/); [Ollama performance tuning](https://eastondev.com/blog/en/posts/ai/20260410-ollama-performance-optimization/); [ollama#17666 (batched decode)](https://github.com/ollama/ollama/issues/17666) | Every runner here was `-np 1`; the app already refused a second concurrent ask per model because the measurement (35 s span for 31.5 s of compute) showed no gain — which was the runner's setting, not the hardware. | **Yes.** `OLLAMA_NUM_PARALLEL=2` (systemd drop-in `zz-parallel.conf`, restarted 11:59Z, runners now `-np 2`), `OLLAMA_LANES=2` in compose, `_ollama_lane` permits and the tint/station caps follow it. |
| **Gemma has no system role.** The chat template is `<start_of_turn>user … <end_of_turn><start_of_turn>model`; a "system" message is merged into the first user turn. Instructions belong in the user turn, and stay effective there. | [Prompting Guide: Gemma](https://www.promptingguide.ai/models/gemma); [transformers#40849](https://github.com/huggingface/transformers/issues/40849); [hub-docs#1836](https://github.com/huggingface/hub-docs/issues/1836) | The crystal already sends one composed prompt; nothing is lost by the missing role. It does mean the *order inside that one message* is the only structure the model sees — hence the prefix work above. | Nothing to change; documented. |
| **Decide the rhyme word before the line.** "Last Word First" prepends the landing word to each verse and lets the model write towards it: rhyming precision 11 % → 56 % (→ 90 % with rhyme-aware decoding) on T5; reverse-order rhyme modelling is the same idea in DeepRapper. These are fine-tuning results, not prompts. | [Encoder-decoder framework with LWF (2405.05176)](https://arxiv.org/html/2405.05176v1); [DeepRapper (2107.01875)](https://arxiv.org/pdf/2107.01875); [PoeLM (2205.12206)](https://arxiv.org/pdf/2205.12206) | The prompt analogue is a planning order: pick the landing pair first, from the source's own facts or the retrieved WORD OPTIONS (the CMUdict endings the index already supplies), then write to land on it. | **Yes.** Rule 3 of the frame now says so. Measure: the grader's rhyme-evidence refusals per attempt in the learner ledger. |
| **Repair beats blind resampling for constrained rewriting.** Self-Refine reaches its result with ≤ 4 samples where best-of-n used 16–32; the repair-vs-resample choice is model-dependent and is an exploration/exploitation trade. | [Self-Refine (2303.17651)](https://arxiv.org/pdf/2303.17651); [Iterative self-repair across model scales (2604.10508)](https://arxiv.org/html/2604.10508v1) | The station already repairs with the grader's faults (two/three asks per line under the hold). What was missing was that a *new* preparation of the same line started from nothing. | **Yes (#1082).** `tint_prior_lesson` puts the earlier refusals' faults and refused wording on the first ask of a line seen before; the strike cap ends the asks that never move. |
| **Style transfer with small models keeps meaning best when the prompt separates the content contract from the style instruction, uses register/pattern descriptions rather than long rule prose, and reranks candidates on content preservation.** | [Prompt-and-Rerank (2205.11503)](https://arxiv.org/pdf/2205.11503); [Register analysis for arbitrary style transfer (2505.00679)](https://arxiv.org/html/2505.00679); [LLM-based TST: have we taken a step forward?](https://www.researchgate.net/publication/389643037_LLM-based_Text_Style_Transfer_Have_We_Taken_a_Step_Forward) | The crystal's SOURCE CONTRACT (names, numbers, questions, negation) is that separation; the paper's print register (#1075) is the register description; the deterministic grader is the reranker. The remaining gap is prompt length — 16 KB of rules is more than a 2B–30B model reads evenly. | Partly: the frame is reordered, not shortened. Shortening the rules to exemplars is the next prompt change and needs the prompt tests re-pinned (`PROMPT_VERSION` 5). |

## Sampling and the fast model

Gemma's published defaults for its instruction-tuned models are temperature 1.0, top-k 64, top-p 0.95;
the station sets temperature per road and `top_p` 0.9 with no `top_k`. For rhyme work a lower
temperature (0.6–0.8) with the repair loop is the safer default on the deep model; the fast model's
paper bars (16/78 accepted first pass) argue for keeping single-line roads on the deep model until the
prefix cache and the second slot are measured — then trying ads and memos on the fast lane, where a
weaker bar costs less than a queued one (see `docs/system2-capacity-1080.md`, lever 5).

## How to see whether it worked

- `data/model_calls.jsonl`: per call `prompt_eval_ms` (prefix re-read) against `eval_ms` (writing).
  Before tonight the two were of the same order on the deep model `[est]`; with the cached prefix the
  first should fall to a small fraction within the 20-minute window.
- `/api/tint` → `material.age_seconds` (the sample's age), `fault_memo` (lines seen twice),
  `coverage.refused` share (32.6 % at 06:36 CST).
- The learner ledger (`/api/orchestrator/learning`) per attempt: first-pass acceptance per road.
- `/api/dj/pipeline` "answered · … working, … waiting" per model call.

## Recommended on the host, with the evidence

- `OLLAMA_NUM_PARALLEL=2` — done; do not go to 4 on this box: KV memory is slots × context and the
  deep model already holds 2 × 32k.
- Keep `OLLAMA_CONTEXT_LENGTH` at 32768; the prompt is ~4k tokens and a longer context only costs
  memory per slot.
- Leave `OLLAMA_KEEP_ALIVE` at 2 h: a model unload throws the prefix cache away with it.
