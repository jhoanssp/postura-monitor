# Monitor de Postura v3

Onboarding Wizard + Supabase (PostgreSQL)

## Instalacion

sudo apt install python3-tk
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt

## Ejecucion

python3 main.py   # primera vez muestra wizard

## Controles

Q/ESC: Salir
S: Esqueleto ON/OFF
A: Angulos ON/OFF
T: Test Telegram

## Tablas Supabase (crear manualmente)

CREATE TABLE sesiones (
    id SERIAL PRIMARY KEY,
    inicio TIMESTAMP NOT NULL,
    fin TIMESTAMP,
    duracion_segundos REAL DEFAULT 0,
    usuario TEXT DEFAULT 'estudiante'
);

CREATE TABLE registros_postura (
    id SERIAL PRIMARY KEY,
    sesion_id INTEGER REFERENCES sesiones(id),
    timestamp TIMESTAMP NOT NULL,
    estado TEXT NOT NULL,
    angulo_cuello REAL,
    angulo_espalda REAL,
    inclinacion_lateral REAL
);

CREATE TABLE alertas (
    id SERIAL PRIMARY KEY,
    sesion_id INTEGER REFERENCES sesiones(id),
    timestamp TIMESTAMP NOT NULL,
    tipo_alerta TEXT NOT NULL,
    tiempo_mala_postura REAL DEFAULT 0,
    notificado_telegram BOOLEAN DEFAULT FALSE
);
