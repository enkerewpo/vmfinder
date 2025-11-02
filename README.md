# VMFinder

wheatfox

```bash
vmfinder vm create rfuse_vm --template ubuntu-20.04 --cpu 12 --memory 20480 --disk-size 30 --force
vmfinder vm start rfuse_vm
vmfinder vm list
vmfinder vm suspend rfuse_vm
vmfinder vm resume rfuse_vm

vmfinder vm console rfuse_vm