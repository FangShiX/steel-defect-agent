"""Content-driven dataset discovery and conversion to YOLO detection format.

The importer deliberately does not infer meaning from directory names.  It
pairs annotations with images using references stored inside the annotation
files and falls back to an unambiguous basename match.  Dataset splits come
from format metadata when available; otherwise a stable hash split is used.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

import yaml
from PIL import Image, UnidentifiedImageError


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
SUPPORTED_FORMATS = {"auto", "yolo", "voc", "coco", "labelme"}


class DatasetImportError(ValueError):
    """A user-correctable dataset discovery or conversion error."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class RawBox:
    class_name: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float


@dataclass(frozen=True)
class Sample:
    image: Path
    width: int
    height: int
    boxes: tuple[RawBox, ...]
    split: str | None = None


def _all_files(root: Path, suffixes: set[str]) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)


class ImageIndex:
    def __init__(self, root: Path):
        self.root = root
        self.images = _all_files(root, IMAGE_SUFFIXES)
        self.by_name: dict[str, list[Path]] = {}
        self.by_stem: dict[str, list[Path]] = {}
        for image in self.images:
            self.by_name.setdefault(image.name.casefold(), []).append(image)
            self.by_stem.setdefault(image.stem.casefold(), []).append(image)

    def resolve(self, reference: str | None, annotation: Path) -> Path:
        """Resolve an annotation image reference without directory-name rules."""
        candidates: list[Path] = []
        if reference:
            normalized = PurePosixPath(reference.replace("\\", "/"))
            direct = (annotation.parent / Path(*normalized.parts)).resolve()
            if self._is_indexed_path(direct):
                return direct
            root_relative = (self.root / Path(*normalized.parts)).resolve()
            if self._is_indexed_path(root_relative):
                return root_relative
            candidates = self.by_name.get(normalized.name.casefold(), [])
            stem = Path(normalized.name).stem.casefold()
        else:
            stem = annotation.stem.casefold()
        if not candidates:
            candidates = self.by_stem.get(stem, [])
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise DatasetImportError(
                "MISSING_IMAGE", f"标注 {annotation.name} 找不到引用的图片",
                {"annotation": str(annotation.relative_to(self.root)), "reference": reference},
            )
        raise DatasetImportError(
            "AMBIGUOUS_IMAGE", f"标注 {annotation.name} 对应多张同名图片，无法安全选择",
            {
                "annotation": str(annotation.relative_to(self.root)),
                "reference": reference,
                "candidates": [str(p.relative_to(self.root)) for p in candidates],
            },
        )

    def _is_indexed_path(self, path: Path) -> bool:
        """References may never escape the extracted upload directory."""
        resolved_root = self.root.resolve()
        return (
            path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and (path == resolved_root or resolved_root in path.parents)
        )


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise DatasetImportError("INVALID_IMAGE", f"图片无法解析: {path.name}") from exc
    if width <= 0 or height <= 0:
        raise DatasetImportError("INVALID_IMAGE", f"图片尺寸无效: {path.name}")
    return width, height


def _clip_box(box: RawBox, width: int, height: int) -> RawBox | None:
    xmin = max(0.0, min(float(width), box.xmin))
    ymin = max(0.0, min(float(height), box.ymin))
    xmax = max(0.0, min(float(width), box.xmax))
    ymax = max(0.0, min(float(height), box.ymax))
    if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)) or xmax <= xmin or ymax <= ymin:
        return None
    return RawBox(box.class_name, xmin, ymin, xmax, ymax)


def _voc_samples(root: Path, index: ImageIndex) -> list[Sample]:
    samples = []
    for xml_path in _all_files(root, {".xml"}):
        try:
            node = ET.parse(xml_path).getroot()
        except ET.ParseError as exc:
            raise DatasetImportError("INVALID_ANNOTATION", f"VOC XML 无法解析: {xml_path.name}") from exc
        if node.tag.casefold() != "annotation":
            continue
        reference = node.findtext("path") or node.findtext("filename")
        image = index.resolve(reference, xml_path)
        width, height = _image_size(image)
        boxes = []
        for obj in node.findall("object"):
            bbox = obj.find("bndbox")
            name = (obj.findtext("name") or "").strip()
            if bbox is None or not name:
                continue
            try:
                raw = RawBox(name, *(float(bbox.findtext(key, "nan")) for key in ("xmin", "ymin", "xmax", "ymax")))
            except ValueError:
                continue
            clipped = _clip_box(raw, width, height)
            if clipped:
                boxes.append(clipped)
        samples.append(Sample(image, width, height, tuple(boxes)))
    return samples


def _json_kind(path: Path) -> tuple[str | None, dict | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None
    if isinstance(payload, dict) and all(isinstance(payload.get(k), list) for k in ("images", "annotations", "categories")):
        return "coco", payload
    if isinstance(payload, dict) and isinstance(payload.get("shapes"), list) and (
        "imagePath" in payload or "imageWidth" in payload or "imageHeight" in payload
    ):
        return "labelme", payload
    return None, None


def _coco_samples(root: Path, index: ImageIndex) -> list[Sample]:
    samples: list[Sample] = []
    seen_ids: set[tuple[Path, object]] = set()
    for json_path in _all_files(root, {".json"}):
        kind, data = _json_kind(json_path)
        if kind != "coco" or data is None:
            continue
        categories = {item.get("id"): str(item.get("name", "")).strip() for item in data["categories"]}
        grouped: dict[object, list[dict]] = {}
        for annotation in data["annotations"]:
            grouped.setdefault(annotation.get("image_id"), []).append(annotation)
        for info in data["images"]:
            image_id = info.get("id")
            identity = (json_path, image_id)
            if identity in seen_ids:
                continue
            seen_ids.add(identity)
            image = index.resolve(str(info.get("file_name") or ""), json_path)
            actual_width, actual_height = _image_size(image)
            width = int(info.get("width") or actual_width)
            height = int(info.get("height") or actual_height)
            if (width, height) != (actual_width, actual_height):
                raise DatasetImportError("IMAGE_SIZE_MISMATCH", f"COCO 图片尺寸与文件不一致: {image.name}")
            boxes = []
            for ann in grouped.get(image_id, []):
                bbox = ann.get("bbox")
                name = categories.get(ann.get("category_id"), "")
                if not name or not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                x, y, w, h = bbox
                clipped = _clip_box(RawBox(name, x, y, x + w, y + h), width, height)
                if clipped:
                    boxes.append(clipped)
            samples.append(Sample(image, width, height, tuple(boxes)))
    return samples


def _labelme_samples(root: Path, index: ImageIndex) -> list[Sample]:
    samples = []
    for json_path in _all_files(root, {".json"}):
        kind, data = _json_kind(json_path)
        if kind != "labelme" or data is None:
            continue
        image = index.resolve(data.get("imagePath"), json_path)
        actual_width, actual_height = _image_size(image)
        width = int(data.get("imageWidth") or actual_width)
        height = int(data.get("imageHeight") or actual_height)
        if (width, height) != (actual_width, actual_height):
            raise DatasetImportError("IMAGE_SIZE_MISMATCH", f"LabelMe 图片尺寸与文件不一致: {image.name}")
        boxes = []
        for shape in data["shapes"]:
            name = str(shape.get("label", "")).strip()
            points = shape.get("points")
            if not name or not isinstance(points, list) or len(points) < 2:
                continue
            try:
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
            except (TypeError, ValueError, IndexError):
                continue
            clipped = _clip_box(RawBox(name, min(xs), min(ys), max(xs), max(ys)), width, height)
            if clipped:
                boxes.append(clipped)
        samples.append(Sample(image, width, height, tuple(boxes)))
    return samples


def detect_format(root: Path) -> str:
    """Detect annotation format from parseable content, never directory names."""
    yaml_files = _all_files(root, {".yaml", ".yml"})
    for path in yaml_files:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(value, dict) and "names" in value and "train" in value:
            return "yolo"
    json_kinds = {_json_kind(path)[0] for path in _all_files(root, {".json"})}
    json_kinds.discard(None)
    if len(json_kinds) > 1:
        raise DatasetImportError("AMBIGUOUS_FORMAT", "压缩包同时包含 COCO 和 LabelMe 标注，请明确选择格式")
    if json_kinds:
        return next(iter(json_kinds))
    for path in _all_files(root, {".xml"}):
        try:
            if ET.parse(path).getroot().tag.casefold() == "annotation":
                return "voc"
        except ET.ParseError:
            continue
    raise DatasetImportError("UNKNOWN_FORMAT", "无法从文件内容识别数据集格式")


def _stable_split(image: Path, root: Path, ratios: tuple[float, float, float], seed: int) -> str:
    key = f"{seed}:{image.relative_to(root).as_posix()}".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64
    if value < ratios[0]:
        return "train"
    if value < ratios[0] + ratios[1]:
        return "val"
    return "test"


def _validate_ratios(ratios: Iterable[float]) -> tuple[float, float, float]:
    values = tuple(float(v) for v in ratios)
    if (
        len(values) != 3
        or any(not math.isfinite(v) or v < 0 or v > 1 for v in values)
        or abs(sum(values) - 1.0) > 1e-6
    ):
        raise DatasetImportError("INVALID_SPLIT", "train/val/test 比例必须在 0-1 内且总和为 1")
    if values[0] <= 0 or values[1] <= 0:
        raise DatasetImportError("INVALID_SPLIT", "训练集和验证集比例必须大于 0")
    return values  # type: ignore[return-value]


def _output_name(image: Path, root: Path, used: set[str]) -> str:
    name = image.name
    if name.casefold() not in used:
        used.add(name.casefold())
        return name
    digest = hashlib.sha1(image.relative_to(root).as_posix().encode("utf-8")).hexdigest()[:10]
    name = f"{image.stem}_{digest}{image.suffix.lower()}"
    used.add(name.casefold())
    return name


def _write_samples(root: Path, target: Path, samples: list[Sample], ratios, seed: int, source_format: str) -> dict:
    if not samples:
        raise DatasetImportError("NO_ANNOTATIONS", f"未发现可转换的 {source_format.upper()} 标注")
    image_keys = [sample.image.resolve() for sample in samples]
    if len(set(image_keys)) != len(image_keys):
        raise DatasetImportError("DUPLICATE_ANNOTATION", "同一图片被多个标注记录重复引用")
    classes = sorted({box.class_name for sample in samples for box in sample.boxes}, key=str.casefold)
    if not classes:
        raise DatasetImportError("NO_CLASSES", "标注中未发现有效类别")
    class_ids = {name: idx for idx, name in enumerate(classes)}
    ratio_values = _validate_ratios(ratios)
    counts = {"train": 0, "val": 0, "test": 0}
    box_count = 0
    used_names: set[str] = set()
    target.mkdir(parents=True, exist_ok=False)
    for sample in samples:
        split = sample.split or _stable_split(sample.image, root, ratio_values, seed)
        image_dir = target / "images" / split
        label_dir = target / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        output_name = _output_name(sample.image, root, used_names)
        shutil.copy2(sample.image, image_dir / output_name)
        lines = []
        for box in sample.boxes:
            x = (box.xmin + box.xmax) / 2 / sample.width
            y = (box.ymin + box.ymax) / 2 / sample.height
            w = (box.xmax - box.xmin) / sample.width
            h = (box.ymax - box.ymin) / sample.height
            lines.append(f"{class_ids[box.class_name]} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
        (label_dir / f"{Path(output_name).stem}.txt").write_text("\n".join(lines), encoding="utf-8")
        counts[split] += 1
        box_count += len(lines)
    config = {
        "path": ".",
        "train": "images/train",
        "val": "images/val",
        "names": {idx: name for idx, name in enumerate(classes)},
        "nc": len(classes),
    }
    if counts["test"]:
        config["test"] = "images/test"
    (target / "data.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"source_format": source_format, "classes": classes, "splits": counts, "images": len(samples), "boxes": box_count}


def _copy_yolo_dataset(root: Path, target: Path) -> dict:
    configs = []
    for path in _all_files(root, {".yaml", ".yml"}):
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(value, dict) and "names" in value and "train" in value:
            configs.append((path, value))
    if len(configs) != 1:
        raise DatasetImportError("AMBIGUOUS_YOLO_CONFIG", "YOLO 数据集必须且只能包含一个可识别的 data.yaml")
    config_path, config = configs[0]
    source_root = config_path.parent
    resolved_splits: dict[str, Path] = {}
    for split in ("train", "val", "test"):
        reference = config.get(split)
        if reference is None and split == "test":
            continue
        if not isinstance(reference, str) or not reference.strip():
            raise DatasetImportError("INVALID_YOLO_CONFIG", f"data.yaml 缺少有效的 {split} 图片路径")
        normalized = PurePosixPath(reference.replace("\\", "/"))
        relative_parts = tuple(part for part in normalized.parts if part not in ("/", "..", "."))
        candidates = [
            (config_path.parent / Path(*normalized.parts)).resolve(),
            (source_root / Path(*relative_parts)).resolve(),
            (root / Path(*relative_parts)).resolve(),
        ]
        matches = []
        for candidate in candidates:
            if candidate.is_dir() and (candidate == root.resolve() or root.resolve() in candidate.parents):
                if candidate not in matches:
                    matches.append(candidate)
        if len(matches) != 1:
            raise DatasetImportError(
                "AMBIGUOUS_YOLO_PATH",
                f"无法唯一解析 data.yaml 的 {split} 路径: {reference}",
                {"reference": reference, "candidates": [str(path.relative_to(root)) for path in matches]},
            )
        resolved_splits[split] = matches[0]
    names = config.get("names", [])
    if isinstance(names, dict):
        try:
            indexed_names = {int(key): value for key, value in names.items()}
        except (TypeError, ValueError) as exc:
            raise DatasetImportError("INVALID_YOLO_CONFIG", "data.yaml 的类别 ID 必须是整数") from exc
        if sorted(indexed_names) != list(range(len(indexed_names))):
            raise DatasetImportError("INVALID_YOLO_CONFIG", "data.yaml 的类别 ID 必须从 0 连续编号")
        classes = [indexed_names[index] for index in range(len(indexed_names))]
    else:
        classes = list(names) if isinstance(names, list) else []
    if not classes or any(not isinstance(name, str) or not name.strip() for name in classes):
        raise DatasetImportError("INVALID_YOLO_CONFIG", "data.yaml 必须包含非空类别名称")

    # YOLO TXT has no image path field.  Pair only when the basename is
    # unique; the directories containing either side carry no semantics.
    labels_by_stem: dict[str, list[Path]] = {}
    for path in _all_files(root, {".txt"}):
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        is_label = True
        for line in lines:
            if not line.strip():
                continue
            fields = line.split()
            try:
                class_id = int(fields[0])
                coordinates = [float(value) for value in fields[1:]]
            except (ValueError, IndexError):
                is_label = False
                break
            if len(fields) != 5 or not 0 <= class_id < len(classes) or not all(math.isfinite(v) for v in coordinates):
                is_label = False
                break
        if is_label:
            labels_by_stem.setdefault(path.stem.casefold(), []).append(path)

    target.mkdir(parents=True, exist_ok=False)
    used_names: set[str] = set()
    counts = {"train": 0, "val": 0, "test": 0}
    box_count = 0
    for split, image_root in resolved_splits.items():
        images = _all_files(image_root, IMAGE_SUFFIXES)
        if split in {"train", "val"} and not images:
            raise DatasetImportError("EMPTY_SPLIT", f"YOLO {split} 集没有图片")
        for image in images:
            _image_size(image)
            candidates = labels_by_stem.get(image.stem.casefold(), [])
            if len(candidates) > 1:
                raise DatasetImportError(
                    "AMBIGUOUS_LABEL", f"图片 {image.name} 对应多个同名 YOLO 标签",
                    {"candidates": [str(path.relative_to(root)) for path in candidates]},
                )
            output_name = _output_name(image, root, used_names)
            image_output = target / "images" / split / output_name
            label_output = target / "labels" / split / f"{Path(output_name).stem}.txt"
            image_output.parent.mkdir(parents=True, exist_ok=True)
            label_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image, image_output)
            label_text = candidates[0].read_text(encoding="utf-8-sig") if candidates else ""
            label_output.write_text(label_text.strip(), encoding="utf-8")
            box_count += sum(1 for line in label_text.splitlines() if line.strip())
            counts[split] += 1

    output_config = {
        "path": ".",
        "train": "images/train",
        "val": "images/val",
        "nc": len(classes),
        "names": {index: name for index, name in enumerate(classes)},
    }
    if counts["test"]:
        output_config["test"] = "images/test"
    (target / "data.yaml").write_text(
        yaml.safe_dump(output_config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return {"source_format": "yolo", "classes": classes, "splits": counts, "images": sum(counts.values()), "boxes": box_count}


def import_dataset(
    source: Path,
    target: Path,
    dataset_format: str = "auto",
    split_ratios: Iterable[float] = (0.8, 0.1, 0.1),
    seed: int = 42,
) -> dict:
    """Discover and atomically prepare a dataset in a caller-owned target path."""
    requested = dataset_format.casefold()
    if requested not in SUPPORTED_FORMATS:
        raise DatasetImportError("UNSUPPORTED_FORMAT", f"不支持的数据集格式: {dataset_format}")
    if not 0 <= seed <= 2_147_483_647:
        raise DatasetImportError("INVALID_SPLIT", "随机种子必须在 0 到 2147483647 之间")
    detected = detect_format(source) if requested == "auto" else requested
    if detected == "yolo":
        return _copy_yolo_dataset(source, target)
    index = ImageIndex(source)
    if not index.images:
        raise DatasetImportError("NO_IMAGES", "压缩包中未发现支持的图片")
    loaders = {"voc": _voc_samples, "coco": _coco_samples, "labelme": _labelme_samples}
    samples = loaders[detected](source, index)
    return _write_samples(source, target, samples, split_ratios, seed, detected)
