# Windows Packaging

Homuncula packages as two local processes inside one desktop product.

The Electron application provides the user interface, tray lifecycle, and the narrow IPC bridge. The Python runtime is frozen as agentd.exe with PyInstaller and shipped as an Electron extra resource. The packaged desktop starts that executable with the same per-user owner token used by its IPC bridge.

User data is deliberately outside the application install directory under %USERPROFILE%\.homuncula. Uninstalling the application does not delete memory, responsibilities, permissions, browser profile data, or protected secrets.

## Local package build

From the repository root on Windows:

    .\build-windows.ps1

The script creates the Python environment, runs the Python test suite, freezes agentd.exe, installs desktop dependencies, typechecks the desktop, and creates the NSIS installer under desktop\release.

## Code signing

The release pipeline is compatible with electron-builder signing. Production releases should provide a Windows code-signing certificate through the CI secret store using electron-builder's standard CSC_LINK and CSC_KEY_PASSWORD environment variables. Certificates and passwords must never be committed to this repository.

Unsigned development installers are allowed for local testing. Public releases should be signed.
