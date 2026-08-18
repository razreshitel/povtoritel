# Povtoritel

Povtoritel is a Windows application for instant replay and continuous screen
recording. It keeps the selected time window in RAM and saves it to MP4 on
request. The application operates from the system tray and can start with
Windows.

![Settings window](docs/settings.png)

## Requirements

- Windows 10 or Windows 11
- Python 3.12 or later
- NVIDIA or AMD GPU with a supported hardware encoder

## Installation

```powershell
git clone https://github.com/razreshitel/povtoritel.git
cd povtoritel
powershell -ExecutionPolicy Bypass -File setup.ps1
pythonw povtoritel.pyw
```

The setup script downloads FFmpeg. On first launch, the application creates
its configuration, tray icons, and autostart entry.

## Usage

- The replay hotkey saves the configured number of recent minutes.
- The recording hotkey starts or stops continuous recording.
- Continuous recording can instead use a two-second hold of the replay hotkey.
- Additional held Shift, Ctrl, or Alt keys do not prevent a configured hotkey
  from working. If replay and recording combinations overlap, recording takes
  priority and only one action is performed.
- Settings can be changed from the tray menu and are applied without restarting
  the application.

The tray icon indicates the current state:

- Green: buffering is active.
- Gray: buffering is paused.
- Red: continuous recording is active.

Recordings are saved to the folder selected in Settings. Notifications are
displayed on the captured screen and are excluded from the recording.

## Commands

```powershell
pythonw povtoritel.pyw
py povtoritel.pyw --settings
py povtoritel.pyw --save
py povtoritel.pyw --quit
py povtoritel.pyw --check
```

## Notes

- One screen is recorded at a time.
- Desktop audio, microphone audio, and automatic per-application tracks are
  configurable.
- The RAM buffer is cleared when capture restarts.
- Screen lock and display sleep temporarily suspend capture. Recovery is
  automatic when the desktop becomes available.
- `mpo_disable.reg` can improve capture stability under high GPU load. A sign
  out or restart is required after applying it. `mpo_enable.reg` restores the
  default Windows setting.
