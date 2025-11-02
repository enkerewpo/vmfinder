"""VM configuration commands: set-cpu, set-memory, fix-permissions, resize-disk."""

import sys
from pathlib import Path

from vmfinder.config import Config
from vmfinder.vm_manager import VMManager
from vmfinder.disk import DiskManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_vm_set_cpu(args):
    """Set CPU count for a virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            manager.set_cpu(args.name, args.cpu)
            logger.info(f"✓ Set CPU count to {args.cpu} for VM: {args.name}")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_set_memory(args):
    """Set memory for a virtual machine (in MB)."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            manager.set_memory(args.name, args.memory)
            logger.info(f"✓ Set memory to {args.memory} MB for VM: {args.name}")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_fix_permissions(args):
    """Fix disk permissions for a VM so libvirt can access it."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        # Get VM info to find disk path
        with VMManager(uri) as manager:
            info = manager.get_vm_info(args.name)
            if not info:
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)
            
            # Get disk paths from VM info
            disks = info.get('disks', [])
            if not disks:
                logger.warning(f"No disks found for VM '{args.name}'.")
                return
            
            # Also try to get disk from storage directory (fallback)
            storage_dir = config.get_storage_dir()
            disk_path = storage_dir / f"{args.name}.qcow2"
            
            fixed = False
            for disk in disks:
                disk_file = disk.get('source')
                if disk_file:
                    disk_path_obj = Path(disk_file)
                    if disk_path_obj.exists():
                        if DiskManager.fix_disk_permissions(disk_path_obj):
                            logger.info(f"✓ Fixed permissions for {disk_file}")
                            fixed = True
                        else:
                            logger.warning(f"Could not fix permissions for {disk_file}")
            
            # Also try the standard storage location
            if disk_path.exists() and disk_path not in [Path(d.get('source')) for d in disks if d.get('source')]:
                if DiskManager.fix_disk_permissions(disk_path):
                    logger.info(f"✓ Fixed permissions for {disk_path}")
                    fixed = True
            
            if not fixed:
                logger.error("Could not automatically fix permissions. You may need to run:")
                for disk in disks:
                    disk_file = disk.get('source')
                    if disk_file:
                        print(f"  sudo chgrp kvm {disk_file}")
                        print(f"  sudo chmod 660 {disk_file}")
                print("Or use ACL:")
                for disk in disks:
                    disk_file = disk.get('source')
                    if disk_file:
                        print(f"  setfacl -m u:libvirt-qemu:rw {disk_file}")
                sys.exit(1)
            else:
                logger.info(f"✓ Permissions fixed successfully for VM '{args.name}'")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_resize_disk(args):
    """Resize a VM's disk image file."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            # Check if VM exists
            info = manager.get_vm_info(args.name)
            if not info:
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)
            
            # Get current disk info
            disks = info.get('disks', [])
            if not disks:
                logger.error(f"No disks found for VM '{args.name}'.")
                sys.exit(1)
            
            # Get current disk size
            disk_path_str = disks[0].get('source')
            if not disk_path_str:
                logger.error(f"Could not determine disk path for VM '{args.name}'.")
                sys.exit(1)
            
            disk_path = Path(disk_path_str)
            current_info = DiskManager.get_disk_info(disk_path)
            if current_info:
                current_size = current_info['virtual_size']
                logger.info(f"Current disk size: {current_size:.1f} GB")
                if args.size <= current_size:
                    logger.error(f"New size ({args.size}GB) must be larger than current size ({current_size:.1f}GB).")
                    sys.exit(1)
            
            logger.info(f"\nResizing disk for VM '{args.name}' to {args.size}GB...")
            
            # Resize the disk
            result = manager.resize_vm_disk(args.name, args.size)
            
            if not result['success']:
                logger.error(f"Failed to resize disk: {result.get('message', 'Unknown error')}")
                sys.exit(1)
            
            logger.info(f"✓ Disk image resized to {args.size}GB")
            
            logger.info(f"\n✓ Disk resize complete!")
            print("\nNote: The disk image has been resized, but you need to manually expand")
            print("      the partition and filesystem inside the VM.")
            
            disk_device = result.get('disk_device', '/dev/vda')
            print("\nTo expand the partition and filesystem inside the VM:")
            step = 1
            if info['state'] != 'running':
                print(f"  {step}. Start the VM: vmfinder vm start {args.name}")
                step += 1
            print(f"  {step}. SSH into the VM: vmfinder vm ssh {args.name}")
            step += 1
            print(f"  {step}. Run: sudo growpart {disk_device} 1")
            step += 1
            print(f"  {step}. Run: sudo resize2fs {disk_device}1  (for ext4)")
            print(f"      or: sudo xfs_growfs /  (for xfs)")
                
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

