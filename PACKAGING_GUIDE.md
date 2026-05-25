# Guía de Empaquetado — Monitor de Postura v4

## Cambios aplicados en esta versión

| Problema | Solución |
|---|---|
| Credenciales en texto plano | Obfuscación XOR+Base64 en `config/credentials.py` |
| Rutas relativas al proyecto | Rutas XDG: `~/.config/postura-monitor/` |
| `opencv-python` conflicto Qt | Cambiado a `opencv-python-headless` |
| `matplotlib` faltante | Agregado a requirements y hiddenimports |
| `libxcb-cursor0` faltante | Agregado como dependencia en el .deb |
| Launcher sin rutas Qt | Lanzador fija `QT_QPA_PLATFORM_PLUGIN_PATH` |
| Python 3.12 incompatible | Auto-detección de Python 3.10/3.11 |
| Directorio `/opt` no limpio al desinstalar | Script `postrm` añadido |

---

## Construir el .deb (Linux)

### Requisitos
- Ubuntu 22.04 / Bodhi Linux 7 (64-bit)
- Python 3.10 o 3.11
- `dpkg-dev` instalado

### Pasos

```bash
# Instalar dependencias del sistema (solo la primera vez)
sudo apt-get install -y python3.10-venv dpkg-dev libgl1 \
  libglib2.0-0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxkbcommon-x11-0 libxcb-cursor0

# Construir
chmod +x packaging/build_deb.sh
./packaging/build_deb.sh

# Instalar
sudo dpkg -i build_output/postura-monitor_4.0.0_amd64.deb

# Si faltan dependencias
sudo apt-get install -f
```

### En otras máquinas (distribución del .deb)
El .deb generado funciona en cualquier Ubuntu/Debian 22.04+ de 64 bits.
La única dependencia extra que puede faltar es `libxcb-cursor0`:
```bash
sudo apt-get install libxcb-cursor0
sudo dpkg -i postura-monitor_4.0.0_amd64.deb
```

---

## Construir el instalador de Windows (.exe)

### Requisitos
- Windows 10/11 64-bit
- Python 3.10 o 3.11 desde [python.org](https://python.org) (**marcar "Add to PATH"**)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (opcional, para el instalador .exe)

### Pasos
```
1. Doble clic en: packaging\build_windows.bat
2. Esperar (~10-15 min la primera vez)
3. Resultado en: build_output\
   - postura-monitor_4.0.0_windows.zip   (siempre)
   - postura-monitor_4.0.0_setup.exe     (si Inno Setup está instalado)
```

---

## Flujo del usuario final

```
Instala .deb o .exe
       │
       ▼
Primer inicio → Wizard Qt6
  1. Pantalla de bienvenida
  2. Aceptar términos
  3. Buscar @mi_postura_bot en Telegram → enviar mensaje
  4. Clic "Detectar Chat ID"
  5. Clic "Guardar y continuar"
       │
       ▼
Guarda: ~/.config/postura-monitor/config.env
  (solo TELEGRAM_CHAT_ID=... del usuario)
       │
       ▼
Monitor inicia en modo producción
```

---

## Archivos del usuario (no se eliminan al desinstalar)
```
~/.config/postura-monitor/
  config.env                 ← TELEGRAM_CHAT_ID del usuario
  .onboarding_completed      ← Estado del wizard

~/.local/share/postura-monitor/
  logs/sistema.log           ← Logs rotativos
```

Para resetear la configuración del usuario:
```bash
rm -rf ~/.config/postura-monitor ~/.local/share/postura-monitor
```
