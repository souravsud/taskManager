from pathlib import Path
from shutil import copytree, ignore_patterns
from jinja2 import Template
import json
import os
import re
import subprocess
import warnings
from multiprocessing import Pool
from datetime import datetime

from .config_utils import load_runtime_config
from .constants import MeshStatus, JobStatus


class OpenFOAMCaseGenerator:

    def __init__(self, template_path, input_dir, output_dir, cluster_path=None, config_path=None):
        self.template_path = Path(template_path)
        self.input_root = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.config, self.config_path = load_runtime_config(config_path)

        cluster_config = self.config.get("cluster", {})
        legacy_config = self.config.get("deucalion", {})
        if legacy_config:
            warnings.warn(
                "The 'deucalion' config key is deprecated. Use 'cluster' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.cluster_host = cluster_config.get("host") or legacy_config.get("host")
        configured_remote_path = cluster_config.get("remote_base_path") or legacy_config.get("remote_base_path")
        self.cluster_path = cluster_path if cluster_path is not None else configured_remote_path

        self.hpc_defaults = self.config["hpc"]
        self.openfoam_defaults = self.config["openfoam"]
        self.parallel_defaults = self.config["parallel"]
        self.timeouts = self.config["timeouts"]
        self.input_format = self.config["input_format"]

    # --------------------------------------------------
    # UTILITIES
    # --------------------------------------------------

    @staticmethod
    def _as_path(p):
        """Normalise a str-or-Path argument to a Path object."""
        return p if isinstance(p, Path) else Path(p)

    @staticmethod
    def _coerce_value(s):
        """Try to convert a string to int, then float; return the original string on failure."""
        try:
            return int(s)
        except (ValueError, TypeError):
            pass
        try:
            return float(s)
        except (ValueError, TypeError):
            pass
        return s

    def _require_cluster_path(self):
        if not self.cluster_path:
            raise ValueError(
                "Remote cluster path is not configured. Set cluster.remote_base_path in YAML "
                "or pass cluster_path to OpenFOAMCaseGenerator."
            )

    # --------------------------------------------------
    # CASE DISCOVERY
    # --------------------------------------------------

    def find_cases(self):
        case_info = []

        metadata_filename = self.input_format["metadata_filename"]
        folder_levels = self.input_format.get("folder_levels", [])
        n_levels = len(folder_levels)

        for root, dirs, files in os.walk(self.input_root):
            if metadata_filename not in files:
                continue

            metadata_path = Path(root) / metadata_filename
            with open(metadata_path) as f:
                metadata = json.load(f)

            # Walk up n_levels folders above the metadata file to extract param values
            params = {}
            if folder_levels:
                ancestors = []
                p = Path(root)
                for _ in range(n_levels):
                    ancestors.append(p.name)
                    p = p.parent
                ancestors.reverse()  # outermost first

                for level, folder_name in zip(folder_levels, ancestors):
                    value = folder_name
                    prefix = level.get("prefix", "")
                    suffix = level.get("suffix", "")
                    if prefix and value.startswith(prefix):
                        value = value[len(prefix):]
                    if suffix and value.endswith(suffix):
                        value = value[:-len(suffix)]
                    params[level["name"]] = self._coerce_value(value)

            case_info.append({
                'case_dir': root,
                **params,
                'metadata': metadata
            })

        return case_info

    # --------------------------------------------------
    # FILE RENDERING
    # --------------------------------------------------

    def render_j2_file(self, j2_path, context):
        """Render a Jinja2 .j2 template file, write output without the .j2 suffix, then delete the template."""
        j2_path = self._as_path(j2_path)
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
        case_name = self.input_format["case_name_template"].format(**case_info)
        output_case = self.output_dir / case_name

        # Build template context from all extracted folder-level params + metadata
        params = {k: v for k, v in case_info.items() if k not in ('case_dir', 'metadata')}
        metadata = case_info['metadata']
        terrain_config = metadata.get('configurations', {}).get('terrain', {})
        coverage = metadata.get('processing_results', {}).get('geographic_coverage', {})
        grid_stats = metadata.get('processing_results', {}).get('grid_statistics', {})

        easting = terrain_config.get('easting')
        northing = terrain_config.get('northing')
        bounds = grid_stats.get('bounds')
        if (easting is None or northing is None) and isinstance(bounds, list) and len(bounds) >= 4:
            easting = 0.5 * (float(bounds[0]) + float(bounds[1]))
            northing = 0.5 * (float(bounds[2]) + float(bounds[3]))

        context = {
            **params,
            'end_time': self.openfoam_defaults["end_time"],
            'write_interval': self.openfoam_defaults["write_interval"],
            'n_procs': self.hpc_defaults["ntasks"],
            'wind_direction': coverage.get('wind_direction_deg', terrain_config.get('rotation_deg', 0)),
            'easting': easting,
            'northing': northing,
            **metadata
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
        metadata_dest = output_case / self.input_format["metadata_filename"]
        with open(metadata_dest, 'w') as f:
            json.dump(case_info['metadata'], f, indent=2)

        # Merge geometry / input files
        copytree(
            case_info['case_dir'],
            output_case,
            dirs_exist_ok=True,
            ignore=ignore_patterns('*.png', '*.vtk', self.input_format["metadata_filename"])
        )

        # Initialize status file
        self.initialize_case_status(output_case)

        return output_case

    # --------------------------------------------------
    # STATUS MANAGEMENT
    # --------------------------------------------------

    def initialize_case_status(self, case_path):
        case_path = self._as_path(case_path)
        status_file = case_path / "case_status.json"

        if not status_file.exists():
            status = {
                "mesh_status": MeshStatus.NOT_RUN,
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
        case_path = self._as_path(case_path)
        status_file = case_path / "case_status.json"
        with open(status_file) as f:
            status = json.load(f)

        status.update(updates)

        with open(status_file, 'w') as f:
            json.dump(status, f, indent=2)

    def get_status(self, case_path):
        case_path = self._as_path(case_path)
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
        case_path = self._as_path(case_path)
        print(f"[MESH START] {case_path.name}")

        try:
            env = os.environ.copy()
            env["RUN_STAGE"] = self.openfoam_defaults["run_stage_mesh"]

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
                        "mesh_status": MeshStatus.DONE,
                        "mesh_ok": True
                    })
                    return True
                else:
                    print(f"[MESH FAILED] {case_path.name}")
                    self.update_status(case_path, {
                        "mesh_status": MeshStatus.FAILED,
                        "mesh_ok": False
                    })
                    return False
            else:
                print(f"[MESH ERROR] No log.checkMesh found for {case_path.name}")
                self.update_status(case_path, {
                    "mesh_status": MeshStatus.ERROR,
                    "mesh_ok": False
                })
                return False

        except subprocess.CalledProcessError as e:
            print(f"[MESH ERROR] {case_path.name}: {e}")
            self.update_status(case_path, {
                "mesh_status": MeshStatus.ERROR,
                "mesh_ok": False
            })
            return False

    # --------------------------------------------------
    # PARALLEL MESHING
    # --------------------------------------------------

    def mesh_cases_parallel(self, cases, n_workers=None):
        """Mesh multiple cases in parallel"""
        if n_workers is None:
            n_workers = self.parallel_defaults["mesh_workers"]

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
        case_path = self._as_path(case_path)
        j2_file = case_path / "openfoam.sh.j2"
        if j2_file.exists():
            context = {"job_name": f"of_{case_name}", **self.hpc_defaults}
            self.render_j2_file(j2_file, context)
            os.chmod(case_path / "openfoam.sh", 0o755)

    # --------------------------------------------------
    # CLUSTER COPY
    # --------------------------------------------------

    def copy_to_cluster(self, case_path):
        """Copy meshed case to the remote HPC cluster using rsync with compression"""
        case_path = self._as_path(case_path)
        case_name = case_path.name
        self._require_cluster_path()
        
        print(f"[COPY START] {case_name} -> {self.cluster_host}")

        try:
            # Rsync with compression, preserve permissions
            cmd = [
                "rsync",
                "-avz",  # archive, verbose, compress
                "--progress",
                f"{case_path}/",
                f"{self.cluster_host}:{self.cluster_path}/{case_name}/"
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
        case_path = self._as_path(case_path)
        case_name = case_path.name
        self._require_cluster_path()
        
        print(f"[SUBMIT START] {case_name}")

        try:
            # SSH into cluster and submit
            cmd = [
                "ssh",
                self.cluster_host,
                f"cd {self.cluster_path}/{case_name} && sbatch openfoam.sh"
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
                    "job_status": JobStatus.PENDING,
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
            return JobStatus.NO_JOB_ID
        
        try:
            # Try squeue first (for running/pending jobs)
            cmd = f"squeue -j {job_id} --noheader --format=%T"
            result = subprocess.run(
                ["ssh", self.cluster_host, cmd],
                capture_output=True,
                text=True,
                timeout=self.timeouts["job_status_ssh"]
            )
            
            if result.returncode == 0 and result.stdout.strip():
                status = result.stdout.strip().upper()
                return status  # PENDING, RUNNING, etc.
            
            # If not in squeue, check sacct (for completed jobs)
            cmd = f"sacct -j {job_id} --noheader --format=State -P 2>/dev/null | head -1"
            result = subprocess.run(
                ["ssh", self.cluster_host, cmd],
                capture_output=True,
                text=True,
                timeout=self.timeouts["job_status_ssh"]
            )
            
            if result.returncode == 0 and result.stdout.strip():
                status = result.stdout.strip().upper()
                return status  # COMPLETED, FAILED, TIMEOUT, etc.
            
            # If we can't find it in either queue, assume UNKNOWN
            return JobStatus.UNKNOWN

        except subprocess.TimeoutExpired:
            return JobStatus.TIMEOUT
        except Exception as e:
            print(f"[STATUS CHECK ERROR] Job {job_id}: {e}")
            return JobStatus.ERROR

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
        return self.list_cases_by_status(mesh_status=MeshStatus.DONE, submitted=False)

    def list_failed_cases(self):
        """List cases with failed meshing"""
        return self.list_cases_by_status(mesh_status=[MeshStatus.FAILED, MeshStatus.ERROR])

    # --------------------------------------------------
    # COPY + SUBMIT HELPER
    # --------------------------------------------------

    def copy_and_submit(self, case):
        """Copy a ready case to HPC and submit it (retries if already copied but not submitted)."""
        status = self.get_status(case)
        if not status:
            return
        if not status.get("copied_to_hpc"):
            if self.copy_to_cluster(case):
                self.submit_case(case)
        elif not status.get("submitted"):
            self.submit_case(case)

    # --------------------------------------------------
    # CONTROLDICT PARSING & TIME STEP DETECTION
    # --------------------------------------------------

    def get_last_timestep(self, case_path):
        """Parse controlDict to get endTime (the last saved timestep)"""
        case_path = self._as_path(case_path)
        control_dict = case_path / "system" / "controlDict"
        
        if not control_dict.exists():
            return None
        
        try:
            with open(control_dict) as f:
                content = f.read()
            
            # Look for "endTime" entry (simple parsing)
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
                ["ssh", self.cluster_host, cmd],
                capture_output=True,
                text=True,
                timeout=self.timeouts["remote_list_timesteps"]
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

    def _fetch_postprocessing(self, case_local, case_remote):
        """Rsync the postProcessing/ folder from the remote case."""
        print(f"  → Fetching postProcessing/…")
        cmd = [
            "rsync",
            "-avz",
            f"{self.cluster_host}:{case_remote}/postProcessing/",
            str(case_local) + "/postProcessing/"
        ]
        try:
            subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                timeout=self.timeouts["fetch_postprocessing"],
            )
            print(f"    ✓ postProcessing synced")
        except Exception as e:
            print(f"    ⚠ postProcessing sync failed: {e}")

    def _fetch_logs(self, case_local, case_remote):
        """Rsync solver log files (excluding blockMesh/checkMesh) from the remote case."""
        print(f"  → Fetching log files…")
        cmd_str = "ls -1 {} | grep '^log\\.' | grep -v -E '(blockMesh|checkMesh)'".format(case_remote)
        result = subprocess.run(
            ["ssh", self.cluster_host, cmd_str],
            capture_output=True,
            text=True,
            timeout=self.timeouts["fetch_log_list"]
        )

        if result.returncode == 0 and result.stdout.strip():
            log_files = result.stdout.strip().split('\n')
            for log_file in log_files:
                try:
                    remote_file = f"{self.cluster_host}:{case_remote}/{log_file}"
                    local_file = case_local / log_file
                    subprocess.run(
                        ["rsync", "-avz", remote_file, str(local_file)],
                        check=False,
                        capture_output=True,
                        timeout=self.timeouts["fetch_single_log"]
                    )
                except Exception as e:
                    print(f"    ⚠ Failed to fetch {log_file}: {e}")
            print(f"    ✓ {len(log_files)} log file(s) synced")
        else:
            print(f"    ⚠ No log files found or error querying")

    def _fetch_last_timestep(self, case_local, case_remote):
        """Rsync the last available timestep directory from the remote case.

        Args:
            case_local (Path): Local case directory where the timestep will be written.
            case_remote (str): Remote path to the case directory on the HPC cluster.

        Returns:
            bool: True if a timestep was successfully synced or none were found (non-fatal),
                  False if a timestep existed but could not be fetched.
        """
        print(f"  → Fetching last timestep…")
        timesteps = self.get_result_timesteps(case_remote)

        if not timesteps:
            print(f"    ⚠ No timestep directories found on remote")
            return True  # non-fatal

        last_ts = timesteps[-1]
        print(f"    Last timestep found: {last_ts}")

        try:
            cmd = [
                "rsync",
                "-avz",
                f"{self.cluster_host}:{case_remote}/{last_ts}/",
                str(case_local / str(last_ts)) + "/"
            ]
            subprocess.run(
                cmd,
                check=True,
                capture_output=False,
                timeout=self.timeouts["fetch_last_timestep"],
            )
            print(f"    ✓ Timestep {last_ts} synced")
            self.update_status(case_local, {"results_fetched": True, "last_fetched_timestep": last_ts})
            return True
        except Exception as e:
            print(f"    ✗ Failed to fetch timestep {last_ts}: {e}")
            return False

    def _fetch_extra_files(self, case_local, case_remote, patterns):
        """Rsync extra files/globs from the remote case root to the local case directory."""
        print(f"  → Fetching extra files: {patterns}")
        for pattern in patterns:
            try:
                subprocess.run(
                    ["rsync", "-avz", f"{self.cluster_host}:{case_remote}/{pattern}", str(case_local) + "/"],
                    check=False,
                    capture_output=True,
                    timeout=self.timeouts.get("fetch_single_log", 60),
                )
            except Exception as e:
                print(f"    ⚠ Failed to fetch '{pattern}': {e}")

    def fetch_case_results(self, case_local, case_remote=None, fetch_last_timestep=True,
                           fetch_postprocessing=True, fetch_logs=True, extra_files=None):
        """
        Fetch selected results from HPC back to local machine.

        Args:
            case_local: Path to local case directory
            case_remote: Path to remote case on HPC (if None, constructed from case name)
            fetch_last_timestep: Fetch only the last saved timestep directory
            fetch_postprocessing: Fetch postProcessing/ folder
            fetch_logs: Fetch log files (but not blockMesh/checkMesh)
            extra_files: Optional list of file names, relative paths, or shell glob patterns
                (e.g. ``["slurm*", "foam.log"]``) to rsync from the remote case root.

        Returns:
            bool: True if successful, False otherwise
        """
        case_local = self._as_path(case_local)
        case_name = case_local.name
        self._require_cluster_path()

        if case_remote is None:
            case_remote = f"{self.cluster_path}/{case_name}"

        print(f"[FETCH START] {case_name} from {self.cluster_host}")

        try:
            if fetch_postprocessing:
                self._fetch_postprocessing(case_local, case_remote)

            if fetch_logs:
                self._fetch_logs(case_local, case_remote)

            if fetch_last_timestep:
                if not self._fetch_last_timestep(case_local, case_remote):
                    return False

            if extra_files:
                self._fetch_extra_files(case_local, case_remote, extra_files)

            print(f"[FETCH OK] {case_name}")
            return True

        except Exception as e:
            print(f"[FETCH FAILED] {case_name}: {e}")
            return False

    def fetch_multiple_results(self, case_paths, **fetch_kwargs):
        """Fetch results from multiple cases sequentially.

        Note: fetching is intentionally sequential rather than parallel because
        concurrent SSH/rsync connections to the same HPC cluster are unreliable.

        Args:
            case_paths (list[Path | str]): Local case directories whose results should be fetched.
            **fetch_kwargs: Keyword arguments forwarded to :meth:`fetch_case_results`
                (e.g. ``fetch_last_timestep``, ``fetch_postprocessing``, ``fetch_logs``).

        Returns:
            list[bool]: A list of per-case success flags in the same order as *case_paths*.
        """
        print(f"\nFetching results from {len(case_paths)} case(s)…\n")

        results = []
        for i, case_path in enumerate(case_paths, 1):
            print(f"[{i}/{len(case_paths)}] Processing {self._as_path(case_path).name}")
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

        for case_num, case_info in enumerate(cases, start=1):
            enriched = {**case_info, 'case_num': case_num}
            params = {k: v for k, v in enriched.items() if k not in ('case_dir', 'metadata')}
            print(f"Processing [{case_num}/{len(cases)}] {params}")
            output = self.setup_case(enriched)
            print(f"  → {output}")