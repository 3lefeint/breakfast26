# PyInstaller recipe for the standalone build (one folder, no Python needed on the PC).
# Run from the repository root, after `npm run build` in frontend/:
#     pyinstaller windows/breakfast.spec --noconfirm
#
# The data files keep the layout of the source tree (breakfast/web/dist, tools/, CHANGELOG.md),
# so the paths the code builds from __file__ resolve inside the bundle without any special case.
import glob
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent

datas = [
    (str(root / "frontend" / "dist"), "breakfast/web/dist"),   # the output of `npm run build`
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
)
coll = COLLECT(exe, a.binaries, a.datas, name="breakfast")
