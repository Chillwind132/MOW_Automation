# Diagnostics

Current documentation: [start here](../docs/INDEX.md).

Optional tools, separate from normal hosting and record-only recording. Run scripts
from this folder by absolute path, or from the project root as shown below.

| Tools | Purpose |
| --- | --- |
| `memory_diagnostics.py`, `heap_ownership.py`, `resource_census.py` | Memory/address-space and resource observations |
| `allocation_trace.py`, `.js`, `.c`, `summarize_allocations.py` | Allocation tracing and summaries |
| `audio_data_census.py`, `audio_data_watch.py`, `engine_owner_watch.py` | Targeted ownership and audio observations |
| `renderer_present_probe.py`, `texture_descriptor_probe.py` and `.js` | Rendering and texture investigations |
| `headless_music_patch.py`, `headless_texture_patch.py` | Explicit reversible archive/preference changes |
| `stability_loop.py`, `stress_supervisor.py`, `overnight_investigation.py` | Controlled AI campaigns; can launch/stop games and change test settings |
| `cleanup_experiment.py` | Explicit experimental native cleanup, outside normal hosting |
| `capture_combat_log.py` | Combat-log capture |
| `ai_feasibility_probe.py` | AI source capture and optional bounded external reads comparing native code with the reference dump; no game mutations |
| `tactical_map.py`, `AnalyzeTactical.java`, `tactical_observe.py`, `tactical_trace.py` | Tactical AI research: external reads, read-only Ghidra mapping and explicit temporary observation hooks; see [findings](../docs/TACTICAL_AI_MAPPING.md) |
| `compare_memory_runs.py`, `plot_memory_comparison.py` | Offline comparison/reporting |

Inspect a tool's options first, for example:

```powershell
py diagnostics/headless_music_patch.py --help
py diagnostics/stress_supervisor.py --help
```

These utilities keep data and new evidence in project-root `data/` and `validation/`.
`reference/` holds the executable dump used to verify diagnostic signatures.
`_bootstrap.py` locates active host imports for direct script execution.

Historical findings: [memory investigation](../archive/notes/OVERNIGHT_MEMORY.md),
[repair experiments](../archive/notes/MEMORY_REPAIR.md), and
[stability loop](../archive/notes/STABILITY_LOOP.md). Those reports describe past
runs; any root-level diagnostic script paths now need the `diagnostics/` prefix.
