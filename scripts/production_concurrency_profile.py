"""Explicit, versioned opt-in capacity; never changes legacy execution defaults."""
import copy
import json
from pathlib import Path

SCHEMA = 'sermon-production-concurrency-profile-v1'
PROFILE = {'schemaVersion': SCHEMA, 'totalCodexSlots': 24, 'businessCodexSlots': 23,
           'supervisorSlots': 1, 'maxBranches': 4, 'sourceASRWorkers': 4,
           'sourceJudgeWorkers': 8, 'maxActiveLocales': 3, 'studyBranches': 2,
           'backASRBatchSize': 8, 'cpuWorkers': 4, 'layer2GroupWorkers': 23,
           'busyWaitSeconds': 180}


def profile_v1():
    return copy.deepcopy(PROFILE)


def validate_profile(value):
    if type(value) is not dict or set(value) != set(PROFILE) or any(
            type(value[k]) is not type(v) or value[k] != v for k, v in PROFILE.items()):
        raise ValueError('invalid_production_concurrency_profile')
    return copy.deepcopy(value)


def load_profile(path):
    return validate_profile(json.loads(Path(path).read_text()))
