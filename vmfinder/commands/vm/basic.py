"""Basic VM operations: list, start, stop, suspend, resume, restart."""

import sys
from pathlib import Path
from tabulate import tabulate

from vmfinder.config import Config
from vmfinder.vm_manager import VMManager
from vmfinder.virtiofsd import VirtiofsdManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_vm_list(args):
    """List all virtual machines."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        with VMManager(uri) as manager:
            vms = manager.list_vms()

            if not vms:
                logger.info("No VMs found.")
                return

            headers = ["Name", "State", "CPU", "Memory (MB)", "Max Memory (MB)"]
            rows = []
            for vm in vms:
                if "error" in vm:
                    rows.append(
                        [
                            vm["name"],
                            f"error: {vm.get('error', 'unknown')}",
                            "-",
                            "-",
                            "-",
                        ]
                    )
                else:
                    rows.append(
                        [
                            vm["name"],
                            vm["state"],
                            vm.get("cpu", "-"),
                            f"{vm.get('memory', 0):.0f}",
                            f"{vm.get('max_memory', 0):.0f}",
                        ]
                    )
            print(tabulate(rows, headers=headers, tablefmt="grid"))
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_start(args):
    """Start a virtual machine."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        # Check for virtio-fs devices and start virtiofsd if needed
        with VMManager(uri) as manager:
            virtiofs_devices = manager.list_virtiofs_devices(args.name)

            if virtiofs_devices:
                virtiofs_manager = VirtiofsdManager(config.config_dir)

                # Check if virtiofsd is already running
                if not virtiofs_manager.is_running(args.name):
                    # Get source path from state
                    status = virtiofs_manager.get_status(args.name)
                    if status:
                        source_path = Path(status.get("source_path", ""))
                        mount_tag = status.get("mount_tag", "shared")

                        if source_path.exists():
                            logger.info(f"Starting virtiofsd for VM '{args.name}'...")
                            virtiofs_manager.start_virtiofsd(
                                vm_name=args.name,
                                source_path=source_path,
                                mount_tag=mount_tag,
                            )
                        else:
                            socket_path = virtiofs_devices[0].get("socket_path", "")
                            logger.error(
                                f"virtio-fs source path not found: {source_path}. "
                                f"Cannot start virtiofsd."
                            )
                            logger.error(
                                f"\nPlease start virtiofsd manually with:"
                                f"\n  vmfinder virtiofs start {args.name} <source_directory_path>"
                            )
                            if socket_path:
                                logger.error(f"\nExpected socket path: {socket_path}")
                            sys.exit(1)
                    else:
                        # State not found - need to start manually
                        socket_path = virtiofs_devices[0].get("socket_path", "")
                        logger.error(
                            f"virtio-fs configured but virtiofsd state not found. "
                            f"Cannot start VM without virtiofsd running."
                        )
                        logger.error(
                            f"\nPlease start virtiofsd manually with:"
                            f"\n  vmfinder virtiofs start {args.name} <source_directory_path>"
                        )
                        if socket_path:
                            logger.error(f"\nExpected socket path: {socket_path}")
                        logger.error(
                            f"\nThen run this command again: vmfinder vm start {args.name}"
                        )
                        sys.exit(1)

        # Start the VM
        with VMManager(uri) as manager:
            if manager.start_vm(args.name):
                logger.info(f"✓ Started VM: {args.name}")
            else:
                logger.warning(
                    f"VM {args.name} is already running or in an invalid state."
                )
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_stop(args):
    """Stop a virtual machine."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        # Stop the VM first
        with VMManager(uri) as manager:
            # Check if VM is running first
            info = manager.get_vm_info(args.name)
            if not info:
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)
            
            if info["state"] != "running":
                logger.warning(f"VM {args.name} is already stopped.")
            else:
                # Use kill mode if requested
                if getattr(args, 'kill', False):
                    logger.info(f"Force killing VM '{args.name}'...")
                    killed = manager.kill_vm(args.name)
                    if killed:
                        logger.info(f"✓ Killed VM: {args.name}")
                    else:
                        logger.warning(f"VM {args.name} is already stopped.")
                else:
                    stopped = manager.stop_vm(args.name, args.force)
                    if stopped:
                        action = "destroyed" if args.force else "stopped"
                        logger.info(f"✓ {action.capitalize()} VM: {args.name}")
                    else:
                        # Check if VM is still running (shutdown timeout)
                        current_info = manager.get_vm_info(args.name)
                        if current_info and current_info["state"] == "running":
                            # If graceful shutdown failed, try force stop
                            if not args.force:
                                logger.warning(
                                    f"VM '{args.name}' did not shut down gracefully. "
                                    f"Attempting force stop..."
                                )
                                stopped = manager.stop_vm(args.name, force=True)
                                if stopped:
                                    logger.info(f"✓ Destroyed VM: {args.name}")
                                else:
                                    # Last resort: kill
                                    logger.warning(
                                        f"Force stop failed. Attempting kill..."
                                    )
                                    killed = manager.kill_vm(args.name)
                                    if killed:
                                        logger.info(f"✓ Killed VM: {args.name}")
                                    else:
                                        logger.error(f"Failed to stop VM: {args.name}")
                                        sys.exit(1)
                            else:
                                # Force already tried, use kill
                                logger.warning(
                                    f"Force stop failed. Attempting kill..."
                                )
                                killed = manager.kill_vm(args.name)
                                if killed:
                                    logger.info(f"✓ Killed VM: {args.name}")
                                else:
                                    logger.error(f"Failed to stop VM: {args.name}")
                                    sys.exit(1)
                        else:
                            # VM actually stopped, just took a while
                            logger.info(f"✓ Stopped VM: {args.name}")

        # Stop virtiofsd if it's running
        virtiofs_manager = VirtiofsdManager(config.config_dir)
        if virtiofs_manager.is_running(args.name):
            logger.info(f"Stopping virtiofsd for VM '{args.name}'...")
            # Use kill mode for virtiofsd too if kill was requested
            virtiofs_manager.stop_virtiofsd(
                args.name, 
                force=getattr(args, 'kill', False) or args.force
            )

    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_suspend(args):
    """Suspend a virtual machine."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        with VMManager(uri) as manager:
            if manager.suspend_vm(args.name):
                logger.info(f"✓ Suspended VM: {args.name}")
            else:
                logger.warning(
                    f"VM {args.name} cannot be suspended (not running or invalid state)."
                )
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_resume(args):
    """Resume a suspended virtual machine."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        with VMManager(uri) as manager:
            if manager.resume_vm(args.name):
                logger.info(f"✓ Resumed VM: {args.name}")
            else:
                logger.warning(f"VM {args.name} cannot be resumed (not suspended).")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_restart(args):
    """Restart a virtual machine (stop and start)."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        with VMManager(uri) as manager:
            # Check if VM is running
            info = manager.get_vm_info(args.name)
            if not info:
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)

            # Stop VM if running
            if info["state"] == "running":
                logger.info(f"Stopping VM '{args.name}'...")
                if manager.stop_vm(args.name, args.force):
                    action = "destroyed" if args.force else "stopped"
                    logger.info(f"✓ {action.capitalize()} VM: {args.name}")
                else:
                    logger.warning(f"VM {args.name} is already stopped.")

            # Start VM
            logger.info(f"Starting VM '{args.name}'...")
            if manager.start_vm(args.name):
                logger.info(f"✓ Started VM: {args.name}")
            else:
                logger.warning(
                    f"VM {args.name} may already be running or in an invalid state."
                )
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
