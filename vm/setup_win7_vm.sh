#!/usr/bin/env bash
# ==============================================================================
# open-ppi-bridge: Asistente de Instalación y Configuración de VM Windows 7
# 
# Este asistente automatiza:
# 1. Verificación de dependencias (QEMU, KVM, permisos de usuario).
# 2. Búsqueda y selección de la imagen ISO de Windows 7.
# 3. Creación del disco duro virtual optimizado (.qcow2).
# 4. Configuración del puerto COM1 con ppi_proxy.py (filtro anti-960B).
# 5. Primer arranque de instalación asistida.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}${BOLD}   🛠️  OPEN-PPI-BRIDGE: CONFIGURADOR AUTOMÁTICO DE VM WIN7      ${NC}"
echo -e "${CYAN}=================================================================${NC}"
echo -e "Este asistente preparará todo lo necesario para ejecutar"
echo -e "STEP 7-Micro/WIN en una máquina virtual Windows 7 sobre Linux.\n"

# ------------------------------------------------------------------------------
# 1. Comprobación e instalación de paquetes de virtualización
# ------------------------------------------------------------------------------
echo -e "${BOLD}[1/4] Verificando dependencias del sistema...${NC}"

MISSING_PKGS=()
if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    MISSING_PKGS+=(qemu-system-x86)
fi
if ! command -v qemu-img >/dev/null 2>&1; then
    MISSING_PKGS+=(qemu-utils)
fi

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo -e "${YELLOW}[!] Faltan paquetes de virtualización: ${MISSING_PKGS[*]}${NC}"
    if command -v apt-get >/dev/null 2>&1; then
        read -rp "¿Deseas instalarlos automáticamente con sudo apt? [S/n]: " RESP_APT
        RESP_APT="${RESP_APT:-s}"
        if [[ "$RESP_APT" =~ ^[sSyY]$ ]]; then
            sudo apt-get update && sudo apt-get install -y "${MISSING_PKGS[@]}"
        else
            echo -e "${RED}[-] Por favor instala los paquetes manualmente y vuelve a ejecutar este script.${NC}"
            exit 1
        fi
    elif command -v pacman >/dev/null 2>&1; then
        echo -e "${YELLOW}[i] Ejecuta: sudo pacman -S qemu-desktop${NC}"
        exit 1
    elif command -v dnf >/dev/null 2>&1; then
        echo -e "${YELLOW}[i] Ejecuta: sudo dnf install -y @virtualization qemu-img${NC}"
        exit 1
    else
        echo -e "${RED}[-] No se pudo detectar gestor de paquetes. Instala QEMU manualmente.${NC}"
        exit 1
    fi
fi
echo -e "  ${GREEN}[✓] QEMU y utilidades de disco detectados.${NC}"

# Verificar aceleración por hardware KVM
if [ -e /dev/kvm ]; then
    if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
        echo -e "  ${GREEN}[✓] Aceleración por hardware KVM habilitada y con permisos de usuario.${NC}"
    else
        echo -e "  ${YELLOW}[!] /dev/kvm existe pero el usuario actual ($USER) no tiene permisos de lectura/escritura.${NC}"
        echo -e "      Agregando usuario al grupo 'kvm' y 'dialout'..."
        sudo usermod -aG kvm,dialout "$USER" || true
        echo -e "      ${GREEN}[✓] Permisos actualizados temporalmente para esta sesión.${NC}"
        sudo chmod 666 /dev/kvm || true
    fi
else
    echo -e "  ${YELLOW}[!] Advertencia: /dev/kvm no encontrado. Verifica si la virtualización (VT-x / AMD-V) está activada en tu BIOS/UEFI.${NC}"
    echo -e "      (La VM podrá funcionar pero con emulación de CPU más lenta).${NC}"
fi

# ------------------------------------------------------------------------------
# 2. Localización de la ISO de Windows 7
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[2/4] Buscando imagen ISO de Windows 7...${NC}"

ISO_CANDIDATE="${1:-}"

if [ -z "$ISO_CANDIDATE" ]; then
    # Buscar en ubicaciones comunes
    FOUND_ISOS=()
    while IFS= read -r f; do
        [ -n "$f" ] && FOUND_ISOS+=("$f")
    done < <(find "$HOME/Downloads" "$HOME/Descargas" "$HOME/VMs" "$HOME" "$REPO_ROOT" -maxdepth 3 -type f \( -iname "*win7*.iso" -o -iname "*windows*7*.iso" -o -iname "*.iso" \) 2>/dev/null | grep -v -i "driver" | grep -v -i "archivos" | head -n 6 || true)

    if [ ${#FOUND_ISOS[@]} -gt 0 ]; then
        echo -e "  Se encontraron las siguientes imágenes ISO en tu equipo:"
        for i in "${!FOUND_ISOS[@]}"; do
            echo -e "    $((i+1))) ${CYAN}${FOUND_ISOS[$i]}${NC}"
        done
        echo -e "    $(( ${#FOUND_ISOS[@]} + 1 ))) Ingresar otra ruta manualmente"

        read -rp "Selecciona una opción [1-${#FOUND_ISOS[@]}]: " ISO_CHOICE
        if [[ "$ISO_CHOICE" =~ ^[0-9]+$ ]] && [ "$ISO_CHOICE" -ge 1 ] && [ "$ISO_CHOICE" -le "${#FOUND_ISOS[@]}" ]; then
            ISO_CANDIDATE="${FOUND_ISOS[$((ISO_CHOICE-1))]}"
        fi
    fi
fi

while [ -z "$ISO_CANDIDATE" ] || [ ! -f "$ISO_CANDIDATE" ]; do
    echo -e "${YELLOW}[!] Introduce la ruta completa hacia tu archivo ISO de Windows 7:${NC}"
    read -rp "Ruta de la ISO: " USER_INPUT_ISO
    # Expandir ~ si se utilizó
    USER_INPUT_ISO="${USER_INPUT_ISO/#\~/$HOME}"
    if [ -f "$USER_INPUT_ISO" ]; then
        ISO_CANDIDATE="$USER_INPUT_ISO"
    else
        echo -e "${RED}[-] Archivo no encontrado: $USER_INPUT_ISO. Intenta de nuevo.${NC}"
    fi
done

echo -e "  ${GREEN}[✓] ISO seleccionada: $ISO_CANDIDATE${NC}"

# ------------------------------------------------------------------------------
# 3. Preparación del disco virtual (qcow2)
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[3/4] Configuración del disco duro virtual...${NC}"

DISK_PATH="$SCRIPT_DIR/disks/win7.qcow2"
mkdir -p "$SCRIPT_DIR/disks" "$SCRIPT_DIR/shared" "$SCRIPT_DIR/logs"

if [ -f "$DISK_PATH" ]; then
    DISK_SIZE_HUMAN=$(du -h "$DISK_PATH" | cut -f1)
    echo -e "  ${YELLOW}[i] Ya existe un disco virtual en: $DISK_PATH (Tamaño actual en disco: $DISK_SIZE_HUMAN)${NC}"
    read -rp "  ¿Deseas conservarlo y usarlo? [S/n]: " RESP_DISK
    RESP_DISK="${RESP_DISK:-s}"
    if [[ ! "$RESP_DISK" =~ ^[sSyY]$ ]]; then
        read -rp "  ¿Deseas BORRARLO y crear un disco nuevo desde cero? [s/N]: " RESP_DEL
        if [[ "$RESP_DEL" =~ ^[sSyY]$ ]]; then
            rm -f "$DISK_PATH"
            echo -e "  Creando nuevo disco de 30GB (formato dinámico qcow2)..."
            qemu-img create -f qcow2 "$DISK_PATH" 30G
            echo -e "  ${GREEN}[✓] Disco creado exitosamente.${NC}"
        fi
    fi
else
    echo -e "  Creando nuevo disco de 30GB en: $DISK_PATH..."
    qemu-img create -f qcow2 "$DISK_PATH" 30G
    echo -e "  ${GREEN}[✓] Disco creado exitosamente.${NC}"
fi

# ------------------------------------------------------------------------------
# 4. Resumen y puesta en marcha
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[4/4] Resumen de configuración lista:${NC}"
echo -e "  • Disco virtual : ${CYAN}$DISK_PATH${NC}"
echo -e "  • ISO Instalación: ${CYAN}$ISO_CANDIDATE${NC}"
echo -e "  • Carpeta Compartida : ${CYAN}$SCRIPT_DIR/shared${NC}"
echo -e "  • Puerto COM1 : Mapeado automáticamente con ${CYAN}ppi_proxy.py${NC} (filtro 960B)"
echo -e "  • Servidor Web : Disponible dentro de Win7 en ${CYAN}http://10.0.2.2:8000${NC}\n"

read -rp "¿Deseas iniciar la instalación de Windows 7 ahora mismo? [S/n]: " START_NOW
START_NOW="${START_NOW:-s}"

if [[ "$START_NOW" =~ ^[sSyY]$ ]]; then
    echo -e "\n${GREEN}[*] Arrancando VM para instalación...${NC}"
    echo -e "    ${YELLOW}Nota: En la ventana de QEMU, sigue los pasos clásicos del instalador de Windows.${NC}"
    echo -e "    ${YELLOW}Una vez completada la instalación y llegado al escritorio, puedes cerrar la ventana.${NC}\n"
    exec bash "$SCRIPT_DIR/run_win7_vm.sh" --install "$ISO_CANDIDATE" --disk "$DISK_PATH"
else
    echo -e "\n${GREEN}[✓] Configuración completada.${NC}"
    echo -e "Cuando desees iniciar la instalación, simplemente ejecuta:"
    echo -e "    ${BOLD}bash vm/run_win7_vm.sh --install \"$ISO_CANDIDATE\"${NC}"
    echo -e "Y para el uso diario normal (sin ISO):"
    echo -e "    ${BOLD}bash vm/run_win7_vm.sh${NC}\n"
fi
