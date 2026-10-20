# Poise Setup

`Poise_Setup.exe` is the only thing users see. It is a PyQt6 window that
looks like Poise - frameless, with the app's About-page mark, its gold
lattice and its own close control - and behind it sits an Inno Setup core
that does the actual installing.

```
Poise_Setup.exe  (PyQt6, installer/bootstrapper/)
   |  asks for a location, shows four screens
   |
   +-- extracts PoiseCore.exe to a temp dir
   +-- runs it:  /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
                 /LOG=<temp>.log /DIR=<chosen> [ /TASKS=desktopicon ]
   |
   +-- tails <temp>.log for POISE:phase=... / POISE:driver=...
   +-- maps the exit code to ok / reboot / cancelled / failed
```

## Why two programs

The Inno core keeps everything that touches the system: file copying,
shortcuts, the uninstall registry entry, the uninstaller, and the
VB-Cable driver. Rewriting any of that in Python would be a worse
installer. The window only replaces what Inno cannot do - its stock
wizard - so the risky half stays the tested half.

The two halves talk through exactly one contract, in the core's log:

| Marker | Meaning |
| --- | --- |
| `POISE:phase=files` | `ssInstall`: file copy has begun |
| `POISE:phase=driver` | `ssPostInstall`: audio driver step |
| `POISE:phase=finish` | `ssDone`: about to exit |
| `POISE:driver=install` | VB-Cable setup is running |
| `POISE:driver=skip` | CABLE already present, or nothing bundled |
| `POISE:driver=done` | Driver handled |
| `POISE:driver=reboot` | Driver installed; a restart is required |
| `POISE:driver=failed` | Driver setup could not be launched |

`installer/bootstrapper/core.py` owns the parsing, and
`tests/test_installer_core.py` fails if `setup.iss` emits a marker the
window does not know.

## Building

```powershell
# 1. the app itself
pyinstaller poise_windows.spec --noconfirm

# 2. the silent core (needs Inno Setup 6)
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DCORE setup.iss

# 3. the window, with the core embedded
pyinstaller installer/PoiseSetup.spec --noconfirm `
    --distpath installer --workpath build/installer
```

`setup.iss` without `/DCORE` still produces the plain Inno installer
(`installer/Poise_Setup.exe`), which remains a working fallback.

Working on the window alone does not need Inno or a 100 MB payload:

```powershell
python -m installer.bootstrapper --mock --autoplay   # rehearse a run
python -m installer.bootstrapper --screenshot build\shots
```

The screenshot mode renders every screen to PNG at the real window size
and is what the visual tests use.

## Trade-offs

- **Size.** The core is embedded in the window, so the download is about
  the app plus the Qt runtime the window needs. A sibling-file layout
  (`--core` pointing at a loose `PoiseCore.exe`) is supported for
  development but not shipped.
- **SmartScreen.** This adds a second unsigned executable to the trust
  chain. Until Poise is code-signed, the "Windows protected your PC"
  warning applies to `Poise_Setup.exe` exactly as before.
- **Progress is phase-based.** Inno reports no percentages when it runs
  silently, so the bar eases between the phases it announces rather than
  pretending to know byte counts.
- **Cancel is not offered mid-copy.** Killing Inno during installation
  can leave a partial tree; the window asks the user to wait instead.
  Cancel works before the install starts and from the failure screen.
