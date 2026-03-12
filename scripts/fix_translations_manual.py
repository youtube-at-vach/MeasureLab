import os
from translation_utils import LANG_DIR, load_json, save_json

# Define translations for missing keys
TRANSLATIONS = {
    # Existing entries (kept for completeness)
    "Period:": {
        "de": "Periode:",
        "es": "Período:",
        "fr": "Période :",
        "ja": "周期:",
        "ko": "주기:",
        "pt": "Período:",
        "ru": "Период:",
        "zh": "周期:"
    },
    "Math": {
        "de": "Mathe",
        "es": "Matemáticas",
        "fr": "Maths",
        "ja": "演算",
        "ko": "수학",
        "pt": "Matemática",
        "ru": "Математика",
        "zh": "数学"
    },
    "Math:": {
        "de": "Mathe:",
        "es": "Matemáticas:",
        "fr": "Maths :",
        "ja": "演算:",
        "ko": "수학:",
        "pt": "Matemática:",
        "ru": "Математика:",
        "zh": "数学:"
    },
    "Math ({0})": {
        "de": "Mathe ({0})",
        "es": "Matemáticas ({0})",
        "fr": "Maths ({0})",
        "ja": "演算 ({0})",
        "ko": "수학 ({0})",
        "pt": "Matemática ({0})",
        "ru": "Математика ({0})",
        "zh": "数学 ({0})"
    },
    "Latency": {
        "de": "Latenz",
        "es": "Latencia",
        "fr": "Latence",
        "ja": "レイテンシ",
        "ko": "지연 시간",
        "pt": "Latência",
        "ru": "Задержка",
        "zh": "延迟"
    },
    "Cursors: Off": {
        "de": "Cursor: Aus",
        "es": "Cursores: Off",
        "fr": "Curseurs : Off",
        "ja": "カーソル: オフ",
        "ko": "커서: 끄기",
        "pt": "Cursores: Desligado",
        "ru": "Курсоры: Выкл",
        "zh": "光标: 关闭"
    },
    "FFT size:": {
        "de": "FFT-Größe:",
        "es": "Tamaño FFT:",
        "fr": "Taille FFT :",
        "ja": "FFTサイズ:",
        "ko": "FFT 크기:",
        "pt": "Tamanho FFT:",
        "ru": "Размер БПФ:",
        "zh": "FFT 大小:"
    },
    "In: {0} | Out: {1}": {
        "de": "Ein: {0} | Aus: {1}",
        "es": "Ent: {0} | Sal: {1}",
        "fr": "Entrée : {0} | Sortie : {1}",
        "ja": "入力: {0} | 出力: {1}",
        "ko": "입력: {0} | 출력: {1}",
        "pt": "Ent: {0} | Saída: {1}",
        "ru": "Вх: {0} | Вых: {1}",
        "zh": "输入: {0} | 输出: {1}"
    },
    "In: - | Out: -": {
        "de": "Ein: - | Aus: -",
        "es": "Ent: - | Sal: -",
        "fr": "Entrée : - | Sortie : -",
        "ja": "入力: - | 出力: -",
        "ko": "입력: - | 출력: -",
        "pt": "Ent: - | Saída: -",
        "ru": "Вх: - | Вых: -",
        "zh": "输入: - | 输出: -"
    },
    "Gen Out: {0}": {
        "de": "Gen Aus: {0}",
        "es": "Sal Gen: {0}",
        "fr": "Sortie Gen : {0}",
        "ja": "ジェネレータ出力: {0}",
        "ko": "Gen 출력: {0}",
        "pt": "Saída Gen: {0}",
        "ru": "Вых. Ген.: {0}",
        "zh": "发生器输出: {0}"
    },
    "Gen Out: --:--:--:--": {
        "de": "Gen Aus: --:--:--:--",
        "es": "Sal Gen: --:--:--:--",
        "fr": "Sortie Gen : --:--:--:--",
        "ja": "ジェネレータ出力: --:--:--:--",
        "ko": "Gen 출력: --:--:--:--",
        "pt": "Saída Gen: --:--:--:--",
        "ru": "Вых. Ген.: --:--:--:--",
        "zh": "发生器输出: --:--:--:--"
    },
    "America/New_York": {
        "de": "Amerika/New_York",
        "es": "América/Nueva_York",
        "fr": "Amérique/New_York",
        "ja": "アメリカ/ニューヨーク",
        "ko": "아메리카/뉴욕",
        "pt": "América/Nova_Iorque",
        "ru": "Америка/Нью_Йорк",
        "zh": "美洲/纽约"
    },
    "Asia/Tokyo": {
        "de": "Asien/Tokio",
        "es": "Asia/Tokio",
        "fr": "Asie/Tokyo",
        "ja": "アジア/東京",
        "ko": "아시아/도쿄",
        "pt": "Ásia/Tóquio",
        "ru": "Азия/Токио",
        "zh": "亚洲/东京"
    },
    "Europe/London": {
        "de": "Europa/London",
        "es": "Europa/Londres",
        "fr": "Europe/Londres",
        "ja": "ヨーロッパ/ロンドン",
        "ko": "유럽/런던",
        "pt": "Europa/Londres",
        "ru": "Европа/Лондон",
        "zh": "欧洲/伦敦"
    },
    "Loading {0} ({1}/{2})...": {
        "de": "Laden von {0} ({1}/{2})...",
        "es": "Cargando {0} ({1}/{2})...",
        "fr": "Chargement de {0} ({1}/{2})...",
        "ja": "読み込み中 {0} ({1}/{2})...",
        "ko": "{0} 로드 중 ({1}/{2})...",
        "pt": "A carregar {0} ({1}/{2})...",
        "ru": "Загрузка {0} ({1}/{2})...",
        "zh": "正在加载 {0} ({1}/{2})..."
    },
    "Warming Up... ({0}/{1})": {
        "de": "Aufwärmen... ({0}/{1})",
        "es": "Calentando... ({0}/{1})",
        "fr": "Préchauffage... ({0}/{1})",
        "ja": "ウォームアップ中... ({0}/{1})",
        "ko": "워밍업 중... ({0}/{1})",
        "pt": "Aquecendo... ({0}/{1})",
        "ru": "Разогрев... ({0}/{1})",
        "zh": "预热中... ({0}/{1})"
    },
    # New Leaks Fixed
    "Calculating Articulation Index ({})...": {
        "de": "Berechne Articulation Index ({})...",
        "es": "Calculando Índice de Articulación ({})...",
        "fr": "Calcul de l'indice d'articulation ({})...",
        "ja": "明瞭度指数を計算中 ({})...",
        "ko": "명료도 지수 (AI) 계산 중 ({})...",
        "pt": "Calculando Índice de Articulação ({})...",
        "ru": "Вычисление индекса артикуляции ({})...",
        "zh": "正在计算清晰度指数 ({})..."
    },
    "Calculating Fluctuation Strength ({})...": {
        "de": "Berechne Schwankungsstärke ({})...",
        "es": "Calculando Fuerza de Fluctuación ({})...",
        "fr": "Calcul de la force de fluctuation ({})...",
        "ja": "変動強度を計算中 ({})...",
        "ko": "변동 강도 계산 중 ({})...",
        "pt": "Calculando Força de Flutuação ({})...",
        "ru": "Вычисление силы флуктуации ({})...",
        "zh": "正在计算波动强度 ({})..."
    },
    "Export Failed": {
        "de": "Export fehlgeschlagen",
        "es": "Exportación fallida",
        "fr": "Échec de l'exportation",
        "ja": "エクスポート失敗",
        "ko": "내보내기 실패",
        "pt": "Falha na exportação",
        "ru": "Ошибка экспорта",
        "zh": "导出失败"
    },
    "Export Metrics to CSV": {
        "de": "Metriken als CSV exportieren",
        "es": "Exportar métricas a CSV",
        "fr": "Exporter les mesures au format CSV",
        "ja": "メトリクスをCSVにエクスポート",
        "ko": "CSV로 측정항목 내보내기",
        "pt": "Exportar métricas para CSV",
        "ru": "Экспорт метрик в CSV",
        "zh": "导出指标到 CSV"
    },
    "Export Successful": {
        "de": "Export erfolgreich",
        "es": "Exportación exitosa",
        "fr": "Exportation réussie",
        "ja": "エクスポート成功",
        "ko": "내보내기 성공",
        "pt": "Exportação bem-sucedida",
        "ru": "Экспорт успешен",
        "zh": "导出成功"
    },
    "File && Analysis": {
        "de": "Datei && Analyse",
        "es": "Archivo && Análisis",
        "fr": "Fichier && Analyse",
        "ja": "ファイル && 解析",
        "ko": "파일 && 분석",
        "pt": "Arquivo && Análise",
        "ru": "Файл && Анализ",
        "zh": "文件 && 分析"
    },
    "Successfully exported metrics to:\n{}": {
        "de": "Metriken erfolgreich exportiert nach:\n{}",
        "es": "Métricas exportadas exitosamente a:\n{}",
        "fr": "Mesures exportées avec succès vers :\n{}",
        "ja": "メトリクスのエクスポートに成功しました:\n{}",
        "ko": "측정항목을 다음으로 성공적으로 내보냈습니다:\n{}",
        "pt": "Métricas exportadas com sucesso para:\n{}",
        "ru": "Метрики успешно экспортированы в:\n{}",
        "zh": "成功导出指标至:\n{}"
    }
}


def main():
    print("=== Fixing Translation Leaks ===")

    # Get all language files
    lang_files = [f for f in os.listdir(LANG_DIR) if f.endswith('.json') and f != 'en.json']

    for lang_file in lang_files:
        lang_code = os.path.splitext(lang_file)[0]
        lang_path = os.path.join(LANG_DIR, lang_file)

        print(f"Updating {lang_file}...")
        try:
            data = load_json(lang_path)
            updated_count = 0

            for key, translations in TRANSLATIONS.items():
                if key in data:
                    if lang_code in translations:
                        new_value = translations[lang_code]
                        # Only update if current value is untranslated (same as English key) OR forced update
                        # Here we check if the current value is same as key (untranslated) or empty
                        # Or if we want to overwrite even if translated (to fix bad translations)
                        # We will overwrite if current value == key
                        if data[key] == key or data[key] == "":
                            print(f"  Fixing '{key}': '{data[key]}' -> '{new_value}'")
                            data[key] = new_value
                            updated_count += 1
                        elif data[key] != new_value:
                             # Check if it's the known untranslated state (English)
                             # Since we don't have en.json here easily, we rely on the fact that TRANSLATIONS has the correction.
                             # But we should be careful not to overwrite valid manual translations if they differ slightly.
                             # Let's trust the TRANSLATIONS dict as the source of truth for these specific problematic keys.
                             print(f"  Updating '{key}': '{data[key]}' -> '{new_value}'")
                             data[key] = new_value
                             updated_count += 1
                    else:
                        print(f"  Warning: No translation for '{key}' in language '{lang_code}'")

            if updated_count > 0:
                save_json(lang_path, data)
                print(f"✓ Saved {updated_count} updates to {lang_file}")
            else:
                print(f"✓ No updates needed for {lang_file}")

        except Exception as e:
            print(f"Error processing {lang_file}: {e}")

if __name__ == "__main__":
    main()
