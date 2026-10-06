# Windows Packaging

Homuncula packages as one user-facing Windows application containing two local processes.

Electron owns the desktop interface, authenticated IPC bridge, tray lifecycle, launch-at-login setting, native notifications, model setup actions, and local host recovery.

agentd owns the persistent agent runtime. PyInstaller freezes the Python runtime and its dependencies into agentd.exe. electron-builder then ships that executable as an application resource inside the Windows package.

## Data separation

Application binaries and durable user data are intentionally separate.

The default durable application home is:

    %USERPROFILE%\.homuncula

The packaged default workspace is:

    %USERPROFILE%\Homuncula Workspace

The durable home can contain the SQLite database, owner token, DPAPI-protected secrets, local skills, browser profile, and other persistent runtime state.

Uninstalling Homuncula does not silently delete this durable data.

## Runtime startup

The Electron main process generates or loads the per-user owner token and starts agentd with that token in its local process environment.

The renderer never receives arbitrary Node.js access and does not receive the owner token.

When Homuncula is configured to launch at login, the packaged application starts hidden and remains available from the system tray.

Closing the main window also leaves the runtime active in the tray. Explicit Quit terminates the local runtime.

## First-run inference setup

The packaged application does not require the end user to install Python or Node.js.

Ollama remains an external local inference service. If Ollama is missing on Windows, the desktop can explicitly invoke Windows Package Manager to install Ollama.

The desktop can then call the authenticated local model-management API to list installed Ollama models, pull a model, select it, and persist the selected model in SQLite.

Model downloads are not bundled into the Homuncula installer because their size and hardware requirements vary.

## Local development package build

From PowerShell in the repository root:

    .\build-windows.ps1

The script creates the Python environment when needed, installs Homuncula with development and package dependencies, runs pytest and Ruff, freezes agentd.exe, installs desktop dependencies, typechecks the Electron application, and creates the NSIS installer under:

    desktop\release

## CI package validation

The GitHub Actions package job performs a clean Windows build.

It installs Python and Node.js, installs Homuncula package dependencies, freezes agentd with PyInstaller, installs Electron dependencies, runs the production desktop build through electron-builder, creates the NSIS installer, and uploads the resulting executable as the Homuncula-Windows artifact.

The package gate runs alongside Windows Python tests, Ubuntu Python tests, the real Chromium integration harness, and Electron typecheck/build.

A change is not treated as packaged-ready merely because source tests pass.

## PyInstaller boundary

The package build explicitly collects Playwright and pywinauto because their runtime resources are not reliably inferred from ordinary imports.

Browser automation on packaged Windows defaults to the installed Microsoft Edge channel. This avoids requiring a bundled Chromium browser for the normal Windows product.

Playwright Chromium is installed separately only in the CI integration job that exercises the deterministic browser harness.

## NSIS behavior

The desktop package is configured as a per-user one-click NSIS installer.

The installer does not request machine-wide installation by default.

Application uninstall does not delete Homuncula user data.

The generated executable name follows:

    Homuncula-Setup-<version>.exe

## Code signing

The release configuration is compatible with electron-builder's standard Windows signing flow.

A production release can provide the certificate and password through CI secrets using:

    CSC_LINK
    CSC_KEY_PASSWORD

Signing credentials must never be committed to the repository, stored in model context, or written into build logs.

Current CI verifies unsigned development installers. A public production release should be signed before distribution.

## Release evidence

A release decision should use the exact commit SHA that produced the installer artifact and confirm that the same SHA passed the Python, browser, desktop, and package gates.

The verification rule is intentionally stronger than "the build probably succeeded." Installer provenance should be tied to an exact tested source head.
