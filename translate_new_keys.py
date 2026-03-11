import os
import json

lang_dir = "src/assets/lang"

translations = {
    "Other Presets": {
        "ja": "その他のプリセット",
        "es": "Otros preajustes",
        "fr": "Autres préréglages",
        "de": "Weitere Voreinstellungen",
        "ko": "기타 프리셋",
        "pt": "Outras predefinições",
        "ru": "Другие пресеты",
        "zh": "其他预设"
    },
    "Include Mains Power": {
        "ja": "電源を含める",
        "es": "Incluir alimentación de red",
        "fr": "Inclure l'alimentation secteur",
        "de": "Netzstrom einbeziehen",
        "ko": "주전원 포함",
        "pt": "Incluir alimentação da rede",
        "ru": "Включить сетевое питание",
        "zh": "包含市电"
    },
    "Include Default Presets (Sample Rates, SMPS, etc.)": {
        "ja": "デフォルトのプリセットを含める (サンプリング周波数、SMPSなど)",
        "es": "Incluir preajustes predeterminados (tasas de muestreo, SMPS, etc.)",
        "fr": "Inclure les préréglages par défaut (taux d'échantillonnage, SMPS, etc.)",
        "de": "Standardvoreinstellungen einbeziehen (Abtastraten, SMPS, usw.)",
        "ko": "기본 프리셋 포함 (샘플레이트, SMPS 등)",
        "pt": "Incluir predefinições padrão (taxas de amostragem, SMPS, etc.)",
        "ru": "Включить пресеты по умолчанию (частоты дискретизации, SMPS и т.д.)",
        "zh": "包含默认预设 (采样率、SMPS等)"
    }
}

for lang_file in os.listdir(lang_dir):
    if lang_file.endswith(".json") and lang_file != "en.json":
        lang_code = lang_file.split(".")[0]
        filepath = os.path.join(lang_dir, lang_file)
        
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        updated = False
        for key, trans in translations.items():
            if lang_code in trans:
                data[key] = trans[lang_code]
                updated = True
                
        if updated:
            # Sort keys for consistency
            data = dict(sorted(data.items(), key=lambda x: x[0].lower() if x[0] else ""))
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"Updated {lang_file}")
