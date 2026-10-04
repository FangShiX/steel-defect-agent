"""
YOLO 数据集重划分工具

功能：
    1. 读取标准 YOLO 目录结构数据集
    2. 按指定比例重新随机划分 train/val/test
    3. 保持类别分布（分层抽样，每类在各 split 中比例一致）
    4. 支持固定随机种子，保证可复现
    5. 输出到新目录，不破坏原始数据

使用方式：
    cd backend

    # 默认 7:2:1 划分
    python tools/resplit_dataset.py --input datasets/ssdd --output datasets/ssdd_resplit

    # 自定义比例 8:1:1
    python tools/resplit_dataset.py --input datasets/ssdd --output datasets/ssdd_82 \
        --ratio 0.8 0.1 0.1

    # 只划分 train/val（无 test）
    python tools/resplit_dataset.py --input datasets/ssdd --output datasets/ssdd_nottest \
        --ratio 0.8 0.2 --splits train val

    # 指定随机种子
    python tools/resplit_dataset.py --input datasets/ssdd --output datasets/ssdd_v2 --seed 42

依赖：
    pip install numpy
"""

import argparse
import os
import random
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


def load_class_names(dataset_dir: str) -> dict:
    """从 data.yaml 加载类别名称"""
    yaml_path = os.path.join(dataset_dir, "data.yaml")
    if not os.path.exists(yaml_path):
        return {}

    names = {}
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            in_names = False
            for line in f:
                line = line.strip()
                if line.startswith("names:"):
                    in_names = True
                    continue
                if in_names and line:
                    if line[0].isdigit():
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            names[int(parts[0].strip())] = parts[1].strip()
                elif in_names and not line:
                    break
    except Exception:
        pass
    return names


def collect_samples(dataset_dir: str, splits: list = None) -> list:
    """
    收集所有图像-标注配对，返回列表 [(img_path, lbl_path, split, filename), ...]
    """
    if splits is None:
        splits = ["train", "val", "test"]

    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    samples = []

    for split in splits:
        img_dir = os.path.join(dataset_dir, "images", split)
        lbl_dir = os.path.join(dataset_dir, "labels", split)

        if not os.path.exists(img_dir):
            continue

        for fname in sorted(os.listdir(img_dir)):
            stem = Path(fname).stem
            ext = Path(fname).suffix.lower()
            if ext not in image_exts:
                continue

            img_path = os.path.join(img_dir, fname)
            lbl_path = os.path.join(lbl_dir, f"{stem}.txt")

            samples.append((img_path, lbl_path, fname, stem))

    return samples


def get_sample_classes(label_path: str) -> set:
    """读取标注文件，返回该图片包含的类别 ID 集合"""
    classes = set()
    if not os.path.exists(label_path):
        return classes
    try:
        with open(label_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if parts:
                    classes.add(int(parts[0]))
    except Exception:
        pass
    return classes


def stratified_split(
    samples: list,
    ratios: list,
    split_names: list,
    seed: int = 42,
) -> dict:
    """
    分层划分：尽可能保持各类别在每个 split 中的分布一致

    算法：
      1. 统计每张图片包含的类别
      2. 按「主要类别」（或所有类别）分组
      3. 对每个类别组按比例随机划分
      4. 合并各组，去重（同一图片可能属于多类）

    Args:
        samples: [(img_path, lbl_path, fname, stem), ...]
        ratios: 比例列表，如 [0.7, 0.2, 0.1]
        split_names: split 名称列表，如 ["train", "val", "test"]
        seed: 随机种子

    Returns:
        {split_name: [sample, ...], ...}
    """
    rng = np.random.RandomState(seed)
    random.seed(seed)

    # 按图片的类别归属分组
    class_groups = defaultdict(list)
    for s in samples:
        classes = get_sample_classes(s[1])
        if not classes:
            # 无标注的图片归入 "background" 组
            class_groups[-1].append(s)
        else:
            for cls in classes:
                class_groups[cls].append(s)

    # 为每张图片分配一个主类别（用于分层）
    sample_primary_class = {}
    for s in samples:
        classes = get_sample_classes(s[1])
        sample_primary_class[s[3]] = min(classes) if classes else -1

    # 按主类别分组去重
    primary_groups = defaultdict(list)
    for s in samples:
        primary_groups[sample_primary_class[s[3]]].append(s)

    # 对每个类别组分别划分
    assignments = {}

    for cls, group in primary_groups.items():
        rng.shuffle(group)
        n = len(group)
        cumsum = 0
        for i, (ratio, name) in enumerate(zip(ratios, split_names)):
            if i == len(split_names) - 1:
                count = n - cumsum
            else:
                count = max(1, int(n * ratio))
            count = min(count, n - cumsum)
            for s in group[cumsum : cumsum + count]:
                assignments.setdefault(name, []).append(s)
            cumsum += count

    return assignments


def copy_split(samples: list, src_dataset: str, dst_dataset: str, split_name: str):
    """将样本复制到目标数据集的指定 split 目录（硬链接优先）"""
    img_dst = os.path.join(dst_dataset, "images", split_name)
    lbl_dst = os.path.join(dst_dataset, "labels", split_name)
    os.makedirs(img_dst, exist_ok=True)
    os.makedirs(lbl_dst, exist_ok=True)

    copied = 0
    for img_path, lbl_path, fname, stem in samples:
        dst_img = os.path.join(img_dst, fname)
        dst_lbl = os.path.join(lbl_dst, f"{stem}.txt")

        # 优先硬链接（节省空间），失败则复制
        try:
            if os.path.exists(dst_img):
                os.remove(dst_img)
            os.link(img_path, dst_img)
        except (OSError, PermissionError):
            shutil.copy2(img_path, dst_img)

        if os.path.exists(lbl_path):
            try:
                if os.path.exists(dst_lbl):
                    os.remove(dst_lbl)
                os.link(lbl_path, dst_lbl)
            except (OSError, PermissionError):
                shutil.copy2(lbl_path, dst_lbl)

        copied += 1

    return copied


def update_data_yaml(src_dataset: str, dst_dataset: str, split_names: list):
    """复制并更新 data.yaml"""
    src_yaml = os.path.join(src_dataset, "data.yaml")
    if not os.path.exists(src_yaml):
        return

    dst_yaml = os.path.join(dst_dataset, "data.yaml")
    shutil.copy2(src_yaml, dst_yaml)

    # 更新 path 字段
    with open(dst_yaml, "r", encoding="utf-8") as f:
        content = f.read()

    abs_dst = os.path.abspath(dst_dataset)
    new_content = []
    for line in content.split("\n"):
        if line.strip().startswith("path:"):
            new_content.append(f"path: {abs_dst}")
        elif line.strip().startswith("train:"):
            new_content.append(f"train: images/train")
        elif line.strip().startswith("val:"):
            new_content.append(f"val: images/val")
        elif line.strip().startswith("test:"):
            new_content.append(f"test: images/test")
        else:
            new_content.append(line)

    with open(dst_yaml, "w", encoding="utf-8") as f:
        f.write("\n".join(new_content))


def print_statistics(assignments: dict, class_names: dict):
    """打印划分统计"""
    print(f"\n{'='*60}")
    print("  数据集划分统计")
    print(f"{'='*60}")

    total = sum(len(v) for v in assignments.values())
    for name, samples in assignments.items():
        class_counts = defaultdict(int)
        for s in samples:
            classes = get_sample_classes(s[1])
            for cls in classes:
                class_counts[class_names.get(cls, f"class_{cls}")] += 1
        print(f"\n  [{name}] {len(samples)} 张 ({len(samples)/total*100:.1f}%)")
        for cls_name, count in sorted(class_counts.items()):
            print(f"    {cls_name}: {count}")

    print(f"\n  总计: {total} 张")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="YOLO 数据集重划分工具 — 按比例重新随机分配 train/val/test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 默认 7:2:1 划分
  python tools/resplit_dataset.py -i datasets/ssdd -o datasets/ssdd_v2

  # 自定义 8:1:1
  python tools/resplit_dataset.py -i datasets/ssdd -o datasets/ssdd_82 --ratio 0.8 0.1 0.1

  # 只划分 train/val（无 test）
  python tools/resplit_dataset.py -i datasets/ssdd -o datasets/ssdd_nv --ratio 0.8 0.2 --splits train val
        """,
    )

    parser.add_argument("--input", "-i", type=str, required=True, help="输入数据集目录")
    parser.add_argument("--output", "-o", type=str, required=True, help="输出数据集目录")
    parser.add_argument(
        "--ratio", "-r", type=float, nargs="+", default=[0.7, 0.2, 0.1],
        help="train/val/test 比例（默认: 0.7 0.2 0.1）",
    )
    parser.add_argument(
        "--splits", "-s", nargs="+", default=["train", "val", "test"],
        help="split 名称列表（默认: train val test）",
    )
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认: 42）")

    args = parser.parse_args()

    # 校验比例与 split 数量一致
    if len(args.ratio) != len(args.splits):
        print(f"[错误] --ratio 数量 ({len(args.ratio)}) 与 --splits 数量 ({len(args.splits)}) 不一致")
        sys.exit(1)

    if not os.path.exists(args.input):
        print(f"[错误] 输入数据集不存在: {args.input}")
        sys.exit(1)

    if not os.path.exists(os.path.join(args.input, "data.yaml")):
        print(f"[警告] data.yaml 不存在，将尝试继续")

    class_names = load_class_names(args.input)
    print(f"类别: {class_names}")

    # 收集样本
    samples = collect_samples(args.input)
    if not samples:
        print("[错误] 未找到任何图像-标注配对")
        sys.exit(1)
    print(f"共收集 {len(samples)} 个样本")

    # 分层划分
    assignments = stratified_split(samples, args.ratio, args.splits, args.seed)

    # 创建输出目录
    os.makedirs(args.output, exist_ok=True)

    # 复制文件
    total_copied = 0
    for name in args.splits:
        count = copy_split(assignments.get(name, []), args.input, args.output, name)
        print(f"  [{name}] 复制 {count} 张")
        total_copied += count

    # 更新 data.yaml
    update_data_yaml(args.input, args.output, args.splits)

    # 打印统计
    print_statistics(assignments, class_names)

    print(f"重划分完成，输出目录: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
