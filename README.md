# OpenFOAM Case Management - Usage Guide

## Overview
This system meshes OpenFOAM cases locally in parallel, copies them to deucalion HPC, and auto-submits jobs.

## Files
- `taskManager.py` - Core class with all functionality
- `run_cases.py` - Main script to mesh + submit cases
- `monitor_jobs.py` - Background job status monitor

## Workflow

### 1. Generate Cases
```bash
# One-time setup: generate case folders from templates
python3 generate_cases.py
```

### 2. Mesh + Submit Cases
```bash
# Mesh N cases in parallel and auto-submit to deucalion
python3 run_cases.py
```

**Settings in run_cases.py:**
- `N_CASES_TO_MESH = 4` - How many cases to process
- `N_PARALLEL_WORKERS = 4` - Simultaneous meshing operations (adjust for your CPU)
- `AUTO_SUBMIT = True` - Auto-copy and submit after meshing

**Output:**
```
Starting parallel meshing: 4 cases, 4 workers
[MESH START] case_0001_210deg
[MESH START] case_0002_045deg
...
[MESH OK] case_0001_210deg
[COPY START] case_0001_210deg -> deucalion
[COPY OK] case_0001_210deg
[SUBMIT START] case_0001_210deg
[SUBMIT OK] case_0001_210deg -> Job ID: 123456
```

### 3. Monitor Jobs (Optional)
```bash
# Run in background to check job status every 2 hours
nohup python3 monitor_jobs.py > monitor.log 2>&1 &

# Or run interactively
python3 monitor_jobs.py
```

**Settings in monitor_jobs.py:**
- `CHECK_INTERVAL_MINUTES = 120` - Poll every 2 hours
- `MAX_ITERATIONS = None` - Run forever (or set number)

**Stop monitoring:**
```bash
# If running in background
pkill -f monitor_jobs.py

# If interactive: Ctrl+C
```

## Status Tracking

Each case has `case_status.json`:
```json
{
  "mesh_status": "DONE",
  "mesh_ok": true,
  "copied_to_hpc": true,
  "submitted": true,
  "job_id": "123456",
  "job_status": "RUNNING",
  "last_checked": "2026-02-11T14:30:00"
}
```

**Status values:**
- `mesh_status`: NOT_RUN, DONE, FAILED, ERROR
- `job_status`: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, TIMEOUT

## Handling Failures

### Failed Meshing
```bash
# Check which cases failed
grep -l '"mesh_status": "FAILED"' /home/sourav/CFD_Dataset/openFoamCases/*/case_status.json

# Inspect log
cat /home/sourav/CFD_Dataset/openFoamCases/case_XXXX_YYYdeg/log.checkMesh
```

**To retry failed cases:**
- Fix the issue (mesh parameters, geometry, etc.)
- Manually set status back to NOT_RUN:
```bash
# Edit case_status.json, change "mesh_status": "NOT_RUN"
```
- Run `python3 run_cases.py` again

### Failed Jobs on HPC
Monitor script will flag these. Investigate on deucalion:
```bash
ssh deucalion
cd /projects/EEHPC-BEN-2026B02-011/cfd_data/case_XXXX_YYYdeg
cat log.simpleFoam
sacct -j <job_id> --format=JobID,State,ExitCode,Elapsed
```

## Tips

**Adjust parallel workers:**
- Your PC has 12 cores
- 4 workers = safe (leaves resources for OS)
- Can increase to 6-8 if nothing else running

**Check progress:**
```bash
# Count meshed cases
grep -l '"mesh_ok": true' /home/sourav/CFD_Dataset/openFoamCases/*/case_status.json | wc -l

# Count submitted jobs
grep -l '"submitted": true' /home/sourav/CFD_Dataset/openFoamCases/*/case_status.json | wc -l
```

**Manual operations:**
```python
from taskManager import OpenFOAMCaseGenerator

generator = OpenFOAMCaseGenerator(
    template_path="/home/sourav/CFD_Dataset/openfoam_caseGenerator/template",
    input_dir="/home/sourav/CFD_Dataset/generateInputs/Data_test/downloads",
    output_dir="/home/sourav/CFD_Dataset/openFoamCases",
    deucalion_path="/projects/EEHPC-BEN-2026B02-011/cfd_data"
)

# List ready cases
ready = generator.list_ready_cases()

# List failed cases
failed = generator.list_failed_cases()

# Check specific job
status = generator.check_job_status("123456")

# Update all job statuses
submitted = generator.list_cases_by_status(submitted=True)
for case in submitted:
    generator.update_job_status(case)
```# taskManager
