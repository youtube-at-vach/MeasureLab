import json
import os

LANG_DIR = 'src/assets/lang'
langs = ['de', 'es', 'fr', 'ja', 'ko', 'pt', 'ru', 'zh']

translations = {
    "Recorder & Player": {
        "ja": "レコーダー & プレーヤー",
        "de": "Recorder & Player",
        "es": "Grabadora y Reproductor",
        "fr": "Enregistreur et Lecteur",
        "ko": "레코더 & 플레이어",
        "pt": "Gravador e Leitor",
        "ru": "Запись и воспроизведение",
        "zh": "录音机与播放器"
    },
    "LUFS & Level Meter": {
        "ja": "LUFS & レベルメーター",
        "de": "LUFS & Pegelmesser",
        "es": "Medidor LUFS y Nivel",
        "fr": "LUFS & Niveau-mètre",
        "ko": "LUFS & 레벨 미터",
        "pt": "Medidor de LUFS e Nível",
        "ru": "Измеритель LUFS и уровня",
        "zh": "LUFS 与电平表"
    },
    "Lock-in THD+N": {
        "ja": "ロックイン THD+N",
        "de": "Lock-in THD+N",
        "es": "Lock-in THD+N",
        "fr": "Lock-in THD+N",
        "ko": "Lock-in THD+N",
        "pt": "Lock-in THD+N",
        "ru": "Синхронный THD+N",
        "zh": "锁定 THD+N"
    },
    "{0} deg": {
        "ja": "{0} 度",
        "zh": "{0} 度",
        "ko": "{0} 도",
        "de": "{0} Grad",
        "fr": "{0} deg",
        "es": "{0} grad",
        "pt": "{0} graus",
        "ru": "{0} град"
    }
}

# Unit keys - same as English
unit_keys = ["{0} dBFS", "{0} dBV", "{0} dBu", "{0} V", "{0} mV", "{0} FS"]
for k in unit_keys:
    translations[k] = {l: k for l in langs}

for lang in langs:
    path = os.path.join(LANG_DIR, f"{lang}.json")
    if not os.path.exists(path):
        continue

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    updated = False
    for key, trans_map in translations.items():
        if lang in trans_map:
            # Always update/add
            if data.get(key) != trans_map[lang]:
                data[key] = trans_map[lang]
                updated = True
                print(f"[{lang}] Set: {key} -> {trans_map[lang]}")

    if updated:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write('\n')
        print(f"Saved {lang}.json")
