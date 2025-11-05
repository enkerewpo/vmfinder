# VMFinder

[![PyPI](https://img.shields.io/pypi/v/vmfinder.svg)](https://pypi.python.org/pypi/vmfinder)

## features
- vm creation and management
- template management
- cloud image support
- network management
- disk management
- virtio-fs shared folder support
- cloud-init support

## quick start

```bash
pip install vmfinder

vmfinder init
vmfinder install-completion
```

example usage:

```bash
vmfinder vm create rfuse_vm --template ubuntu-20.04 --cpu 12 --memory 20480 --disk-size 60 --force
vmfinder vm start rfuse_vm
vmfinder vm list
vmfinder vm console rfuse_vm
vmfinder vm ssh rfuse_vm
vmfinder vm ssh rfuse_vm --username ubuntu
vmfinder vm ssh rfuse_vm --key ~/.ssh/id_rsa
ssh -p 1234 ubuntu@<ip_address>
vmfinder vm set-password rfuse_vm
```

```bash
# extfuse
vmfinder vm create extfuse_vm --template ubuntu-16.04 --cpu 12 --memory 20480 --disk-size 60 --force
# cache_ext
vmfinder vm create cache_vm --template ubuntu-22.04 --cpu 12 --memory 20480 --disk-size 60 --force
# virtio-fs shared folder
vmfinder vm create vm1 \
    --template ubuntu-24.04 \
    --cpu 12 \
    --memory 20480 \
    --disk-size 80 \
    --force

# Start VM (virtiofsd will be started automatically)
vmfinder vm start vm1

# Manage virtiofsd manually
vmfinder virtiofs status vm1
vmfinder virtiofs stop vm1
vmfinder virtiofs start vm1 /path/to/shared/dir
vmfinder virtiofs restart vm1
```

**Note:** When creating a VM with `--virtiofs`, the virtiofsd daemon will be started automatically. The VM will automatically start/stop virtiofsd when you start/stop the VM. Inside the VM, mount the shared directory with:

```bash
sudo mkdir -p /mnt/shared
sudo mount -t virtiofs shared /mnt/shared
```

---

copyright 2025 wheatfox <<wheatfox17@icloud.com>>