#!/usr/bin/env bash
# ==============================================================================
# open-ppi-bridge: Example QEMU/KVM Windows 7 Startup Script
#
# This script bridges the Windows 7 virtual COM1 port to the UNIX socket
# created by ppi_proxy.py (/tmp/qemu_serial.sock).
# ==============================================================================

set -euo pipefail

SOCKET_PATH="/tmp/qemu_serial.sock"
VM_DISK="${1:-win7.qcow2}"

if [ ! -S "$SOCKET_PATH" ]; then
    echo "[-] Error: S7-200 PPI proxy socket ($SOCKET_PATH) not found."
    echo "    Please start the proxy first:"
    echo "    python3 scripts/ppi_proxy.py"
    exit 1
fi

if [ ! -f "$VM_DISK" ]; then
    echo "[-] Error: Virtual disk '$VM_DISK' does not exist."
    echo "    Usage: $0 [path/to/win7.qcow2]"
    exit 1
fi

echo "[+] Starting Windows 7 QEMU/KVM with COM1 -> $SOCKET_PATH..."

qemu-system-x86_64 \
    -enable-kvm \
    -m 2048 \
    -smp 2,sockets=1,cores=2,threads=1 \
    -cpu host,hv_relaxed,hv_vapic,hv_spinlocks=0x1fff,hv_time \
    -rtc base=localtime,clock=host,driftfix=slew \
    -drive "file=$VM_DISK,format=qcow2,if=ide,cache=writeback" \
    -chardev "socket,id=serial0,path=$SOCKET_PATH" \
    -serial chardev:serial0 \
    -display default
