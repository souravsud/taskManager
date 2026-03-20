# taskManager

OpenFOAM case generation, meshing, HPC submission, and job monitoring toolkit.

## Installation

```bash
pip install git+https://github.com/souravsud/taskManager.git
```

Or clone and install locally:

```bash
pip install .
```

## Usage

All functionality is exposed through `OpenFOAMCaseGenerator`. Point it at your template, input metadata, and output directory, and it handles the rest.

```python
from taskmanager import OpenFOAMCaseGenerator

generator = OpenFOAMCaseGenerator(
    template_path="./template",
    input_dir="/path/to/downloads",
    output_dir="/path/to/openFoamCases",
    config_path="taskmanager_config.yaml",  # optional, falls back to defaults
)

# 1. Generate case folders from template + metadata
generator.generate_all_cases()

# 2. Mesh cases in parallel (reads n_workers from config)
cases_to_mesh = generator.list_cases_by_status(mesh_status="NOT_RUN")
generator.mesh_cases_parallel(cases_to_mesh)

# 3. Copy meshed cases to HPC and submit jobs
for case in generator.list_ready_cases():
    generator.copy_and_submit(case)

# 4. Check job status
for case in generator.list_cases_by_status(submitted=True):
    status = generator.update_job_status(case)
    print(case.name, status)

# 5. Fetch results back from HPC
for case in generator.list_cases_by_status(submitted=True):
    generator.fetch_case_results(case)
```

## Configuration

Copy `taskmanager_config.yaml` to your project directory and edit the required fields:

```yaml
paths:
  template_path: ./template
  input_dir: /path/to/downloads
  output_dir: /path/to/openFoamCases

cluster:
  host: your-cluster-hostname
  remote_base_path: /path/to/remote/cfd_data

input_format:
  metadata_filename: pipeline_metadata.json
  terrain_folder_prefix: terrain_
  rotation_folder_prefix: rotatedTerrain_
  rotation_folder_suffix: _deg
  case_name_template: "case_{terrain_index}_{rotation_degree:03d}deg"

hpc:
  account: your-hpc-account
  ntasks: 128
  walltime: "10:00:00"
```

The config file in the current working directory is loaded automatically; pass `config_path=` to override.

## Status tracking

Each case folder contains `case_status.json`:

```json
{
  "mesh_status": "DONE",
  "mesh_ok": true,
  "copied_to_hpc": true,
  "submitted": true,
  "job_id": "123456",
  "job_status": "RUNNING"
}
```

`mesh_status` values: `NOT_RUN`, `DONE`, `FAILED`, `ERROR`  
`job_status` values: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMEOUT`
