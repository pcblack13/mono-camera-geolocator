"""After the CUDA torch install: is the GPU seen, and how fast is YOLO on it vs the CPU?"""
import time, sys
import numpy as np
import torch
print("torch", torch.__version__, "| cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
from ultralytics import YOLO
model_path = sys.argv[1]
frame = (np.random.rand(720, 1280, 3) * 255).astype("uint8")
for device in (["cuda:0"] if torch.cuda.is_available() else []) + ["cpu"]:
    m = YOLO(model_path)
    for _ in range(3):
        m.predict(frame, imgsz=480, device=device, verbose=False, quantize=16 if device.startswith("cuda") else None)
    t0 = time.perf_counter(); n = 20
    for _ in range(n):
        m.predict(frame, imgsz=480, device=device, verbose=False, quantize=16 if device.startswith("cuda") else None)
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    print(f"{device}: {(time.perf_counter() - t0) / n * 1000:.1f} ms per frame @480")
