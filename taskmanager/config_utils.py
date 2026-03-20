from copy import deepcopy
from pathlib import Path


DEFAULT_CONFIG = {
    "cluster": {
        "host": None,
        "remote_base_path": None,
    },
    "paths": {
        "template_path": None,
        "input_dir": None,
        "output_dir": None,
    },
    "input_format": {
        "metadata_filename": "pipeline_metadata.json",
        "folder_levels": [
            {"name": "terrain_index", "prefix": "terrain_"},
            {"name": "rotation_degree", "prefix": "rotatedTerrain_", "suffix": "_deg"},
        ],
        "case_name_template": "case_{case_num:03d}_{terrain_index}_{rotation_degree:03d}deg",
    },
    "openfoam": {
        "end_time": 20000,
        "write_interval": 5000,
        "run_stage_mesh": "mesh",
    },
    "hpc": {
        "account": None,
        "partition": None,
        "nodes": 1,
        "ntasks": 128,
        "walltime": "10:00:00",
        "openfoam_version": None,
    },
    "parallel": {
        "mesh_workers": 4,
        "fetch_workers": 2,
    },
    "timeouts": {
        "job_status_ssh": 15,
        "remote_list_timesteps": 10,
        "fetch_postprocessing": 120,
        "fetch_log_list": 10,
        "fetch_single_log": 60,
        "fetch_last_timestep": 300,
    },
    "run_cases": {
        "n_cases_to_mesh": 4,
        "n_parallel_workers": 4,
        "auto_submit": True,
    },
    "monitor_jobs": {
        "check_interval_minutes": 120,
        "max_iterations": None,
    },
}


def deep_update(base, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_yaml_config(config_path):
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to read task manager config files. "
            "Install it with: pip install pyyaml"
        ) from exc

    with open(config_path, "r") as f:
        loaded = yaml.safe_load(f) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a YAML mapping at the root: {config_path}")

    return loaded


def resolve_config_path(config_path=None):
    if config_path:
        return Path(config_path).expanduser()
    cwd_config = Path.cwd() / "taskmanager_config.yaml"
    if cwd_config.exists():
        return cwd_config
    return Path(__file__).resolve().parent / "taskmanager_config.yaml"


def load_runtime_config(config_path=None):
    selected_config_path = resolve_config_path(config_path)
    config = deepcopy(DEFAULT_CONFIG)
    loaded_config_path = None

    if selected_config_path.exists():
        file_config = load_yaml_config(selected_config_path)
        deep_update(config, file_config)
        loaded_config_path = selected_config_path

    return config, loaded_config_path


def required_path(config, key):
    value = config.get("paths", {}).get(key)
    if not value:
        raise ValueError(f"Missing paths.{key} in config")
    return value


def get_path_value(cli_value, config, key):
    if cli_value:
        return cli_value

    value = config.get("paths", {}).get(key)
    if value:
        return value

    raise ValueError(
        f"Missing value for {key}. Set paths.{key} in YAML or pass --{key.replace('_', '-')}"
    )