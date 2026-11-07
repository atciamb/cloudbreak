"""Real-image perception for drone frames (ground GPU).

* Semantic: YOLO26s-sem trained on VDD (Varied Drone Dataset; dronefreak/vdd-yolo26s-sem, AGPL-3.0, 76.4 mIoU).
  VDD classes: other, wall, road, vegetation, vehicle, roof, water.
* Dynamic hazards: YOLO11s trained on VisDrone (dronefreak/visdrone-yolo11s, AGPL-3.0): pedestrians, people,
  bicycles, cars, vans, trucks, buses, motors -- drawn into the person/vehicle channels (boxes inflated 30 %).
* VDD lumps grass and trees into "vegetation": those pixels are returned in `veg` and split later by the LiDAR
  height-above-ground at each pixel's ground point (short_grass < 0.3 m < tall_veg < 2 m < tree).
* Outputs are calibrated soft labels: predicted class 0.85 (~VDD pixel accuracy), rest spread uniformly.
"""
from __future__ import annotations

import numpy as np

from cloudbreak.common.classes import IDX, K
from cloudbreak.common.config import data_dir

VDD = ["other", "wall", "road", "vegetation", "vehicle", "roof", "water"]
VDD_TO_CB = {"wall": "building", "road": "pavement", "vehicle": "vehicle", "roof": "building", "water": "water"}
VISDRONE_PERSON = {0, 1, 2, 9}        # pedestrian, people, bicycle, motor (rider)
VISDRONE_VEHICLE = {3, 4, 5, 6, 7, 8}


class AerialSegmenter:
    def __init__(self, seg_repo="dronefreak/vdd-yolo26s-sem", det_repo="dronefreak/visdrone-yolo11s", device=0,
                 p_class=0.85, det_conf=0.35, imgsz=1024):
        from huggingface_hub import hf_hub_download
        from ultralytics import YOLO

        cache = str(data_dir() / "models")
        self.seg = YOLO(hf_hub_download(seg_repo, "best.pt", cache_dir=cache))
        self.det = YOLO(hf_hub_download(det_repo, "best.pt", cache_dir=cache)) if det_repo else None
        self.device, self.p, self.det_conf, self.imgsz = device, p_class, det_conf, imgsz
        self.last_dets: list = []

    def _soft(self, labels: np.ndarray) -> np.ndarray:
        probs = np.full(labels.shape + (K,), (1 - self.p) / (K - 1), np.float32)
        np.put_along_axis(probs, labels[..., None].astype(np.int64), self.p, axis=-1)
        return probs

    def probs_and_veg(self, img_rgb: np.ndarray):
        import cv2

        H, W = img_rgb.shape[:2]
        bgr = np.ascontiguousarray(img_rgb[..., ::-1])
        r = self.seg.predict(bgr, imgsz=self.imgsz, device=self.device, verbose=False)[0]
        m = r.semantic_mask
        m = m.cpu().numpy() if hasattr(m, "cpu") else m
        m = getattr(m, "data", m)                                # ultralytics SemanticMask -> ndarray
        m = np.asarray(m).squeeze().astype(np.uint8)
        if m.shape != (H, W):
            m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
        lab = np.full((H, W), IDX["rough"], np.uint8)          # VDD "other": not safe until proven otherwise
        for i, name in enumerate(VDD):
            if name in VDD_TO_CB:
                lab[m == i] = IDX[VDD_TO_CB[name]]
        veg = m == VDD.index("vegetation")
        lab[veg] = IDX["short_grass"]                          # placeholder; resolved by lidar HAG in core.fuse
        probs = self._soft(lab)
        other = m == VDD.index("other")
        probs[other] = (1 - 0.7) / (K - 2)
        probs[other, IDX["rough"]] = 0.35
        probs[other, IDX["dirt"]] = 0.35
        self.last_dets = []
        if self.det is not None:
            d = self.det.predict(bgr, imgsz=self.imgsz, device=self.device, conf=self.det_conf, verbose=False)[0]
            for (x1, y1, x2, y2), c, s in zip(d.boxes.xyxy.cpu().numpy(), d.boxes.cls.cpu().numpy().astype(int),
                                              d.boxes.conf.cpu().numpy()):
                cls = "person" if c in VISDRONE_PERSON else "vehicle" if c in VISDRONE_VEHICLE else None
                if cls is None:
                    continue
                cx, cy, hw, hh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * 0.65, (y2 - y1) * 0.65
                xa, xb = int(max(0, cx - hw)), int(min(W, cx + hw))
                ya, yb = int(max(0, cy - hh)), int(min(H, cy + hh))
                probs[ya:yb, xa:xb] = (1 - 0.9) / (K - 1)
                probs[ya:yb, xa:xb, IDX[cls]] = 0.9
                veg[ya:yb, xa:xb] = False
                self.last_dets.append(dict(cls=cls, conf=float(s), box=[float(x1), float(y1), float(x2), float(y2)]))
        return probs, veg

    def probs(self, img_rgb):
        return self.probs_and_veg(img_rgb)[0]
