"""
Sistema de internacionalización (i18n) — Monitor de Postura v4.3
Idiomas soportados: Español (es) | English (en)
"""

import os
from pathlib import Path
from config.settings import CONFIG_DIR

# ── Traducciones ──────────────────────────────────────────────────────────────

TRADUCCIONES = {

    # ── Wizard general ────────────────────────────────────────────────────────
    "app_title": {
        "es": "Monitor de Postura — Configuración",
        "en": "Posture Monitor — Setup",
    },
    "app_subtitle": {
        "es": "Cuida tu espalda mientras estudias",
        "en": "Take care of your back while you study",
    },
    "app_desc": {
        "es": (
            "Analiza tu postura en tiempo real con IA.\n"
            "Recibe alertas por Telegram cuando detecta una mala posición sostenida."
        ),
        "en": (
            "Analyzes your posture in real time with AI.\n"
            "Receive Telegram alerts when poor posture is detected."
        ),
    },

    # ── Sidebar ───────────────────────────────────────────────────────────────
    "nav_inicio":        {"es": "Inicio",        "en": "Home"},
    "nav_terminos":      {"es": "Términos",       "en": "Terms"},
    "nav_telegram":      {"es": "Telegram",       "en": "Telegram"},
    "nav_preferencias":  {"es": "Preferencias",   "en": "Preferences"},
    "nav_listo":         {"es": "Listo",           "en": "Done"},
    "btn_desinstalar":   {"es": "Desinstalar",     "en": "Uninstall"},

    # ── Botones comunes ───────────────────────────────────────────────────────
    "btn_siguiente":     {"es": "Siguiente",               "en": "Next"},
    "btn_atras":         {"es": "Atrás",                   "en": "Back"},
    "btn_comenzar":      {"es": "Comenzar configuración",  "en": "Start setup"},
    "btn_guardar":       {"es": "Guardar y continuar",     "en": "Save & continue"},
    "btn_finalizar":     {"es": "Guardar y finalizar",     "en": "Save & finish"},
    "btn_iniciar":       {"es": "Iniciar Monitor",         "en": "Start Monitor"},
    "btn_aceptar":       {"es": "Aceptar y continuar",     "en": "Accept & continue"},
    "btn_copiar":        {"es": "Copiar",                  "en": "Copy"},
    "btn_detectar":      {"es": "Detectar mi Chat ID",     "en": "Detect my Chat ID"},
    "btn_prueba":        {"es": "Enviar mensaje de prueba","en": "Send test message"},

    # ── Página inicio ─────────────────────────────────────────────────────────
    "feat_ia":        {"es": "Detección con IA",    "en": "AI Detection"},
    "feat_telegram":  {"es": "Alertas Telegram",    "en": "Telegram Alerts"},
    "feat_nube":      {"es": "Datos en la nube",    "en": "Cloud Data"},

    # ── Página términos ───────────────────────────────────────────────────────
    "terminos_titulo": {"es": "Términos y Condiciones", "en": "Terms & Conditions"},
    "terminos_check":  {
        "es": "He leído y acepto los términos y condiciones",
        "en": "I have read and accept the terms and conditions",
    },
    "terminos_texto": {
        "es": (
            "TÉRMINOS Y CONDICIONES DE USO\n\n"
            "1. ACEPTACIÓN\nAl utilizar este software, aceptas estos términos.\n\n"
            "2. PRIVACIDAD\n"
            "- Los datos de postura se almacenan en Supabase (nube).\n"
            "- Las imágenes NO se guardan ni transmiten.\n"
            "- Los datos se usan para análisis académico anonimizado.\n\n"
            "3. CÁMARA\nSe requiere acceso a la cámara web. "
            "Las imágenes se procesan localmente en tu equipo.\n\n"
            "4. NOTIFICACIONES\nEl sistema enviará alertas a tu cuenta de Telegram.\n\n"
            "5. RESPONSABILIDAD\nHerramienta de asistencia. No reemplaza consejo médico.\n\n"
            "6. LEY APLICABLE\nRepública del Ecuador."
        ),
        "en": (
            "TERMS AND CONDITIONS OF USE\n\n"
            "1. ACCEPTANCE\nBy using this software, you agree to these terms.\n\n"
            "2. PRIVACY\n"
            "- Posture data is stored in Supabase (cloud).\n"
            "- Images are NOT saved or transmitted.\n"
            "- Data is used for anonymized academic analysis.\n\n"
            "3. CAMERA\nWebcam access is required. "
            "Images are processed locally on your device.\n\n"
            "4. NOTIFICATIONS\nThe system will send alerts to your configured Telegram account.\n\n"
            "5. DISCLAIMER\nThis is an assistive tool. It does not replace medical advice.\n\n"
            "6. GOVERNING LAW\nRepublic of Ecuador."
        ),
    },

    # ── Página Telegram ───────────────────────────────────────────────────────
    "telegram_titulo":   {"es": "Configuración de Telegram",    "en": "Telegram Setup"},
    "telegram_bot_label":{"es": "Bot:",                         "en": "Bot:"},
    "telegram_info": {
        "es": "1. Busca <b>{bot}</b> en Telegram y envíale cualquier mensaje\n2. Haz clic en <b>Detectar mi Chat ID</b>",
        "en": "1. Search for <b>{bot}</b> on Telegram and send any message\n2. Click <b>Detect my Chat ID</b>",
    },
    "telegram_auto":     {"es": "Detección automática",         "en": "Auto detection"},
    "telegram_manual":   {"es": "O ingrésalo manualmente",      "en": "Or enter it manually"},
    "telegram_placeholder": {"es": "Ej: 123456789",             "en": "E.g.: 123456789"},
    "telegram_copiado":  {"es": "Copiado",                      "en": "Copied"},
    "telegram_msg_copiado": {
        "es": "'{bot}' copiado al portapapeles",
        "en": "'{bot}' copied to clipboard",
    },
    "telegram_consultando": {"es": "Consultando...",            "en": "Checking..."},
    "telegram_enviando":    {"es": "Enviando...",               "en": "Sending..."},
    "telegram_sin_id": {
        "es": "Ingresa tu Chat ID primero",
        "en": "Enter your Chat ID first",
    },
    "telegram_requerido": {
        "es": "Chat ID requerido",
        "en": "Chat ID required",
    },
    "telegram_requerido_desc": {
        "es": "Detecta o ingresa tu Chat ID.",
        "en": "Detect or enter your Chat ID.",
    },

    # ── Página preferencias ───────────────────────────────────────────────────
    "pref_titulo":        {"es": "Preferencias",                "en": "Preferences"},
    "pref_autoarranque":  {"es": "Inicio automático",           "en": "Auto-start"},
    "pref_auto_desc": {
        "es": "Si lo activas, el monitor se iniciará automáticamente\ncada vez que enciendas tu computadora.",
        "en": "If enabled, the monitor will start automatically\nevery time you turn on your computer.",
    },
    "pref_auto_check": {
        "es": "Iniciar Monitor de Postura con el sistema",
        "en": "Start Posture Monitor with the system",
    },
    "pref_idioma":        {"es": "Idioma / Language",           "en": "Language / Idioma"},
    "pref_info": {
        "es": "💡 Puedes cambiar estas preferencias más adelante\nejecutando: postura-monitor --configurar",
        "en": "💡 You can change these preferences later\nby running: postura-monitor --configurar",
    },

    # ── Página completado ─────────────────────────────────────────────────────
    "done_titulo":   {"es": "¡Todo listo!",                     "en": "All set!"},
    "done_telegram": {"es": "✓ Telegram configurado correctamente", "en": "✓ Telegram configured successfully"},
    "done_config":   {"es": "✓ Configuración guardada",         "en": "✓ Settings saved"},
    "done_auto_si":  {"es": "✓ Se iniciará automáticamente con el sistema", "en": "✓ Will start automatically with the system"},
    "done_auto_no":  {"es": "→ Inicio manual (ejecuta 'postura-monitor')",  "en": "→ Manual start (run 'postura-monitor')"},

    # ── Desinstalar ───────────────────────────────────────────────────────────
    "des_titulo":   {"es": "Desinstalar Monitor de Postura",    "en": "Uninstall Posture Monitor"},
    "des_mensaje": {
        "es": (
            "¿Estás seguro de que deseas desinstalar el programa?\n\n"
            "Se eliminarán los archivos de la aplicación.\n"
            "Tu configuración de Telegram NO se eliminará."
        ),
        "en": (
            "Are you sure you want to uninstall the program?\n\n"
            "Application files will be removed.\n"
            "Your Telegram settings will NOT be deleted."
        ),
    },
    "des_exito":   {"es": "Desinstalado",                       "en": "Uninstalled"},
    "des_exito_msg": {
        "es": "Monitor de Postura se ha desinstalado correctamente.",
        "en": "Posture Monitor has been successfully uninstalled.",
    },
    "des_error_msg": {
        "es": (
            "No se pudo desinstalar automáticamente.\n\n"
            "En Linux ejecuta:\n  sudo dpkg -r postura-monitor\n\n"
            "En Windows usa:\n  Panel de Control → Programas → Desinstalar"
        ),
        "en": (
            "Could not uninstall automatically.\n\n"
            "On Linux run:\n  sudo dpkg -r postura-monitor\n\n"
            "On Windows use:\n  Control Panel → Programs → Uninstall"
        ),
    },

    # ── Validaciones ─────────────────────────────────────────────────────────
    "aceptacion_requerida": {
        "es": "Aceptación requerida",
        "en": "Acceptance required",
    },
    "aceptacion_requerida_msg": {
        "es": "Debes aceptar los términos primero.",
        "en": "You must accept the terms first.",
    },
    "config_pendiente": {
        "es": "Configuración pendiente",
        "en": "Setup pending",
    },
    "config_pendiente_msg": {
        "es": "Completa la configuración de Telegram.",
        "en": "Complete the Telegram setup.",
    },

    # ── Notificaciones Telegram ───────────────────────────────────────────────
    "notif_alerta_titulo": {
        "es": "⚠️ Alerta de Postura",
        "en": "⚠️ Posture Alert",
    },
    "notif_tipo":          {"es": "Tipo",           "en": "Type"},
    "notif_duracion":      {"es": "Duración",        "en": "Duration"},
    "notif_angulo_cuello": {"es": "Ángulo cuello",   "en": "Neck angle"},
    "notif_angulo_espalda":{"es": "Ángulo espalda",  "en": "Back angle"},
    "notif_minutos":       {"es": "min",             "en": "min"},
    "notif_segundos":      {"es": "seg",             "en": "sec"},
    "notif_sedentarismo": {
        "es": "🪑 Llevas {t} min sin moverte. ¡Levántate y estira!",
        "en": "🪑 You've been sitting for {t} min. Get up and stretch!",
    },
    "notif_conexion_ok": {
        "es": "✅ Monitor de Postura configurado correctamente.",
        "en": "✅ Posture Monitor configured successfully.",
    },
    "notif_resumen_titulo": {
        "es": "📊 Resumen de sesión",
        "en": "📊 Session summary",
    },
    "notif_sesion_duracion": {"es": "Duración",      "en": "Duration"},
    "notif_alertas_enviadas":{"es": "Alertas",        "en": "Alerts"},

    # ── Estados de postura ────────────────────────────────────────────────────
    "estado_correcta":     {"es": "Correcta",         "en": "Correct"},
    "estado_advertencia":  {"es": "Advertencia",      "en": "Warning"},
    "estado_incorrecta":   {"es": "Incorrecta",       "en": "Incorrect"},
    "estado_sin_deteccion":{"es": "Sin detección",    "en": "No detection"},
}


# ── Motor de traducción ───────────────────────────────────────────────────────

class I18n:
    _idioma: str = "es"

    @classmethod
    def cargar(cls) -> None:
        """Lee el idioma guardado en config.env."""
        env = CONFIG_DIR / "config.env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("IDIOMA="):
                    val = line.split("=", 1)[1].strip()
                    if val in ("es", "en"):
                        cls._idioma = val
                        return
        cls._idioma = os.environ.get("IDIOMA", "es")

    @classmethod
    def guardar(cls, idioma: str) -> None:
        if idioma not in ("es", "en"):
            return
        cls._idioma = idioma
        env = CONFIG_DIR / "config.env"
        lineas = []
        if env.exists():
            lineas = [l for l in env.read_text(encoding="utf-8").splitlines()
                      if not l.startswith("IDIOMA=")]
        lineas.append(f"IDIOMA={idioma}")
        env.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    @classmethod
    def t(cls, clave: str, **kwargs) -> str:
        """Traduce una clave. Acepta kwargs para formateo."""
        entrada = TRADUCCIONES.get(clave, {})
        texto = entrada.get(cls._idioma, entrada.get("es", clave))
        if kwargs:
            try:
                texto = texto.format(**kwargs)
            except KeyError:
                pass
        return texto

    @classmethod
    def idioma(cls) -> str:
        return cls._idioma


# Instancia global
i18n = I18n()
i18n.cargar()


def t(clave: str, **kwargs) -> str:
    """Atajo global: from config.i18n import t"""
    return I18n.t(clave, **kwargs)
