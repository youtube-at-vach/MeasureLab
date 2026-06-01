import os
import json

PROJECT_ROOT = "/Users/vach/MeasureLab"
LANG_DIR = os.path.join(PROJECT_ROOT, "src", "assets", "lang")
WHITELIST_PATH = os.path.join(PROJECT_ROOT, "scripts", "translation_whitelist.json")

# Define the 38 keys to remove from the whitelist
KEYS_TO_REMOVE = [
    "Amp", "Amp (dBFS)", "Amp Sweep", "Amplitude", "Amplitude:", "Articulation Index",
    "Auto", "Azimuth:", "Bode", "Compensation", "Configuration", "Correction",
    "Delta", "Details", "Diff from target", "Distribution", "Done", "Duration",
    "Excellent", "Follow Cursor", "Format:", "Fundamental", "Fundamental Tone",
    "Inductance", "Integral", "Loudness Range", "None", "None (Instant)", "None (Raw)",
    "Play/Pause", "Screenshot", "Screenshots", "Secondary Y", "Start", "Start (s):",
    "Start:", "Triangle", "Zoom to Selection"
]

# Define localized translations for each key across all 7 non-English languages
TRANSLATION_MAP = {
    "Amp": {
        "de": "Amplitude", "es": "Amplitud", "fr": "Amplitude",
        "ko": "진폭", "pt": "Amplitude", "ru": "Амплитуда", "zh": "振幅"
    },
    "Amp (dBFS)": {
        "de": "Amplitude (dBFS)", "es": "Amplitud (dBFS)", "fr": "Amplitude (dBFS)",
        "ko": "진폭 (dBFS)", "pt": "Amplitude (dBFS)", "ru": "Амплитуда (dBFS)", "zh": "振幅 (dBFS)"
    },
    "Amp Sweep": {
        "de": "Amplitudensweep", "es": "Barrido de amplitud", "fr": "Balayage d'amplitude",
        "ko": "진폭 스위프", "pt": "Varredura de amplitude", "ru": "Амплитудный свип", "zh": "振幅扫频"
    },
    "Amplitude": {
        "de": "Amplitude", "es": "Amplitud", "fr": "Amplitude",
        "ko": "진폭", "pt": "Amplitude", "ru": "Амплитуда", "zh": "振幅"
    },
    "Amplitude:": {
        "de": "Amplitude:", "es": "Amplitud:", "fr": "Amplitude :",
        "ko": "진폭:", "pt": "Amplitude:", "ru": "Амплитуда:", "zh": "振幅:"
    },
    "Articulation Index": {
        "de": "Artikulationsindex", "es": "Índice de articulación", "fr": "Indice d'articulation",
        "ko": "명료도 지수 (AI)", "pt": "Índice de articulação", "ru": "Индекс артикуляции (AI)", "zh": "清晰度指数 (AI)"
    },
    "Auto": {
        "de": "Automatisch", "es": "Automático", "fr": "Automatique",
        "ko": "자동", "pt": "Automático", "ru": "Автоматически", "zh": "自动"
    },
    "Azimuth:": {
        "de": "Azimut:", "es": "Acimut:", "fr": "Azimut :",
        "ko": "방위각 (Az):", "pt": "Azimute:", "ru": "Азимут:", "zh": "方位角 (Az):"
    },
    "Bode": {
        "de": "Bode-Diagramm", "es": "Diagrama de Bode", "fr": "Diagramme de Bode",
        "ko": "보드", "pt": "Diagrama de Bode", "ru": "Боде", "zh": "波特"
    },
    "Compensation": {
        "de": "Kompensation", "es": "Compensación", "fr": "Compensation",
        "ko": "왜곡 보정", "pt": "Compensação", "ru": "Компенсация искажений", "zh": "失真补偿"
    },
    "Configuration": {
        "de": "Konfiguration", "es": "Configuración", "fr": "Configuration",
        "ko": "설정", "pt": "Configuração", "ru": "Конфигурация", "zh": "配置"
    },
    "Correction": {
        "de": "Korrektur", "es": "Corrección", "fr": "Correction",
        "ko": "보정", "pt": "Correção", "ru": "Коррекция", "zh": "修正"
    },
    "Delta": {
        "de": "Differenz", "es": "Diferencia", "fr": "Différence",
        "ko": "차이", "pt": "Diferença", "ru": "Разность", "zh": "差值"
    },
    "Details": {
        "de": "Einzelheiten", "es": "Detalles", "fr": "Détails",
        "ko": "상세 정보", "pt": "Detalhes", "ru": "Подробности", "zh": "详细信息"
    },
    "Diff from target": {
        "de": "Abweichung vom Sollwert", "es": "Diferencia del objetivo", "fr": "Différence par rapport à la cible",
        "ko": "타겟과의 편차", "pt": "Diferença do alvo", "ru": "Отклонение от цели", "zh": "与目标差值"
    },
    "Distribution": {
        "de": "Verteilung", "es": "Distribución", "fr": "Distribution",
        "ko": "분포", "pt": "Distribuição", "ru": "Распределение", "zh": "分布"
    },
    "Done": {
        "de": "Fertig", "es": "Hecho", "fr": "Terminé",
        "ko": "완료", "pt": "Concluído", "ru": "Готово", "zh": "已完成"
    },
    "Duration": {
        "de": "Messdauer", "es": "Duración de medición", "fr": "Durée de mesure",
        "ko": "측정 시간", "pt": "Duração da medição", "ru": "Время измерения", "zh": "测量时间"
    },
    "Excellent": {
        "de": "Hervorragend", "es": "Excelente", "fr": "Excellent",
        "ko": "양호", "pt": "Excelente", "ru": "Отлично", "zh": "良好"
    },
    "Follow Cursor": {
        "de": "Cursor folgen", "es": "Seguir cursor", "fr": "Suivre le curseur",
        "ko": "커서에 추적", "pt": "Seguir cursor", "ru": "Следовать за курсором", "zh": "跟随光标"
    },
    "Format:": {
        "de": "Format:", "es": "Formato:", "fr": "Format :",
        "ko": "포맷:", "pt": "Formato:", "ru": "Формат:", "zh": "格式:"
    },
    "Fundamental": {
        "de": "Grundwelle", "es": "Fundamental", "fr": "Fondamental",
        "ko": "기본파", "pt": "Fundamental", "ru": "Основная гармоника", "zh": "基本波"
    },
    "Fundamental Tone": {
        "de": "Grundton", "es": "Tono fundamental", "fr": "Ton fondamental",
        "ko": "기본파 톤", "pt": "Tom fundamental", "ru": "Основной тон", "zh": "基本波音"
    },
    "Inductance": {
        "de": "Induktivität", "es": "Inductancia", "fr": "Inductance",
        "ko": "인덕턴스", "pt": "Indutância", "ru": "Индуктивность", "zh": "电感"
    },
    "Integral": {
        "de": "Integral", "es": "Integral", "fr": "Intégrale",
        "ko": "적분", "pt": "Integral", "ru": "Интеграл", "zh": "积分"
    },
    "Loudness Range": {
        "de": "Lautheitsbereich", "es": "Rango de sonoridad", "fr": "Plage de loudness",
        "ko": "라우드니스 범위", "pt": "Faixa de sonoridade", "ru": "Диапазон громкости", "zh": "响度范围"
    },
    "None": {
        "de": "Keine", "es": "Ninguno", "fr": "Aucun",
        "ko": "없음", "pt": "Nenhum", "ru": "Нет", "zh": "无"
    },
    "None (Instant)": {
        "de": "Keine (sofort)", "es": "Ninguno (instantáneo)", "fr": "Aucun (instantané)",
        "ko": "없음 (즉시)", "pt": "Nenhum (imediato)", "ru": "Нет (мгновенно)", "zh": "无 (即时)"
    },
    "None (Raw)": {
        "de": "Keine (Rohdaten)", "es": "Ninguno (crudo)", "fr": "Aucun (brut)",
        "ko": "없음 (원시 데이터)", "pt": "Nenhum (bruto)", "ru": "Нет (сырые данные)", "zh": "无 (原始数据)"
    },
    "Play/Pause": {
        "de": "Wiedergabe/Pause", "es": "Reproducir/Pausa", "fr": "Lecture/Pause",
        "ko": "재생/일시정지", "pt": "Reproduzir/Pausa", "ru": "Воспроизведение/Пауза", "zh": "播放/暂停"
    },
    "Screenshot": {
        "de": "Screenshot", "es": "Captura de pantalla", "fr": "Capture d'écran",
        "ko": "스크린샷", "pt": "Captura de tela", "ru": "Снимок экрана", "zh": "屏幕截图"
    },
    "Screenshots": {
        "de": "Screenshots", "es": "Capturas de pantalla", "fr": "Captures d'écran",
        "ko": "스크린샷", "pt": "Capturas de tela", "ru": "Снимки экрана", "zh": "屏幕截图"
    },
    "Secondary Y": {
        "de": "Sekundäre Y-Achse", "es": "Eje Y secundario", "fr": "Axe Y secondaire",
        "ko": "보조 Y축", "pt": "Eixo Y secundário", "ru": "Вспомогательная ось Y", "zh": "辅助 Y 轴"
    },
    "Start": {
        "de": "Starten", "es": "Iniciar", "fr": "Démarrer",
        "ko": "시작", "pt": "Iniciar", "ru": "Старт", "zh": "开始"
    },
    "Start (s):": {
        "de": "Start (s):", "es": "Inicio (s):", "fr": "Début (s) :",
        "ko": "시작 (초):", "pt": "Início (s):", "ru": "Старт (с):", "zh": "开始 (秒):"
    },
    "Start:": {
        "de": "Starten:", "es": "Iniciar:", "fr": "Démarrer :",
        "ko": "시작:", "pt": "Iniciar:", "ru": "Старт:", "zh": "开始:"
    },
    "Triangle": {
        "de": "Dreieck", "es": "Triángulo", "fr": "Triangle",
        "ko": "삼각파", "pt": "Triângulo", "ru": "Треугольник", "zh": "三角波"
    },
    "Zoom to Selection": {
        "de": "Auf Auswahl zoomen", "es": "Ajustar zoom a la selección", "fr": "Zoomer sur la sélection",
        "ko": "선택 영역으로 확대", "pt": "Zoom para a seleção", "ru": "Масштабировать по выделению", "zh": "缩放到选择"
    }
}

def clean_whitelist():
    print("--- Cleaning scripts/translation_whitelist.json ---")
    if not os.path.exists(WHITELIST_PATH):
        print(f"Error: {WHITELIST_PATH} not found.")
        return False

    with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
        wl_data = json.load(f)

    original_len = len(wl_data["exact_keys"])
    wl_data["exact_keys"] = [k for k in wl_data["exact_keys"] if k not in KEYS_TO_REMOVE]
    new_len = len(wl_data["exact_keys"])

    print(f"Removed {original_len - new_len} keys from exact_keys in whitelist.")

    with open(WHITELIST_PATH, "w", encoding="utf-8") as f:
        json.dump(wl_data, f, ensure_ascii=False, indent=4)
        f.write("\n")
    print("✓ Successfully saved cleaned whitelist.")
    return True

def apply_translations():
    print("--- Applying professional translations to JSON files ---")
    lang_files = [f for f in os.listdir(LANG_DIR) if f.endswith(".json") and f != "en.json"]

    for lf in sorted(lang_files):
        lang_code = os.path.splitext(lf)[0]
        path = os.path.join(LANG_DIR, lf)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        updated = 0
        for key, lang_map in TRANSLATION_MAP.items():
            if key in data:
                # Get the premium translation for this language
                translation = lang_map.get(lang_code)
                if translation:
                    # Update the value in JSON
                    old_val = data[key]
                    data[key] = translation
                    if old_val != translation:
                        updated += 1

        print(f"{lf}: Updated {updated} translations.")

        # Save sorted data
        sorted_data = dict(sorted(data.items()))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted_data, f, ensure_ascii=False, indent=4)
            f.write("\n")

    print("✓ Successfully localized all language files.")

if __name__ == "__main__":
    if clean_whitelist():
        apply_translations()
