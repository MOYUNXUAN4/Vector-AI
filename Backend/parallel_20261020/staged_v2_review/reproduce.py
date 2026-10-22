"""Read-only module review with in-memory synthetic inputs; never applies patches."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2] / 'parallel_20261019/staged_patches_v2_20261019'

def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

episodes = load('review_episodes', 'patch_3_warning_episodes/cluster_warning_episodes_v2.py')
rows = [dict(source_timestamp='10.0', warning_active='true', run_id='run-a', platform_level='1'),
        dict(source_timestamp='10.1', warning_active='true', run_id='run-b', platform_level='2')]
groups = episodes.group_runs(rows, .5)
print('cross_run_warning_groups', len(groups), 'run_ids_in_first', [r['run_id'] for r in groups[0]])
rows2 = [dict(source_timestamp='10.0', warning_active='true'),
         dict(source_timestamp='10.1', warning_active='false'),
         dict(source_timestamp='10.2', warning_active='true')]
print('explicit_clear_warning_groups', len(episodes.group_runs(rows2, .5)))

profile = load('review_profile', 'patch_4_clock_profile/piecewise_clock_profile.py')
src = 1_700_000_000 + np.arange(100) * .02
latency = np.r_[np.full(50, .005), np.full(50, .105)]
profile.load = lambda _: (src, src + latency, np.arange(100)*.02, list(range(100)))
result = profile.analyse('in_memory_100ms_latency_step_without_source_gap', .4, 5)
print('100ms_latency_step', json.dumps({k:result[k] for k in ['step_detected','max_adjacent_step_ms','latency_max_ms','segments']}))

wii = load('review_wii', 'patch_5_wii_preflight/wii_cop_preflight_v2.py')
wii.load_wii = lambda _: (np.full(50,80.), np.zeros(50), np.zeros(50), np.zeros(50))
print('wii_without_identity_center_timing_evidence', wii.audit('in_memory',50,20.,1.,1.5)['verdict'])

closure = load('review_closure', 'tools/session_closure_audit.py')
print('closure_rule_is_heuristic', 'simultaneous end timestamps do not establish receiver fault or absence of network loss')
