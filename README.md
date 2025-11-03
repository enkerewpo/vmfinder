# VMFinder

[![PyPI](https://img.shields.io/pypi/v/vmfinder.svg)](https://pypi.python.org/pypi/vmfinder)

wheatfox

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
```

copyright 2025 wheatfox