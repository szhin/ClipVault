# PyInstaller spec: bản macOS (.app). Chạy từ thư mục gốc dự án trên macOS: bash packaging/build_macos.sh
# Chưa ký/notarize (Gatekeeper sẽ cảnh báo). Chưa kiểm chứng trên máy thật.
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "src" / "clipvault" / "__init__.py").read_text(encoding="utf-8")).group(1)

# Giống clipvault.spec: chỉ Qt Core/Gui/Widgets, loại module mạng (app không gọi mạng).
EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL",
    "PySide6.QtSvg", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtRemoteObjects", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtStateMachine",
    "tkinter", "unittest", "pytest", "test",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "assets" / "icon.png"), "assets")],
    hiddenimports=["AppKit", "Foundation"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ClipVault", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ClipVault")
app = BUNDLE(
    coll,
    name="ClipVault.app",
    icon=str(ROOT / "build" / "icon.icns"),
    bundle_identifier="com.clipvault.app",
    version=VERSION,
    info_plist={"CFBundleName": "ClipVault", "CFBundleShortVersionString": VERSION,
                "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"},
)
