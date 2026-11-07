#!/usr/bin/env bash
# ==============================================================================
# open-ppi-bridge: Windows 7 QEMU/KVM Virtual Machine Launcher
# 
# Permite ejecutar STEP 7-Micro/WIN en Windows 7 conectando el puerto COM1
# virtual directamente al filtro inteligente anti-960B (ppi_proxy.py) o
# puente inalámbrico BLE para programar PLC Siemens SIMATIC S7-200.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DISK="${DISK:-$SCRIPT_DIR/disks/win7.qcow2}"
RAM="${RAM:-2048}"
SMP="${SMP:-2}"
ISO=""
START_PROXY=1
USE_BLE=0
SERIAL_NODE=""
START_WEB=1
WEB_PORT=8000

# Colores de salida
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # Sin color

usage() {
    cat <<EOF
Uso: $0 [opciones]

Opciones:
  --install <iso>       Modo instalación: Arranca desde la imagen ISO de Windows 7.
  --iso <iso>           Monta la ISO especificada como unidad de CD-ROM.
  --disk <ruta>         Ruta al disco virtual qcow2 (Por defecto: vm/disks/win7.qcow2).
  --ram <MB>            Memoria RAM asignada en MB (Por defecto: 2048).
  --smp <núcleos>       Número de núcleos de CPU (Por defecto: 2).
  --ble                 Activar puente serie inalámbrico Bluetooth LE (S7-200-PPI-BLE).
  --serial <nodo>       Dispositivo serie específico (ej. /dev/ttyUSB0).
  --no-proxy            No iniciar ppi_proxy.py (pasar COM1 directo si hay puerto).
  --no-web              No iniciar el servidor web de transferencia de archivos.
  -h, --help            Muestra este mensaje de ayuda.

Ejemplos:
  $0 --install ~/Descargas/win7_x86.iso
  $0
  $0 --ble
EOF
    exit 0
}

# Procesar argumentos
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install)
            ISO="$2"
            shift 2
            ;;
        --iso)
            ISO="$2"
            shift 2
            ;;
        --disk)
            DISK="$2"
            shift 2
            ;;
        --ram)
            RAM="$2"
            shift 2
            ;;
        --smp)
            SMP="$2"
            shift 2
            ;;
        --ble)
            USE_BLE=1
            shift
            ;;
        --serial)
            SERIAL_NODE="$2"
            shift 2
            ;;
        --no-proxy)
            START_PROXY=0
            shift
            ;;
        --no-web)
            START_WEB=0
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [[ -f "$1" && "$1" == *.iso ]]; then
                ISO="$1"
                shift
            else
                echo -e "${RED}[-] Opción no reconocida: $1${NC}"
                usage
            fi
            ;;
    esac
done

echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}   🚀 OPEN-PPI-BRIDGE: LANZADOR DE MÁQUINA VIRTUAL WINDOWS 7     ${NC}"
echo -e "${CYAN}=================================================================${NC}"

# Validar existencia de disco
if [ ! -f "$DISK" ]; then
    echo -e "${YELLOW}[!] El disco virtual '$DISK' no existe.${NC}"
    if [ -z "$ISO" ]; then
        echo -e "${RED}[-] Para instalar Windows 7 ejecuta primero:${NC}"
        echo -e "    ${GREEN}bash $SCRIPT_DIR/setup_win7_vm.sh${NC}"
        exit 1
    else
        echo -e "[*] Creando disco virtual base de 30GB en $DISK..."
        mkdir -p "$(dirname "$DISK")"
        qemu-img create -f qcow2 "$DISK" 30G
    fi
fi

# PIDs para limpieza
BLE_PID=""
PROXY_PID=""
WEB_PID=""

cleanup() {
    echo -e "\n${YELLOW}[*] Cerrando servicios de soporte...${NC}"
    if [ -n "$BLE_PID" ]; then
        kill "$BLE_PID" 2>/dev/null || true
        wait "$BLE_PID" 2>/dev/null || true
    fi
    if [ -n "$PROXY_PID" ]; then
        kill "$PROXY_PID" 2>/dev/null || true
        wait "$PROXY_PID" 2>/dev/null || true
    fi
    if [ -n "$WEB_PID" ]; then
        kill "$WEB_PID" 2>/dev/null || true
        wait "$WEB_PID" 2>/dev/null || true
    fi
    rm -f /tmp/qemu_serial.sock 2>/dev/null || true
    echo -e "${GREEN}[✓] Sesión finalizada correctamente.${NC}"
}
trap cleanup EXIT INT TERM

# 1. Enlace BLE si se solicita
if [ "$USE_BLE" -eq 1 ]; then
    BLE_SCRIPT="$REPO_ROOT/scripts/ble_serial_bridge.py"
    if [ -f "$BLE_SCRIPT" ]; then
        echo -e "[*] Iniciando enlace inalámbrico BLE hacia S7-200-PPI-BLE..."
        pkill -f "ble_serial_bridge.py" 2>/dev/null || true
        rm -f /tmp/ttyPPI
        python3 "$BLE_SCRIPT" > "$SCRIPT_DIR/logs/ble_bridge.log" 2>&1 &
        BLE_PID=$!
        for i in $(seq 1 40); do
            [ -e "/tmp/ttyPPI" ] && break
            sleep 0.1
        done
        if [ -e "/tmp/ttyPPI" ]; then
            echo -e "  ${GREEN}[✓] Enlace BLE conectado en /tmp/ttyPPI${NC}"
            SERIAL_NODE="/tmp/ttyPPI"
        else
            echo -e "  ${YELLOW}[!] Advertencia: No se detectó S7-200-PPI-BLE en tiempo. Continuando sin BLE.${NC}"
            kill "$BLE_PID" 2>/dev/null || true
            BLE_PID=""
        fi
    fi
fi

# 2. Detección automática de dispositivo serie si no se especificó
if [ -z "$SERIAL_NODE" ]; then
    if [ -e "/tmp/ttyPPI" ]; then
        SERIAL_NODE="/tmp/ttyPPI"
    elif [ -e "/dev/serial/by-id" ]; then
        FTDI_DEV=$(ls /dev/serial/by-id/*FTDI* 2>/dev/null | head -n 1 || true)
        if [ -n "$FTDI_DEV" ]; then
            SERIAL_NODE="$FTDI_DEV"
        fi
    fi
    if [ -z "$SERIAL_NODE" ]; then
        for dev in /dev/ttyUSB0 /dev/ttyUSB1 /dev/ttyACM0; do
            if [ -e "$dev" ]; then
                SERIAL_NODE="$dev"
                break
            fi
        done
    fi
fi

# 3. Calibración de latencia FTDI si corresponde
if [ -n "$SERIAL_NODE" ] && [[ "$SERIAL_NODE" == *ttyUSB* || "$SERIAL_NODE" == *FTDI* ]]; then
    REAL_TTY=$(basename "$(readlink -f "$SERIAL_NODE" 2>/dev/null || echo "$SERIAL_NODE")")
    LATENCY_FILE="/sys/bus/usb-serial/devices/$REAL_TTY/latency_timer"
    if [ -w "$LATENCY_FILE" ]; then
        echo 1 > "$LATENCY_FILE" 2>/dev/null || true
        echo -e "  ${GREEN}[✓] Latencia FTDI configurada a 1ms ($REAL_TTY)${NC}"
    fi
fi

# 4. Proxy Inteligente PPI (Filtro Anti-960B)
SERIAL_ARGS=()
if [ "$START_PROXY" -eq 1 ]; then
    PROXY_SCRIPT="$REPO_ROOT/scripts/ppi_proxy.py"
    if [ -f "$PROXY_SCRIPT" ] && [ -n "$SERIAL_NODE" ]; then
        echo -e "[*] Iniciando Proxy Inteligente PPI (Filtro 960B) sobre $SERIAL_NODE..."
        mkdir -p "$SCRIPT_DIR/logs"
        rm -f /tmp/qemu_serial.sock
        pkill -f "ppi_proxy.py" 2>/dev/null || true

        python3 "$PROXY_SCRIPT" "$SERIAL_NODE" > "$SCRIPT_DIR/logs/proxy.log" 2>&1 &
        PROXY_PID=$!

        for i in $(seq 1 30); do
            [ -S "/tmp/qemu_serial.sock" ] && break
            sleep 0.1
        done

        if [ -S "/tmp/qemu_serial.sock" ]; then
            echo -e "  ${GREEN}[✓] Proxy activo (/tmp/qemu_serial.sock) -> Conectado a COM1 virtual.${NC}"
            SERIAL_ARGS+=(-chardev "socket,id=serial0,path=/tmp/qemu_serial.sock" -serial chardev:serial0)
        else
            echo -e "  ${YELLOW}[!] No se pudo crear socket del proxy. Intentando puerto directo...${NC}"
            SERIAL_ARGS+=(-serial "$SERIAL_NODE")
        fi
    elif [ -n "$SERIAL_NODE" ]; then
        echo -e "[*] Asignando puerto directo $SERIAL_NODE como COM1..."
        SERIAL_ARGS+=(-serial "$SERIAL_NODE")
    else
        echo -e "  ${YELLOW}[i] Sin adaptador serie detectado. COM1 virtual no conectado (Modo Offline).${NC}"
    fi
fi

# 5. Servidor de transferencia web para intercambiar .awl/.mwp
if [ "$START_WEB" -eq 1 ]; then
    WEB_SCRIPT="$REPO_ROOT/scripts/web_transfer.py"
    SHARED_DIR="$SCRIPT_DIR/shared"
    mkdir -p "$SHARED_DIR" "$SCRIPT_DIR/logs"

    if [ -f "$WEB_SCRIPT" ]; then
        pkill -f "web_transfer.py" 2>/dev/null || true
        python3 "$WEB_SCRIPT" --dir "$SHARED_DIR" --port "$WEB_PORT" > "$SCRIPT_DIR/logs/web_transfer.log" 2>&1 &
        WEB_PID=$!
        echo -e "  ${GREEN}[✓] Servidor de transferencia activo:${NC}"
        echo -e "      Host:   $SHARED_DIR"
        echo -e "      Win7:   ${CYAN}http://10.0.2.2:$WEB_PORT${NC} (en Internet Explorer)"
    fi
fi

# 6. Preparar argumentos de QEMU
QEMU_ARGS=(
    -enable-kvm
    -m "$RAM"
    -smp "$SMP,sockets=1,cores=$SMP,threads=1"
    -cpu host,hv_relaxed,hv_vapic,hv_spinlocks=0x1fff,hv_time
    -rtc base=localtime,clock=host,driftfix=slew
    -drive "file=$DISK,format=qcow2,if=ide,cache=writeback,aio=threads,discard=unmap"
    -device usb-tablet
    -device intel-hda
    -device hda-duplex
    -nic user,model=e1000
    -display default
)

if [ -n "$ISO" ]; then
    if [ ! -f "$ISO" ]; then
        echo -e "${RED}[-] Error: El archivo ISO '$ISO' no existe.${NC}"
        exit 1
    fi
    echo -e "[*] Montando medio de instalación: $ISO"
    QEMU_ARGS+=(-drive "file=$ISO,media=cdrom,readonly=on" -boot order=d)
else
    QEMU_ARGS+=(-boot order=c)
fi

QEMU_ARGS+=("${SERIAL_ARGS[@]}")

echo -e "\n${GREEN}[+] Lanzando máquina virtual Windows 7...${NC}"
echo -e "    RAM: ${RAM}MB | CPUs: ${SMP} | Disco: $DISK"
echo -e "${CYAN}-----------------------------------------------------------------${NC}"

qemu-system-x86_64 "${QEMU_ARGS[@]}"
