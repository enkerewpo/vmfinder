"""Cloud-init related VM commands."""

import sys
import os
import tempfile
import shutil
from pathlib import Path

from vmfinder.config import Config
from vmfinder.vm_manager import VMManager
from vmfinder.disk import DiskManager
from vmfinder.cloud_init import CloudInitManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_vm_fix_cloud_init(args):
    """Fix cloud-init metadata service warnings by attaching a cloud-init ISO."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        # Check if VM exists
        with VMManager(uri) as manager:
            if not manager.vm_exists(args.name):
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)

            # Stop VM if running
            was_running = False
            try:
                info = manager.get_vm_info(args.name)
                if info and info["state"] == "running":
                    logger.info(f"Stopping VM '{args.name}'...")
                    manager.stop_vm(args.name, force=True)
                    logger.info(f"✓ VM stopped")
                    was_running = True
            except Exception as e:
                logger.warning(f"Could not stop VM: {e}")

        # Create cloud-init ISO
        logger.info(f"Creating cloud-init ISO to fix metadata service warnings...")
        storage_dir = config.get_storage_dir()
        iso_path = storage_dir / f"{args.name}-cloud-init.iso"

        # Create ISO with a temporary name first to avoid permission issues
        temp_iso = Path(tempfile.mktemp(suffix=".iso", dir=str(storage_dir)))

        try:
            # Create basic meta-data with instance-id and hostname
            meta_data = f"""instance-id: iid-{args.name}
local-hostname: {args.name}
"""

            # Create minimal user-data (just enable basic features)
            user_data = """#cloud-config
# Basic cloud-init configuration to prevent network metadata service requests
"""

            # Create the ISO
            CloudInitManager.create_cloud_init_iso(
                user_data, meta_data=meta_data, output_path=temp_iso
            )

            # Remove existing ISO if it exists (may be owned by libvirt-qemu)
            if iso_path.exists():
                try:
                    iso_path.unlink()
                except PermissionError:
                    try:
                        os.chmod(iso_path, 0o666)
                        iso_path.unlink()
                    except (PermissionError, OSError):
                        raise RuntimeError(
                            f"Cannot remove existing ISO file {iso_path}. "
                            f"It may be owned by libvirt-qemu. Remove it manually with: "
                            f"sudo rm {iso_path}"
                        )

            # Move temp ISO to final location
            shutil.move(str(temp_iso), str(iso_path))
        except Exception:
            # Clean up temp file on error
            if temp_iso.exists():
                try:
                    temp_iso.unlink()
                except Exception:
                    pass
            raise

        # Set permissions for libvirt
        DiskManager.fix_disk_permissions(iso_path)

        # Attach ISO to VM
        logger.info(f"Attaching cloud-init ISO to VM...")
        CloudInitManager.attach_cloud_init_iso_to_vm(args.name, iso_path, uri)
        logger.info(f"✓ Cloud-init ISO attached")

        print(f"\n✓ Cloud-init configuration fixed!")
        print(f"The VM will no longer try to connect to network metadata services.")

        # Start VM if it was running before (automatic) or if explicitly requested
        if was_running:
            logger.info(f"\nStarting VM '{args.name}' (was running before)...")
            with VMManager(uri) as manager:
                manager.start_vm(args.name)
            logger.info(f"✓ VM started")
            print(f"\nThe metadata service warnings should be gone on next boot.")
        elif args.start:
            logger.info(f"\nStarting VM '{args.name}'...")
            with VMManager(uri) as manager:
                manager.start_vm(args.name)
            logger.info(f"✓ VM started")
            print(f"\nThe metadata service warnings should be gone on next boot.")

    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
