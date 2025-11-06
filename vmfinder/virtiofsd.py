"""VirtioFS daemon management."""

import os
import subprocess
import shutil
import json
import signal
from pathlib import Path
from typing import Optional, Dict, List, Any
from vmfinder.logger import get_logger

logger = get_logger()


class VirtiofsdManager:
    """Manages virtiofsd daemon processes."""

    def __init__(self, config_dir: Path):
        """Initialize virtiofsd manager.

        Args:
            config_dir: VMFinder config directory (e.g., ~/.vmfinder)
        """
        self.config_dir = config_dir
        self.state_dir = config_dir / "virtiofsd"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _get_state_file(self, vm_name: str) -> Path:
        """Get state file path for a VM's virtiofsd."""
        return self.state_dir / f"{vm_name}.json"

    def _get_socket_path(self, vm_name: str) -> str:
        """Get virtiofsd socket path for a VM."""
        # Use /var/run/vmfinder-virtiofsd or fallback to state_dir
        runtime_dir = Path("/var/run/vmfinder-virtiofsd")
        try:
            runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
            return str(runtime_dir / f"{vm_name}.sock")
        except PermissionError:
            # Fallback to state_dir if we can't create in /var/run
            return str(self.state_dir / f"{vm_name}.sock")

    def _find_virtiofsd_binary(self) -> Optional[Path]:
        """Find virtiofsd binary in system PATH."""
        # Common locations
        common_paths = [
            "/usr/libexec/virtiofsd",
            "/usr/lib/qemu/virtiofsd",
            "/usr/bin/virtiofsd",
        ]

        # First check common paths
        for path in common_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return Path(path)

        # Then check PATH
        virtiofsd = shutil.which("virtiofsd")
        if virtiofsd:
            return Path(virtiofsd)

        return None

    def _find_processes_by_socket(self, socket_path: str) -> List[int]:
        """Find all virtiofsd processes using the specified socket path.
        
        Args:
            socket_path: Socket path to search for
            
        Returns:
            List of PIDs using this socket
        """
        pids = []
        try:
            # Use ps to find all virtiofsd processes
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                check=False,
            )
            
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "virtiofsd" in line and socket_path in line:
                        # Extract PID (second column in ps aux output)
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[1])
                                pids.append(pid)
                            except (ValueError, IndexError):
                                continue
        except Exception:
            # If ps fails, try using pgrep
            try:
                result = subprocess.run(
                    ["pgrep", "-f", f"virtiofsd.*{socket_path}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    for pid_str in result.stdout.strip().split():
                        try:
                            pids.append(int(pid_str))
                        except ValueError:
                            continue
            except Exception:
                pass
        
        return pids

    def _kill_processes_by_socket(self, socket_path: str, force: bool = False) -> int:
        """Kill all virtiofsd processes using the specified socket path.
        
        Args:
            socket_path: Socket path to search for
            force: Force kill if graceful shutdown fails
            
        Returns:
            Number of processes killed
        """
        pids = self._find_processes_by_socket(socket_path)
        killed = 0
        
        for pid in pids:
            try:
                # Try graceful shutdown first
                os.kill(pid, signal.SIGTERM)
                
                # Wait for process to terminate (max 2 seconds)
                import time
                for _ in range(20):  # 20 * 0.1 = 2 seconds
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        # Process terminated
                        killed += 1
                        break
                    time.sleep(0.1)
                else:
                    # Process still running, force kill if requested
                    if force:
                        try:
                            os.kill(pid, signal.SIGKILL)
                            time.sleep(0.2)
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                killed += 1
                        except (ProcessLookupError, PermissionError):
                            pass
            except (ProcessLookupError, PermissionError):
                # Process already dead or no permission
                pass
        
        return killed

    def start_virtiofsd(
        self,
        vm_name: str,
        source_path: Path,
        mount_tag: str = "shared",
        cache: str = "auto",
        xattr: str = "auto",
        readdirplus: bool = True,
    ) -> bool:
        """Start virtiofsd daemon for a VM.

        Args:
            vm_name: Name of the VM
            source_path: Host directory path to share
            mount_tag: Mount tag name (default: "shared")
            cache: Cache mode (none, auto, always) - default: auto
            xattr: Extended attributes mode (off, on, auto) - default: auto
            readdirplus: Enable readdirplus optimization - default: True

        Returns:
            True if started successfully, False otherwise
        """
        # Get socket path first (needed for cleanup)
        socket_path = self._get_socket_path(vm_name)
        socket_path_obj = Path(socket_path)
        
        # Check if socket file exists and is being used by another process
        if socket_path_obj.exists():
            # Check if there are any processes using this socket
            pids = self._find_processes_by_socket(socket_path)
            if pids:
                logger.warning(
                    f"Found {len(pids)} existing virtiofsd process(es) using socket "
                    f"'{socket_path}'. Cleaning up..."
                )
                killed = self._kill_processes_by_socket(socket_path, force=True)
                if killed > 0:
                    logger.info(f"Killed {killed} stale virtiofsd process(es)")
                
                # Wait a bit for socket to be released
                import time
                time.sleep(0.5)
                
                # Remove stale socket file if it still exists
                if socket_path_obj.exists():
                    try:
                        socket_path_obj.unlink()
                    except Exception:
                        pass
        
        # Check if already running (by state file)
        if self.is_running(vm_name):
            logger.warning(f"virtiofsd for VM '{vm_name}' is already running")
            return False

        # Validate source path
        if not source_path.exists():
            raise ValueError(f"Source path does not exist: {source_path}")
        if not source_path.is_dir():
            raise ValueError(f"Source path is not a directory: {source_path}")

        # Find virtiofsd binary
        virtiofsd_bin = self._find_virtiofsd_binary()
        if not virtiofsd_bin:
            raise RuntimeError(
                "virtiofsd binary not found. Please install qemu-virtiofsd or virtiofsd package."
            )

        # Prepare command - only include supported options
        # Some virtiofsd versions don't support --cache or --xattr with "auto" value
        cmd = [
            str(virtiofsd_bin),
            "--socket-path",
            socket_path,
            "--shared-dir",
            str(source_path),
        ]

        # Only add cache option if it's not "auto" (some versions don't support auto)
        if cache and cache != "auto":
            cmd.extend(["--cache", cache])

        # Only add xattr option if it's not "auto" (some versions don't support auto)
        if xattr and xattr != "auto":
            cmd.extend(["--xattr", xattr])

        # Only add readdirplus option if False (some versions only support --no-readdirplus)
        # Default behavior is readdirplus enabled, so we only disable it if explicitly False
        if not readdirplus:
            cmd.append("--no-readdirplus")

        # Start virtiofsd as daemon
        try:
            # Use subprocess.Popen with proper file handles
            log_file = self.state_dir / f"{vm_name}.log"

            # Ensure socket directory exists and has correct permissions
            socket_dir = socket_path_obj.parent
            socket_dir.mkdir(parents=True, exist_ok=True)

            # Try to set permissions on socket directory for libvirt-qemu
            try:
                import grp

                for group_name in ["kvm", "qemu", "libvirt-qemu", "libvirt"]:
                    try:
                        qemu_group = grp.getgrnam(group_name)
                        os.chown(socket_dir, -1, qemu_group.gr_gid)
                        os.chmod(socket_dir, 0o775)
                        break
                    except (KeyError, PermissionError, OSError):
                        continue
            except Exception:
                pass  # Continue even if permission setting fails

            with open(log_file, "w") as log:
                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,  # Detach from parent
                )

            # Wait a bit for socket to be created
            import time

            max_wait = 3  # Wait up to 3 seconds
            waited = 0
            while waited < max_wait:
                if socket_path_obj.exists():
                    # Socket created, try to set permissions
                    try:
                        import grp

                        for group_name in ["kvm", "qemu", "libvirt-qemu", "libvirt"]:
                            try:
                                qemu_group = grp.getgrnam(group_name)
                                os.chown(socket_path_obj, -1, qemu_group.gr_gid)
                                os.chmod(socket_path_obj, 0o666)  # rw-rw-rw-
                                break
                            except (KeyError, PermissionError, OSError):
                                continue
                        # Also try ACL if available
                        try:
                            subprocess.run(
                                ["setfacl", "-m", "g:qemu:rw", str(socket_path_obj)],
                                check=False,
                                capture_output=True,
                            )
                            subprocess.run(
                                [
                                    "setfacl",
                                    "-m",
                                    "g:libvirt-qemu:rw",
                                    str(socket_path_obj),
                                ],
                                check=False,
                                capture_output=True,
                            )
                        except Exception:
                            pass
                    except Exception:
                        pass
                    break
                time.sleep(0.1)
                waited += 0.1

            # Check if process is still running
            if process.poll() is not None:
                # Process exited immediately - read log for error
                with open(log_file, "r") as f:
                    log_content = f.read()
                raise RuntimeError(
                    f"virtiofsd failed to start. Log: {log_content[:500]}"
                )

            # Save state
            state = {
                "vm_name": vm_name,
                "pid": process.pid,
                "socket_path": socket_path,
                "source_path": str(source_path),
                "mount_tag": mount_tag,
                "cache": cache,
                "xattr": xattr,
                "readdirplus": readdirplus,
            }

            state_file = self._get_state_file(vm_name)
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)

            logger.info(
                f"✓ Started virtiofsd for VM '{vm_name}' "
                f"(PID: {process.pid}, socket: {socket_path})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start virtiofsd: {e}")
            return False

    def stop_virtiofsd(self, vm_name: str, force: bool = False) -> bool:
        """Stop virtiofsd daemon for a VM.

        Args:
            vm_name: Name of the VM
            force: Force kill if graceful shutdown fails

        Returns:
            True if stopped successfully, False otherwise
        """
        state_file = self._get_state_file(vm_name)

        socket_path = None
        pid = None
        
        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    state = json.load(f)
                socket_path = state.get("socket_path")
                pid = state.get("pid")
            except Exception:
                pass

        # First, try to stop by PID if we have it
        if pid:
            try:
                os.kill(pid, 0)  # Check if process exists
            except ProcessLookupError:
                # Process already dead
                pid = None
            except PermissionError:
                # Process exists but we don't have permission
                logger.warning(
                    f"Cannot access virtiofsd process for VM '{vm_name}' "
                    f"(PID: {pid}). May need root privileges."
                )
                pid = None

        # Also clean up all processes using the socket (in case there are duplicates)
        socket_stopped = False
        if socket_path:
            pids_by_socket = self._find_processes_by_socket(socket_path)
            if pids_by_socket:
                logger.info(
                    f"Found {len(pids_by_socket)} virtiofsd process(es) using socket "
                    f"'{socket_path}'. Stopping all..."
                )
                killed = self._kill_processes_by_socket(socket_path, force=force)
                if killed > 0:
                    logger.info(f"✓ Stopped {killed} virtiofsd process(es) for VM '{vm_name}'")
                    socket_stopped = True
                    
                    # Remove socket file if it exists
                    socket_path_obj = Path(socket_path)
                    if socket_path_obj.exists():
                        try:
                            socket_path_obj.unlink()
                        except Exception:
                            pass

        if not state_file.exists():
            if socket_stopped:
                return True
            logger.warning(f"No virtiofsd state found for VM '{vm_name}'")
            return False

        if not pid:
            if socket_stopped:
                return True
            logger.info(f"virtiofsd for VM '{vm_name}' is not running")
            return True

        # Try graceful shutdown first
        try:
            os.kill(pid, signal.SIGTERM)

            # Wait for process to terminate (max 5 seconds)
            import time

            for _ in range(50):  # 50 * 0.1 = 5 seconds
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    # Process terminated
                    logger.info(f"✓ Stopped virtiofsd for VM '{vm_name}'")
                    # Remove socket file if it exists
                    if socket_path:
                        socket_path_obj = Path(socket_path)
                        if socket_path_obj.exists():
                            try:
                                socket_path_obj.unlink()
                            except Exception:
                                pass
                    return True
                time.sleep(0.1)
            else:
                # Process still running, force kill if requested
                if force:
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.2)
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        logger.info(f"✓ Stopped virtiofsd for VM '{vm_name}'")
                        # Remove socket file if it exists
                        if socket_path:
                            socket_path_obj = Path(socket_path)
                            if socket_path_obj.exists():
                                try:
                                    socket_path_obj.unlink()
                                except Exception:
                                    pass
                        return True
                    else:
                        logger.error(
                            f"Failed to kill virtiofsd for VM '{vm_name}' (PID: {pid})"
                        )
                        return False
                else:
                    logger.warning(
                        f"virtiofsd for VM '{vm_name}' did not terminate. "
                        f"Use --force to kill it."
                    )
                    return False

        except ProcessLookupError:
            # Process already terminated
            logger.info(f"virtiofsd for VM '{vm_name}' already stopped")
            # Remove socket file if it exists
            if socket_path:
                socket_path_obj = Path(socket_path)
                if socket_path_obj.exists():
                    try:
                        socket_path_obj.unlink()
                    except Exception:
                        pass
            return True
        except Exception as e:
            logger.error(f"Failed to stop virtiofsd: {e}")
            return False

    def is_running(self, vm_name: str) -> bool:
        """Check if virtiofsd is running for a VM.

        Args:
            vm_name: Name of the VM

        Returns:
            True if running, False otherwise
        """
        state_file = self._get_state_file(vm_name)

        if not state_file.exists():
            return False

        try:
            with open(state_file, "r") as f:
                state = json.load(f)

            pid = state.get("pid")
            socket_path = state.get("socket_path")
            
            # Check if process is still running by PID
            if pid:
                try:
                    os.kill(pid, 0)
                    return True
                except ProcessLookupError:
                    # PID is dead, but check if socket is still in use
                    pass
                except PermissionError:
                    # Process exists but we can't check (assume running)
                    return True

            # Also check if socket is being used by any process
            if socket_path:
                pids = self._find_processes_by_socket(socket_path)
                if pids:
                    return True

            return False

        except Exception:
            return False

    def get_status(self, vm_name: str) -> Optional[Dict[str, Any]]:
        """Get status information for virtiofsd.

        Args:
            vm_name: Name of the VM

        Returns:
            Dict with status info or None if not found
        """
        state_file = self._get_state_file(vm_name)

        if not state_file.exists():
            return None

        try:
            with open(state_file, "r") as f:
                state = json.load(f)

            # Check if process is running
            pid = state.get("pid")
            is_alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    is_alive = True
                except (ProcessLookupError, PermissionError):
                    pass

            state["running"] = is_alive
            return state

        except Exception:
            return None

    def list_all(self) -> List[Dict[str, Any]]:
        """List all virtiofsd instances.

        Returns:
            List of status dicts for all virtiofsd instances
        """
        instances = []

        for state_file in self.state_dir.glob("*.json"):
            try:
                vm_name = state_file.stem
                status = self.get_status(vm_name)
                if status:
                    instances.append(status)
            except Exception:
                continue

        return instances

    def cleanup_stale(self) -> int:
        """Clean up stale state files for dead processes.

        Returns:
            Number of stale instances cleaned up
        """
        cleaned = 0

        for state_file in self.state_dir.glob("*.json"):
            try:
                vm_name = state_file.stem
                if not self.is_running(vm_name):
                    # State file exists but process is dead
                    # Check if file is still there (is_running might have deleted it)
                    if state_file.exists():
                        state_file.unlink()
                        cleaned += 1
            except Exception:
                continue

        return cleaned
