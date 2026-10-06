# Windows Packaging

Homuncula is packaged as an Electron desktop plus a frozen local Python runtime.

Electron owns the user interface, tray lifecycle, native notifications, login startup, microphone capture, audio playback, and the narrow IPC bridge. PyInstaller freezes `agentd.exe`, including Playwright, pywinauto, and sherpa-onnx native components. electron-builder then creates the NSIS installer.

## User data

Durable state is outside the install directory under `%USERPROFILE%\.homuncula`. This includes SQLite state, skills, browser profile data, protected secrets, and downloaded voice models. The packaged workspace defaults to `%USERPROFILE%\Homuncula Workspace`.

The NSIS uninstaller does not silently delete user data.

## Voice packaging

The installer contains the sherpa-onnx runtime but not the ASR or TTS model archives. This keeps the base installer smaller and lets voice remain optional.

From the desktop, the user can install:

    sherpa-onnx-whisper-tiny.en
    kokoro-en-v0_19

Those model packages are downloaded from the official sherpa-onnx GitHub releases into the Homuncula data directory. They survive application upgrades.

The PyInstaller command must retain:

    --collect-all sherpa_onnx

Removing that collection step can produce a package that builds successfully but lacks the native voice runtime at execution time.

## Local package build

From the repository root on Windows:

    .\build-windows.ps1

The script installs development and package dependencies, runs tests and Ruff, freezes `agentd.exe`, installs desktop dependencies, typechecks Electron, builds the production renderer, and creates the NSIS installer under `desktop\release`.

## CI release gates

A releasable head must pass Python tests and Ruff on Windows and Ubuntu, the real Playwright Chromium integration, Electron TypeScript typecheck and production build, and the Windows PyInstaller plus NSIS package job.

Voice model downloads are intentionally not performed in CI because they are large external release artifacts. Voice model layout, archive containment, authenticated endpoint behavior, and missing-model failure behavior are covered by deterministic tests.

## Code signing

electron-builder supports Windows code signing through its standard `CSC_LINK` and `CSC_KEY_PASSWORD` environment variables. Signing credentials must live in the CI secret store and must never be committed.

Development installers may be unsigned. Public release installers should be signed.
