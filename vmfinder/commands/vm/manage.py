"""VM management commands: create, delete, info."""

import sys
import os
import tempfile
import shutil
import getpass
from pathlib import Path

from vmfinder.config import Config
from vmfinder.vm_manager import VMManager
from vmfinder.template import TemplateManager
from vmfinder.disk import DiskManager
from vmfinder.cloud_image import CloudImageManager
from vmfinder.cloud_init import CloudInitManager
from vmfinder.logger import get_logger

logger = get_logger()


def cmd_vm_create(args):
    """Create a new virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    try:
        # Get template
        template_manager = TemplateManager(config.templates_dir)
        template_data = template_manager.get_template(args.template)
        if not template_data:
            logger.error(f"Template '{args.template}' not found.")
            logger.error("Run 'vmfinder template list' to see available templates.")
            sys.exit(1)
        
        # Check if VM or disk already exists
        storage_dir = config.get_storage_dir()
        disk_path = storage_dir / f"{args.name}.qcow2"
        disk_exists = disk_path.exists()
        
        # Check if VM exists in libvirt
        with VMManager(uri) as manager:
            vm_exists = manager.vm_exists(args.name)
        
        # If VM or disk exists, prompt for deletion
        if (vm_exists or disk_exists) and not args.force:
            if vm_exists and disk_exists:
                msg = f"VM '{args.name}' and its disk already exist. Delete and recreate? [Y/n]: "
            elif vm_exists:
                msg = f"VM '{args.name}' already exists. Delete and recreate? [Y/n]: "
            else:
                msg = f"Disk for VM '{args.name}' already exists. Delete and recreate? [Y/n]: "
            
            if input(msg).lower() == 'n':
                logger.info("Cancelled. Use '--force' to overwrite without prompting.")
                sys.exit(0)
            
            # Delete existing VM if it exists
            if vm_exists:
                logger.info(f"Deleting existing VM '{args.name}'...")
                try:
                    with VMManager(uri) as manager:
                        manager.delete_vm(args.name)
                    logger.info(f"✓ Deleted VM '{args.name}'")
                except Exception as e:
                    logger.warning(f"Failed to delete VM: {e}")
            
            # Delete existing disk if it exists
            if disk_exists:
                logger.info(f"Deleting existing disk {disk_path}...")
                try:
                    if DiskManager.delete_disk(disk_path):
                        logger.info(f"✓ Deleted disk")
                except Exception as e:
                    logger.warning(f"Failed to delete disk: {e}")
        elif (vm_exists or disk_exists) and args.force:
            # Force mode: silently delete
            if vm_exists:
                try:
                    with VMManager(uri) as manager:
                        manager.delete_vm(args.name)
                except Exception:
                    pass
            if disk_exists:
                try:
                    DiskManager.delete_disk(disk_path)
                except Exception:
                    pass
        
        # Check if auto-install is supported and enabled
        cloud_image_support = template_data.get('cloud_image_support', False)
        use_cloud_image = args.auto_install and cloud_image_support
        
        if use_cloud_image:
            # Download and use cloud image
            logger.info(f"Creating VM '{args.name}' with auto-installed OS from cloud image...")
            cache_dir = config.get_cache_dir()
            cloud_manager = CloudImageManager(cache_dir)
            
            try:
                cloud_image_path = cloud_manager.download_cloud_image(
                    args.template,
                    template_data,
                    echo_func=lambda msg: logger.info(msg)
                )
                logger.info(f"Creating disk {disk_path} ({args.disk_size}GB) from cloud image...")
                cloud_manager.create_disk_from_cloud_image(cloud_image_path, disk_path, args.disk_size)
                logger.info(f"✓ Disk created with OS pre-installed (size: {args.disk_size}GB)")
                logger.info(f"  Note: The file system will automatically expand to use all {args.disk_size}GB on first boot.")
            except ValueError as e:
                # Template doesn't support cloud images, fall back to empty disk
                logger.warning(f"{e}. Creating empty disk instead.")
                logger.info(f"Creating disk {disk_path} ({args.disk_size}GB)...")
                DiskManager.create_disk(disk_path, args.disk_size)
                print("Note: You'll need to manually install an OS on this disk.")
        else:
            # Create empty disk
            logger.info(f"Creating disk {disk_path} ({args.disk_size}GB)...")
            DiskManager.create_disk(disk_path, args.disk_size)
            if not args.auto_install:
                print("Note: You'll need to manually install an OS on this disk.")
        
        # Create VM
        logger.info(f"Creating VM '{args.name}' with template '{args.template}'...")
        with VMManager(uri) as manager:
            manager.create_vm(args.name, template_data, disk_path, args.cpu, args.memory, args.network)
        
        # If using cloud image, create and attach cloud-init ISO
        if use_cloud_image:
            try:
                logger.info(f"Creating cloud-init ISO for metadata service...")
                storage_dir = config.get_storage_dir()
                iso_path = storage_dir / f"{args.name}-cloud-init.iso"
                temp_iso = Path(tempfile.mktemp(suffix='.iso', dir=str(storage_dir)))
                
                try:
                    meta_data = f"""instance-id: iid-{args.name}
local-hostname: {args.name}
"""
                    user_data = """#cloud-config
# Basic cloud-init configuration to prevent network metadata service requests
"""
                    CloudInitManager.create_cloud_init_iso(
                        user_data,
                        meta_data=meta_data,
                        output_path=temp_iso
                    )
                    
                    # Remove existing ISO if it exists
                    if iso_path.exists():
                        try:
                            iso_path.unlink()
                        except PermissionError:
                            try:
                                os.chmod(iso_path, 0o666)
                                iso_path.unlink()
                            except (PermissionError, OSError):
                                pass
                    
                    shutil.move(str(temp_iso), str(iso_path))
                    DiskManager.fix_disk_permissions(iso_path)
                    
                    logger.info(f"Attaching cloud-init ISO to VM...")
                    CloudInitManager.attach_cloud_init_iso_to_vm(args.name, iso_path, uri)
                    logger.info(f"✓ Cloud-init ISO attached")
                except Exception as e:
                    logger.warning(f"Failed to create cloud-init ISO: {e}")
                    logger.warning(f"         VM will still work, but cloud-init may try to connect to metadata service.")
                    if temp_iso.exists():
                        try:
                            temp_iso.unlink()
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Cloud-init setup failed: {e}")
        
        logger.info(f"✓ VM '{args.name}' created successfully!")
        print(f"\nTo start the VM, run: vmfinder vm start {args.name}")
        if use_cloud_image:
            print(f"Note: OS is already installed. The VM should boot directly.")
            print(f"Note: Default username is usually 'ubuntu' (Ubuntu) or 'debian' (Debian).")
            print(f"      You may need to set a password using 'vmfinder vm set-password {args.name}' or console access.")
        elif not args.auto_install:
            print(f"Note: You'll need to install an OS on the disk before starting.")
            print(f"     Use virt-install or manually attach an ISO installer.")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_delete(args):
    """Delete a virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    # Confirmation
    if not args.yes:
        if input(f"Are you sure you want to delete VM '{args.name}'? [y/N]: ").lower() != 'y':
            logger.info("Cancelled.")
            sys.exit(0)
    
    try:
        with VMManager(uri) as manager:
            manager.delete_vm(args.name)
            logger.info(f"✓ Deleted VM: {args.name}")
        
        if args.delete_disk:
            storage_dir = config.get_storage_dir()
            disk_path = storage_dir / f"{args.name}.qcow2"
            if DiskManager.delete_disk(disk_path):
                logger.info(f"✓ Deleted disk: {disk_path}")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_vm_info(args):
    """Show detailed information about a virtual machine."""
    config = Config()
    uri = config.get('libvirt_uri', 'qemu:///system')
    
    def format_label_value(label, value, label_width=12):
        """Format label:value with alignment."""
        padded_label = label.ljust(label_width)
        return f"{padded_label}: {value}"
    
    try:
        import libvirt
        with VMManager(uri) as manager:
            info = manager.get_vm_info(args.name)
            if not info:
                logger.error(f"VM '{args.name}' not found.")
                sys.exit(1)
            
            # Calculate max label width for alignment
            labels = ['VM', 'State', 'CPU', 'Memory', 'Max Memory', 'CPU Time']
            max_label_width = max(len(label) for label in labels)
            
            # Format and display VM info
            print(f"\n{format_label_value('VM', info['name'], max_label_width)}")
            print(format_label_value('State', info['state'], max_label_width))
            print(format_label_value('CPU', str(info['cpu']), max_label_width))
            print(format_label_value('Memory', f"{info['memory']:.0f} MB", max_label_width))
            print(format_label_value('Max Memory', f"{info['max_memory']:.0f} MB", max_label_width))
            print(format_label_value('CPU Time', f"{info['cpu_time']:.2f} seconds", max_label_width))
            
            if info.get('disks'):
                print("\nDisks:")
                disk_labels = ['Format', 'Virtual Size', 'Actual Size', 'File Size']
                disk_label_width = max(len(label) for label in disk_labels)
                
                for disk in info['disks']:
                    disk_source = disk.get('source')
                    disk_target = disk.get('target', 'unknown')
                    disk_type = disk.get('type', 'file')
                    
                    if disk_type == 'file' and disk_source:
                        disk_path = Path(disk_source)
                        is_iso = disk_source.lower().endswith('.iso')
                        
                        if is_iso:
                            print(f"  - {disk_target}: {disk_source} (ISO)")
                            if disk_path.exists():
                                try:
                                    file_size = disk_path.stat().st_size
                                    size_mb = file_size / (1024 * 1024)
                                    size_gb = file_size / (1024 ** 3)
                                    if size_gb >= 1:
                                        print(f"    {format_label_value('File Size', f'{size_gb:.2f} GB ({size_mb:.2f} MB)', disk_label_width)}")
                                    else:
                                        print(f"    {format_label_value('File Size', f'{size_mb:.2f} MB', disk_label_width)}")
                                except Exception:
                                    pass
                        else:
                            disk_info = DiskManager.get_disk_info(disk_path)
                            if disk_info:
                                virtual_size = disk_info.get('virtual_size', 0)
                                actual_size = disk_info.get('actual_size', 0)
                                format_type = disk_info.get('format', 'unknown')
                                print(f"  - {disk_target}: {disk_source}")
                                print(f"    {format_label_value('Format', format_type, disk_label_width)}")
                                print(f"    {format_label_value('Virtual Size', f'{virtual_size:.2f} GB', disk_label_width)}")
                                print(f"    {format_label_value('Actual Size', f'{actual_size:.2f} MB ({actual_size/1024:.2f} GB)', disk_label_width)}")
                            else:
                                print(f"  - {disk_target}: {disk_source}")
                                if disk_path.exists():
                                    try:
                                        file_size = disk_path.stat().st_size
                                        size_mb = file_size / (1024 * 1024)
                                        size_gb = file_size / (1024 ** 3)
                                        if size_gb >= 1:
                                            print(f"    {format_label_value('File Size', f'{size_gb:.2f} GB ({size_mb:.2f} MB)', disk_label_width)}")
                                        else:
                                            print(f"    {format_label_value('File Size', f'{size_mb:.2f} MB', disk_label_width)}")
                                    except Exception:
                                        print(f"    (unable to read disk information)")
                                else:
                                    print(f"    (file does not exist)")
                    else:
                        print(f"  - {disk_target}: {disk_source} ({disk_type})")
            
            if info.get('interfaces'):
                print("\nNetwork Interfaces:")
                mac_to_ips = {}
                if info['state'] == 'running':
                    try:
                        conn = manager.connect()
                        dom = conn.lookupByName(args.name)
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
                            try:
                                ip_addresses = manager.get_vm_ip_addresses(args.name)
                                for ip_info in ip_addresses:
                                    interface_name = ip_info.get('interface', '')
                                    if ':' in interface_name and len(interface_name.split(':')) == 6:
                                        mac_addr = interface_name.lower()
                                        if ip_info.get('type') == 'ipv4':
                                            if mac_addr not in mac_to_ips:
                                                mac_to_ips[mac_addr] = []
                                            mac_to_ips[mac_addr].append(ip_info['ip'])
                            except Exception:
                                pass
                    except Exception:
                        pass
                
                mac_width = 17
                for iface in info['interfaces']:
                    mac = iface['mac'].lower() if iface.get('mac') else None
                    mac_display = iface.get('mac', 'N/A')
                    iface_info = f"  - {mac_display.ljust(mac_width)}: {iface['source']} ({iface['type']})"
                    
                    if mac and mac in mac_to_ips:
                        ip_addrs = mac_to_ips[mac]
                        if ip_addrs:
                            ip_display = ', '.join(ip_addrs)
                            iface_info += f" -> {ip_display}"
                    
                    print(iface_info)
                
                if mac_to_ips and info['state'] == 'running':
                    displayed_macs = {iface['mac'].lower() for iface in info['interfaces'] if iface.get('mac')}
                    unmatched_ips = []
                    for mac, ips in mac_to_ips.items():
                        if mac not in displayed_macs:
                            unmatched_ips.extend(ips)
                    
                    if unmatched_ips:
                        print("\nAdditional IP Addresses:")
                        for ip in unmatched_ips:
                            print(f"  - {ip}")
            
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

