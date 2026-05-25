import os
from typing import List
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QComboBox,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QWidget
)
from src.core.localization import tr
from src.core.export import ExportManager
from src.core.comparison_manager import ComparisonTrace

class ExportSettingsDialog(QDialog):
    def __init__(self, traces: List[ComparisonTrace], parent=None):
        super().__init__(parent)
        self.traces = traces
        self.export_manager = ExportManager.instance()
        self.selected_filepath = ""

        self.init_ui()
        self.update_format_options()

    def init_ui(self):
        self.setWindowTitle(tr("Export Settings"))
        self.resize(460, 380)

        main_layout = QVBoxLayout(self)

        # 1. Format Selection
        format_layout = QHBoxLayout()
        format_label = QLabel(tr("Format:"))
        self.format_combo = QComboBox()

        for fmt_id, exporter in self.export_manager.get_all_exporters().items():
            self.format_combo.addItem(exporter.name, fmt_id)

        self.format_combo.currentIndexChanged.connect(self.on_format_changed)
        format_layout.addWidget(format_label)
        format_layout.addWidget(self.format_combo)
        main_layout.addLayout(format_layout)

        # 2. Options Stack (Dynamic options based on format)
        self.options_stack = QStackedWidget()
        main_layout.addWidget(self.options_stack)

        # --- Create JSON/MLComp Options Widget ---
        self.json_widget = QWidget()
        json_layout = QVBoxLayout(self.json_widget)
        json_group = QGroupBox(tr("JSON Options"))
        json_group_layout = QVBoxLayout(json_group)
        json_desc = QLabel(tr("Saves comparison traces as highly compatible MeasureLab proprietary format (.mlcomp). This allows importing them back into Plot Comparer later."))
        json_desc.setWordWrap(True)
        json_group_layout.addWidget(json_desc)
        json_layout.addWidget(json_group)
        self.options_stack.addWidget(self.json_widget)

        # --- Create CSV Options Widget ---
        self.csv_widget = QWidget()
        csv_layout = QVBoxLayout(self.csv_widget)
        csv_group = QGroupBox(tr("CSV Options"))
        csv_group_layout = QVBoxLayout(csv_group)

        # Delimiter Choice
        delim_layout = QHBoxLayout()
        delim_label = QLabel(tr("Delimiter:"))
        self.delim_comma = QRadioButton(tr("Comma (,)"))
        self.delim_tab = QRadioButton(tr("Tab (\\t)"))
        self.delim_comma.setChecked(True)
        self.delim_group = QButtonGroup(self)
        self.delim_group.addButton(self.delim_comma)
        self.delim_group.addButton(self.delim_tab)
        delim_layout.addWidget(delim_label)
        delim_layout.addWidget(self.delim_comma)
        delim_layout.addWidget(self.delim_tab)
        delim_layout.addStretch()
        csv_group_layout.addLayout(delim_layout)

        csv_group_layout.addSpacing(10)

        # Data Layout Choice
        layout_label = QLabel(tr("Data Layout:"))
        self.layout_merged = QRadioButton(tr("Merged on Common X-Axis"))
        self.layout_indep = QRadioButton(tr("Independent Columns"))
        self.layout_merged.setChecked(True)
        self.layout_group = QButtonGroup(self)
        self.layout_group.addButton(self.layout_merged)
        self.layout_group.addButton(self.layout_indep)
        self.layout_merged.toggled.connect(self.on_layout_mode_changed)

        csv_group_layout.addWidget(layout_label)
        csv_group_layout.addWidget(self.layout_merged)

        # Sub-option: Reference Trace (for merged mode)
        self.ref_container = QWidget()
        ref_layout = QHBoxLayout(self.ref_container)
        ref_layout.setContentsMargins(20, 0, 0, 0)
        ref_label = QLabel(tr("Reference Trace:"))
        self.ref_combo = QComboBox()
        self.ref_combo.addItem(tr("Union of all traces (interpolated)"), "union")
        for t in self.traces:
            self.ref_combo.addItem(t.name, t.id)
        ref_layout.addWidget(ref_label)
        ref_layout.addWidget(self.ref_combo)
        csv_group_layout.addWidget(self.ref_container)

        csv_group_layout.addWidget(self.layout_indep)

        csv_group_layout.addSpacing(10)

        # Output Headers / Metadata Checks
        self.chk_headers = QCheckBox(tr("Include Column Headers"))
        self.chk_headers.setChecked(True)
        self.chk_metadata = QCheckBox(tr("Include Commented Metadata"))
        self.chk_metadata.setChecked(True)
        csv_group_layout.addWidget(self.chk_headers)
        csv_group_layout.addWidget(self.chk_metadata)

        csv_layout.addWidget(csv_group)
        self.options_stack.addWidget(self.csv_widget)

        # 3. Output File Path Selection
        path_group = QGroupBox(tr("Output File"))
        path_layout = QHBoxLayout(path_group)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(tr("Select destination file..."))
        self.btn_browse = QPushButton(tr("Browse..."))
        self.btn_browse.clicked.connect(self.browse_filepath)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.btn_browse)
        main_layout.addWidget(path_group)

        main_layout.addStretch()

        # 4. Dialog Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton(tr("Export"))
        self.btn_export.setDefault(True)
        self.btn_export.clicked.connect(self.do_export)
        self.btn_cancel = QPushButton(tr("Cancel"))
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)

    def on_format_changed(self, index):
        self.update_format_options()

    def update_format_options(self):
        fmt_id = self.format_combo.currentData()

        # Change Stacked Widget view
        if fmt_id == "json":
            self.options_stack.setCurrentWidget(self.json_widget)
        elif fmt_id == "csv":
            self.options_stack.setCurrentWidget(self.csv_widget)

        # Update output filepath extension
        current_path = self.path_edit.text().strip()
        exporter = self.export_manager.get_exporter(fmt_id)
        if exporter:
            ext = exporter.default_extension
            if current_path:
                base, _ = os.path.splitext(current_path)
                self.path_edit.setText(base + ext)
            else:
                self.path_edit.setText("comparison_export" + ext)

    def on_layout_mode_changed(self):
        # Enable/Disable reference trace combobox based on layout choice
        is_merged = self.layout_merged.isChecked()
        self.ref_container.setEnabled(is_merged)

    def browse_filepath(self):
        fmt_id = self.format_combo.currentData()
        exporter = self.export_manager.get_exporter(fmt_id)
        if not exporter:
            return

        default_name = self.path_edit.text().strip() or "comparison_export" + exporter.default_extension

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            tr("Select Destination File"),
            default_name,
            exporter.file_filter
        )
        if filepath:
            self.path_edit.setText(filepath)

    def do_export(self):
        filepath = self.path_edit.text().strip()
        if not filepath:
            QMessageBox.warning(self, tr("Export Error"), tr("Please select a destination file path."))
            return

        fmt_id = self.format_combo.currentData()
        exporter = self.export_manager.get_exporter(fmt_id)
        if not exporter:
            QMessageBox.critical(self, tr("Export Error"), tr("Exporter not found for format: {0}").format(fmt_id))
            return

        # Gather exporter specific options
        options = {}
        if fmt_id == "csv":
            options["delimiter"] = "comma" if self.delim_comma.isChecked() else "tab"
            options["layout"] = "merged" if self.layout_merged.isChecked() else "independent"
            options["reference_trace_id"] = self.ref_combo.currentData()
            options["include_headers"] = self.chk_headers.isChecked()
            options["include_metadata"] = self.chk_metadata.isChecked()

        # Execute Export
        ok = exporter.export_traces(filepath, self.traces, options)
        if ok:
            QMessageBox.information(self, tr("Success"), tr("Traces exported successfully."))
            self.accept()
        else:
            QMessageBox.warning(self, tr("Export Error"), tr("Failed to export traces to: {0}").format(filepath))
