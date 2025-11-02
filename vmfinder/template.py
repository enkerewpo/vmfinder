"""Template management for OS images."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any


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
                with open(template_file, 'r') as f:
                    template = yaml.safe_load(f)
                    template_name = template.get('name', template_file.stem)
                    self._templates[template_name] = template
            except Exception as e:
                print(f"Warning: Failed to load template {template_file}: {e}")
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """List all available templates."""
        templates = []
        for name, template in self._templates.items():
            templates.append({
                'name': name,
                'os': template.get('os', 'unknown'),
                'version': template.get('version', 'unknown'),
                'arch': template.get('arch', 'x86_64'),
                'description': template.get('description', ''),
            })
        return templates
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a template by name."""
        return self._templates.get(name)
    
    def create_template(self, name: str, template: Dict[str, Any]):
        """Create or update a template."""
        template['name'] = name
        template_file = self.templates_dir / f"{name}.yaml"
        with open(template_file, 'w') as f:
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
        
        default_templates = [
            {
                'name': 'ubuntu-20.04',
                'os': 'ubuntu',
                'version': '20.04',
                'os_type': 'hvm',
                'os_variant': 'ubuntu20.04',
                'arch': 'x86_64',
                'boot': 'hd',
                'description': 'Ubuntu 20.04 LTS (Focal Fossa)',
                'cloud_image_support': True,
            },
            {
                'name': 'ubuntu-22.04',
                'os': 'ubuntu',
                'version': '22.04',
                'os_type': 'hvm',
                'os_variant': 'ubuntu22.04',
                'arch': 'x86_64',
                'boot': 'hd',
                'description': 'Ubuntu 22.04 LTS (Jammy Jellyfish)',
                'cloud_image_support': True,
            },
            {
                'name': 'ubuntu-24.04',
                'os': 'ubuntu',
                'version': '24.04',
                'os_type': 'hvm',
                'os_variant': 'ubuntu24.04',
                'arch': 'x86_64',
                'boot': 'hd',
                'description': 'Ubuntu 24.04 LTS (Noble Numbat)',
                'cloud_image_support': True,
            },
            {
                'name': 'debian-11',
                'os': 'debian',
                'version': '11',
                'os_type': 'hvm',
                'os_variant': 'debian11',
                'arch': 'x86_64',
                'boot': 'hd',
                'description': 'Debian 11 (Bullseye)',
                'cloud_image_support': True,
            },
            {
                'name': 'debian-12',
                'os': 'debian',
                'version': '12',
                'os_type': 'hvm',
                'os_variant': 'debian12',
                'arch': 'x86_64',
                'boot': 'hd',
                'description': 'Debian 12 (Bookworm)',
                'cloud_image_support': True,
            },
            {
                'name': 'debian-13',
                'os': 'debian',
                'version': '13',
                'os_type': 'hvm',
                'os_variant': 'debian13',
                'arch': 'x86_64',
                'boot': 'hd',
                'description': 'Debian 13 (Trixie)',
                'cloud_image_support': True,
            },
        ]
        
        manager = TemplateManager(templates_dir)
        for template in default_templates:
            manager.create_template(template['name'], template)
