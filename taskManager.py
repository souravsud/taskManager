from pathlib import Path
from shutil import copytree, ignore_patterns
from jinja2 import Template
import json
import os
import subprocess
from multiprocessing import Pool
from datetime import datetime


class OpenFOAMCaseGenerator:

    def __init__(self, template_path, input_dir, output_dir, deucalion_path=None):
        self.template_path = Path(template_path)
        self.input_root = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Deucalion remote path
        self.deucalion_host = "deucalion"
        self.deucalion_path = deucalion_path or "/projects/EEHPC-BEN-2026B02-011/cfd_data"

        # Centralized HPC defaults
        self.hpc_defaults = {
            "account": "eehpc-ben-2026b02-011x",
            "partition": "normal-x86",
            "nodes": 1,
            "ntasks": 128,
            "walltime": "10:00:00"
        }

    # --------------------------------------------------
    # CASE DISCOVERY
    # --------------------------------------------------

    def find_cases(self):
        case_info = []

        for root, dirs, files in os.walk(self.input_root):
            if 'pipeline_metadata.json' not in files:
                continue

            metadata_path = Path(root) / 'pipeline_metadata.json'
            with open(metadata_path) as f:
                metadata = json.load(f)

            case_path = Path(root)
            rotation_folder = case_path.name
            terrain_folder = case_path.parent.name

            terrain_index = None
            location = None
            if terrain_folder.startswith('terrain_'):
                parts = terrain_folder.split('_')
                if len(parts) >= 2:
                    terrain_index = parts[1]
                    if len(parts) >= 6:
                        location = f"{parts[2]}.{parts[3]} {parts[4]}.{parts[5]}"

            rotation_degree = None
            if rotation_folder.startswith('rotatedTerrain_') and rotation_folder.endswith('_deg'):
                degree_part = rotation_folder[len('rotatedTerrain_'):-len('_deg')]
                if degree_part.isdigit():
                    rotation_degree = int(degree_part)

            case_info.append({
                'case_dir': root,
                'terrain_index': terrain_index,
                'location': location,
                'rotation_degree': rotation_degree,
                'metadata': metadata
            })

        return case_info

    # --------------------------------------------------
    # FILE RENDERING
    # --------------------------------------------------

    def render_j2_file(self, j2_path, context):
        """Render a Jinja2 .j2 template file, write output without the .j2 suffix, then delete the template."""
        j2_path = Path(j2_path)
        if j2_path.suffix != '.j2':
            raise ValueError(f"Expected a .j2 file, got: {j2_path}")
        output_path = j2_path.with_suffix('')
        with open(j2_path) as f:
            template = Template(f.read())
        with open(output_path, 'w') as f:
            f.write(template.render(context))
        j2_path.unlink()

    # --------------------------------------------------
    # CASE SETUP
    # --------------------------------------------------

    def setup_case(self, case_info):
        case_name = f"case_{case_info['terrain_index']}_{case_info['rotation_degree']:03d}deg"
        output_case = self.output_dir / case_name

        context = {
            'terrain_index': case_info['terrain_index'],
            'rotation_degree': case_info['rotation_degree'],
            'location': case_info['location'],
            'end_time': 20000,
            'write_interval': 5000,
            'n_procs': self.hpc_defaults["ntasks"],
            'wind_direction': case_info['metadata'].get('wind_direction_deg', 0),
            **case_info['metadata']
        }

        # Copy template
        copytree(self.template_path, output_case, dirs_exist_ok=True)

        # Render OpenFOAM dictionary files
        files_to_render = [
            output_case / 'system' / 'controlDict.j2',
            output_case / 'system' / 'decomposeParDict.j2',
            output_case / 'system' / 'fvSolution.j2',
        ]

        for file in files_to_render:
            if file.exists():
                self.render_j2_file(file, context)

        # Render openfoam.sh from template
        self.render_hpc_script(output_case, case_name)

        # Copy metadata
        metadata_dest = output_case / 'pipeline_metadata.json'
        with open(metadata_dest, 'w') as f:
            json.dump(case_info['metadata'], f, indent=2)

        # Merge geometry / input files
        copytree(
            case_info['case_dir'],
            output_case,
            dirs_exist_ok=True,
            ignore=ignore_patterns('*.png', '*.vtk', 'pipeline_metadata.json')
        )

        # Initialize status file
        self.initialize_case_status(output_case)

        return output_case

    # --------------------------------------------------
    # STATUS MANAGEMENT
    # --------------------------------------------------

    def initialize_case_status(self, case_path):
        case_path = Path(case_path)
        status_file = case_path / "case_status.json"

        if not status_file.exists():
            status = {
                "mesh_status": "NOT_RUN",
                "mesh_ok": False,
                "copied_to_hpc": False,
                "submitted": False,
                "job_id": None,
                "job_status": None,
                "last_checked": None,
                "results_fetched": False,
                "last_fetched_timestep": None
            }
            with open(status_file, 'w') as f:
                json.dump(status, f, indent=2)

    def update_status(self, case_path, updates):
        case_path = Path(case_path)
        status_file = case_path / "case_status.json"
        with open(status_file) as f:
            status = json.load(f)

        status.update(updates)

        with open(status_file, 'w') as f:
            json.dump(status, f, indent=2)

    def get_status(self, case_path):
        case_path = Path(case_path)
        status_file = case_path / "case_status.json"
        if not status_file.exists():
            return None
        with open(status_file) as f:
            return json.load(f)

    # --------------------------------------------------
    # LOCAL MESHING (Single case - used by parallel worker)
    # --------------------------------------------------

    def mesh_case(self, case_path):
        """Mesh a single case - designed to be called by parallel workers"""
        case_path = Path(case_path)  # Ensure Path object
        print(f"[MESH START] {case_path.name}")

        try:
            env = os.environ.copy()
            env["RUN_STAGE"] = "mesh"

            subprocess.run(
                ["bash", "Allrun"],
                cwd=case_path,
                env=env,
                check=True,
                capture_output=True,
                text=True
            )

            # Check mesh log
            log_file = case_path / "log.checkMesh"

            if log_file.exists():
                with open(log_file) as f:
                    content = f.read()

                if "Mesh OK" in content:
                    print(f"[MESH OK] {case_path.name}")
                    self.update_status(case_path, {
                        "mesh_status": "DONE",
                        "mesh_ok": True
                    })
                    return True
                else:
                    print(f"[MESH FAILED] {case_path.name}")
                    self.update_status(case_path, {
                        "mesh_status": "FAILED",
                        "mesh_ok": False
                    })
                    return False
            else:
                print(f"[MESH ERROR] No log.checkMesh found for {case_path.name}")
                self.update_status(case_path, {
                    "mesh_status": "ERROR",
                    "mesh_ok": False
                })
                return False

        except subprocess.CalledProcessError as e:
            print(f"[MESH ERROR] {case_path.name}: {e}")
            self.update_status(case_path, {
                "mesh_status": "ERROR",
                "mesh_ok": False
            })
            return False

    # --------------------------------------------------
    # PARALLEL MESHING
    # --------------------------------------------------

    def mesh_cases_parallel(self, cases, n_workers=4):
        """Mesh multiple cases in parallel"""
        print(f"\n{'='*60}")
        print(f"Starting parallel meshing: {len(cases)} cases, {n_workers} workers")
        print(f"{'='*60}\n")

        with Pool(n_workers) as pool:
            results = pool.map(self.mesh_case, cases)

        # Summary
        success = sum(results)
        failed = len(results) - success
        
        print(f"\n{'='*60}")
        print(f"Meshing complete: {success} succeeded, {failed} failed")
        print(f"{'='*60}\n")

        return results

    # --------------------------------------------------
    # HPC SCRIPT RENDERING
    # --------------------------------------------------

    def render_hpc_script(self, case_path, case_name):
        case_path = Path(case_path)
        j2_file = case_path / "openfoam.sh.j2"
        if j2_file.exists():
            context = {"job_name": f"of_{case_name}", **self.hpc_defaults}
            self.render_j2_file(j2_file, context)
            os.chmod(case_path / "openfoam.sh", 0o755)

    # --------------------------------------------------
    # DEUCALION COPY
    # --------------------------------------------------

    def copy_to_deucalion(self, case_path):
        """Copy meshed case to deucalion using rsync with compression"""
        case_path = Path(case_path)
        case_name = case_path.name
        
        print(f"[COPY START] {case_name} -> deucalion")

        try:
            # Rsync with compression, preserve permissions
            cmd = [
                "rsync",
                "-avz",  # archive, verbose, compress
                "--progress",
                f"{case_path}/",
                f"{self.deucalion_host}:{self.deucalion_path}/{case_name}/"
            ]

            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )

            print(f"[COPY OK] {case_name}")
            self.update_status(case_path, {"copied_to_hpc": True})
            return True

        except subprocess.CalledProcessError as e:
            print(f"[COPY FAILED] {case_name}: {e.stderr}")
            return False

    # --------------------------------------------------
    # HPC SUBMISSION
    # --------------------------------------------------

    def submit_case(self, case_path):
        """Submit case to HPC via SSH sbatch"""
        case_path = Path(case_path)
        case_name = case_path.name
        
        print(f"[SUBMIT START] {case_name}")

        try:
            # SSH into deucalion and submit
            cmd = [
                "ssh",
                self.deucalion_host,
                f"cd {self.deucalion_path}/{case_name} && sbatch openfoam.sh"
            ]

            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )

            # Parse job ID from sbatch output: "Submitted batch job 123456"
            output = result.stdout.strip()
            if "Submitted batch job" in output:
                job_id = output.split()[-1]
                print(f"[SUBMIT OK] {case_name} -> Job ID: {job_id}")
                
                self.update_status(case_path, {
                    "submitted": True,
                    "job_id": job_id,
                    "job_status": "PENDING",
                    "last_checked": datetime.now().isoformat()
                })
                return job_id
            else:
                print(f"[SUBMIT ERROR] {case_name}: Unexpected sbatch output")
                return None

        except subprocess.CalledProcessError as e:
            print(f"[SUBMIT FAILED] {case_name}: {e.stderr}")
            return None

    # --------------------------------------------------
    # JOB STATUS CHECK
    # --------------------------------------------------

    def check_job_status(self, job_id):
        """Check job status using squeue/sacct with improved error handling"""
        if not job_id:
            return "NO_JOB_ID"
        
        try:
            # Try squeue first (for running/pending jobs)
            cmd = f"squeue -j {job_id} --noheader --format=%T"
            result = subprocess.run(
                ["ssh", self.deucalion_host, cmd],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode == 0 and result.stdout.strip():
                status = result.stdout.strip().upper()
                return status  # PENDING, RUNNING, etc.
            
            # If not in squeue, check sacct (for completed jobs)
            cmd = f"sacct -j {job_id} --noheader --format=State -P 2>/dev/null | head -1"
            result = subprocess.run(
                ["ssh", self.deucalion_host, cmd],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode == 0 and result.stdout.strip():
                status = result.stdout.strip().upper()
                return status  # COMPLETED, FAILED, TIMEOUT, etc.
            
            # If we can't find it in either queue, assume UNKNOWN
            return "UNKNOWN"

        except subprocess.TimeoutExpired:
            return "TIMEOUT"
        except Exception as e:
            print(f"[STATUS CHECK ERROR] Job {job_id}: {e}")
            return "ERROR"

    def update_job_status(self, case_path):
        """Update job status for a specific case"""
        status = self.get_status(case_path)
        
        if not status or not status.get("job_id"):
            return None
        
        job_id = status["job_id"]
        job_status = self.check_job_status(job_id)
        
        self.update_status(case_path, {
            "job_status": job_status,
            "last_checked": datetime.now().isoformat()
        })
        
        return job_status

    # --------------------------------------------------
    # CASE LISTING
    # --------------------------------------------------

    def list_cases_by_status(self, mesh_status=None, submitted=None):
        """List cases filtered by status. mesh_status can be a string or list of strings."""
        cases = []

        for case_dir in sorted(self.output_dir.iterdir()):
            if not case_dir.is_dir():
                continue
                
            status = self.get_status(case_dir)
            if not status:
                continue

            # Apply filters
            if mesh_status is not None:
                allowed = mesh_status if isinstance(mesh_status, list) else [mesh_status]
                if status.get("mesh_status") not in allowed:
                    continue
            if submitted is not None and status.get("submitted") != submitted:
                continue

            cases.append(case_dir)

        return cases

    def list_ready_cases(self):
        """List cases ready for HPC submission (meshed but not submitted)"""
        return self.list_cases_by_status(mesh_status="DONE", submitted=False)

    def list_failed_cases(self):
        """List cases with failed meshing"""
        return self.list_cases_by_status(mesh_status=["FAILED", "ERROR"])

    # --------------------------------------------------
    # COPY + SUBMIT HELPER
    # --------------------------------------------------

    def copy_and_submit(self, case):
        """Copy a ready case to HPC and submit it (retries if already copied but not submitted)."""
        status = self.get_status(case)
        if not status:
            return
        if not status.get("copied_to_hpc"):
            if self.copy_to_deucalion(case):
                self.submit_case(case)
        elif not status.get("submitted"):
            self.submit_case(case)

    # --------------------------------------------------
    # CONTROLDICT PARSING & TIME STEP DETECTION
    # --------------------------------------------------

    def get_last_timestep(self, case_path):
        """Parse controlDict to get endTime (the last saved timestep)"""
        case_path = Path(case_path)
        control_dict = case_path / "system" / "controlDict"
        
        if not control_dict.exists():
            return None
        
        try:
            with open(control_dict) as f:
                content = f.read()
            
            # Look for "endTime" entry (simple parsing)
            import re
            match = re.search(r'endTime\s+(\d+);', content)
            if match:
                return int(match.group(1))
            return None
        except Exception as e:
            print(f"Error parsing controlDict: {e}")
            return None

    def get_result_timesteps(self, case_path_remote):
        """Query remote OpenFOAM case directory to find available timestep directories"""
        try:
            # List all numeric directories in the remote case
            cmd = f"ls -1 {case_path_remote} | grep -E '^[0-9]+$' | sort -n"
            result = subprocess.run(
                ["ssh", self.deucalion_host, cmd],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                timesteps = [int(ts) for ts in result.stdout.strip().split('\n') if ts]
                return sorted(timesteps)
            return []
        except Exception as e:
            print(f"Error querying timesteps: {e}")
            return []

    # --------------------------------------------------
    # RESULT FETCHING FROM HPC
    # --------------------------------------------------

    def fetch_case_results(self, case_local, case_remote=None, fetch_last_timestep=True, 
                          fetch_postprocessing=True, fetch_logs=True):
        """
        Fetch selected results from HPC back to local machine.
        
        Args:
            case_local: Path to local case directory
            case_remote: Path to remote case on HPC (if None, constructed from case name)
            fetch_last_timestep: Fetch only the last saved timestep directory
            fetch_postprocessing: Fetch postProcessing/ folder
            fetch_logs: Fetch log files (but not blockMesh/checkMesh)
            
        Returns:
            bool: True if successful, False otherwise
        """
        case_local = Path(case_local)
        case_name = case_local.name
        
        if case_remote is None:
            case_remote = f"{self.deucalion_path}/{case_name}"
        
        print(f"[FETCH START] {case_name} from {self.deucalion_host}")
        
        try:
            # 1. Fetch postProcessing folder if requested
            if fetch_postprocessing:
                print(f"  → Fetching postProcessing/…")
                cmd = [
                    "rsync",
                    "-avz",
                    f"{self.deucalion_host}:{case_remote}/postProcessing/",
                    str(case_local) + "/postProcessing/"
                ]
                try:
                    subprocess.run(cmd, check=False, capture_output=True, timeout=120)
                    print(f"    ✓ postProcessing synced")
                except Exception as e:
                    print(f"    ⚠ postProcessing sync failed: {e}")
            
            # 2. Fetch log files (excluding blockMesh/checkMesh)
            if fetch_logs:
                print(f"  → Fetching log files…")
                excluded_logs = ["log.blockMesh", "log.checkMesh"]
                
                # Get list of logs on remote
                cmd_str = "ls -1 {} | grep '^log\\.' | grep -v -E '(blockMesh|checkMesh)'".format(case_remote)
                result = subprocess.run(
                    ["ssh", self.deucalion_host, cmd_str],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    log_files = result.stdout.strip().split('\n')
                    for log_file in log_files:
                        try:
                            remote_file = f"{self.deucalion_host}:{case_remote}/{log_file}"
                            local_file = case_local / log_file
                            subprocess.run(
                                ["rsync", "-avz", remote_file, str(local_file)],
                                check=False,
                                capture_output=True,
                                timeout=60
                            )
                        except Exception as e:
                            print(f"    ⚠ Failed to fetch {log_file}: {e}")
                    print(f"    ✓ {len(log_files)} log file(s) synced")
                else:
                    print(f"    ⚠ No log files found or error querying")
            
            # 3. Fetch last timestep directory if requested
            if fetch_last_timestep:
                print(f"  → Fetching last timestep…")
                timesteps = self.get_result_timesteps(case_remote)
                
                if timesteps:
                    last_ts = timesteps[-1]
                    print(f"    Last timestep found: {last_ts}")
                    
                    try:
                        cmd = [
                            "rsync",
                            "-avz",
                            f"{self.deucalion_host}:{case_remote}/{last_ts}/",
                            str(case_local / str(last_ts)) + "/"
                        ]
                        subprocess.run(cmd, check=True, capture_output=False, timeout=300)
                        print(f"    ✓ Timestep {last_ts} synced")
                        
                        # Update status to track that results were fetched
                        self.update_status(case_local, {"results_fetched": True, "last_fetched_timestep": last_ts})
                    except Exception as e:
                        print(f"    ✗ Failed to fetch timestep {last_ts}: {e}")
                        return False
                else:
                    print(f"    ⚠ No timestep directories found on remote")
            
            print(f"[FETCH OK] {case_name}")
            return True

        except Exception as e:
            print(f"[FETCH FAILED] {case_name}: {e}")
            return False

    def fetch_multiple_results(self, case_paths, n_workers=2, **fetch_kwargs):
        """Fetch results from multiple cases in sequence (slower but more reliable)"""
        print(f"\nFetching results from {len(case_paths)} case(s)…\n")
        
        results = []
        for i, case_path in enumerate(case_paths, 1):
            print(f"[{i}/{len(case_paths)}] Processing {Path(case_path).name}")
            success = self.fetch_case_results(case_path, **fetch_kwargs)
            results.append(success)
            print()
        
        succeeded = sum(results)
        failed = len(results) - succeeded
        print(f"{'='*60}")
        print(f"Result fetching complete: {succeeded} succeeded, {failed} failed")
        print(f"{'='*60}\n")
        
        return results

    # --------------------------------------------------
    # BULK GENERATION
    # --------------------------------------------------

    def generate_all_cases(self):
        cases = self.find_cases()
        print(f"Found {len(cases)} cases")

        for case_info in cases:
            print(f"Processing terrain_{case_info['terrain_index']} @ {case_info['rotation_degree']}°")
            output = self.setup_case(case_info)
            print(f"  → {output}")