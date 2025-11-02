"""Auto-completion support for VMFinder CLI."""

import os
from typing import List


def get_vm_names() -> List[str]:
    """Get list of VM names for completion."""
    try:
        from vmfinder.config import Config
        from vmfinder.vm_manager import VMManager
        
        config = Config()
        uri = config.get('libvirt_uri', 'qemu:///system')
        
        with VMManager(uri) as manager:
            vms = manager.list_vms()
            return [vm['name'] for vm in vms]
    except Exception:
        # If we can't get VM names, return empty list
        return []


def get_template_names() -> List[str]:
    """Get list of template names for completion."""
    try:
        from vmfinder.config import Config
        from vmfinder.template import TemplateManager
        
        config = Config()
        manager = TemplateManager(config.templates_dir)
        templates = manager.list_templates()
        return [t['name'] for t in templates]
    except Exception:
        # If we can't get template names, return empty list
        return []


def get_network_names() -> List[str]:
    """Get list of network names for completion."""
    try:
        from vmfinder.config import Config
        import libvirt
        
        config = Config()
        uri = config.get('libvirt_uri', 'qemu:///system')
        
        conn = libvirt.open(uri)
        if conn is None:
            return []
        
        try:
            networks = conn.listAllNetworks()
            names = [net.name() for net in networks]
            conn.close()
            return names
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return []
    except Exception:
        return []


def complete_vm_name(prefix, parsed_args, **kwargs) -> List[str]:
    """Completion function for VM name arguments."""
    vm_names = get_vm_names()
    return [name for name in vm_names if name.startswith(prefix)]


def complete_template_name(prefix, parsed_args, **kwargs) -> List[str]:
    """Completion function for template name arguments."""
    template_names = get_template_names()
    return [name for name in template_names if name.startswith(prefix)]


def complete_network_name(prefix, parsed_args, **kwargs) -> List[str]:
    """Completion function for network name arguments."""
    network_names = get_network_names()
    return [name for name in network_names if name.startswith(prefix)]


def complete_file_path(prefix, parsed_args, **kwargs) -> List[str]:
    """Completion function for file path arguments."""
    # Expand ~ to home directory
    original_prefix = prefix
    if prefix.startswith('~'):
        expanded_prefix = os.path.expanduser(prefix)
    else:
        expanded_prefix = prefix
    
    # Get directory and filename
    dirname = os.path.dirname(expanded_prefix) or '.'
    basename = os.path.basename(expanded_prefix)
    
    try:
        if not os.path.exists(dirname):
            return []
        
        completions = []
        for item in os.listdir(dirname):
            if item.startswith(basename):
                item_path = os.path.join(dirname, item)
                if os.path.isdir(item_path):
                    completions.append(item + '/')
                else:
                    completions.append(item)
        
        # Convert back to relative paths if original was relative
        if original_prefix.startswith('~'):
            home = os.path.expanduser('~')
            completions = [
                os.path.join(os.path.dirname(original_prefix) or '~', item).replace(home, '~', 1)
                if dirname.startswith(home) else item
                for item in completions
            ]
        
        return completions
    except Exception:
        return []

