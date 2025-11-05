"""VirtioFS management commands."""

import sys
from pathlib import Path
from tabulate import tabulate

from vmfinder.config import Config
from vmfinder.virtiofsd import VirtiofsdManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_virtiofs_start(args):
    """Start virtiofsd for a VM."""
    config = Config()
    virtiofs_manager = VirtiofsdManager(config.config_dir)

    try:
        # If source not provided, try to get from saved state
        if not args.source:
            status = virtiofs_manager.get_status(args.name)
            if status:
                source_path = Path(status.get("source_path", ""))
                if source_path.exists():
                    logger.info(f"Using saved source path: {source_path}")
                    args.source = str(source_path)
                else:
                    logger.error(
                        f"Saved source path does not exist: {source_path}. "
                        f"Please provide source directory path."
                    )
                    sys.exit(1)
            else:
                logger.error(
                    f"No saved state found for VM '{args.name}'. "
                    f"Please provide source directory path."
                )
                logger.error(
                    f"\nUsage: vmfinder virtiofs start {args.name} <source_directory_path>"
                )
                sys.exit(1)

        source_path = Path(args.source)
        if not source_path.exists():
            logger.error(f"Source path does not exist: {source_path}")
            sys.exit(1)
        if not source_path.is_dir():
            logger.error(f"Source path is not a directory: {source_path}")
            sys.exit(1)

        if virtiofs_manager.start_virtiofsd(
            vm_name=args.name,
            source_path=source_path,
            mount_tag=getattr(args, "tag", "shared"),
            cache=getattr(args, "cache", "auto"),
            xattr=getattr(args, "xattr", "auto"),
            readdirplus=getattr(args, "readdirplus", True),
        ):
            logger.info(f"✓ Started virtiofsd for VM '{args.name}'")
        else:
            logger.warning(f"virtiofsd for VM '{args.name}' is already running")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_virtiofs_stop(args):
    """Stop virtiofsd for a VM."""
    config = Config()
    virtiofs_manager = VirtiofsdManager(config.config_dir)

    try:
        if virtiofs_manager.stop_virtiofsd(
            args.name, force=getattr(args, "force", False)
        ):
            logger.info(f"✓ Stopped virtiofsd for VM '{args.name}'")
        else:
            logger.warning(f"virtiofsd for VM '{args.name}' is not running")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_virtiofs_status(args):
    """Show virtiofsd status for a VM."""
    config = Config()
    virtiofs_manager = VirtiofsdManager(config.config_dir)

    try:
        if args.name:
            # Show status for specific VM
            status = virtiofs_manager.get_status(args.name)
            if status:
                print(f"\nVM: {status['vm_name']}")
                print(f"Status: {'Running' if status.get('running') else 'Stopped'}")
                if status.get("pid"):
                    print(f"PID: {status['pid']}")
                print(f"Socket: {status.get('socket_path', 'N/A')}")
                print(f"Source: {status.get('source_path', 'N/A')}")
                print(f"Mount Tag: {status.get('mount_tag', 'N/A')}")
            else:
                logger.warning(f"No virtiofsd found for VM '{args.name}'")
        else:
            # List all virtiofsd instances
            instances = virtiofs_manager.list_all()
            if not instances:
                logger.info("No virtiofsd instances found")
                return

            headers = ["VM Name", "Status", "PID", "Source", "Mount Tag", "Socket"]
            rows = []
            for instance in instances:
                rows.append(
                    [
                        instance.get("vm_name", "N/A"),
                        "Running" if instance.get("running") else "Stopped",
                        instance.get("pid", "N/A"),
                        instance.get("source_path", "N/A"),
                        instance.get("mount_tag", "N/A"),
                        instance.get("socket_path", "N/A"),
                    ]
                )
            print(tabulate(rows, headers=headers, tablefmt="grid"))
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_virtiofs_restart(args):
    """Restart virtiofsd for a VM."""
    config = Config()
    virtiofs_manager = VirtiofsdManager(config.config_dir)

    try:
        # Stop first
        if virtiofs_manager.is_running(args.name):
            logger.info(f"Stopping virtiofsd for VM '{args.name}'...")
            virtiofs_manager.stop_virtiofsd(args.name, force=True)

        # Get status to retrieve source path
        status = virtiofs_manager.get_status(args.name)
        if not status:
            logger.error(f"No virtiofsd configuration found for VM '{args.name}'")
            logger.error("Please start virtiofsd first with 'vmfinder virtiofs start'")
            sys.exit(1)

        source_path = Path(status.get("source_path", ""))
        if not source_path.exists():
            logger.error(f"Source path does not exist: {source_path}")
            sys.exit(1)

        # Start again
        logger.info(f"Starting virtiofsd for VM '{args.name}'...")
        virtiofs_manager.start_virtiofsd(
            vm_name=args.name,
            source_path=source_path,
            mount_tag=status.get("mount_tag", "shared"),
            cache=status.get("cache", "auto"),
            xattr=status.get("xattr", "auto"),
            readdirplus=status.get("readdirplus", True),
        )
        logger.info(f"✓ Restarted virtiofsd for VM '{args.name}'")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
