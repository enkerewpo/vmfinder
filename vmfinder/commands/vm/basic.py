"""Basic VM operations: list, start, stop, suspend, resume, restart."""

import sys
from tabulate import tabulate

from vmfinder.config import Config
from vmfinder.vm_manager import VMManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_vm_list(args):
    """List all virtual machines."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            vms = manager.list_vms()
            
            if not vms:
                logger.info("No VMs found.")
                return
            
            headers = ['Name', 'State', 'CPU', 'Memory (MB)', 'Max Memory (MB)']
            rows = []
            for vm in vms:
                if 'error' in vm:
                    rows.append([vm['name'], f"error: {vm.get('error', 'unknown')}", '-', '-', '-'])
                else:
                    rows.append([
                        vm['name'],
                        vm['state'],
                        vm.get('cpu', '-'),
                        f"{vm.get('memory', 0):.0f}",
                        f"{vm.get('max_memory', 0):.0f}",
                    ])
            print(tabulate(rows, headers=headers, tablefmt='grid'))
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_start(args):
    """Start a virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.start_vm(args.name):
                logger.info(f"✓ Started VM: {args.name}")
            else:
                logger.warning(f"VM {args.name} is already running or in an invalid state.")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_stop(args):
    """Stop a virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.stop_vm(args.name, args.force):
                action = "destroyed" if args.force else "stopped"
                logger.info(f"✓ {action.capitalize()} VM: {args.name}")
            else:
                logger.warning(f"VM {args.name} is already stopped.")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_suspend(args):
    """Suspend a virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.suspend_vm(args.name):
                logger.info(f"✓ Suspended VM: {args.name}")
            else:
                logger.warning(f"VM {args.name} cannot be suspended (not running or invalid state).")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_resume(args):
    """Resume a suspended virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.resume_vm(args.name):
                logger.info(f"✓ Resumed VM: {args.name}")
            else:
                logger.warning(f"VM {args.name} cannot be resumed (not suspended).")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_restart(args):
    """Restart a virtual machine (stop and start)."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            # Check if VM is running
            info = manager.get_vm_info(args.name)
            if not info:
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)
            
            # Stop VM if running
            if info['state'] == 'running':
                logger.info(f"Stopping VM '{args.name}'...")
                if manager.stop_vm(args.name, args.force):
                    action = "destroyed" if args.force else "stopped"
                    logger.info(f"✓ {action.capitalize()} VM: {args.name}")
                else:
                    logger.warning(f"VM {args.name} is already stopped.")
            
            # Start VM
            logger.info(f"Starting VM '{args.name}'...")
            if manager.start_vm(args.name):
                logger.info(f"✓ Started VM: {args.name}")
            else:
                logger.warning(f"VM {args.name} may already be running or in an invalid state.")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

