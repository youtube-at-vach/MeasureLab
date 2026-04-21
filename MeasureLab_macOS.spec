# -*- mode: python ; coding: utf-8 -*-
import json
from PyInstaller.utils.hooks import collect_all

# Load version from version.json
with open('version.json', 'r') as f:
    version_data = json.load(f)
version = version_data.get('version', '0.0.0')

datas = [('src', 'src')]
binaries = []
hiddenimports = ['pyfftw']

tmp_ret = collect_all('backports')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('soundfile')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyfftw')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MeasureLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['MeasureLab.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MeasureLab',
)
app = BUNDLE(
    coll,
    name='MeasureLab.app',
    icon='MeasureLab.icns',
    bundle_identifier='com.github_vach.measurelab',
    info_plist={
        'CFBundleShortVersionString': version,
        'CFBundleVersion': version,
        'NSMicrophoneUsageDescription': 'Microphone access is required for audio measurement.'
    },
)
