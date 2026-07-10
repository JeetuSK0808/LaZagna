# YAML v2 schema fix (optimizer config emitter)

## Symptom
Every optimizer trial (columns / sampler / 2D-vs-3D) failed *instantly* (pruned with no flow
run). The error, surfaced from the trial's stored `err`:

```
File ".../lazagna/yaml_file_processing_v2.py", line 129, in load_param_ranges_v2
    raise ValueError(
ValueError: 'experiment_name' is required in every setup file. Add it to the top level of your YAML.
```

## Root cause
The lab moved `lazagna/main.py` onto a new YAML processor
(`yaml_file_processing_v2.get_run_params_from_yaml_v2`, commit *"Updated YAML configuration"*).
v2 expects a **nested** config and requires a top-level `experiment_name`:

```yaml
experiment_name: "..."          # REQUIRED (no default)
grid: {width_3d, height_3d, width_2d, height_2d, channel_width}
architectures: [{type, arch_file}]
benchmarks: {directory, is_verilog}
placement: {algorithm}
seeds: {mode, value}
switch_block_3d: {connectivity, connection_type, switch_name, segment_name, location_pattern, ...}
interlayer_delay: {vertical_connectivity, delay_ratio, base_delay_switch, update_arch_delay, switch_pairs}
advanced: {additional_vpr_options}
```

The optimizer's `ExperimentOptions.to_dict()` (`lazagna_arch_model.py`) still emitted the **old
flat** schema (`width`, `type_sb`, `percent_connectivity`, `cur_loop_identifier`, ...) that the
previous `yaml_file_processing.py` consumed. v2 rejects it outright, so no trial ever ran.

(v2 deep-merges the user config over `setup_files/defaults.yaml`, replacing lists/scalars and
recursing into dicts, so only `experiment_name` is strictly required — but the emitter writes a
full config anyway.)

## Fix (2 files)
1. `lazagna_arch_model.py`
   - `ExperimentOptions.to_dict()` rewritten to emit the nested v2 schema.
   - `run_lazagna` now injects the generated arch into `architectures[0].arch_file`
     (v2 has no top-level `arch_file`).
2. `campaign/phase_hardblock.py`
   - `CONFIG_TMPL` (the phase-4 CLI setup file) rewritten from flat to nested v2.

Phases 1/2/3 all drive the flow through `run_lazagna`, so `to_dict` is the single fix point for
them. Phase 0 (smoke) uses the lab's own `setup_files/simple_test.yaml`, already v2.

## Verification (local, before handoff)
- `_run_one` on clma (connectivity, 30x30 cw100): completed in ~66 s, **CPD 8.62 ns / WL 24956**
  (matches the known-good laptop range ~8.7 ns / ~24662).
- `main.py -f setup_files/simple_test.yaml` (phase-0 smoke): exit 0.
- Grep confirmed no remaining flat-schema YAML construction in `campaign/` or the optimizer files.

## Cluster impact
The container clones the fork and the campaign drives the optimizer, so the fork must carry the
updated `lazagna_arch_model.py` (and the new `campaign/phase_hardblock.py`). See UPLOAD_MANIFEST.md.
