"""
entrenamiento_rf.py — Entrena y guarda los modelos Random Forest
================================================================
Uso:
    python entrenamiento_rf.py                   # usa data.csv junto a este script
    python entrenamiento_rf.py --csv ruta/data.csv

Genera en ./models/:
    rf_upperbody.pkl   — modelo tronco superior
    rf_lowerbody.pkl   — modelo piernas
    le_upperbody.pkl   — LabelEncoder tronco
    le_lowerbody.pkl   — LabelEncoder piernas
    feature_cols.pkl   — lista de columnas de features

Resultados esperados (dataset Zenodo 14230872, 4794 muestras):
    Upperbody CV accuracy : 96.9% ± 1.2%
    Lowerbody CV accuracy : 94.6% ± 4.0%
"""

import argparse
import sys
from pathlib import Path

# ── Dependencias ──────────────────────────────────────────────────────────────
try:
    import pandas as pd
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score, GroupKFold
    from sklearn.preprocessing import LabelEncoder
    import numpy as np
except ImportError as e:
    print(f"[ERROR] Dependencia faltante: {e}")
    print("Instala con:  pip install scikit-learn joblib pandas")
    sys.exit(1)


# ── Argumentos ────────────────────────────────────────────────────────────────
def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Entrena modelos RF para detección de postura")
    p.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "data.csv"),
        help="Ruta al archivo data.csv del dataset (default: ./data.csv)",
    )
    p.add_argument(
        "--out",
        default=str(Path(__file__).parent / "models"),
        help="Directorio de salida para los .pkl (default: ./models/)",
    )
    p.add_argument(
        "--n-estimators",
        type=int,
        default=100,
        help="Número de árboles en el Random Forest (default: 100)",
    )
    p.add_argument(
        "--no-cv",
        action="store_true",
        help="Omitir validación cruzada (más rápido)",
    )
    return p.parse_args()


# ── Entrenamiento ─────────────────────────────────────────────────────────────
def entrenar(csv_path: str, out_dir: str, n_estimators: int, hacer_cv: bool) -> None:
    csv_path = Path(csv_path)
    out_dir  = Path(out_dir)

    if not csv_path.exists():
        print(f"[ERROR] No se encontró el CSV: {csv_path}")
        print("Descárgalo de: https://zenodo.org/records/14230872")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Cargar datos ──────────────────────────────────────────────────────────
    print(f"[1/5] Cargando {csv_path} ...", end=" ", flush=True)
    df = pd.read_csv(csv_path)
    print(f"{len(df)} filas, {len(df.columns)} columnas")

    feature_cols = [c for c in df.columns if c not in ["subject", "upperbody_label", "lowerbody_label"]]
    X       = df[feature_cols].values.astype(np.float32)
    groups  = df["subject"].values

    le_up = LabelEncoder()
    y_up  = le_up.fit_transform(df["upperbody_label"])

    le_lo = LabelEncoder()
    y_lo  = le_lo.fit_transform(df["lowerbody_label"])

    print(f"       Features : {len(feature_cols)}")
    print(f"       Tronco   : {list(le_up.classes_)}")
    print(f"       Piernas  : {list(le_lo.classes_)}")
    print(f"       Sujetos  : {sorted(df['subject'].unique())}")

    # ── Validación cruzada ────────────────────────────────────────────────────
    if hacer_cv:
        print("[2/5] Validación cruzada (GroupKFold, subject-independent) ...")
        gkf = GroupKFold(n_splits=5)
        rf_tmp = RandomForestClassifier(n_estimators=n_estimators, random_state=42, n_jobs=-1)

        sc_up = cross_val_score(rf_tmp, X, y_up, groups=groups, cv=gkf, scoring="accuracy")
        sc_lo = cross_val_score(rf_tmp, X, y_lo, groups=groups, cv=gkf, scoring="accuracy")

        print(f"       Tronco CV accuracy : {sc_up.mean():.3f} ± {sc_up.std():.3f}")
        print(f"       Piernas CV accuracy: {sc_lo.mean():.3f} ± {sc_lo.std():.3f}")
    else:
        print("[2/5] Validación cruzada omitida (--no-cv)")

    # ── Entrenamiento final (todos los datos) ─────────────────────────────────
    print(f"[3/5] Entrenando modelos finales (n_estimators={n_estimators}) ...")

    rf_up = RandomForestClassifier(n_estimators=n_estimators, random_state=42, n_jobs=-1)
    rf_lo = RandomForestClassifier(n_estimators=n_estimators, random_state=42, n_jobs=-1)

    rf_up.fit(X, y_up)
    print("       Upper body RF entrenado")

    rf_lo.fit(X, y_lo)
    print("       Lower body RF entrenado")

    # ── Guardar ───────────────────────────────────────────────────────────────
    print(f"[4/5] Guardando modelos en {out_dir} ...")

    joblib.dump(rf_up,        out_dir / "rf_upperbody.pkl")
    joblib.dump(rf_lo,        out_dir / "rf_lowerbody.pkl")
    joblib.dump(le_up,        out_dir / "le_upperbody.pkl")
    joblib.dump(le_lo,        out_dir / "le_lowerbody.pkl")
    joblib.dump(feature_cols, out_dir / "feature_cols.pkl")

    # ── Tamaño de archivos ────────────────────────────────────────────────────
    print("[5/5] Archivos generados:")
    for f in sorted(out_dir.glob("*.pkl")):
        kb = f.stat().st_size / 1024
        print(f"       {f.name:<25} {kb:>8.1f} KB")

    print("\n✓ Entrenamiento completo. Ejecuta main.py para usar el clasificador RF.")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = _args()
    entrenar(
        csv_path     = args.csv,
        out_dir      = args.out,
        n_estimators = args.n_estimators,
        hacer_cv     = not args.no_cv,
    )
