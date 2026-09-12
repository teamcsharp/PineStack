# Custom openWakeWord training on the DGX (aarch64)

Working end-to-end pipeline lives in `~/oww-train` on the DGX (built 2026-08-17 for `hey_dj`).

## Layout
- `venv` (py3.10 via uv): torch 2.5.1 CPU, openWakeWord (git, editable), tflite-runtime 2.14, piper-phonemize 1.1.0, numpy 1.26.4
- `venv-tf` (py3.10): plain `tensorflow` (aarch64 wheel) + onnx — conversion only
- `piper-sample-generator` **pinned to tag v2.0.0** — main (v3.x) dropped the flat `generate_samples.py` that openwakeword's train.py imports; TTS model `models/en_US-libritts_r-medium.pt` (204MB, from GitHub release v2.0.0)
- Data: `data/openwakeword_features_ACAV100M_2000_hrs_16bit.npy` (17.3GB, shape (5.6M,16,96) f16), `data/validation_set_features.npy`, `audioset_16k/` (1000 wavs from agkphysics/AudioSet parquets — repo is parquet now, tars are gone), `mit_rirs/` (270 wavs)
- Config `hey_dj.yml`; scripts `03_generate.sh`/`04_augment.sh`/`05_train.sh`/`08_chain.sh` (chain = generate→augment→train with markers in `logs/`)

## Traps (all hit for real)
- **wget and huggingface_hub both STALL at 0 bytes against the HF xet-bridge CDN on this box; curl works** (~2MB/s per connection). Use `~/oww-train/pget.py URL out N` — parallel segmented curl, 8–12 segs ≈ 8–11MB/s. GitHub downloads are fine.
- **onnx_tf is unusable on aarch64** (requires tensorflow-addons, x86-only wheels), so train.py's `--convert_to_tflite` always dies. Use `~/oww-train/convert_manual.py in.onnx out.tflite` (venv-tf): walks the ONNX graph (Gemm/Relu/LayerNorm-decomposed/Sigmoid), rebuilds as TF concrete function, TFLiteConverter. Verified 1e-7 vs onnxruntime via `verify_tflite.py`.
- uv venvs ship **no setuptools** → `pkg_resources` missing for piper code; and setuptools ≥81 removed pkg_resources — pin `setuptools==80.9.0`.
- `datasets==2.14.4` needs `pyarrow==12` (`PyExtensionType` gone in new pyarrow). FMA music streaming never worked anyway; audioset balanced has plenty of music.
- Piper phrase check: generate 6 samples/variant, STT via wyoming-whisper (host network, `127.0.0.1:10300`) with `asr_test.py`. "hey DJ", "hey deejay", "hey dee jay" all render as "Hey DJ".

## wyoming-openwakeword container (:10400)
- Image 2.1.0 uses **pyopen_wakeword** (tflite C API via ctypes, bundled libtensorflowlite_c.so), NOT python tflite_runtime. Loads any float32 `[1,T,96]→[1,1]` head; window count read from the model.
- `-v ~/openwakeword-custom:/custom` + `--custom-model-dir /custom`; wake word name = filename stem. `docker restart openwakeword` to pick up new files; verify with `describe_check.py` (wyoming describe) and live audio via `wake_test.py "POS:x.wav" "NEG:y.wav"`.

## hey_dj model results (modest build: 3000 pos + 3000 adversarial, aug rounds 2)
- `~/openwakeword-custom/hey_dj.tflite` (206KB, input [1,16,96])
- Offline eval (`eval_model.py`): 80.3% clip detection @0.5 on held-out synthetic positives; ~3 FP/h on dense audioset audio (quiet living room ≪). train.py internal operating point: recall 0.508 @ 1.59 FP/h.
- Live socket test: all 3 pronunciations DETECTED, negatives NOT_DETECTED.
- To retrain stronger: raise n_samples (10–30k) and rerun `08_chain.sh` path; 22GB of data/tooling kept in ~/oww-train.
