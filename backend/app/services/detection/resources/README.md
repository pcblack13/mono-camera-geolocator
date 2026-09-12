# Tracker models

`vittrack_2023sep.onnx` — OpenCV Zoo's VitTrack (`object_tracking_vittrack_2023sep.onnx`,
Apache-2.0), the learned single-object tracker behind `cv2.TrackerVit`. 715 KB, CPU,
~25 ms per frame at 1280x720. Fetched from
`https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_tracking_vittrack/`
and pinned by the `.sha256` beside it.

★ WHY IT IS HERE AND NOT DOWNLOADED AT RUNTIME: a tracker the operator reaches for
mid-run must be there without a network. Committed because it is small; the YOLO
weights (tens of MB) stay outside the repo in `desktop/local-resources`.
