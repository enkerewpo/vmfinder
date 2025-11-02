"""Template management for OS images."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any

from vmfinder.default_templates import DEFAULT_TEMPLATES


class TemplateManager:
    """Manages VM templates for different OS versions."""

    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._templates = {}
        self._load_templates()

    def _load_templates(self):
        """Load templates from directory."""
        for template_file in self.templates_dir.glob("*.yaml"):
            try:
                with open(template_file, "r") as f:
                    template = yaml.safe_load(f)
                    template_name = template.get("name", template_file.stem)
                    self._templates[template_name] = template
            except Exception as e:
                print(f"Warning: Failed to load template {template_file}: {e}")

    def _version_key(self, version: str) -> tuple:
        """Convert version string to a sortable tuple.

        Handles versions like "16.04", "20.04", "7", "38", etc.
        """
        try:
            # Try to parse as decimal version (e.g., "16.04", "20.04")
            parts = version.split(".")
            return tuple(int(p) for p in parts)
        except ValueError:
            # Fallback to string comparison
            return (float("inf"), version)

    def list_templates(self) -> List[Dict[str, Any]]:
        """List all available templates, sorted by OS and version."""
        templates = []
        for name, template in self._templates.items():
            templates.append(
                {
                    "name": name,
                    "os": template.get("os", "unknown"),
                    "version": template.get("version", "unknown"),
                    "arch": template.get("arch", "x86_64"),
                    "description": template.get("description", ""),
                }
            )

        # Sort by OS first, then by version
        templates.sort(key=lambda t: (t["os"], self._version_key(t["version"])))
        return templates

    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a template by name."""
        return self._templates.get(name)

    def create_template(self, name: str, template: Dict[str, Any]):
        """Create or update a template."""
        template["name"] = name
        template_file = self.templates_dir / f"{name}.yaml"
        with open(template_file, "w") as f:
            yaml.dump(template, f, default_flow_style=False)
        self._templates[name] = template

    def delete_template(self, name: str) -> bool:
        """Delete a template."""
        template_file = self.templates_dir / f"{name}.yaml"
        if template_file.exists():
            template_file.unlink()
            self._templates.pop(name, None)
            return True
        return False

    @staticmethod
    def create_default_templates(templates_dir: Path):
        """Create default templates for common OS versions."""
        templates_dir.mkdir(parents=True, exist_ok=True)

        manager = TemplateManager(templates_dir)
        for template in DEFAULT_TEMPLATES:
            manager.create_template(template["name"], template)
