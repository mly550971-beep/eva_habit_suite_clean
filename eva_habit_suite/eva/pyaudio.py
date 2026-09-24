"""
pyaudio.py
----------
Compatibility shim - NOT a real reimplementation of anything.

The `speech_recognition` library (used by voice.py's STTEngine) does
`import pyaudio` internally to access the microphone. The original PyAudio
project doesn't publish prebuilt Windows wheels for current Python
versions, so requirements.txt installs `PyAudioWPatch` instead (an
actively-maintained fork with the same API, importable as
`pyaudiowpatch`, that does ship current wheels).

This file exists purely so that `import pyaudio` - written elsewhere,
outside this project's control - transparently resolves to that fork
instead. It replaces this module in sys.modules with the real
pyaudiowpatch module object itself (not a partial re-export), so every
attribute/class/constant behaves identically to importing pyaudiowpatch
directly.

Nothing in this project imports `pyaudio` directly - this shim is only
here for the third-party library's benefit. If a future PyAudioWPatch
version renames its package, only this one file needs to change.
"""
import sys

import pyaudiowpatch

sys.modules[__name__] = pyaudiowpatch
