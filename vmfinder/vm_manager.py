"""Core VM management using libvirt."""

import libvirt
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

# Import disk manager for permission fixes
from vmfinder.disk import DiskManager


class VMState(Enum):
    """VM state enumeration."""
    RUNNING = "running"
    IDLE = "idle"
    PAUSED = "paused"
    SHUTDOWN = "shutdown"
    SHUTOFF = "shutoff"
    CRASHED = "crashed"
    PMSUSPENDED = "pmsuspended"
    UNKNOWN = "unknown"


class VMManager:
    """Manages virtual machines using libvirt."""
    
    def __init__(self, uri: str = "qemu:///system"):
        self.uri = uri
        self.conn = None
    
    def connect(self):
        """Connect to libvirt daemon."""
        if self.conn is None:
            try:
                self.conn = libvirt.open(self.uri)
                if self.conn is None:
                    raise RuntimeError(f"Failed to open connection to {self.uri}")
            except libvirt.libvirtError as e:
                raise RuntimeError(f"Failed to connect to libvirt: {e}")
        return self.conn
    
    def disconnect(self):
        """Disconnect from libvirt daemon."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
    
    def list_vms(self) -> List[Dict[str, Any]]:
        """List all VMs with their status."""
        conn = self.connect()
        vms = []
        
        # Get both running and defined VMs
        domain_ids = conn.listDomainsID()
        domain_names = conn.listDefinedDomains()
        all_names = set()
        
        for domain_id in domain_ids:
            try:
                dom = conn.lookupByID(domain_id)
                all_names.add(dom.name())
            except libvirt.libvirtError:
                pass
        
        for name in domain_names:
            all_names.add(name)
        
        for name in sorted(all_names):
            try:
                dom = conn.lookupByName(name)
                info = dom.info()
                state_code, _ = dom.state()
                
                # Map libvirt state codes to VMState
                state_map = {
                    libvirt.VIR_DOMAIN_RUNNING: VMState.RUNNING,
                    libvirt.VIR_DOMAIN_BLOCKED: VMState.IDLE,
                    libvirt.VIR_DOMAIN_PAUSED: VMState.PAUSED,
                    libvirt.VIR_DOMAIN_SHUTDOWN: VMState.SHUTDOWN,
                    libvirt.VIR_DOMAIN_SHUTOFF: VMState.SHUTOFF,
                    libvirt.VIR_DOMAIN_CRASHED: VMState.CRASHED,
                    libvirt.VIR_DOMAIN_PMSUSPENDED: VMState.PMSUSPENDED,
                }
                state = state_map.get(state_code, VMState.UNKNOWN)
                
                vms.append({
                    'name': name,
                    'state': state.value,
                    'cpu': info[3],  # Number of CPUs
                    'memory': info[2] / 1024,  # Memory in MB
                    'max_memory': info[1] / 1024,  # Max memory in MB
                })
            except libvirt.libvirtError as e:
                vms.append({
                    'name': name,
                    'state': 'error',
                    'error': str(e),
                })
        
        return vms
    
    def vm_exists(self, name: str) -> bool:
        """Check if a VM exists."""
        conn = self.connect()
        try:
            conn.lookupByName(name)
            return True
        except libvirt.libvirtError:
            return False
    
    def get_vm_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            info = dom.info()
            state_code, _ = dom.state()
            
            # Map libvirt state codes to VMState
            state_map = {
                libvirt.VIR_DOMAIN_RUNNING: VMState.RUNNING,
                libvirt.VIR_DOMAIN_BLOCKED: VMState.IDLE,
                libvirt.VIR_DOMAIN_PAUSED: VMState.PAUSED,
                libvirt.VIR_DOMAIN_SHUTDOWN: VMState.SHUTDOWN,
                libvirt.VIR_DOMAIN_SHUTOFF: VMState.SHUTOFF,
                libvirt.VIR_DOMAIN_CRASHED: VMState.CRASHED,
                libvirt.VIR_DOMAIN_PMSUSPENDED: VMState.PMSUSPENDED,
            }
            state = state_map.get(state_code, VMState.UNKNOWN)
            
            # Get XML configuration
            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            
            # Extract network info
            interfaces = []
            for iface in root.findall('.//interface'):
                mac = iface.find('mac')
                source = iface.find('source')
                if mac is not None and source is not None:
                    interfaces.append({
                        'mac': mac.get('address'),
                        'type': iface.get('type'),
                        'source': source.get('network') or source.get('bridge'),
                    })
            
            # Extract disk info
            disks = []
            for disk in root.findall('.//disk'):
                source = disk.find('source')
                target = disk.find('target')
                if source is not None and target is not None:
                    disks.append({
                        'source': source.get('file'),
                        'target': target.get('dev'),
                        'type': disk.get('type'),
                    })
            
            return {
                'name': name,
                'state': state.value,
                'cpu': info[3],
                'memory': info[2] / 1024,
                'max_memory': info[1] / 1024,
                'cpu_time': info[4] / 1e9,  # CPU time in seconds
                'interfaces': interfaces,
                'disks': disks,
            }
        except libvirt.libvirtError:
            return None
    
    def create_vm(self, name: str, template: Dict[str, Any], 
                  disk_path: Path, cpu: int = 2, memory_mb: int = 2048,
                  network: str = "default") -> bool:
        """Create a new VM from template."""
        conn = self.connect()
        
        # Check if VM already exists
        try:
            conn.lookupByName(name)
            raise ValueError(f"VM {name} already exists")
        except libvirt.libvirtError:
            pass  # VM doesn't exist, which is good
        
        # Generate XML from template
        xml = self._generate_vm_xml(name, template, disk_path, cpu, memory_mb, network)
        
        try:
            dom = conn.defineXML(xml)
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to create VM: {e}")
    
    def _generate_vm_xml(self, name: str, template: Dict[str, Any],
                         disk_path: Path, cpu: int, memory_mb: int,
                         network: str) -> str:
        """Generate libvirt XML for a VM."""
        # OS type detection
        os_type = template.get('os_type', 'hvm')
        os_variant = template.get('os_variant', 'generic')
        
        # Architecture
        arch = template.get('arch', 'x86_64')
        
        # Boot device
        boot_dev = template.get('boot', 'hd')
        
        xml = f"""<domain type='kvm'>
  <name>{name}</name>
  <memory unit='MiB'>{memory_mb}</memory>
  <currentMemory unit='MiB'>{memory_mb}</currentMemory>
  <vcpu placement='static'>{cpu}</vcpu>
  <os>
    <type arch='{arch}'>{os_type}</type>
    <boot dev='{boot_dev}'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <pae/>
  </features>
  <cpu mode='host-passthrough'/>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='{disk_path}'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='network'>
      <source network='{network}'/>
      <model type='virtio'/>
    </interface>
    <console type='pty'>
      <target type='serial' port='0'/>
    </console>
    <graphics type='vnc' port='-1' autoport='yes' listen='127.0.0.1'/>
    <video>
      <model type='cirrus' vram='9216' heads='1'/>
    </video>
  </devices>
</domain>"""
        return xml
    
    def start_vm(self, name: str) -> bool:
        """Start a VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            if dom.isActive():
                return False  # Already running
            
            # Fix disk permissions before starting to avoid permission errors
            # Get disk path from VM XML
            try:
                xml_desc = dom.XMLDesc(0)
                root = ET.fromstring(xml_desc)
                for disk in root.findall('.//disk[@type="file"]'):
                    source = disk.find('source')
                    if source is not None and source.get('file'):
                        disk_path = Path(source.get('file'))
                        if disk_path.exists():
                            DiskManager.fix_disk_permissions(disk_path)
            except Exception:
                # If we can't fix permissions, continue anyway
                # The actual error will be raised by libvirt if permissions are wrong
                pass
            
            dom.create()
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to start VM: {e}")
    
    def stop_vm(self, name: str, force: bool = False) -> bool:
        """Stop a VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            if not dom.isActive():
                return False  # Already stopped
            
            if force:
                dom.destroy()
            else:
                dom.shutdown()
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to stop VM: {e}")
    
    def suspend_vm(self, name: str) -> bool:
        """Suspend a VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            if not dom.isActive():
                return False
            dom.suspend()
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to suspend VM: {e}")
    
    def resume_vm(self, name: str) -> bool:
        """Resume a suspended VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            state = dom.state()[0]
            if state != libvirt.VIR_DOMAIN_PAUSED:
                return False
            dom.resume()
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to resume VM: {e}")
    
    def delete_vm(self, name: str) -> bool:
        """Delete a VM (undefine it)."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            if dom.isActive():
                dom.destroy()
            dom.undefine()
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to delete VM: {e}")
    
    def set_cpu(self, name: str, cpu: int) -> bool:
        """Set CPU count for a VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            
            # Get current XML to check maxvcpu
            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            vcpu_elem = root.find('vcpu')
            
            # Always fix placement='auto' to 'static' if present (numad may not be available)
            placement_fixed = False
            is_active = dom.isActive()  # Get this once before any changes
            
            if vcpu_elem is not None:
                placement = vcpu_elem.get('placement')
                if placement == 'auto':
                    vcpu_elem.set('placement', 'static')
                    placement_fixed = True
            
            # Also fix numatune/memory placement='auto' (this also triggers numad)
            numatune = root.find('numatune')
            if numatune is not None:
                memory = numatune.find('memory')
                if memory is not None and memory.get('placement') == 'auto':
                    # Remove placement attribute instead of changing to 'static'
                    # (static requires nodeset which we don't have)
                    del memory.attrib['placement']
                    placement_fixed = True
            
            # Update config if placement was fixed
            if placement_fixed:
                new_xml = ET.tostring(root, encoding='unicode')
                if is_active:
                    dom.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)
                    conn.defineXML(new_xml)
                    dom = conn.lookupByName(name)
                else:
                    dom.undefine()
                    dom = conn.defineXML(new_xml)
                # Re-read XML after fix
                xml_desc = dom.XMLDesc(0)
                root = ET.fromstring(xml_desc)
                vcpu_elem = root.find('vcpu')
            
            # Check if we need to update maxvcpu
            if vcpu_elem is not None:
                # Get current max vcpu - it's either in the 'current' attribute or in the text
                maxvcpu_attr = vcpu_elem.get('current')
                maxvcpu_text = vcpu_elem.text
                if maxvcpu_attr:
                    maxvcpu = int(maxvcpu_attr)
                elif maxvcpu_text:
                    maxvcpu = int(maxvcpu_text.strip())
                else:
                    maxvcpu = 0
                
                # If requested CPU is greater than max, update max first
                if cpu > maxvcpu:
                    is_active = dom.isActive()
                    
                    # For running VM, maxvcpu cannot be increased without stopping
                    if is_active:
                        # Update the persistent config for next boot
                        # Set maxvcpu in text, and current in attribute
                        vcpu_elem.text = str(cpu)
                        vcpu_elem.set('current', str(maxvcpu))  # Keep current at existing max
                        
                        # Change placement from 'auto' to 'static' if needed
                        # 'auto' requires numad which may not be available
                        placement = vcpu_elem.get('placement')
                        if placement == 'auto':
                            vcpu_elem.set('placement', 'static')
                        
                        # Update only the persistent config (will take effect after restart)
                        new_xml = ET.tostring(root, encoding='unicode')
                        dom.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)
                        conn.defineXML(new_xml)
                        
                        # Cannot increase maxvcpu for running VM - raise error with clear message
                        raise RuntimeError(
                            f"Cannot increase CPU count from {maxvcpu} to {cpu} while VM is running. "
                            f"Maximum vCPU count of a live domain cannot be modified. "
                            f"Please stop the VM first with 'vmfinder vm stop {name}', "
                            f"then run 'vmfinder vm set-cpu {name} {cpu}', "
                            f"then start it again with 'vmfinder vm start {name}'. "
                            f"The configuration has been updated for next boot."
                        )
                    else:
                        # For stopped VM, we can freely update maxvcpu
                        # Set maxvcpu in text, current in attribute (or same as max if not specified)
                        vcpu_elem.text = str(cpu)
                        vcpu_elem.set('current', str(cpu))
                        
                        # Change placement from 'auto' to 'static' if needed
                        # 'auto' requires numad which may not be available
                        placement = vcpu_elem.get('placement')
                        if placement == 'auto':
                            vcpu_elem.set('placement', 'static')
                        # Keep 'static' or remove placement attribute for default behavior
                        
                        # Update the domain XML config
                        new_xml = ET.tostring(root, encoding='unicode')
                        dom.undefine()
                        dom = conn.defineXML(new_xml)
            
            # Now set the CPU count
            if dom.isActive():
                dom.setVcpusFlags(cpu, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            dom.setVcpusFlags(cpu, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to set CPU count: {e}")
    
    def set_memory(self, name: str, memory_mb: int) -> bool:
        """Set memory for a VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            memory_kb = memory_mb * 1024
            # Need to update both live and config
            if dom.isActive():
                dom.setMemoryFlags(memory_kb, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            dom.setMemoryFlags(memory_kb, libvirt.VIR_DOMAIN_AFFECT_CONFIG)
            return True
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to set memory: {e}")
    
    def get_vm_ip_addresses(self, name: str) -> List[Dict[str, str]]:
        """Get IP addresses for a VM's network interfaces.
        
        Returns:
            List of dicts with 'interface', 'ip', and 'type' keys
        """
        conn = self.connect()
        ip_addresses = []
        try:
            dom = conn.lookupByName(name)
            if not dom.isActive():
                return ip_addresses  # VM not running, no IP addresses
            
            # Get interface addresses using libvirt API
            # This works for active VMs
            try:
                ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                if ifaces:
                    for iface_name, iface_data in ifaces.items():
                        addrs = iface_data.get('addrs', [])
                        for addr in addrs:
                            # addr['type'] is 0 for IPv4, 1 for IPv6
                            addr_type = addr.get('type', -1)
                            ip_type = 'ipv4' if addr_type == 0 else ('ipv6' if addr_type == 1 else 'unknown')
                            ip_addr = addr.get('addr', '')
                            if ip_addr:  # Only add if we have an actual IP
                                ip_addresses.append({
                                    'interface': iface_name,
                                    'ip': ip_addr,
                                    'type': ip_type,
                                })
            except (libvirt.libvirtError, AttributeError):
                # Fallback: try using DHCP leases
                pass
            
            # If no addresses found via API, try to get MAC and query network
            if not ip_addresses:
                xml_desc = dom.XMLDesc(0)
                root = ET.fromstring(xml_desc)
                for iface in root.findall('.//interface'):
                    mac = iface.find('mac')
                    if mac is not None:
                        mac_addr = mac.get('address')
                        # Try to get IP from network DHCP leases
                        source = iface.find('source')
                        if source is not None:
                            network_name = source.get('network') or source.get('bridge')
                            if network_name:
                                # Query network for DHCP leases
                                try:
                                    net = conn.networkLookupByName(network_name)
                                    # Get DHCP leases (requires libvirt 1.2.0+)
                                    try:
                                        leases = net.DHCPLeases()
                                        for lease in leases:
                                            if lease.get('mac') == mac_addr:
                                                ip_addresses.append({
                                                    'interface': mac_addr,
                                                    'ip': lease.get('ipaddr', ''),
                                                    'type': 'ipv4',
                                                })
                                    except (libvirt.libvirtError, AttributeError):
                                        # DHCPLeases not available, skip
                                        pass
                                except libvirt.libvirtError:
                                    pass
        except libvirt.libvirtError:
            pass
        return ip_addresses
    
    def get_console(self, name: str) -> Optional[str]:
        """Get console command for a VM."""
        conn = self.connect()
        try:
            dom = conn.lookupByName(name)
            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            
            # Look for serial console
            console = root.find('.//console[@type="pty"]')
            if console is not None:
                target = console.find('target')
                if target is not None:
                    port = target.get('port', '0')
                    # Include URI in command to ensure correct connection
                    uri = self.uri if self.uri != "qemu:///system" else ""
                    if uri:
                        return f"virsh -c {uri} console {name}"
                    else:
                        return f"virsh -c qemu:///system console {name}"
        except libvirt.libvirtError:
            pass
        return None
    
    def resize_vm_disk(self, name: str, size_gb: int, disk_device: str = None) -> Dict[str, Any]:
        """Resize VM disk and expand filesystem inside VM.
        
        This is a complete process that:
        1. Gets the disk path from VM configuration
        2. Resizes the disk image file
        3. Attempts to expand the partition and filesystem inside the VM
        
        Args:
            name: VM name
            size_gb: New disk size in GB
            disk_device: Optional disk device path inside VM (e.g., /dev/vda)
                        If not provided, will try to detect from VM config
        
        Returns:
            Dict with 'success', 'disk_resized', 'filesystem_expanded', and 'message' keys
        """
        from vmfinder.disk import DiskManager
        from pathlib import Path
        
        conn = self.connect()
        result = {
            'success': False,
            'disk_resized': False,
            'filesystem_expanded': False,
            'message': '',
            'disk_path': None,
            'disk_device': disk_device,
        }
        
        try:
            dom = conn.lookupByName(name)
            
            # Get disk path from VM XML
            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            
            # Find the first disk with type='file'
            disk_elem = None
            if disk_device:
                # Try to match by target device
                for disk in root.findall('.//disk'):
                    target = disk.find('target')
                    if target is not None and target.get('dev') == disk_device.replace('/dev/', ''):
                        disk_elem = disk
                        break
            else:
                # Use first file disk
                for disk in root.findall('.//disk[@type="file"]'):
                    disk_elem = disk
                    break
            
            if disk_elem is None:
                raise ValueError("No suitable disk found in VM configuration")
            
            source = disk_elem.find('source')
            target_elem = disk_elem.find('target')
            
            if source is None or source.get('file') is None:
                raise ValueError("Disk source file not found in VM configuration")
            
            disk_path = Path(source.get('file'))
            if target_elem is not None:
                result['disk_device'] = f"/dev/{target_elem.get('dev')}"
            
            result['disk_path'] = str(disk_path)
            
            # Step 1: Resize the disk image file
            DiskManager.resize_disk(disk_path, size_gb)
            result['disk_resized'] = True
            
            # Step 2: Try to expand filesystem inside VM
            # This requires VM to be running and accessible
            state_code, _ = dom.state()
            if state_code == libvirt.VIR_DOMAIN_RUNNING:
                # VM is running, try to expand via SSH or qemu-agent
                # For now, we'll provide instructions for manual expansion
                # The CLI command will handle SSH expansion if IP is available
                result['message'] = (
                    f"Disk image resized to {size_gb}GB. "
                    f"VM is running - you may need to expand the partition and filesystem manually, "
                    f"or use the CLI with --expand-filesystem flag if SSH is available."
                )
            else:
                result['message'] = (
                    f"Disk image resized to {size_gb}GB. "
                    f"VM is not running. After starting the VM, you may need to expand "
                    f"the partition and filesystem. Many cloud images will auto-expand on first boot."
                )
            
            result['success'] = True
            return result
            
        except libvirt.libvirtError as e:
            raise RuntimeError(f"Failed to resize VM disk: {e}")