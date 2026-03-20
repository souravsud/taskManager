# taskManager

OpenFOAM case generation, meshing, HPC submission, and job monitoring toolkit.

---

## Installation

```bash
pip install git+https://github.com/souravsud/taskManager.git
```

Or clone and install locally:

```bash
pip install .
```

---

## Quickstart

```python
from taskmanager import OpenFOAMCaseGenerator

generator = OpenFOAMCaseGenerator(
    template_path="./template",
    input_dir="/path/to/downloads",
    output_dir="/path/to/openFoamCases",
)

generator.generate_all_cases()
```

---

## Usage

All functionality is exposed through `OpenFOAMCaseGenerator`.

```python
from taskmanager import OpenFOAMCaseGenerator

generator = OpenFOAMCaseGenerator(
    template_path="./template",
    input_dir="/path/to/downloads",
    output_dir="/path/to/openFoamCases",
    config_path="taskmanager_config.yaml",  # optional
)

# 1. Generate cases
generator.generate_all_cases()

# 2. Mesh cases
cases_to_mesh = generator.list_cases_by_status(mesh_status="NOT_RUN")
generator.mesh_cases_parallel(cases_to_mesh)

# 3. Submit to HPC
for case in generator.list_ready_cases():
    generator.copy_and_submit(case)

# 4. Monitor jobs
for case in generator.list_cases_by_status(submitted=True):
    status = generator.update_job_status(case)
    print(case.name, status)

# 5. Fetch results
for case in generator.list_cases_by_status(submitted=True):
    generator.fetch_case_results(case)
```

---

## Configuration

Create a `taskmanager_config.yaml`:

```yaml
paths:
  template_path: ./template
  input_dir: /path/to/downloads
  output_dir: /path/to/openFoamCases

cluster:
  host: your-cluster-hostname
  remote_base_path: /path/to/remote/cfd_data

hpc:
  account: your-hpc-account
  ntasks: 128
  walltime: "10:00:00"
```

The config file in the current working directory is loaded automatically. Use `config_path=` to override.

📘 Full configuration guide: [docs/configuration.md](docs/configuration.md)

---

## Cluster prerequisites

This toolkit communicates with the HPC cluster over SSH. Ensure passwordless SSH is configured before submitting jobs.

📘 Setup guide: [docs/ssh_setup.md](docs/ssh_setup.md)

---

## Status tracking

Each case folder contains a `case_status.json` file tracking progress.

Common values:
- `mesh_status`: `NOT_RUN`, `DONE`, `FAILED`, `ERROR`
- `job_status`: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMEOUT`

📘 Full details: [docs/status.md](docs/status.md)