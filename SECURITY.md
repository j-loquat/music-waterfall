# Security policy

## Supported version

Security fixes are made on the current `main` branch. No earlier release line is
currently maintained.

## Reporting a vulnerability

Use **Security > Report a vulnerability** on the GitHub repository when private
vulnerability reporting is available. If that option is unavailable, open a minimal
issue asking the maintainer to establish a private contact channel; do not include
exploit details or private user data in the public issue.

Music Waterfall processes untrusted MIDI, PDF, MusicXML, and media files through local
Python libraries and external tools. A report is especially useful if it identifies a
path traversal, command execution, unsafe file overwrite, dependency compromise, or an
unexpected network transmission.

## Privacy boundary

The application itself is local and offline. It has no account system, telemetry,
upload feature, or cloud processing. The installation process uses the network to obtain
packages and tools from their documented upstream sources. GitHub Actions runs only on
repository source and the public-domain test fixtures.
