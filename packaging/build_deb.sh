#!/usr/bin/env bash
# =============================================================================
# build_deb.sh — Construye el paquete .deb de Monitor de Postura v4
# Ejecutar desde la RAÍZ del proyecto: ./packaging/build_deb.sh
# Probado en: Ubuntu 22.04, Bodhi Linux 7 (jammy)
# =============================================================================
set -euo pipefail

APP_NAME="postura-monitor"
APP_VERSION="4.4.1"
ARCH="amd64"
MAINTAINER="Tu Nombre <tu@email.com>"
DESCRIPTION="Monitor de postura en tiempo real con IA, Telegram y Supabase"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build_output"
DIST_DIR="$PROJECT_ROOT/dist/postura-monitor"
DEB_STAGE="$BUILD_DIR/deb_stage"

echo "============================================================"
echo "  Monitor de Postura v4 — Build .deb"
echo "============================================================"
echo "Proyecto: $PROJECT_ROOT"

# ── Detectar versión de Python compatible (3.10 o 3.11, NO 3.12) ─────────────
detect_python() {
    for cmd in python3.10 python3.11 python3; do
        if command -v "$cmd" &>/dev/null; then
            ver=$("$cmd" -c "import sys; print(sys.version_info[:2])")
            if [[ "$ver" == "(3, 10)" || "$ver" == "(3, 11)" ]]; then
                echo "$cmd"; return
            fi
        fi
    done
    echo ""
}

PYTHON=$(detect_python)
if [ -z "$PYTHON" ]; then
    echo ""
    echo "ERROR: No se encontró Python 3.10 o 3.11."
    echo "Instala con: sudo apt-get install python3.10 python3.10-venv"
    exit 1
fi
echo "Usando: $PYTHON ($($PYTHON --version))"

# ── 1. Entorno virtual ────────────────────────────────────────────────────────
echo ""
echo ">>> [1/5] Preparando entorno virtual..."
cd "$PROJECT_ROOT"

rm -rf venv/
"$PYTHON" -m venv venv
source venv/bin/activate

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet
echo "    Dependencias instaladas."

# ── 2. PyInstaller ────────────────────────────────────────────────────────────
echo ""
echo ">>> [2/5] Compilando con PyInstaller..."
rm -rf dist/ build/
pyinstaller packaging/postura_monitor.spec --noconfirm --clean

if [ ! -d "$DIST_DIR" ]; then
    echo "ERROR: PyInstaller no generó '$DIST_DIR'"
    exit 1
fi
echo "    Compilación exitosa. Tamaño:"
du -sh "$DIST_DIR"

# ── 3. Estructura del paquete .deb ────────────────────────────────────────────
echo ""
echo ">>> [3/5] Creando estructura del paquete..."
rm -rf "$DEB_STAGE"
mkdir -p "$DEB_STAGE/DEBIAN"
mkdir -p "$DEB_STAGE/opt/$APP_NAME"
mkdir -p "$DEB_STAGE/usr/local/bin"
mkdir -p "$DEB_STAGE/usr/share/applications"
mkdir -p "$DEB_STAGE/usr/share/doc/$APP_NAME"

cp -r "$DIST_DIR/." "$DEB_STAGE/opt/$APP_NAME/"

# Lanzador — fija rutas Qt para evitar conflicto cv2 vs PySide6
cat > "$DEB_STAGE/usr/local/bin/$APP_NAME" << 'LAUNCHER'
#!/bin/bash
export QT_QPA_PLATFORM_PLUGIN_PATH=/opt/postura-monitor/_internal/PySide6/Qt/plugins/platforms
export QT_PLUGIN_PATH=/opt/postura-monitor/_internal/PySide6/Qt/plugins
export QT_QPA_PLATFORM=xcb
exec /opt/postura-monitor/postura-monitor "$@"
LAUNCHER
chmod +x "$DEB_STAGE/usr/local/bin/$APP_NAME"

# Entrada de escritorio
cat > "$DEB_STAGE/usr/share/applications/$APP_NAME.desktop" << 'DESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=Monitor de Postura
Comment=Monitoreo de postura en tiempo real con IA
Exec=/usr/local/bin/postura-monitor
Icon=/opt/postura-monitor/onboarding/img/monitoreo-postura.jpg
Terminal=false
Categories=Utility;Science;
Keywords=postura;salud;cámara;monitor;
StartupNotify=true
DESKTOP

cp "$PROJECT_ROOT/README.md" "$DEB_STAGE/usr/share/doc/$APP_NAME/" 2>/dev/null || true

# ── 4. Metadatos DEBIAN ───────────────────────────────────────────────────────
echo ""
echo ">>> [4/5] Generando metadatos DEBIAN..."

INSTALLED_SIZE=$(du -sk "$DEB_STAGE/opt" | cut -f1)

cat > "$DEB_STAGE/DEBIAN/control" << CTRL
Package: $APP_NAME
Version: $APP_VERSION
Architecture: $ARCH
Maintainer: $MAINTAINER
Installed-Size: $INSTALLED_SIZE
Depends: libgl1, libglib2.0-0, libxcb-xinerama0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xkb1, libxkbcommon-x11-0, libdbus-1-3, libxcb-cursor0
Recommends: v4l-utils
Section: utils
Priority: optional
Description: $DESCRIPTION
 Detecta en tiempo real si tu postura frente a la computadora
 es correcta usando inteligencia artificial (MediaPipe).
 Envía alertas personalizadas por Telegram y registra
 estadísticas en Supabase (nube).
 .
 Solo requiere conectar tu cuenta de Telegram en el primer inicio.
CTRL

cat > "$DEB_STAGE/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
chmod +x /opt/postura-monitor/postura-monitor || true
chmod +x /usr/local/bin/postura-monitor || true
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications/ || true
fi
echo ""
echo "✅ Monitor de Postura instalado correctamente."
echo "   Ejecuta 'postura-monitor' o búscalo en el menú de aplicaciones."
echo "   En el primer inicio se abrirá el asistente de configuración."
echo ""
exit 0
POSTINST
chmod 755 "$DEB_STAGE/DEBIAN/postinst"

cat > "$DEB_STAGE/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
set -e
echo "Desinstalando Monitor de Postura..."
exit 0
PRERM
chmod 755 "$DEB_STAGE/DEBIAN/prerm"

# Script postrm — limpia /opt si queda vacío
cat > "$DEB_STAGE/DEBIAN/postrm" << 'POSTRM'
#!/bin/bash
set -e
rm -rf /opt/postura-monitor 2>/dev/null || true
exit 0
POSTRM
chmod 755 "$DEB_STAGE/DEBIAN/postrm"

# ── 5. Empaquetar ─────────────────────────────────────────────────────────────
echo ""
echo ">>> [5/5] Construyendo el .deb..."
mkdir -p "$BUILD_DIR"
dpkg-deb --build --root-owner-group "$DEB_STAGE" \
    "$BUILD_DIR/${APP_NAME}_${APP_VERSION}_${ARCH}.deb"

deactivate

echo ""
echo "============================================================"
echo "  ✅  LISTO"
echo "  Paquete: $BUILD_DIR/${APP_NAME}_${APP_VERSION}_${ARCH}.deb"
echo ""
echo "  Para instalar:"
echo "    sudo dpkg -i $BUILD_DIR/${APP_NAME}_${APP_VERSION}_${ARCH}.deb"
echo "    sudo apt-get install -f   # si faltan dependencias"
echo ""
echo "  Para desinstalar:"
echo "    sudo dpkg -r $APP_NAME"
echo "============================================================"
