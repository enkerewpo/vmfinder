"""Configuration management for VMFinder."""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """Manages VMFinder configuration."""

    DEFAULT_CONFIG_DIR = Path.home() / ".vmfinder"
    CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
    VMS_DIR = DEFAULT_CONFIG_DIR / "vms"
    TEMPLATES_DIR = DEFAULT_CONFIG_DIR / "templates"

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or self.DEFAULT_CONFIG_DIR
        self.config_file = self.config_dir / "config.yaml"
        self.vms_dir = self.config_dir / "vms"
        self.templates_dir = self.config_dir / "templates"
        self._ensure_dirs()
        self._config = self._load_config()

    def _ensure_dirs(self):
        """Create necessary directories."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.vms_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if self.config_file.exists():
            with open(self.config_file, "r") as f:
                return yaml.safe_load(f) or {}
        return {
            "libvirt_uri": "qemu:///system",
            "default_storage_pool": "default",
            "default_network": "default",
            "storage_dir": str(self.config_dir / "storage"),
            "cache_dir": str(self.config_dir / "cache"),
        }

    def save_config(self):
        """Save configuration to file."""
        with open(self.config_file, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        """Set configuration value."""
        self._config[key] = value
        self.save_config()

    def get_storage_dir(self) -> Path:
        """Get storage directory for VM disks."""
        storage_dir = Path(self.get("storage_dir"))
        storage_dir.mkdir(parents=True, exist_ok=True)
        # Set directory permissions for libvirt access
        try:
            # First try ACL (doesn't require root)
            import subprocess

            for qemu_user in ["libvirt-qemu", "qemu", "kvm"]:
                try:
                    subprocess.run(
                        ["setfacl", "-m", f"u:{qemu_user}:rx", str(storage_dir)],
                        check=False,
                        capture_output=True,
                    )
                    # Also set for parent directories if needed
                    parent = storage_dir.parent
                    while parent != parent.parent:
                        subprocess.run(
                            ["setfacl", "-m", f"u:{qemu_user}:rx", str(parent)],
                            check=False,
                            capture_output=True,
                        )
                        parent = parent.parent
                except Exception:
                    pass

            # Also try group ownership (requires root or group membership)
            import grp

            qemu_group = None
            for group_name in ["kvm", "qemu", "libvirt-qemu", "libvirt"]:
                try:
                    qemu_group = grp.getgrnam(group_name)
                    break
                except KeyError:
                    continue

            if qemu_group:
                try:
                    os.chown(storage_dir, -1, qemu_group.gr_gid)
                    os.chmod(storage_dir, 0o2775)  # Setgid bit + rwxrwxr-x
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError, ImportError):
            pass
        return storage_dir

    def get_cache_dir(self) -> Path:
        """Get cache directory for cloud images."""
        cache_dir = Path(self.get("cache_dir", str(self.config_dir / "cache")))
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir
