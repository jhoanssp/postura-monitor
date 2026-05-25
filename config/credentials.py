"""
Credenciales de la aplicación — ofuscadas con XOR + Base64.
No son visibles como texto plano en el binario compilado.
El usuario solo provee su TELEGRAM_CHAT_ID durante el onboarding.
"""

import base64


def _d(s: str) -> str:
    """Decodifica un valor ofuscado."""
    k = 73
    raw = base64.b64decode(s.encode()).decode("latin-1")
    return "".join(chr(ord(c) ^ k) for c in raw)


# ── Valores ofuscados (XOR key=73 + Base64) ──────────────────────────────────
_T = "cX99fH9weH59enMICA4oGiQnGTAZBhEQER0nGQUuJTF5EwUAAxk+Bn8fDRg5Og=="
_U = "IT09OTpzZmYtJiUlJiwzJiQ+IS0lMSs+LCshJWc6PDkoKyg6LGcqJg=="
_K = (
    "LDADISsOKiAGIAMAHDMAeAcgADoAJxt8KgoAfwAiOREfCgNwZywwAzkqegQgBiADMy0R"
    "CyEQJA8zExoAOgAnAyUTIAB/ACQbPysOMT8TETk/KxEtJhMOMX0QJy0lECQhOgAgPiAq"
    "JHA6ExoAfwAkDzwre30gBQoDORARGCAGIwx6BzMiMAYNGDAHDRw6ACQffSoKAH8EIwh8"
    "Bw0uewQNAHkHEXlnZAsIOxocAAQsJgcdcBEHERsjCgYoPnkzGxMkASgWIXsbKgc9Ez0i"
    "ZH8qDA=="
)
_B = "CSQgFjkmOj08OygWKyY9"

# ── API pública ───────────────────────────────────────────────────────────────
def get_telegram_bot_token() -> str:
    return _d(_T)


def get_supabase_url() -> str:
    return _d(_U)


def get_supabase_anon_key() -> str:
    return _d(_K)


def get_bot_username() -> str:
    return _d(_B)
