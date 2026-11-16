"""Local face check: is the person in a frame the person on a character sheet?

Two small ONNX models from the insightface "buffalo_sc" pack do the work:
SCRFD (det_500m.onnx) finds faces and five landmarks on each; ArcFace MobileFaceNet
(w600k_mbf.onnx) turns an aligned face into 512 numbers. Two faces of the same person
give vectors that point the same way, so their cosine similarity is high.

Why local: Gemini failed this check in the smoke test (it called two different personas
the same person). The models are for non-commercial research use only (insightface licence).
Fetch them once with `python -m adgen fetch-face-model` (15 MB, into models/, gitignored).
"""
import io
import zipfile
from pathlib import Path

import httpx
import numpy as np
import onnxruntime
from PIL import Image

MODEL_DIR = Path("models/buffalo_sc")
MODEL_ZIP = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip"
DETECTOR, RECOGNIZER = "det_500m.onnx", "w600k_mbf.onnx"
DETECT_SIZE = 640
MIN_FACE_SCORE = 0.5
OVERLAP_LIMIT = 0.4   # boxes that overlap more than this are the same face
STRIDES = (8, 16, 32)
ANCHORS_PER_CELL = 2
# Where ArcFace expects the eyes, nose tip and mouth corners in its 112x112 input.
ARCFACE_POINTS = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                           [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def fetch_models(model_dir: Path = MODEL_DIR) -> None:
    """Download the model pack (15 MB) and keep only the two model files we use."""
    model_dir.mkdir(parents=True, exist_ok=True)
    archive = zipfile.ZipFile(io.BytesIO(httpx.get(MODEL_ZIP, follow_redirects=True, timeout=300).content))
    for member in archive.namelist():
        if Path(member).name in (DETECTOR, RECOGNIZER):  # by file name only: no paths from the zip are trusted
            (model_dir / Path(member).name).write_bytes(archive.read(member))


def similarity_transform(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """The 2x3 matrix (rotate, scale, shift) that best moves `source` points onto `target` (Umeyama)."""
    source_mean, target_mean = source.mean(0), target.mean(0)
    source_c, target_c = source - source_mean, target - target_mean
    u, s, vt = np.linalg.svd(target_c.T @ source_c / len(source))
    flip = np.array([1.0, -1.0 if np.linalg.det(u) * np.linalg.det(vt) < 0 else 1.0])
    rotation = u @ np.diag(flip) @ vt
    scale = (s * flip).sum() / source_c.var(0).sum()
    shift = target_mean - scale * rotation @ source_mean
    return np.hstack([scale * rotation, shift[:, None]])


def keep_distinct(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    """Indexes of the best box for each face (non-maximum suppression)."""
    order, kept = list(np.argsort(-scores)), []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order:
        best = order.pop(0)
        kept.append(int(best))
        x1, y1 = np.maximum(boxes[best, :2], boxes[order, :2]).T
        x2, y2 = np.minimum(boxes[best, 2:], boxes[order, 2:]).T
        overlap = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        ratio = overlap / (areas[best] + areas[order] - overlap)
        order = [index for index, r in zip(order, ratio) if r <= OVERLAP_LIMIT]
    return kept


class FaceMatcher:
    def __init__(self, model_dir: Path = MODEL_DIR):
        if not (model_dir / DETECTOR).exists():
            raise FileNotFoundError(f"face models missing in {model_dir}: run `python -m adgen fetch-face-model`")
        options = {"providers": ["CPUExecutionProvider"]}
        self.detector = onnxruntime.InferenceSession(str(model_dir / DETECTOR), **options)
        self.recognizer = onnxruntime.InferenceSession(str(model_dir / RECOGNIZER), **options)

    def _detect(self, image: Image.Image) -> list[tuple[float, np.ndarray]]:
        """Faces in the image as (box area, five landmark points), in original pixel positions."""
        scale = DETECT_SIZE / max(image.size)
        small = image.resize((round(image.width * scale), round(image.height * scale)))
        canvas = Image.new("RGB", (DETECT_SIZE, DETECT_SIZE))
        canvas.paste(small)  # top-left, rest stays black
        blob = ((np.asarray(canvas, dtype=np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None]
        outputs = self.detector.run(None, {self.detector.get_inputs()[0].name: blob})
        tables = [out.reshape(-1, out.shape[-1]) for out in outputs]  # rows x (1, 4 or 10) columns

        boxes, scores, points = [], [], []
        for stride in STRIDES:
            cells = DETECT_SIZE // stride
            rows = cells * cells * ANCHORS_PER_CELL
            # This stride's three outputs, found by row count and keyed by column count:
            # 1 = face score, 4 = box edges, 10 = five landmark points.
            by_width = {table.shape[1]: table for table in tables if table.shape[0] == rows}
            ys, xs = np.mgrid[:cells, :cells]
            centers = np.repeat(np.stack([xs, ys], -1).reshape(-1, 2) * stride, ANCHORS_PER_CELL, axis=0)
            good = by_width[1][:, 0] >= MIN_FACE_SCORE
            reach = by_width[4][good] * stride  # distances from the cell centre to the box edges
            boxes.append(np.hstack([centers[good] - reach[:, :2], centers[good] + reach[:, 2:]]))
            scores.append(by_width[1][good, 0])
            points.append(centers[good][:, None, :] + by_width[10][good].reshape(-1, 5, 2) * stride)
        boxes, scores, points = np.vstack(boxes), np.concatenate(scores), np.vstack(points)
        if not len(boxes):
            return []
        faces = [((boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1]) / scale ** 2, points[i] / scale)
                 for i in keep_distinct(boxes, scores)]
        return sorted(faces, key=lambda face: -face[0])

    def _embed(self, image: Image.Image, landmarks: np.ndarray) -> np.ndarray:
        """The face, turned upright and cropped to 112x112, as a unit vector of 512 numbers."""
        to_crop = np.vstack([similarity_transform(landmarks.astype(np.float32), ARCFACE_POINTS), [0, 0, 1]])
        from_crop = np.linalg.inv(to_crop)[:2].flatten()  # Pillow wants the crop-to-image direction
        crop = image.transform((112, 112), Image.Transform.AFFINE, tuple(from_crop), Image.Resampling.BILINEAR)
        blob = ((np.asarray(crop, dtype=np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None]
        vector = self.recognizer.run(None, {self.recognizer.get_inputs()[0].name: blob})[0][0]
        return vector / np.linalg.norm(vector)

    def faces(self, path: Path) -> list[np.ndarray]:
        """One vector per face in the image, largest face first."""
        image = Image.open(path).convert("RGB")
        return [self._embed(image, landmarks) for _, landmarks in self._detect(image)]

    def similarity(self, sheet: Path, frame: Path) -> float | None:
        """Cosine similarity (-1 to 1) between the largest face in the frame and the closest
        view on the character sheet. None if either image has no face."""
        sheet_faces, frame_faces = self.faces(sheet), self.faces(frame)
        if not sheet_faces or not frame_faces:
            return None
        return float(max(view @ frame_faces[0] for view in sheet_faces))
