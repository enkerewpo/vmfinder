"""Cloud-init support for VMs."""

import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import Optional
import os


class CloudInitManager:
    """Manages cloud-init configuration for VMs."""

    @staticmethod
    def create_cloud_init_iso(
        user_data: str,
        meta_data: Optional[str] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Create a cloud-init ISO with user-data and meta-data.

        Args:
            user_data: Cloud-init user-data content (YAML)
            meta_data: Optional cloud-init meta-data content (YAML)
            output_path: Optional output path for ISO, otherwise creates temp file

        Returns:
            Path to created ISO file
        """
        if output_path is None:
            output_path = Path(tempfile.mktemp(suffix=".iso"))

        # Create temporary directory for cloud-init data
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            user_data_path = temp_path / "user-data"
            meta_data_path = temp_path / "meta-data"

            # Write user-data
            user_data_path.write_text(user_data)

            # Write meta-data (minimal if not provided)
            if meta_data is None:
                meta_data = """instance-id: iid-local01
local-hostname: cloudimg
"""
            meta_data_path.write_text(meta_data)

            # Create ISO using genisoimage or mkisofs
            # Check for genisoimage first
            genisoimage_cmd = shutil.which("genisoimage")
            mkisofs_cmd = shutil.which("mkisofs")

            if genisoimage_cmd:
                try:
                    # Change to temp directory and create ISO from current directory
                    subprocess.run(
                        [
                            genisoimage_cmd,
                            "-o",
                            str(output_path),
                            "-volid",
                            "cidata",
                            "-joliet",
                            "-rock",
                            "user-data",
                            "meta-data",
                        ],
                        check=True,
                        cwd=str(temp_path),
                        capture_output=True,
                        text=True,
                    )
                except subprocess.CalledProcessError as e:
                    # If genisoimage fails, try mkisofs
                    if mkisofs_cmd:
                        try:
                            subprocess.run(
                                [
                                    mkisofs_cmd,
                                    "-o",
                                    str(output_path),
                                    "-V",
                                    "cidata",
                                    "-J",
                                    "-r",
                                    "user-data",
                                    "meta-data",
                                ],
                                check=True,
                                cwd=str(temp_path),
                                capture_output=True,
                                text=True,
                            )
                        except subprocess.CalledProcessError as e2:
                            raise RuntimeError(
                                f"Failed to create ISO with both genisoimage and mkisofs. "
                                f"genisoimage error: {e.stderr}, mkisofs error: {e2.stderr}"
                            )
                    else:
                        raise RuntimeError(
                            f"genisoimage failed: {e.stderr}. "
                            "mkisofs not found. Install with: sudo apt install genisoimage"
                        )
            elif mkisofs_cmd:
                try:
                    subprocess.run(
                        [
                            mkisofs_cmd,
                            "-o",
                            str(output_path),
                            "-V",
                            "cidata",
                            "-J",
                            "-r",
                            "user-data",
                            "meta-data",
                        ],
                        check=True,
                        cwd=str(temp_path),
                        capture_output=True,
                        text=True,
                    )
                except subprocess.CalledProcessError as e:
                    raise RuntimeError(f"Failed to create ISO with mkisofs: {e.stderr}")
            else:
                raise RuntimeError(
                    "Neither genisoimage nor mkisofs found. "
                    "Install with: sudo apt install genisoimage"
                )

        return output_path

    @staticmethod
    def create_password_config(
        username: str = "ubuntu", password: str = "ubuntu"
    ) -> str:
        """Create cloud-init user-data for setting password.

        Args:
            username: Username to set password for
            password: Password to set

        Returns:
            Cloud-init user-data YAML string
        """
        # Use chpasswd which accepts plaintext password
        user_data = f"""#cloud-config
users:
  - name: {username}
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false

chpasswd:
  list: |
    {username}:{password}
  expire: false

ssh_pwauth: true
disable_root: false
"""
        return user_data

    @staticmethod
    def attach_cloud_init_iso_to_vm(
        vm_name: str, iso_path: Path, uri: str = "qemu:///system"
    ):
        """Attach cloud-init ISO to a VM.

        Note: This modifies the VM XML configuration. The VM should be stopped.
        """
        import libvirt
        import xml.etree.ElementTree as ET

        conn = libvirt.open(uri)
        if conn is None:
            raise RuntimeError(f"Failed to open connection to {uri}")

        try:
            dom = conn.lookupByName(vm_name)

            # Get current XML
            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)

            devices = root.find("devices")
            if devices is None:
                devices = ET.SubElement(root, "devices")

            # Normalize paths for comparison
            iso_path_str = str(iso_path.resolve())
            cloud_init_pattern = f"{vm_name}-cloud-init.iso"

            # Find all existing cloud-init ISO devices and remove them
            # Also check for devices using 'hda' target that might conflict
            disks_to_remove = []
            existing_cloud_init_disk = None

            for disk in devices.findall("disk"):
                if disk.get("type") == "file" and disk.get("device") == "cdrom":
                    source = disk.find("source")
                    if source is not None:
                        source_file = source.get("file", "")
                        source_file_normalized = (
                            str(Path(source_file).resolve()) if source_file else ""
                        )

                        # Check if this is a cloud-init ISO (by filename pattern or 'cidata' in path)
                        is_cloud_init = (
                            cloud_init_pattern in source_file
                            or "cidata" in source_file.lower()
                            or "-cloud-init.iso" in source_file
                        )

                        if is_cloud_init:
                            # If it's the same file, we can update it
                            if source_file_normalized == iso_path_str:
                                existing_cloud_init_disk = disk
                            else:
                                # Different cloud-init ISO, remove it
                                disks_to_remove.append(disk)
                        else:
                            # Check if this CD-ROM device uses 'hda' target (conflict)
                            target = disk.find("target")
                            if target is not None and target.get("dev") == "hda":
                                # If it's not a cloud-init ISO but uses hda, we need to use a different target
                                # For now, remove conflicting non-cloud-init CD-ROMs using hda
                                # (This is rare, but can happen)
                                if (
                                    not source_file
                                    or "cloud-init" not in source_file.lower()
                                ):
                                    disks_to_remove.append(disk)

            # Remove old/conflicting disks
            for disk in disks_to_remove:
                devices.remove(disk)

            # Update existing device or create new one
            if existing_cloud_init_disk is not None:
                # Update existing cloud-init ISO device
                source = existing_cloud_init_disk.find("source")
                if source is not None:
                    source.set("file", str(iso_path))
                target = existing_cloud_init_disk.find("target")
                if target is not None:
                    target.set("dev", "hda")
                else:
                    # Create target element if it doesn't exist
                    target = ET.SubElement(
                        existing_cloud_init_disk, "target", dev="hda", bus="ide"
                    )
            else:
                # Add new CD-ROM device for cloud-init ISO
                cdrom = ET.SubElement(devices, "disk", type="file", device="cdrom")
                driver = ET.SubElement(cdrom, "driver", name="qemu", type="raw")
                source = ET.SubElement(cdrom, "source", file=str(iso_path))
                target = ET.SubElement(cdrom, "target", dev="hda", bus="ide")
                readonly = ET.SubElement(cdrom, "readonly")

            # Update VM configuration
            conn.defineXML(ET.tostring(root).decode())

        finally:
            conn.close()
