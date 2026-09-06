# DGX resource and recovery audit — request #1060

Measured on the live DGX Spark on 6 September 2026, around 17:45 UTC. The host
had 124,609 MiB total RAM and 52,731 MiB available (about 42%), with no swap.
Voice Director independently reported 51.2 GiB available and pressure tier 0.
Memory exhaustion was not the cause of that afternoon's missing Nabu speech.
Output routing and music restoration defects are covered in
[the continuity audit](station-continuity-1060.md).

The NVIDIA GB10 reported driver 580.159.03, CUDA 13.0, 96% GPU utilization,
71°C and about 40 W. A later sample was 87%, 66°C and 37.44 W. These are short
samples during real work, not sustained benchmarks. GB10 uses unified memory;
`nvidia-smi` reported dedicated VRAM totals as unsupported. The implementation
preserves that as unknown and uses host available memory for pressure decisions.

| Workload | Observed allocation | Ownership and decision |
| --- | --- | --- |
| Gemma 31b | About 26.5 GiB GPU process allocation | Station tint writer; keep while active or queued. |
| Gemma e2b | About 2.8 GiB GPU process allocation | Station writer; keep while active or queued. |
| XTTS | About 2.1 GiB GPU allocation, 4.3 GB RSS | Both selected presenters; keep while recording or selected on air. |
| Nomic embeddings | About 559 MiB GPU allocation | Neural broadcast recall and shared consumers; excluded from station-model eviction. |
| Separate llama-server | About 7.6 GiB GPU allocation | `/proc/PID/cgroup` identified `reachy-gateway-watchdog.service`, port 8088. It is outside station ownership. |
| ComfyUI | About 351 MiB GPU allocation, 2.4 GB RSS | Empty running and pending queues at inspection; release model cache after verified idle periods, without killing its service. |
| spark-agent container | About 2.53 GiB | Station orchestration and playback. |
| Home Assistant / Piper / Whisper | About 390 / 482 / 723 MiB | Device control and voice infrastructure; retained. |
| Open WebUI / Searx | About 628 / 300 MiB | Other user services; retained. |

GPU process allocation, container memory and process RSS overlap and must not
be added into a total. Model metadata sizes also differ from loaded allocations.
No unrelated service was stopped during the audit, and no model was evicted
just because its allocation was large. Existing claims that every XTTS instance
necessarily occupies 23 GB do not describe this measured instance.

The largest demonstrated scheduling loss was writer queue time: some jobs waited
roughly 670 seconds before 0.7–13 seconds of inference. Per-model admission now
bounds station jobs and gives the response catalogue a separate bounded lane.
Recording permits allow independent engines to work concurrently, with live
capacity reserved while broadcasting. The two current presenters both use XTTS,
so their preparations serialize on that engine. Queue-inclusive generation
ratios are explicitly not presented as the hardware's physical throughput limit.

`GET /api/coordinator/resources` now exposes a cached task-manager view: actual
host memory, bounded NVIDIA telemetry, loaded Ollama models and ownership,
active and queued writer jobs, recording booths, recent engine use and the
image queue. Sampling runs every 45 seconds outside the playback loop. GPU
subprocesses have a three-second timeout; HTTP probes are bounded. A read of
the endpoint performs no cleanup or model inference.

The guard records its decisions atomically in `data/resource_history.json`,
retaining the latest 120 observations. It distinguishes healthy, constrained,
critical and unavailable telemetry. High GPU utilization alone does not justify
an unload. Two successive samples below 24 GiB can release only ComfyUI's model
cache, after at least five minutes of observed idle time and an immediate empty
queue recheck, at most once per ten minutes. Failed and skipped actions retain
their reason; they do not receive successful-repair credit.

Automatic engine cleanup now checks active live and preparation work. The idle
clock preserves the selected on-air cast engine. XTTS revival only considers
known station writer models when no admitted writer job exists; shared or
unknown models are excluded. Missing pressure telemetry cannot trigger an
eviction. A wedged XTTS retains its failure evidence while recording is active
and retries its bounded repair after the work finishes. Director HTTP failures
are no longer reported as successful termination or deployment.

Resource evidence is attached to the coordinator brief and actual closed-hour
reports. Each hour receives compact memory ranges, pressure-tier counts and
attempted actions from its retained samples, including failures earlier in the
hour. Loaded models, image-queue activity and recent-engine observations remain
in the bounded history. Reports state the sampled interval and retention limits;
intermittent observations do not establish uninterrupted health. The existing neural outcome index therefore receives measured resource
context together with what really aired and whether the hour improved. Raw
resource samples never masquerade as completed broadcast outcomes. Under
unresolved pressure, the report also carries the ownership question for the
operator instead of guessing which unrelated application can be stopped.

Focused regressions verify unknown telemetry, GB10 N/A fields, healthy-memory
retention, sustained pressure and idle checks, active recording protection,
director failure handling, deferred repair, durable evidence, and an image job
arriving between the first observation and the cleanup recheck. Live deployment
verification is recorded in the consolidated inbox audit.

After deployment, the live resource endpoint returned 121.69 GiB total and
48.16 GiB available, with GB10 at 41% utilization and 65°C. A later idle sample
reported 46.93 GiB available and 0% utilization. Both decisions were healthy,
with no cleanup action. The loaded model list correctly classified the two
Gemma models as station-owned and shared Nomic embeddings as outside eviction
ownership. Live preparation appeared as one XTTS booth; the monitor accumulated
durable observations without adding an inference job. Twenty-one focused
resource tests include the final neural-summary retention check.
