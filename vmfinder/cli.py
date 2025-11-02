"""Command-line interface for VMFinder."""

import click
import sys
import os
import tempfile
import shutil
from pathlib import Path
from tabulate import tabulate
import libvirt

from vmfinder.config import Config
from vmfinder.vm_manager import VMManager
from vmfinder.template import TemplateManager, TemplateManager as TM
from vmfinder.disk import DiskManager
from vmfinder.cloud_image import CloudImageManager
from vmfinder.cloud_init import CloudInitManager


@click.group()
@click.pass_context
def cli(ctx):
    """VMFinder - A libvirt-based VM management tool for paper reproduction."""
    ctx.ensure_object(dict)
    ctx.obj['config'] = Config()


@cli.command()
def init():
    """Initialize VMFinder with default templates."""
    config = Config()
    click.echo(f"Initializing VMFinder in {config.config_dir}...")
    
    # Create default templates
    TM.create_default_templates(config.templates_dir)
    
    click.echo(f"✓ Created configuration directory: {config.config_dir}")
    click.echo(f"✓ Created templates directory: {config.templates_dir}")
    click.echo(f"✓ Created default OS templates")
    click.echo("\nYou can now create VMs using: vmfinder create <name> --template <template>")


@cli.group()
def template():
    """Manage VM templates."""
    pass


@template.command('list')
@click.pass_context
def template_list(ctx):
    """List all available templates."""
    config = ctx.obj['config']
    manager = TemplateManager(config.templates_dir)
    templates = manager.list_templates()
    
    if not templates:
        click.echo("No templates found. Run 'vmfinder init' to create default templates.")
        return
    
    headers = ['Name', 'OS', 'Version', 'Arch', 'Description']
    rows = [[t['name'], t['os'], t['version'], t['arch'], t['description']] 
            for t in templates]
    click.echo(tabulate(rows, headers=headers, tablefmt='grid'))


@template.command('create')
@click.argument('name')
@click.option('--os', required=True, help='Operating system name')
@click.option('--version', required=True, help='OS version')
@click.option('--os-variant', help='OS variant for libvirt')
@click.option('--arch', default='x86_64', help='Architecture')
@click.option('--description', help='Template description')
@click.pass_context
def template_create(ctx, name, os, version, os_variant, arch, description):
    """Create a new template."""
    config = ctx.obj['config']
    manager = TemplateManager(config.templates_dir)
    
    template = {
        'os': os,
        'version': version,
        'os_type': 'hvm',
        'os_variant': os_variant or f"{os}{version}",
        'arch': arch,
        'boot': 'hd',
        'description': description or f"{os} {version}",
    }
    
    manager.create_template(name, template)
    click.echo(f"✓ Created template: {name}")


@cli.group()
def vm():
    """Manage virtual machines."""
    pass


@vm.command('list')
@click.pass_context
def vm_list(ctx):
    """List all virtual machines."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            vms = manager.list_vms()
            
            if not vms:
                click.echo("No VMs found.")
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
            click.echo(tabulate(rows, headers=headers, tablefmt='grid'))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('create')
@click.argument('name')
@click.option('--template', '-t', required=True, help='Template name')
@click.option('--cpu', '-c', default=2, type=int, help='Number of CPUs')
@click.option('--memory', '-m', default=2048, type=int, help='Memory in MB')
@click.option('--disk-size', '-d', default=20, type=int, help='Disk size in GB')
@click.option('--network', default='default', help='Network name')
@click.option('--auto-install/--no-auto-install', default=True, help='Automatically install OS from cloud image (default: enabled)')
@click.option('--force', '-f', is_flag=True, help='Force overwrite existing VM without prompting')
@click.pass_context
def vm_create(ctx, name, template, cpu, memory, disk_size, network, auto_install, force):
    """Create a new virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        # Get template
        template_manager = TemplateManager(config.templates_dir)
        template_data = template_manager.get_template(template)
        if not template_data:
            click.echo(f"Error: Template '{template}' not found.", err=True)
            click.echo("Run 'vmfinder template list' to see available templates.", err=True)
            sys.exit(1)
        
        # Check if VM or disk already exists
        storage_dir = config.get_storage_dir()
        disk_path = storage_dir / f"{name}.qcow2"
        
        disk_exists = disk_path.exists()
        
        # Check if VM exists in libvirt
        with VMManager(uri) as manager:
            vm_exists = manager.vm_exists(name)
        
        # If VM or disk exists, prompt for deletion
        if (vm_exists or disk_exists) and not force:
            if vm_exists and disk_exists:
                msg = f"VM '{name}' and its disk already exist. Delete and recreate?"
            elif vm_exists:
                msg = f"VM '{name}' already exists. Delete and recreate?"
            else:
                msg = f"Disk for VM '{name}' already exists. Delete and recreate?"
            
            if not click.confirm(msg, default=True):
                click.echo("Cancelled. Use '--force' to overwrite without prompting.")
                sys.exit(0)
            
            # Delete existing VM if it exists
            if vm_exists:
                click.echo(f"Deleting existing VM '{name}'...")
                try:
                    with VMManager(uri) as manager:
                        manager.delete_vm(name)
                    click.echo(f"✓ Deleted VM '{name}'")
                except Exception as e:
                    click.echo(f"Warning: Failed to delete VM: {e}", err=True)
            
            # Delete existing disk if it exists
            if disk_exists:
                click.echo(f"Deleting existing disk {disk_path}...")
                try:
                    if DiskManager.delete_disk(disk_path):
                        click.echo(f"✓ Deleted disk")
                except Exception as e:
                    click.echo(f"Warning: Failed to delete disk: {e}", err=True)
        elif (vm_exists or disk_exists) and force:
            # Force mode: silently delete
            if vm_exists:
                try:
                    with VMManager(uri) as manager:
                        manager.delete_vm(name)
                except Exception:
                    pass
            if disk_exists:
                try:
                    DiskManager.delete_disk(disk_path)
                except Exception:
                    pass
        
        # Check if auto-install is supported and enabled
        cloud_image_support = template_data.get('cloud_image_support', False)
        use_cloud_image = auto_install and cloud_image_support
        
        if use_cloud_image:
            # Download and use cloud image
            click.echo(f"Creating VM '{name}' with auto-installed OS from cloud image...")
            cache_dir = config.get_cache_dir()
            cloud_manager = CloudImageManager(cache_dir)
            
            try:
                cloud_image_path = cloud_manager.download_cloud_image(
                    template, 
                    echo_func=lambda msg: click.echo(msg)
                )
                click.echo(f"Creating disk {disk_path} ({disk_size}GB) from cloud image...")
                cloud_manager.create_disk_from_cloud_image(cloud_image_path, disk_path, disk_size)
                click.echo(f"✓ Disk created with OS pre-installed (size: {disk_size}GB)")
                click.echo(f"  Note: The file system will automatically expand to use all {disk_size}GB on first boot.")
            except ValueError as e:
                # Template doesn't support cloud images, fall back to empty disk
                click.echo(f"Warning: {e}. Creating empty disk instead.", err=True)
                click.echo(f"Creating disk {disk_path} ({disk_size}GB)...")
                DiskManager.create_disk(disk_path, disk_size)
                click.echo(f"Note: You'll need to manually install an OS on this disk.")
        else:
            # Create empty disk
            click.echo(f"Creating disk {disk_path} ({disk_size}GB)...")
            DiskManager.create_disk(disk_path, disk_size)
            if not auto_install:
                click.echo(f"Note: You'll need to manually install an OS on this disk.")
        
        # Create VM
        click.echo(f"Creating VM '{name}' with template '{template}'...")
        with VMManager(uri) as manager:
            manager.create_vm(name, template_data, disk_path, cpu, memory, network)
        
        click.echo(f"✓ VM '{name}' created successfully!")
        click.echo(f"\nTo start the VM, run: vmfinder vm start {name}")
        if use_cloud_image:
            click.echo(f"Note: OS is already installed. The VM should boot directly.")
            click.echo(f"Note: Default username is usually 'ubuntu' (Ubuntu) or 'debian' (Debian).")
            click.echo(f"      You may need to set a password using cloud-init or console access.")
        elif not auto_install:
            click.echo(f"Note: You'll need to install an OS on the disk before starting.")
            click.echo(f"     Use virt-install or manually attach an ISO installer.")
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('start')
@click.argument('name')
@click.pass_context
def vm_start(ctx, name):
    """Start a virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.start_vm(name):
                click.echo(f"✓ Started VM: {name}")
            else:
                click.echo(f"VM {name} is already running or in an invalid state.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('stop')
@click.argument('name')
@click.option('--force', '-f', is_flag=True, help='Force stop (destroy)')
@click.pass_context
def vm_stop(ctx, name, force):
    """Stop a virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.stop_vm(name, force):
                action = "destroyed" if force else "stopped"
                click.echo(f"✓ {action.capitalize()} VM: {name}")
            else:
                click.echo(f"VM {name} is already stopped.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('suspend')
@click.argument('name')
@click.pass_context
def vm_suspend(ctx, name):
    """Suspend a virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.suspend_vm(name):
                click.echo(f"✓ Suspended VM: {name}")
            else:
                click.echo(f"VM {name} cannot be suspended (not running or invalid state).")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('resume')
@click.argument('name')
@click.pass_context
def vm_resume(ctx, name):
    """Resume a suspended virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            if manager.resume_vm(name):
                click.echo(f"✓ Resumed VM: {name}")
            else:
                click.echo(f"VM {name} cannot be resumed (not suspended).")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('restart')
@click.argument('name')
@click.option('--force', '-f', is_flag=True, help='Force stop (destroy) before restart')
@click.pass_context
def vm_restart(ctx, name, force):
    """Restart a virtual machine (stop and start)."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            # Check if VM is running
            info = manager.get_vm_info(name)
            if not info:
                click.echo(f"Error: VM '{name}' not found.", err=True)
                sys.exit(1)
            
            # Stop VM if running
            if info['state'] == 'running':
                click.echo(f"Stopping VM '{name}'...")
                if manager.stop_vm(name, force):
                    action = "destroyed" if force else "stopped"
                    click.echo(f"✓ {action.capitalize()} VM: {name}")
                else:
                    click.echo(f"VM {name} is already stopped.")
            
            # Start VM
            click.echo(f"Starting VM '{name}'...")
            if manager.start_vm(name):
                click.echo(f"✓ Started VM: {name}")
            else:
                click.echo(f"Warning: VM {name} may already be running or in an invalid state.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('delete')
@click.argument('name')
@click.option('--delete-disk', is_flag=True, help='Also delete the disk image')
@click.confirmation_option(prompt='Are you sure you want to delete this VM?')
@click.pass_context
def vm_delete(ctx, name, delete_disk):
    """Delete a virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            manager.delete_vm(name)
            click.echo(f"✓ Deleted VM: {name}")
        
        if delete_disk:
            storage_dir = config.get_storage_dir()
            disk_path = storage_dir / f"{name}.qcow2"
            if DiskManager.delete_disk(disk_path):
                click.echo(f"✓ Deleted disk: {disk_path}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('info')
@click.argument('name')
@click.pass_context
def vm_info(ctx, name):
    """Show detailed information about a virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            info = manager.get_vm_info(name)
            if not info:
                click.echo(f"Error: VM '{name}' not found.", err=True)
                sys.exit(1)
            
            click.echo(f"\nVM: {info['name']}")
            click.echo(f"State: {info['state']}")
            click.echo(f"CPU: {info['cpu']}")
            click.echo(f"Memory: {info['memory']:.0f} MB")
            click.echo(f"Max Memory: {info['max_memory']:.0f} MB")
            click.echo(f"CPU Time: {info['cpu_time']:.2f} seconds")
            
            if info.get('disks'):
                click.echo("\nDisks:")
                for disk in info['disks']:
                    disk_source = disk.get('source')
                    disk_target = disk.get('target', 'unknown')
                    disk_type = disk.get('type', 'file')
                    
                    # Skip CD-ROM and other non-file disks for detailed info
                    if disk_type == 'file' and disk_source:
                        disk_path = Path(disk_source)
                        
                        # Check if it's an ISO file (cloud-init or CD-ROM)
                        is_iso = disk_source.lower().endswith('.iso')
                        
                        if is_iso:
                            # For ISO files, just show basic file info
                            click.echo(f"  - {disk_target}: {disk_source} (ISO)")
                            if disk_path.exists():
                                try:
                                    file_size = disk_path.stat().st_size
                                    size_mb = file_size / (1024 * 1024)
                                    size_gb = file_size / (1024 ** 3)
                                    if size_gb >= 1:
                                        click.echo(f"    File Size: {size_gb:.2f} GB ({size_mb:.2f} MB)")
                                    else:
                                        click.echo(f"    File Size: {size_mb:.2f} MB")
                                except Exception:
                                    pass
                        else:
                            # For disk images (qcow2, raw, etc.)
                            disk_info = DiskManager.get_disk_info(disk_path)
                            
                            if disk_info:
                                virtual_size = disk_info.get('virtual_size', 0)
                                actual_size = disk_info.get('actual_size', 0)
                                format_type = disk_info.get('format', 'unknown')
                                
                                # Display basic disk info
                                click.echo(f"  - {disk_target}: {disk_source}")
                                click.echo(f"    Format: {format_type}")
                                click.echo(f"    Virtual Size: {virtual_size:.2f} GB")
                                click.echo(f"    Actual Size: {actual_size:.2f} MB ({actual_size/1024:.2f} GB)")
                            else:
                                # Disk info unavailable
                                click.echo(f"  - {disk_target}: {disk_source}")
                                if disk_path.exists():
                                    try:
                                        file_size = disk_path.stat().st_size
                                        size_mb = file_size / (1024 * 1024)
                                        size_gb = file_size / (1024 ** 3)
                                        if size_gb >= 1:
                                            click.echo(f"    File Size: {size_gb:.2f} GB ({size_mb:.2f} MB)")
                                        else:
                                            click.echo(f"    File Size: {size_mb:.2f} MB")
                                    except Exception:
                                        click.echo(f"    (unable to read disk information)")
                                else:
                                    click.echo(f"    (file does not exist)")
                    else:
                        # Non-file disk (CD-ROM, etc.) - just show basic info
                        click.echo(f"  - {disk_target}: {disk_source} ({disk_type})")
            
            if info.get('interfaces'):
                click.echo("\nNetwork Interfaces:")
                # Get IP addresses and create MAC to IP mapping if VM is running
                mac_to_ips = {}
                if info['state'] == 'running':
                    try:
                        conn = manager.connect()
                        dom = conn.lookupByName(name)
                        # Get interface addresses directly from libvirt
                        try:
                            ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                            if ifaces:
                                for iface_name, iface_data in ifaces.items():
                                    mac = iface_data.get('hwaddr', '').lower()
                                    if mac:
                                        addrs = iface_data.get('addrs', [])
                                        ipv4_addrs = []
                                        for addr in addrs:
                                            addr_type = addr.get('type', -1)
                                            if addr_type == 0:  # IPv4
                                                ip_addr = addr.get('addr', '')
                                                if ip_addr:
                                                    ipv4_addrs.append(ip_addr)
                                        if ipv4_addrs:
                                            mac_to_ips[mac] = ipv4_addrs
                        except (libvirt.libvirtError, AttributeError):
                            # Fallback to get_vm_ip_addresses method
                            try:
                                ip_addresses = manager.get_vm_ip_addresses(name)
                                # Try to match by MAC if interface name contains MAC
                                for ip_info in ip_addresses:
                                    interface_name = ip_info.get('interface', '')
                                    # Check if interface name is actually a MAC address
                                    if ':' in interface_name and len(interface_name.split(':')) == 6:
                                        mac_addr = interface_name.lower()
                                        if ip_info.get('type') == 'ipv4':
                                            if mac_addr not in mac_to_ips:
                                                mac_to_ips[mac_addr] = []
                                            mac_to_ips[mac_addr].append(ip_info['ip'])
                            except Exception:
                                pass
                    except Exception:
                        pass  # If we can't get IPs, continue without them
                
                # Display interfaces with IP addresses if available
                for iface in info['interfaces']:
                    mac = iface['mac'].lower() if iface.get('mac') else None
                    iface_info = f"  - {iface['mac']}: {iface['source']} ({iface['type']})"
                    
                    if mac and mac in mac_to_ips:
                        ip_addrs = mac_to_ips[mac]
                        if ip_addrs:
                            iface_info += f" -> {', '.join(ip_addrs)}"
                    
                    click.echo(iface_info)
                
                # Show unmatched IP addresses if any
                if mac_to_ips and info['state'] == 'running':
                    displayed_macs = {iface['mac'].lower() for iface in info['interfaces'] if iface.get('mac')}
                    unmatched_ips = []
                    for mac, ips in mac_to_ips.items():
                        if mac not in displayed_macs:
                            unmatched_ips.extend(ips)
                    
                    if unmatched_ips:
                        click.echo("\nAdditional IP Addresses:")
                        for ip in unmatched_ips:
                            click.echo(f"  - {ip}")
            
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('set-cpu')
@click.argument('name')
@click.argument('cpu', type=int)
@click.pass_context
def vm_set_cpu(ctx, name, cpu):
    """Set CPU count for a virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            manager.set_cpu(name, cpu)
            click.echo(f"✓ Set CPU count to {cpu} for VM: {name}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('set-memory')
@click.argument('name')
@click.argument('memory', type=int)
@click.pass_context
def vm_set_memory(ctx, name, memory):
    """Set memory for a virtual machine (in MB)."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            manager.set_memory(name, memory)
            click.echo(f"✓ Set memory to {memory} MB for VM: {name}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('console')
@click.argument('name')
@click.pass_context
def vm_console(ctx, name):
    """Show console command for a virtual machine."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            console_cmd = manager.get_console(name)
            if console_cmd:
                click.echo(f"To connect to console, run:")
                click.echo(f"  {console_cmd}")
                click.echo("\nTo exit console, press: Ctrl+]")
                click.echo("\nNote: If the VM doesn't have console configured, you can also use:")
                click.echo(f"  virsh -c {uri} vncdisplay {name}  # View VNC display info")
            else:
                click.echo("Console not available for this VM.")
                click.echo(f"Try: virsh -c {uri} vncdisplay {name}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('set-password')
@click.argument('name')
@click.option('--username', '-u', default='ubuntu', help='Username to set password for (default: ubuntu)')
@click.option('--password', '-p', prompt=True, hide_input=True, confirmation_prompt=True, help='Password to set')
@click.option('--start/--no-start', default=True, help='Start VM after setting password (default: start)')
@click.pass_context
def vm_set_password(ctx, name, username, password, start):
    """Set password for a VM using cloud-init."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        # Check if VM exists
        with VMManager(uri) as manager:
            if not manager.vm_exists(name):
                click.echo(f"Error: VM '{name}' not found.", err=True)
                sys.exit(1)
            
            # Stop VM if running
            try:
                info = manager.get_vm_info(name)
                if info and info['state'] == 'running':
                    click.echo(f"Stopping VM '{name}'...")
                    manager.stop_vm(name, force=True)
                    click.echo(f"✓ VM stopped")
            except Exception as e:
                click.echo(f"Warning: Could not stop VM: {e}", err=True)
        
        # Create cloud-init ISO
        click.echo(f"Creating cloud-init ISO for password setup...")
        storage_dir = config.get_storage_dir()
        iso_path = storage_dir / f"{name}-cloud-init.iso"
        
        # Create ISO with a temporary name first to avoid permission issues
        # with existing files owned by libvirt-qemu
        temp_iso = Path(tempfile.mktemp(suffix='.iso', dir=str(storage_dir)))
        
        try:
            user_data = CloudInitManager.create_password_config(username, password)
            CloudInitManager.create_cloud_init_iso(user_data, output_path=temp_iso)
            
            # Remove existing ISO if it exists (may be owned by libvirt-qemu)
            if iso_path.exists():
                try:
                    iso_path.unlink()
                except PermissionError:
                    # Try to remove it using shutil which might handle it better
                    try:
                        os.chmod(iso_path, 0o666)
                        iso_path.unlink()
                    except (PermissionError, OSError):
                        raise RuntimeError(
                            f"Cannot remove existing ISO file {iso_path}. "
                            f"It may be owned by libvirt-qemu. Remove it manually with: "
                            f"sudo rm {iso_path}"
                        )
            
            # Move temp ISO to final location
            shutil.move(str(temp_iso), str(iso_path))
        except Exception:
            # Clean up temp file on error
            if temp_iso.exists():
                try:
                    temp_iso.unlink()
                except Exception:
                    pass
            raise
        
        # Set permissions for libvirt
        DiskManager.fix_disk_permissions(iso_path)
        
        # Attach ISO to VM
        click.echo(f"Attaching cloud-init ISO to VM...")
        CloudInitManager.attach_cloud_init_iso_to_vm(name, iso_path, uri)
        click.echo(f"✓ Cloud-init ISO attached")
        
        # Start VM if requested
        if start:
            click.echo(f"Starting VM '{name}'...")
            with VMManager(uri) as manager:
                manager.start_vm(name)
            click.echo(f"✓ VM started")
            click.echo(f"\nPassword has been set!")
            click.echo(f"  Username: {username}")
            click.echo(f"  Password: {password}")
            click.echo(f"\nYou can now login using:")
            click.echo(f"  vmfinder vm console {name}")
            click.echo(f"  # Then login with username: {username}")
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('ssh')
@click.argument('name')
@click.option('--username', '-u', default='ubuntu', help='SSH username (default: ubuntu)')
@click.option('--port', '-p', default=22, type=int, help='SSH port (default: 22)')
@click.option('--key', '-k', help='SSH private key file path')
@click.pass_context
def vm_ssh(ctx, name, username, port, key):
    """Show SSH connection information for a VM."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            # Check if VM exists
            if not manager.vm_exists(name):
                click.echo(f"Error: VM '{name}' not found.", err=True)
                sys.exit(1)
            
            # Get VM info
            info = manager.get_vm_info(name)
            if not info:
                click.echo(f"Error: VM '{name}' not found.", err=True)
                sys.exit(1)
            
            # Check if VM is running
            if info['state'] != 'running':
                click.echo(f"Warning: VM '{name}' is not running (state: {info['state']}).", err=True)
                click.echo("Start the VM first with: vmfinder vm start " + name)
                click.echo("\nOnce started, you can get IP address using:")
                click.echo("  virsh domifaddr " + name)
                sys.exit(1)
            
            # Get IP addresses
            ip_addresses = manager.get_vm_ip_addresses(name)
            
            # Filter IPv4 addresses
            ipv4_addresses = [ip_info for ip_info in ip_addresses if ip_info.get('type') == 'ipv4']
            
            if not ipv4_addresses:
                click.echo(f"Could not determine IP address for VM '{name}'.", err=True)
                click.echo("\nThe VM is running but IP address is not available yet.")
                click.echo("This can happen if:")
                click.echo("  - The VM is still booting (wait a few seconds)")
                click.echo("  - The VM doesn't have network access")
                click.echo("  - DHCP lease is not available")
                click.echo("\nYou can try:")
                click.echo(f"  virsh domifaddr {name}")
                click.echo("\nOr connect via console:")
                click.echo(f"  vmfinder vm console {name}")
                sys.exit(1)
            
            # Use the first IPv4 address
            ip_addr = ipv4_addresses[0]['ip']
            
            # Build SSH command
            ssh_cmd_parts = ['ssh']
            if key:
                ssh_cmd_parts.extend(['-i', key])
            if port != 22:
                ssh_cmd_parts.extend(['-p', str(port)])
            ssh_cmd_parts.append(f"{username}@{ip_addr}")
            ssh_cmd = ' '.join(ssh_cmd_parts)
            
            click.echo(f"\nSSH connection information for VM '{name}':")
            click.echo(f"  IP Address: {ip_addr}")
            click.echo(f"  Username: {username}")
            click.echo(f"  Port: {port}")
            
            if len(ipv4_addresses) > 1:
                click.echo(f"\nOther IP addresses:")
                for ip_info in ipv4_addresses[1:]:
                    click.echo(f"  - {ip_info['ip']} ({ip_info.get('interface', 'unknown')})")
            
            click.echo(f"\nTo connect via SSH, run:")
            click.echo(f"  {ssh_cmd}")
            
            click.echo(f"\nOr use the console (no IP needed):")
            click.echo(f"  vmfinder vm console {name}")
            
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('fix-permissions')
@click.argument('name')
@click.pass_context
def vm_fix_permissions(ctx, name):
    """Fix disk permissions for a VM so libvirt can access it."""
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        # Get VM info to find disk path
        with VMManager(uri) as manager:
            info = manager.get_vm_info(name)
            if not info:
                click.echo(f"Error: VM '{name}' not found.", err=True)
                sys.exit(1)
            
            # Get disk paths from VM info
            disks = info.get('disks', [])
            if not disks:
                click.echo(f"Warning: No disks found for VM '{name}'.")
                return
            
            # Also try to get disk from storage directory (fallback)
            storage_dir = config.get_storage_dir()
            disk_path = storage_dir / f"{name}.qcow2"
            
            fixed = False
            for disk in disks:
                disk_file = disk.get('source')
                if disk_file:
                    disk_path_obj = Path(disk_file)
                    if disk_path_obj.exists():
                        if DiskManager.fix_disk_permissions(disk_path_obj):
                            click.echo(f"✓ Fixed permissions for {disk_file}")
                            fixed = True
                        else:
                            click.echo(f"Warning: Could not fix permissions for {disk_file}", err=True)
            
            # Also try the standard storage location
            if disk_path.exists() and disk_path not in [Path(d.get('source')) for d in disks if d.get('source')]:
                if DiskManager.fix_disk_permissions(disk_path):
                    click.echo(f"✓ Fixed permissions for {disk_path}")
                    fixed = True
            
            if not fixed:
                click.echo("Could not automatically fix permissions. You may need to run:")
                for disk in disks:
                    disk_file = disk.get('source')
                    if disk_file:
                        click.echo(f"  sudo chgrp kvm {disk_file}")
                        click.echo(f"  sudo chmod 660 {disk_file}")
                click.echo("Or use ACL:")
                for disk in disks:
                    disk_file = disk.get('source')
                    if disk_file:
                        click.echo(f"  setfacl -m u:libvirt-qemu:rw {disk_file}")
                sys.exit(1)
            else:
                click.echo(f"✓ Permissions fixed successfully for VM '{name}'")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vm.command('resize-disk')
@click.argument('name')
@click.argument('size', type=int)
@click.pass_context
def vm_resize_disk(ctx, name, size):
    """Resize a VM's disk image file.
    
    This command resizes the disk image file to the specified size (in GB).
    After resizing, you need to manually expand the partition and filesystem inside the VM.
    
    The VM does not need to be stopped for disk resizing.
    
    Example:
      vmfinder vm resize-disk myvm 50  # Resize to 50GB
    
    After resizing, SSH into the VM and run:
      sudo growpart /dev/vda 1
      sudo resize2fs /dev/vda1  (for ext4)
      or: sudo xfs_growfs /  (for xfs)
    """
    config = ctx.obj['config']
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        with VMManager(uri) as manager:
            # Check if VM exists
            info = manager.get_vm_info(name)
            if not info:
                click.echo(f"Error: VM '{name}' not found.", err=True)
                sys.exit(1)
            
            # Get current disk info
            disks = info.get('disks', [])
            if not disks:
                click.echo(f"Error: No disks found for VM '{name}'.", err=True)
                sys.exit(1)
            
            # Get current disk size
            disk_path_str = disks[0].get('source')
            if not disk_path_str:
                click.echo(f"Error: Could not determine disk path for VM '{name}'.", err=True)
                sys.exit(1)
            
            disk_path = Path(disk_path_str)
            current_info = DiskManager.get_disk_info(disk_path)
            if current_info:
                current_size = current_info['virtual_size']
                click.echo(f"Current disk size: {current_size:.1f} GB")
                if size <= current_size:
                    click.echo(f"Error: New size ({size}GB) must be larger than current size ({current_size:.1f}GB).", err=True)
                    sys.exit(1)
            
            click.echo(f"\nResizing disk for VM '{name}' to {size}GB...")
            
            # Resize the disk
            result = manager.resize_vm_disk(name, size)
            
            if not result['success']:
                click.echo(f"Error: Failed to resize disk: {result.get('message', 'Unknown error')}", err=True)
                sys.exit(1)
            
            click.echo(f"✓ Disk image resized to {size}GB")
            
            click.echo(f"\n✓ Disk resize complete!")
            click.echo("\nNote: The disk image has been resized, but you need to manually expand")
            click.echo("      the partition and filesystem inside the VM.")
            
            disk_device = result.get('disk_device', '/dev/vda')
            click.echo("\nTo expand the partition and filesystem inside the VM:")
            step = 1
            if info['state'] != 'running':
                click.echo(f"  {step}. Start the VM: vmfinder vm start {name}")
                step += 1
            click.echo(f"  {step}. SSH into the VM: vmfinder vm ssh {name}")
            step += 1
            click.echo(f"  {step}. Run: sudo growpart {disk_device} 1")
            step += 1
            click.echo(f"  {step}. Run: sudo resize2fs {disk_device}1  (for ext4)")
            click.echo(f"      or: sudo xfs_growfs /  (for xfs)")
                
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main():
    """Main entry point."""
    cli(obj={})


if __name__ == '__main__':
    main()
