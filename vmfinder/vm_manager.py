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
