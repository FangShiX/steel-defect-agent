#!/usr/bin/env python3
"""
Roboflow YOLO 导出 → 标准 YOLO 目录结构整理脚本

Roboflow 导出的 YOLOv11 格式目录结构：
    dataset/
    ├── data.yaml              (可能在根目录或 train/ 子目录)
    ├── train/
    │   ├── images/
    │   └── labels/
    ├── valid/                  ← 注意：是 "valid"，不是 "val"
    │   ├── images/
    │   └── labels/
    └── test/
        ├── images/
        └── labels/

标准 YOLO 目录结构（Ultralytics 要求的格式）：
    dataset/
    ├── data.yaml
    ├── images/
    │   ├── train/
    │   ├── val/               ← 注意：是 "val"
    │   └── test/
    └── labels/
        ├── train/
        ├── val/
        └── test/

使用方式：
    cd backend
    python tools/convert_roboflow.py

    或指定数据集目录：
    python tools/convert_roboflow.py /path/to/roboflow_dataset
"""

import os
import re
import shutil
import sys
from pathlib import Path

# ── 默认路径 ──────────────────────────────────────────
# tools/ → backend/ → project_root/（datasets/ 在项目根目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SRC = os.path.join(PROJECT_ROOT, "datasets/ssdd")

# Roboflow 文件命名模式：basename.rf.HASH.ext
# 例：Cr_87_bmp.rf.1a708df32e8906a82cbb87b6301c4073.jpg → Cr_87.jpg
RF_PATTERN = re.compile(r"\.rf\.[a-f0-9]{32}")


def clean_filename(filename: str) -> str:
    """去除 Roboflow 添加的 .rf.HASH 后缀"""
    return RF_PATTERN.sub("", filename)


def find_data_yaml(src_dir: str) -> str | None:
    """在多个可能位置查找 data.yaml"""
    candidates = [
        os.path.join(src_dir, "data.yaml"),
        os.path.join(src_dir, "train", "data.yaml"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def parse_class_names(yaml_path: str) -> tuple[int, list[str]]:
    """从 data.yaml 解析类别信息，返回 (nc, names_list)"""
    nc = 0
    names = []

    if not yaml_path or not os.path.exists(yaml_path):
        return nc, names

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 解析 nc
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("nc:"):
                try:
                    nc = int(line.split(":")[1].strip())
                except ValueError:
                    pass
                break

        # 解析 names（支持两种格式）
        # 格式1: names: ['a', 'b', 'c']
        # 格式2: names:\n  0: a\n  1: b
        import ast

        lines = content.split("\n")
        in_names = False
        dict_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("names:"):
                value = stripped[6:].strip()
                # 尝试 list 格式
                if value.startswith("["):
                    try:
                        names = ast.literal_eval(value)
                        return nc, names
                    except (SyntaxError, ValueError):
                        pass
                # dict 格式
                in_names = True
                continue
            if in_names:
                if stripped and (stripped[0].isdigit() or stripped.startswith("-")):
                    dict_lines.append(stripped)
                elif not stripped:
                    break
                elif dict_lines:
                    break

        if dict_lines:
            for dl in dict_lines:
                parts = dl.split(":", 1)
                if len(parts) == 2:
                    try:
                        idx = int(parts[0].strip().lstrip("-").strip())
                        name = parts[1].strip()
                        while len(names) <= idx:
                            names.append("")
                        names[idx] = name
                    except ValueError:
                        pass
    except Exception:
        pass

    return nc, names


def reorganize_roboflow_dataset(src_dir: str, clean_names: bool = True) -> dict:
    """
    将 Roboflow 导出的目录结构整理为标准 YOLO 格式

    返回统计信息
    """
    src = Path(src_dir)
    stats = {"train": 0, "val": 0, "test": 0, "files_renamed": 0}

    # 映射：Roboflow 子目录名 → 标准子目录名
    split_mapping = {
        "train": "train",
        "valid": "val",
        "test": "test",
    }

    # 先处理 data.yaml
    yaml_src = find_data_yaml(src_dir)
    nc = 0
    class_names = []
    if yaml_src:
        nc, class_names = parse_class_names(yaml_src)
        # data.yaml 已经移动/复制到根目录，后面会重写

    # 创建标准目录结构并复制文件
    for robof_split, std_split in split_mapping.items():
        src_img_dir = src / robof_split / "images"
        src_lbl_dir = src / robof_split / "labels"

        if not src_img_dir.exists():
            print(f"  [跳过] {robof_split}/images/ 不存在")
            continue

        dst_img_dir = src / "images" / std_split
        dst_lbl_dir = src / "labels" / std_split
        dst_img_dir.mkdir(parents=True, exist_ok=True)
        dst_lbl_dir.mkdir(parents=True, exist_ok=True)

        # 复制图片
        for img_file in sorted(src_img_dir.iterdir()):
            if img_file.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}:
                continue

            new_name = clean_filename(img_file.name) if clean_names else img_file.name
            dst_path = dst_img_dir / new_name
            if not dst_path.exists():
                shutil.copy2(img_file, dst_path)
            if new_name != img_file.name:
                stats["files_renamed"] += 1

            # 复制对应的标注文件
            lbl_name = clean_filename(img_file.stem) if clean_names else img_file.stem
            src_lbl = src_lbl_dir / f"{img_file.stem}.txt"
            dst_lbl = dst_lbl_dir / f"{lbl_name}.txt"
            if src_lbl.exists() and not dst_lbl.exists():
                shutil.copy2(src_lbl, dst_lbl)

            stats[std_split] += 1

        print(f"  {robof_split} → {std_split}: {stats[std_split]} 个")

    # 生成标准 data.yaml
    if not class_names:
        class_names = []
    yaml_path = src / "data.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(f"path: .\n")
        f.write(f"train: images/train\n")
        f.write(f"val: images/val\n")
        f.write(f"test: images/test\n")
        f.write(f"\n")
        f.write(f"nc: {len(class_names)}\n")
        f.write(f"names:\n")
        for i, name in enumerate(class_names):
            f.write(f"  {i}: {name}\n")

    print(f"  data.yaml 已更新: {yaml_path}")

    return stats


def main():
    src_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC

    if not os.path.isdir(src_dir):
        print(f"[错误] 目录不存在: {src_dir}")
        sys.exit(1)

    print("=" * 70)
    print("      Roboflow → 标准 YOLO 目录结构整理")
    print("=" * 70)
    print(f"  数据源: {src_dir}")
    print()

    # 保存旧目录供参考，操作完成后可选择删除
    old_dirs = []
    for d in ["train", "valid", "test"]:
        p = os.path.join(src_dir, d)
        if os.path.isdir(p):
            old_dirs.append(p)

    stats = reorganize_roboflow_dataset(src_dir)

    print()
    print("=" * 70)
    print(f"  整理完成！")
    print(f"  train: {stats['train']} 个")
    print(f"  val:   {stats['val']} 个")
    print(f"  test:  {stats['test']} 个")
    if stats["files_renamed"] > 0:
        print(f"  文件名清理: {stats['files_renamed']} 个（去除 .rf.HASH）")
    print()
    print(f"  旧 Roboflow 目录仍保留，确认无误后可手动删除：")
    for d in old_dirs:
        if os.path.isdir(d):
            print(f"    rm -rf {d}")
    print("=" * 70)


if __name__ == "__main__":
    main()
