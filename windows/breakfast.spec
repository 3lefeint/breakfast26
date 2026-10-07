# PyInstaller recipe for the standalone build (one folder, no Python needed on the PC).
# Run from the repository root, after `npm run build` in frontend/:
#     pyinstaller windows/breakfast.spec --noconfirm
#
# The data files keep the layout of the source tree (breakfast/web/dist, tools/, CHANGELOG.md),
# so the paths the code builds from __file__ resolve inside the bundle without any special case.
import glob
import os
import sys
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from breakfast import __version__   # noqa: E402

# The version resource of breakfast.exe (product name and version), which code signing checks.
_nums = (tuple(int(n) for n in __version__.split(".")) + (0, 0, 0, 0))[:4]
_version_file = os.path.join(CONF["workpath"], "version_info.txt")
os.makedirs(CONF["workpath"], exist_ok=True)
with open(_version_file, "w", encoding="utf-8") as fh:
    fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_nums}, prodvers={_nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '3lefeint'),
      StringStruct('FileDescription', 'Breakfast'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'breakfast'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 3lefeint, MIT License'),
      StringStruct('OriginalFilename', 'breakfast.exe'),
      StringStruct('ProductName', 'Breakfast'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
""")

datas = [
    (str(root / "breakfast" / "web" / "dist"), "breakfast/web/dist"),   # the output of `npm run build`
    (str(root / "breakfast" / "web" / "static"), "breakfast/web/static"),
    (str(root / "CHANGELOG.md"), "."),
]
datas += [(plan, "tools") for plan in glob.glob(str(root / "tools" / "voicepack_*.toml"))]
for extra in ("LICENSE", "windows/THIRD_PARTY.md"):   # shown inside the bundle for the notices
    if (root / extra).exists():
        datas.append((str(root / extra), "."))
ffmpeg_dir = root / "windows" / "ffmpeg"
if ffmpeg_dir.is_dir():
    datas.append((str(ffmpeg_dir), "ffmpeg"))

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + ["tools.generate_voicepack", "tzdata"]
)

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="breakfast",
    console=True,
    version=_version_file,
)
coll = COLLECT(exe, a.binaries, a.datas, name="breakfast")
