# Repository layout and housekeeping

```
Thesis/
├── pyballbalancer/                  Host A: PyQt5 control application        → its own README
├── HighPrecisionStepperJuggler-master/
│   ├── Arduino/HighPrecisionStepperJuggler/   Teensy 4.0 firmware (used by BOTH hosts)
│   ├── Unity/HighPrecisionStepperJuggler/     Host B: Unity project
│   ├── Unity/ScriptableRenderPipeline-6.9.1/  HDRP package the Unity project depends on
│   ├── UVCCameraPlugin/                       C++ source of the Unity camera plugin (OpenCV)
│   ├── Latex/                                 Original author's paper source
│   └── LICENSE                                MIT, Tobias Kuhn
├── codes/                           Standalone Teensy test sketches and a Python env check
├── tools/                           Scripts that build the thesis figures and draft document
├── Design/                          Fusion 360 models and arm drawings (.f3d, .pdf)
├── stl files/                       Printable parts (.stl, .3mf) and the full assembly (.step)
├── datasheets/                      Teensy, DM542T, NEMA17, buck converters, level shifter
├── my_documents/                    Wiring diagrams, photos, screen recordings
├── log files/                       Captured Editor/balancing logs and calibration CSV
├── Thesis Report/                   Thesis document (git submodule pointer — see the housekeeping notes below)
└── campus_cham_leitfaden_abschlussarbeiten_en.pdf   University thesis guidelines
```

---

## Working with this repository

- **Git LFS is required.** Binary assets such as the Unity DLLs are stored with LFS. Run
  `git lfs install` before cloning, or those files arrive as small pointer text files.
- **Unity's `Library/` folder is tracked** and Unity rewrites parts of it, along with some `.mat`
  files, whenever the editor is open. Close Unity before committing to keep that churn out of the
  history.
- **`Thesis Report/` is a submodule pointer with no `.gitmodules` entry.** It appears empty in a
  fresh clone; the document lives outside this repository.
- **Low commit memory breaks Git LFS on Windows.** If `git add` fails with a Go
  `out of memory allocating heap arena map` error, close Unity (or enlarge the page file) and retry.
- **`.mcp.json`** configures an Overleaf MCP server for editing the thesis. It reads
  `OVERLEAF_PROJECT_ID` and `OVERLEAF_GIT_TOKEN` from the environment and contains no secrets.

---

## Thesis tooling

| Script | Output |
|---|---|
| [`tools/gen_figs.py`](../tools/gen_figs.py) | IK geometry, sine motion profile and camera FOV diagrams |
| [`tools/gen_block.py`](../tools/gen_block.py) | System block diagram (`fig_block.png`) |
| [`tools/make_thesis.py`](../tools/make_thesis.py) | Rebuilds the draft `.docx` from the figures (`python-docx`; set `THESIS_DIR` / `FIG_DIR`) |
| [`codes/test_setup.py`](../codes/test_setup.py) | Confirms the Python / OpenCV / NumPy environment |

---

[← Back to the main README](../README.md) · [Hardware](hardware.md) · [Firmware](firmware.md) · [PyQt app](../pyballbalancer/README.md) · [Unity app](unity-app.md) · [Camera & motion](camera-and-motion.md) · [Troubleshooting](troubleshooting.md) · [Repository](repository.md)
