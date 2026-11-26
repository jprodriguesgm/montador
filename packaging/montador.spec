# PyInstaller: monta o "Montador" (Mac: .app; Windows: pasta com o .exe).
#   python packaging/build_deps.py        (antes: fontes/ e bin/ com o LibreOffice)
#   pyinstaller --noconfirm packaging/montador.spec
# O LibreOffice é copiado para dentro do app depois (ver .github/workflows/montar.yml).
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
from montador import __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"
NAME = "Montador"
ICON = ROOT / "packaging" / "icon" / ("icon.icns" if IS_MAC else "icon.ico")

datas = [
    (str(ROOT / "montador" / "ui"), "montador/ui"),
    (str(ROOT / "montador" / "motor"), "montador/motor"),          # geradores do Fluxo NPD (rodam por runpy)
    (str(ROOT / "montador" / "keynote_exportar.applescript"), "montador"),
]
if (ROOT / "fontes").is_dir():
    datas.append((str(ROOT / "fontes"), "fontes"))
else:
    print("AVISO: sem a pasta fontes/ (rode packaging/build_deps.py)")

a = Analysis(
    [str(ROOT / "packaging" / "app_main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    # os geradores do motor/ não são analisados (são arquivos de dados): o que eles importam vai aqui
    hiddenimports=collect_submodules("montador") + collect_submodules("pypdfium2") + [
        "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.ImageFilter", "html", "difflib", "copy", "json",
        "urllib.parse", "xml.etree.ElementTree", "unicodedata", "runpy", "urllib.request", "ssl", "certifi"],
    excludes=["tkinter", "matplotlib", "numpy", "pytest", "IPython", "pptx"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=str(ICON), upx=False)
extra = []
if IS_WIN:
    # mesma coisa com janela de terminal: para "montador-terminal.exe diagnostico"
    extra.append(EXE(pyz, a.scripts, [], exclude_binaries=True, name="montador-terminal", console=True,
                     icon=str(ICON), upx=False))

coll = COLLECT(exe, *extra, a.binaries, a.datas, name=NAME, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=NAME + ".app",
        icon=str(ICON),
        bundle_identifier="br.pucminas.npd.montador",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "Montador",
            "CFBundleName": "Montador",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "11.0",
            "LSUIElement": True,              # sem ícone no Dock: o app é a página no navegador
            "NSHighResolutionCapable": True,
            "NSDesktopFolderUsageDescription": "O Montador lê as gravações e salva as sequências na pasta que você escolher.",
            "NSDocumentsFolderUsageDescription": "O Montador lê as gravações e salva as sequências na pasta que você escolher.",
            "NSDownloadsFolderUsageDescription": "O Montador lê transcrições e SRTs da Skoopia que você escolher.",
            "NSRemovableVolumesUsageDescription": "O Montador lê as gravações do disco externo que você escolher.",
            "NSNetworkVolumesUsageDescription": "O Montador lê as gravações da pasta de rede que você escolher.",
            "NSAppleEventsUsageDescription": "O Montador abre a janela para escolher pastas e, sem LibreOffice, usa o Keynote para os slides.",
        },
    )
