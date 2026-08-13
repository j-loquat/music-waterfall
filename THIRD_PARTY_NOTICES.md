# Third-party software and content

Music Waterfall is distributed under the MIT License. Its license applies only to
the code and documentation in this repository unless a file says otherwise.

This repository does not contain Audiveris, FFmpeg, FluidSynth, MuseScore Studio,
Qt/PySide binaries, or a SoundFont. The Windows installer obtains external tools
from their official projects or from WinGet. Music Waterfall invokes the external
programs as separate local processes; it does not copy their source code into this
project or relicense them.

## Direct Python dependencies

`uv.lock` records the complete resolved dependency graph and exact Python package
versions. The following table lists the direct runtime dependencies declared in
`pyproject.toml`. Transitive packages retain their own licenses and notices inside
their installed distributions.

| Component | Purpose | Upstream license | Upstream project |
| --- | --- | --- | --- |
| Mido | MIDI parsing and writing | MIT | [mido](https://github.com/mido/mido) |
| music21 | MusicXML parsing and conversion | BSD-3-Clause | [music21](https://github.com/cuthbertLab/music21) |
| NumPy | PCM signal analysis | Composite permissive licenses; see the installed distribution | [NumPy](https://github.com/numpy/numpy) |
| Pillow | Frame drawing and image buffers | MIT-CMU | [Pillow](https://github.com/python-pillow/Pillow) |
| platformdirs | Per-user configuration paths | MIT | [platformdirs](https://github.com/tox-dev/platformdirs) |
| pypdf | PDF validation and page counting | BSD-3-Clause | [pypdf](https://github.com/py-pdf/pypdf) |
| PySide6 and Shiboken6 | Qt desktop GUI bindings | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | [Qt for Python](https://doc.qt.io/qtforpython-6/) |

The open-source PySide6/Qt installation is replaceable inside the local Python
environment. Do not remove or obstruct a user's ability to replace those libraries
if you redistribute a packaged binary application. Review the current Qt licensing
terms before producing an installer that bundles Qt.

## External local tools

| Component | Purpose | Upstream license | How this project obtains it |
| --- | --- | --- | --- |
| [Audiveris](https://github.com/Audiveris/audiveris) | Optical music recognition from PDF | AGPL-3.0 | Separate WinGet installation |
| [FFmpeg and FFprobe](https://ffmpeg.org/legal.html) | H.264/AAC encoding and media inspection | LGPL-2.1-or-later, or GPL-2.0-or-later when a build enables GPL components | Separate WinGet installation |
| [FluidSynth](https://github.com/FluidSynth/fluidsynth) | Offline MIDI-to-WAV synthesis | LGPL-2.1 | Official Windows release downloaded separately; its release digest is verified |
| [MuseScore Studio](https://github.com/musescore/MuseScore) | Human score correction and MusicXML export | GPL-3.0 | Separate WinGet installation |
| SoundFont selected by the user | Instrument samples used by FluidSynth | Varies by file | Never stored in this repository |
| [uv](https://github.com/astral-sh/uv) | Python and dependency management | Apache-2.0 OR MIT | Separate WinGet installation |

The default setup detects `MS Basic.sf3` from a local MuseScore Studio installation.
The SoundFont is not part of Music Waterfall, and its license is not replaced by this
project's MIT License. Before distributing audio commercially, verify the licenses of
the input score, MIDI file, and selected SoundFont.

## Test fixtures

The two checked-in Für Elise fixtures are from the same Mutopia Project edition and
are identified by Mutopia as public domain. Their source URLs, provenance, and SHA-256
checksums are recorded in [`tests/fixtures/README.md`](tests/fixtures/README.md).

All other trial PDFs, MIDI files, MusicXML files, audio, and video are ignored. Do not
add another fixture without documenting its source, license, and checksum.

## Redistribution boundary

The source-only installation documented here keeps each third-party component separate.
If a future release bundles external executables, Qt libraries, a SoundFont, or other
assets, that release must be audited again and must include every applicable license,
notice, source-code offer, relinking mechanism, and attribution required by those exact
builds. This summary is practical project documentation, not legal advice.
