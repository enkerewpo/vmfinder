"""VM command modules."""

# Import all VM command functions
from vmfinder.commands.vm.basic import (
    cmd_vm_list,
    cmd_vm_start,
    cmd_vm_stop,
    cmd_vm_suspend,
    cmd_vm_resume,
    cmd_vm_restart,
)
from vmfinder.commands.vm.manage import (
    cmd_vm_create,
    cmd_vm_delete,
    cmd_vm_info,
)
from vmfinder.commands.vm.config import (
    cmd_vm_set_cpu,
    cmd_vm_set_memory,
    cmd_vm_fix_permissions,
    cmd_vm_resize_disk,
)
from vmfinder.commands.vm.access import (
    cmd_vm_console,
    cmd_vm_ssh,
    cmd_vm_set_password,
)
from vmfinder.commands.vm.cloud_init import (
    cmd_vm_fix_cloud_init,
)

__all__ = [
    'cmd_vm_list',
    'cmd_vm_start',
    'cmd_vm_stop',
    'cmd_vm_suspend',
    'cmd_vm_resume',
    'cmd_vm_restart',
    'cmd_vm_create',
    'cmd_vm_delete',
    'cmd_vm_info',
    'cmd_vm_set_cpu',
    'cmd_vm_set_memory',
    'cmd_vm_fix_permissions',
    'cmd_vm_resize_disk',
    'cmd_vm_console',
    'cmd_vm_ssh',
    'cmd_vm_set_password',
    'cmd_vm_fix_cloud_init',
]

