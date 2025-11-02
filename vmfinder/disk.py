"""Disk management for VMs."""

import os
import json
import subprocess
import grp
from pathlib import Path
from typing import Optional


class DiskManager:
    """Manages VM disk images."""

    @staticmethod
    def _set_libvirt_permissions(disk_path: Path):
        """Set file permissions so libvirt can access the disk.

        Tries multiple methods in order:
        1. ACL (Access Control List) - doesn't require root, preferred method
        2. Group ownership change - requires root or group membership
        3. World-readable fallback - least secure
        """
        # First, try using ACL (doesn't require root/sudo)
        try:
            # Ensure parent directories are accessible
            parent_dir = disk_path.parent
            while parent_dir != parent_dir.parent:  # Stop at filesystem root
                try:
                    # Set execute permission for libvirt-qemu to traverse directory
                    for qemu_user in ["libvirt-qemu", "qemu", "kvm"]:
                        subprocess.run(
                            ["setfacl", "-m", f"u:{qemu_user}:rx", str(parent_dir)],
                            check=False,
                            capture_output=True,
                        )
                except Exception:
                    pass
                parent_dir = parent_dir.parent

            # Try to use setfacl to give libvirt-qemu user access to the file
            # Common libvirt-qemu user names
            for qemu_user in ["libvirt-qemu", "qemu", "kvm"]:
                try:
                    # Set ACL for the file
                    subprocess.run(
                        ["setfacl", "-m", f"u:{qemu_user}:rw", str(disk_path)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    # Set mask to rw- to ensure effective permissions
                    subprocess.run(
                        ["setfacl", "-m", "m::rw-", str(disk_path)],
                        check=False,
                        capture_output=True,
                    )
                    os.chmod(disk_path, 0o640)
                    return  # Success with ACL
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue
        except Exception:
            pass

        # If ACL failed, try changing group ownership
        try:
            # libvirt-qemu process runs in kvm group typically
            # Try to find the correct group for libvirt-qemu process
            qemu_group = None
            for group_name in ["kvm", "qemu", "libvirt-qemu", "libvirt"]:
                try:
                    qemu_group = grp.getgrnam(group_name)
                    break
                except KeyError:
                    continue

            if qemu_group:
                # Try to change group ownership (requires root or user is in the group)
                try:
                    os.chown(disk_path, -1, qemu_group.gr_gid)
                    os.chmod(disk_path, 0o660)
                    return  # Success with group ownership
                except (PermissionError, OSError):
                    # Can't change group, fall through to next method
                    pass
        except Exception:
            pass

        # Last resort: make it readable by others (less secure but may work)
        try:
            os.chmod(disk_path, 0o644)
        except (PermissionError, OSError):
            pass

    @staticmethod
    def create_disk(disk_path: Path, size_gb: int = 20, format: str = "qcow2") -> bool:
        """Create a new disk image."""
        disk_path.parent.mkdir(parents=True, exist_ok=True)

        if disk_path.exists():
            raise ValueError(f"Disk {disk_path} already exists")

        # Use qemu-img to create disk
        cmd = ["qemu-img", "create", "-f", format, str(disk_path), f"{size_gb}G"]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            # Set permissions so libvirt can access it
            DiskManager._set_libvirt_permissions(disk_path)
            return True
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create disk: {e.stderr.decode()}")
        except FileNotFoundError:
            raise RuntimeError("qemu-img not found. Please install qemu-utils.")

    @staticmethod
    def get_disk_info(disk_path: Path) -> Optional[dict]:
        """Get information about a disk image."""
        if not disk_path.exists():
            return None

        cmd = ["qemu-img", "info", str(disk_path), "--output=json"]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            info = json.loads(result.stdout)
            return {
                "format": info.get("format"),
                "virtual_size": info.get("virtual-size", 0) / (1024**3),  # GB
                "actual_size": info.get("actual-size", 0) / (1024**2),  # MB
            }
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return None

    @staticmethod
    def fix_disk_permissions(disk_path: Path) -> bool:
        """Fix permissions for an existing disk file so libvirt can access it.

        This is useful when a disk file already exists but has incorrect permissions.
        Returns True if permissions were successfully set, False otherwise.
        """
        if not disk_path.exists():
            return False
        try:
            DiskManager._set_libvirt_permissions(disk_path)
            return True
        except Exception:
            return False

    @staticmethod
    def delete_disk(disk_path: Path) -> bool:
        """Delete a disk image."""
        if disk_path.exists():
            disk_path.unlink()
            return True
        return False

    @staticmethod
    def resize_disk(disk_path: Path, size_gb: int) -> bool:
        """Resize a disk image.

        This only resizes the disk image file itself. After resizing,
        you need to manually expand the partition and filesystem inside the VM.
        """
        if not disk_path.exists():
            raise ValueError(f"Disk {disk_path} does not exist")

        # Get current size to check if we're expanding or shrinking
        current_info = DiskManager.get_disk_info(disk_path)
        if current_info:
            current_size_gb = current_info["virtual_size"]
            if size_gb < current_size_gb:
                raise ValueError(
                    f"Cannot shrink disk from {current_size_gb:.1f}GB to {size_gb}GB. "
                    f"Shrinking is not supported for data safety."
                )

        cmd = ["qemu-img", "resize", str(disk_path), f"{size_gb}G"]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            # Fix permissions after resize
            DiskManager._set_libvirt_permissions(disk_path)
            return True
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to resize disk: {e.stderr.decode()}")
