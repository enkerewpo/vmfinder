"""Cloud image download and management."""

import hashlib
import os
import subprocess
import grp
from pathlib import Path
from typing import Optional, Dict

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    import urllib.request


class CloudImageManager:
    """Manages cloud image downloads and caching."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

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

    def get_cloud_image_url(self, template_data: Dict) -> Optional[str]:
        """Get cloud image URL from template data."""
        return template_data.get("cloud_image_url")

    def get_cached_image_path(self, template_name: str, url: str) -> Path:
        """Get path to cached cloud image."""
        # Use URL hash for filename to handle updates
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        filename = f"{template_name}-{url_hash}.qcow2"
        return self.cache_dir / filename

    def download_cloud_image(
        self, template_name: str, template_data: Dict, echo_func=None
    ) -> Path:
        """Download cloud image with resume support if not already cached."""
        url = self.get_cloud_image_url(template_data)
        if not url:
            raise ValueError(f"No cloud image URL in template: {template_name}")

        cached_path = self.get_cached_image_path(template_name, url)
        temp_path = cached_path.with_suffix(cached_path.suffix + ".tmp")

        if cached_path.exists():
            if echo_func:
                echo_func(f"Using cached cloud image: {cached_path}")
            return cached_path

        # Check if there's a partial download
        resume_pos = 0
        if temp_path.exists():
            resume_pos = temp_path.stat().st_size
            if echo_func:
                echo_func(f"Resuming download from {resume_pos} bytes...")

        if echo_func:
            echo_func(f"Downloading cloud image from {url}...")
            if resume_pos > 0:
                echo_func(f"Resuming from {resume_pos:,} bytes...")
            else:
                echo_func("This may take a few minutes depending on your connection...")

        try:
            if REQUESTS_AVAILABLE:
                # Use requests for better resume support
                # Add browser-like headers to avoid 403 errors from some mirror sites
                headers = {
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "identity",  # Don't use compression for binary files
                    "Connection": "keep-alive",
                }
                if resume_pos > 0:
                    headers["Range"] = f"bytes={resume_pos}-"

                # Create a session for better connection handling
                session = requests.Session()
                session.headers.update(headers)

                response = session.get(
                    url, stream=True, timeout=30, allow_redirects=True
                )
                response.raise_for_status()

                # Get total size if available
                total_size = None
                if "Content-Range" in response.headers:
                    # Server supports range requests
                    content_range = response.headers["Content-Range"]
                    if "/" in content_range:
                        total_size = int(content_range.split("/")[1])
                elif "Content-Length" in response.headers:
                    total_size = int(response.headers["Content-Length"])
                    if resume_pos > 0:
                        total_size += resume_pos

                # Open file in append mode if resuming, otherwise create new
                mode = "ab" if resume_pos > 0 else "wb"
                with open(temp_path, mode) as f:
                    downloaded = resume_pos
                    last_percent = -1

                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                            # Show progress
                            if total_size and echo_func:
                                percent = min(100, (downloaded * 100) // total_size)
                                if percent != last_percent and percent % 10 == 0:
                                    echo_func(
                                        f"Progress: {percent}% ({downloaded:,}/{total_size:,} bytes)"
                                    )
                                    last_percent = percent
                            elif echo_func and downloaded % (10 * 1024 * 1024) == 0:
                                # Show progress every 10MB if total size unknown
                                echo_func(f"Downloaded: {downloaded:,} bytes...")

                # Rename temp file to final name
                temp_path.rename(cached_path)

            else:
                # Fallback to urllib (no resume support)
                if resume_pos > 0:
                    if echo_func:
                        echo_func(
                            "Warning: urllib doesn't support resume. Starting from beginning..."
                        )
                    temp_path.unlink()

                last_percent = [0]

                def show_progress(block_num, block_size, total_size):
                    if total_size > 0:
                        percent = min(100, (block_num * block_size * 100) // total_size)
                        if (
                            percent != last_percent[0]
                            and percent % 10 == 0
                            and echo_func
                        ):
                            echo_func(f"Progress: {percent}%")
                            last_percent[0] = percent

                urllib.request.urlretrieve(url, temp_path, reporthook=show_progress)
                temp_path.rename(cached_path)

            if echo_func:
                echo_func(f"✓ Downloaded cloud image: {cached_path}")
            return cached_path

        except Exception as e:
            # Keep partial download for resume
            if temp_path.exists() and temp_path.stat().st_size > 0:
                if echo_func:
                    echo_func(
                        f"Download interrupted. Partial file saved. "
                        f"Run again to resume from {temp_path.stat().st_size:,} bytes."
                    )
            raise RuntimeError(f"Failed to download cloud image: {e}")

    def create_disk_from_cloud_image(
        self, cloud_image_path: Path, disk_path: Path, size_gb: int
    ) -> bool:
        """Create a VM disk from cloud image with specified size.

        The disk will be created with the exact size specified. The cloud image
        will be copied and then the disk will be resized to the target size.
        Note: The file system inside will be automatically expanded on first boot
        by cloud-init's growpart feature (for Ubuntu/Debian cloud images).
        """
        disk_path.parent.mkdir(parents=True, exist_ok=True)

        if disk_path.exists():
            raise ValueError(f"Disk {disk_path} already exists")

        try:
            # First, get the original image size to check if we need to resize
            result = subprocess.run(
                ["qemu-img", "info", "--output=json", str(cloud_image_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            import json

            info = json.loads(result.stdout)
            original_size_gb = info.get("virtual-size", 0) / (1024**3)

            # Copy the cloud image to the target disk
            # Use sparse copy (qcow2) which is efficient
            subprocess.run(
                [
                    "qemu-img",
                    "convert",
                    "-f",
                    "qcow2",
                    "-O",
                    "qcow2",
                    str(cloud_image_path),
                    str(disk_path),
                ],
                check=True,
                capture_output=True,
            )

            # Always resize to the exact size requested
            # This ensures the disk is exactly the size the user specified
            if (
                abs(size_gb - original_size_gb) > 0.1
            ):  # Allow small floating point differences
                subprocess.run(
                    ["qemu-img", "resize", str(disk_path), f"{size_gb}G"],
                    check=True,
                    capture_output=True,
                )

            # Verify the final size
            result = subprocess.run(
                ["qemu-img", "info", "--output=json", str(disk_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            info = json.loads(result.stdout)
            final_size_gb = info.get("virtual-size", 0) / (1024**3)

            # The disk size should match (within reasonable tolerance)
            if abs(final_size_gb - size_gb) > 0.1:
                raise RuntimeError(
                    f"Disk size mismatch: expected {size_gb}GB, got {final_size_gb:.2f}GB"
                )

            # Set permissions so libvirt can access the disk
            CloudImageManager._set_libvirt_permissions(disk_path)

            return True
        except subprocess.CalledProcessError as e:
            # Clean up on error
            if disk_path.exists():
                disk_path.unlink()
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise RuntimeError(f"Failed to create disk from cloud image: {error_msg}")
        except FileNotFoundError:
            raise RuntimeError("qemu-img not found. Please install qemu-utils.")
