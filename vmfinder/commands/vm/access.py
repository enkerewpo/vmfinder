"""VM access commands: console, ssh, set-password."""

import sys
import os
import shutil
import getpass
import time
import shlex
from pathlib import Path

from vmfinder.config import Config
from vmfinder.vm_manager import VMManager
from vmfinder.disk import DiskManager
from vmfinder.cloud_init import CloudInitManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_vm_console(args):
    """Connect to console for a virtual machine."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        with VMManager(uri) as manager:
            console_cmd = manager.get_console(args.name)
            if console_cmd:
                # Print help information
                print("To exit console, press: Ctrl+]")
                print(f"\nConnecting to console in 2 seconds...")
                sys.stdout.flush()

                # Wait 2 seconds
                time.sleep(2)

                # Parse and execute the console command
                cmd_parts = shlex.split(console_cmd)
                virsh_path = shutil.which("virsh")
                if not virsh_path:
                    logger.error(
                        "virsh command not found. Please install libvirt-client."
                    )
                    sys.exit(1)

                # Replace 'virsh' with full path
                cmd_parts[0] = virsh_path

                # Clean up logging handlers to prevent interference with console terminal
                import logging

                root_logger = logging.getLogger("vmfinder")
                for handler in root_logger.handlers[:]:
                    if (
                        isinstance(handler, logging.StreamHandler)
                        and handler.stream == sys.stdout
                    ):
                        root_logger.removeHandler(handler)

                # Flush all streams to ensure clean terminal state before exec
                sys.stdout.flush()
                sys.stderr.flush()

                # Execute console command directly
                os.execve(virsh_path, cmd_parts, os.environ)
            else:
                print("Console not available for this VM.")
                print(f"Try: virsh -c {uri} vncdisplay {args.name}")
                sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_ssh(args):
    """Connect to a VM via SSH."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    try:
        with VMManager(uri) as manager:
            # Check if VM exists
            if not manager.vm_exists(args.name):
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)

            # Get VM info
            info = manager.get_vm_info(args.name)
            if not info:
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)

            # Check if VM is running
            if info["state"] != "running":
                logger.warning(
                    f"VM '{args.name}' is not running (state: {info['state']})."
                )
                print("Start the VM first with: vmfinder vm start " + args.name)
                print("\nOnce started, you can get IP address using:")
                print("  virsh domifaddr " + args.name)
                sys.exit(1)

            # Get IP addresses
            ip_addresses = manager.get_vm_ip_addresses(args.name)

            # Filter IPv4 addresses
            ipv4_addresses = [
                ip_info for ip_info in ip_addresses if ip_info.get("type") == "ipv4"
            ]

            if not ipv4_addresses:
                logger.error(f"Could not determine IP address for VM '{args.name}'.")
                print("\nThe VM is running but IP address is not available yet.")
                print("This can happen if:")
                print("  - The VM is still booting (wait a few seconds)")
                print("  - The VM doesn't have network access")
                print("  - DHCP lease is not available")
                print("\nYou can try:")
                print(f"  virsh domifaddr {args.name}")
                print("\nOr connect via console:")
                print(f"  vmfinder vm console {args.name}")
                sys.exit(1)

            # Use the first IPv4 address
            ip_addr = ipv4_addresses[0]["ip"]

            # Check if ssh command exists
            ssh_path = shutil.which("ssh")
            if not ssh_path:
                logger.error("ssh command not found. Please install OpenSSH client.")
                sys.exit(1)

            # Build SSH command
            # Use -t to force pseudo-terminal allocation (required for mouse and scroll support)
            ssh_cmd_parts = [ssh_path, "-t"]
            if args.key:
                ssh_cmd_parts.extend(["-i", args.key])
            if args.port != 22:
                ssh_cmd_parts.extend(["-p", str(args.port)])
            ssh_cmd_parts.append(f"{args.username}@{ip_addr}")

            # Clean up logging handlers to prevent interference with SSH terminal
            # Remove all stdout handlers to avoid ANSI escape sequences interfering
            import logging

            root_logger = logging.getLogger("vmfinder")
            for handler in root_logger.handlers[:]:
                if (
                    isinstance(handler, logging.StreamHandler)
                    and handler.stream == sys.stdout
                ):
                    root_logger.removeHandler(handler)

            # Output brief connection info to stderr (won't interfere with SSH)
            print(
                f"Connecting to {args.username}@{ip_addr}...",
                file=sys.stderr,
                flush=True,
            )

            # Flush all streams to ensure clean terminal state before exec
            sys.stdout.flush()
            sys.stderr.flush()

            # Execute SSH command directly
            # Use os.execve to replace the current process with ssh, preserving environment
            # This ensures SSH gets clean stdin/stdout/stderr without interference
            os.execve(ssh_path, ssh_cmd_parts, os.environ)

    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_set_password(args):
    """Set password for a VM using cloud-init."""
    config = Config()
    uri = config.get("libvirt_uri", "qemu:///system")

    # Get password if not provided
    if not args.password:
        password = getpass.getpass("Password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            logger.error("Passwords do not match.")
            sys.exit(1)
    else:
        password = args.password

    try:
        # Check if VM exists
        with VMManager(uri) as manager:
            if not manager.vm_exists(args.name):
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)

            # Stop VM if running
            try:
                info = manager.get_vm_info(args.name)
                if info and info["state"] == "running":
                    logger.info(f"Stopping VM '{args.name}'...")
                    manager.stop_vm(args.name, force=True)
                    logger.info(f"✓ VM stopped")
            except Exception as e:
                logger.warning(f"Could not stop VM: {e}")

        # Create cloud-init ISO
        logger.info(f"Creating cloud-init ISO for password setup...")
        storage_dir = config.get_storage_dir()
        iso_path = storage_dir / f"{args.name}-cloud-init.iso"

        # Create ISO with a temporary name first to avoid permission issues
        import tempfile

        temp_iso = Path(tempfile.mktemp(suffix=".iso", dir=str(storage_dir)))

        try:
            user_data = CloudInitManager.create_password_config(args.username, password)
            CloudInitManager.create_cloud_init_iso(user_data, output_path=temp_iso)

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

        # Start VM if requested
        if args.start:
            # Check for virtio-fs devices and start virtiofsd if needed
            with VMManager(uri) as manager:
                virtiofs_devices = manager.list_virtiofs_devices(args.name)

                if virtiofs_devices:
                    from vmfinder.virtiofsd import VirtiofsdManager

                    virtiofs_manager = VirtiofsdManager(config.config_dir)

                    # Check if virtiofsd is already running
                    if not virtiofs_manager.is_running(args.name):
                        # Get source path from state
                        status = virtiofs_manager.get_status(args.name)
                        if status:
                            source_path = Path(status.get("source_path", ""))
                            mount_tag = status.get("mount_tag", "shared")

                            if source_path.exists():
                                logger.info(
                                    f"Starting virtiofsd for VM '{args.name}'..."
                                )
                                virtiofs_manager.start_virtiofsd(
                                    vm_name=args.name,
                                    source_path=source_path,
                                    mount_tag=mount_tag,
                                )
                            else:
                                logger.error(
                                    f"virtio-fs source path not found: {source_path}. "
                                    f"Cannot start virtiofsd."
                                )
                                logger.error(
                                    f"Please start virtiofsd manually with: "
                                    f"vmfinder virtiofs start {args.name} <source_path>"
                                )
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
                                f"\nThen run this command again: vmfinder vm set-password {args.name}"
                            )
                            sys.exit(1)

            logger.info(f"Starting VM '{args.name}'...")
            with VMManager(uri) as manager:
                manager.start_vm(args.name)
            logger.info(f"✓ VM started")
            print(f"\nPassword has been set!")
            print(f"  Username: {args.username}")
            print(f"  Password: {password}")
            print(f"\nYou can now login using:")
            print(f"  vmfinder vm console {args.name}")
            print(f"  # Then login with username: {args.username}")

    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
