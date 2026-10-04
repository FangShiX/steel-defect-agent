"""
YOLO 数据集合并工具

功能：
    1. 合并两个 YOLO 目录结构数据集
    2. 自动处理类别名称/ID 映射（同名合并，异名追加）
    3. 支持直接合并（保持原有 train/val/test 分配）
    4. 支持合并后重新随机划分 train/val/test
    5. 支持指定类别合并：只将 B 中指定类别并入 A
    6. 输出合并后的数据集和 data.yaml

使用方式：
    cd backend

    # 直接合并（保持原有目录结构）
    python tools/merge_datasets.py \\
        -a datasets/dataset_a -b datasets/dataset_b \\
        -o datasets/merged

    # 合并后重新随机划分
    python tools/merge_datasets.py \\
        -a datasets/dataset_a -b datasets/dataset_b \\
        -o datasets/merged --resplit --ratio 0.7 0.2 0.1

    # 合并时忽略 B 中已有类别（只保留 A 的类别体系）
    python tools/merge_datasets.py \\
        -a datasets/base -b datasets/extra \\
        -o datasets/merged --map-mode intersect

    # 只从 B 中抽取指定类别并入 A
    python tools/merge_datasets.py \\
        -a datasets/base -b datasets/extra \\
        -o datasets/merged --classes pitted scratches

依赖：无（纯标准库）
"""

import argparse
import os
import random
import shutil
import sys
from collections import defaultdict
from pathlib import Path


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def load_class_names(dataset_dir: str) -> dict:
    """从 data.yaml 加载类别名称 {0: "crazing", 1: "inclusion", ...}"""
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


def load_dataset_info(dataset_dir: str) -> dict:
    """加载数据集基本信息"""
    return {
        "path": dataset_dir,
        "class_names": load_class_names(dataset_dir),
    }


def collect_samples(dataset_dir: str) -> list:
    """
    收集所有图像-标注配对
    返回: [(img_path, lbl_path, split, stem, ext), ...]
    """
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    samples = []

    for split in ["train", "val", "test"]:
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
            samples.append((img_path, lbl_path, split, stem, ext))
    return samples


def read_label(label_path: str, filter_class_ids: set = None) -> list:
    """读取 YOLO 标注文件，可选按 class_id 过滤
    返回 [(class_id, x, y, w, h), ...]
    """
    entries = []
    if not os.path.exists(label_path):
        return entries
    try:
        with open(label_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 5:
                    cls_id = int(parts[0])
                    if filter_class_ids is not None and cls_id not in filter_class_ids:
                        continue
                    entries.append((
                        cls_id,
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                        float(parts[4]),
                    ))
    except Exception:
        pass
    return entries


def write_label(label_path: str, entries: list):
    """写入 YOLO 标注文件"""
    os.makedirs(os.path.dirname(label_path), exist_ok=True)
    with open(label_path, "w", encoding="utf-8") as f:
        for cls_id, x, y, w, h in entries:
            f.write(f"{cls_id} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n")


# ══════════════════════════════════════════════════════════════
# 类别映射
# ══════════════════════════════════════════════════════════════

def build_class_mapping(
    classes_a: dict,
    classes_b: dict,
    map_mode: str = "union",
) -> tuple:
    """
    构建两个数据集之间的类别 ID 映射

    策略：
      - union（默认）: 合并所有类别，同名合并，异名追加
      - intersect: 只保留 A 中的类别，B 中匹配的合并，不匹配的丢弃
      - rename: B 中与 A 同名的合并，不同名的作为新类别追加（默认 union 即 rename）

    Args:
        classes_a: A 数据集 {id: name}
        classes_b: B 数据集 {id: name}
        map_mode: union / intersect

    Returns:
        (
            merged_classes: {new_id: name},       # 合并后的类别体系
            b_to_merged: {old_b_id: new_id},       # B → 合并后 的 ID 映射
            a_to_merged: {old_a_id: new_id},       # A → 合并后 的 ID 映射
        )
    """
    # 建立名称到 ID 的反向索引
    name_to_id_a = {name: id_ for id_, name in classes_a.items()}

    merged = {}     # {new_id: name}
    name_to_merged = {}  # {name: new_id}
    a_to_merged = {}    # {old_a_id: new_id}
    b_to_merged = {}    # {old_b_id: new_id}

    # 先导入 A 的所有类别
    for old_id, name in sorted(classes_a.items()):
        new_id = len(merged)
        merged[new_id] = name
        name_to_merged[name] = new_id
        a_to_merged[old_id] = new_id

    # 处理 B 的类别
    for old_id, name in sorted(classes_b.items()):
        if name in name_to_merged:
            # 同名类别 → 映射到已有的合并 ID
            b_to_merged[old_id] = name_to_merged[name]
        else:
            if map_mode == "intersect":
                # 丢弃 B 中不匹配的类别
                continue
            # 新类别 → 追加
            new_id = len(merged)
            merged[new_id] = name
            name_to_merged[name] = new_id
            b_to_merged[old_id] = new_id

    return merged, b_to_merged, a_to_merged


# ══════════════════════════════════════════════════════════════
# 合并与输出
# ══════════════════════════════════════════════════════════════

def copy_with_remap(
    samples: list,
    src_dataset: str,
    dst_dataset: str,
    class_mapping: dict,
    dataset_label: str,
    target_split: str = None,
    filter_class_ids: set = None,
):
    """复制样本到目标数据集，同时重映射类别 ID"""
    copied = 0
    for img_path, lbl_path, split, stem, ext in samples:
        out_split = target_split if target_split else split
        out_name = f"{dataset_label}_{stem}{ext}"
        out_stem = f"{dataset_label}_{stem}"

        # 读取并过滤标注
        entries = read_label(lbl_path, filter_class_ids)
        if not entries:
            continue  # 过滤后无标注，跳过该图片

        # 重映射
        remapped = [
            (class_mapping.get(cls_id, cls_id), x, y, w, h)
            for cls_id, x, y, w, h in entries
        ]

        img_dst = os.path.join(dst_dataset, "images", out_split, out_name)
        lbl_dst = os.path.join(dst_dataset, "labels", out_split, f"{out_stem}.txt")
        os.makedirs(os.path.dirname(img_dst), exist_ok=True)
        os.makedirs(os.path.dirname(lbl_dst), exist_ok=True)

        try:
            if os.path.exists(img_dst):
                os.remove(img_dst)
            os.link(img_path, img_dst)
        except (OSError, PermissionError):
            shutil.copy2(img_path, img_dst)

        write_label(lbl_dst, remapped)
        copied += 1
    return copied


def direct_merge(
    dataset_a: str,
    dataset_b: str,
    output_dir: str,
    merged_classes: dict,
    a_to_merged: dict,
    b_to_merged: dict,
):
    """直接合并：保持原有 split 分配"""
    samples_a = collect_samples(dataset_a)
    samples_b = collect_samples(dataset_b)

    total = 0
    for split in ["train", "val", "test"]:
        sa = [s for s in samples_a if s[2] == split]
        sb = [s for s in samples_b if s[2] == split]
        if sa:
            n = copy_with_remap(sa, dataset_a, output_dir, a_to_merged, "a", split)
            total += n
        if sb:
            n = copy_with_remap(sb, dataset_b, output_dir, b_to_merged, "b", split)
            total += n

    return total


def merge_with_resplit(
    dataset_a: str,
    dataset_b: str,
    output_dir: str,
    merged_classes: dict,
    a_to_merged: dict,
    b_to_merged: dict,
    ratios: list,
    split_names: list,
    seed: int,
    b_filter_class_ids: set = None,
):
    """合并后重新随机划分"""
    samples_a = collect_samples(dataset_a)
    samples_b = collect_samples(dataset_b)

    # 所有样本统一标记
    all_samples = []
    for img_path, lbl_path, split, stem, ext in samples_a:
        all_samples.append((img_path, lbl_path, stem, ext, "a", a_to_merged, None))
    for img_path, lbl_path, split, stem, ext in samples_b:
        all_samples.append((img_path, lbl_path, stem, ext, "b", b_to_merged, b_filter_class_ids))

    # 随机打乱
    rng = random.Random(seed)
    rng.shuffle(all_samples)

    # 按比例分配
    n = len(all_samples)
    cumsum = 0
    total = 0
    for i, (ratio, name) in enumerate(zip(ratios, split_names)):
        if i == len(split_names) - 1:
            count = n - cumsum
        else:
            count = max(1, int(n * ratio))
        count = min(count, n - cumsum)

        batch = all_samples[cumsum : cumsum + count]
        for item in batch:
            img_path, lbl_path, stem, ext, dataset_label, class_map, filter_ids = item
            # 读取并过滤标注
            entries = read_label(lbl_path, filter_ids)
            if not entries:
                continue  # 过滤后无标注，跳过

            out_name = f"{dataset_label}_{stem}{ext}"
            out_stem = f"{dataset_label}_{stem}"
            img_dst = os.path.join(output_dir, "images", name, out_name)
            lbl_dst = os.path.join(output_dir, "labels", name, f"{out_stem}.txt")
            os.makedirs(os.path.dirname(img_dst), exist_ok=True)
            os.makedirs(os.path.dirname(lbl_dst), exist_ok=True)

            try:
                if os.path.exists(img_dst):
                    os.remove(img_dst)
                os.link(img_path, img_dst)
            except (OSError, PermissionError):
                shutil.copy2(img_path, img_dst)

            remapped = [
                (class_map.get(cls_id, cls_id), x, y, w, h)
                for cls_id, x, y, w, h in entries
            ]
            write_label(lbl_dst, remapped)
            total += 1

        cumsum += count

    return total


def write_data_yaml(output_dir: str, merged_classes: dict, split_names: list):
    """生成合并后的 data.yaml"""
    abs_path = os.path.abspath(output_dir)

    lines = [f"path: {abs_path}", ""]
    for name in split_names:
        lines.append(f"{name}: images/{name}")
    lines.append("")
    lines.append(f"nc: {len(merged_classes)}")
    lines.append("names:")
    for idx in sorted(merged_classes.keys()):
        lines.append(f"  {idx}: {merged_classes[idx]}")

    yaml_path = os.path.join(output_dir, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def print_merge_report(
    info_a: dict, info_b: dict, merged_classes: dict,
    a_to_merged: dict, b_to_merged: dict, map_mode: str,
):
    """打印合并报告"""
    classes_a = info_a["class_names"]
    classes_b = info_b["class_names"]

    print(f"\n{'='*60}")
    print("  数据集合并报告")
    print(f"{'='*60}")

    print(f"\n  A 类别 ({len(classes_a)}): {dict(sorted(classes_a.items()))}")
    print(f"  B 类别 ({len(classes_b)}): {dict(sorted(classes_b.items()))}")
    print(f"  合并模式: {map_mode}")
    print(f"  合并后类别 ({len(merged_classes)}): {dict(sorted(merged_classes.items()))}")

    # 显示映射变化
    changed_b = {
        old: new for old, new in b_to_merged.items()
        if old != new
    }
    if changed_b:
        print(f"\n  B 类别 ID 变化: {changed_b}")

    print(f"{'='*60}\n")


# ══════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="YOLO 数据集合并工具 — 合并两个 YOLO 数据集并可选重划分",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 直接合并（保持原有 split）
  python tools/merge_datasets.py -a datasets/a -b datasets/b -o datasets/merged

  # 合并 + 重新划分
  python tools/merge_datasets.py -a datasets/a -b datasets/b -o datasets/merged --resplit

  # 只保留 A 的类别体系
  python tools/merge_datasets.py -a datasets/a -b datasets/b -o datasets/merged --map-mode intersect

  # 只将 B 中 pitted、rolled 两个类别并入 A
  python tools/merge_datasets.py -a datasets/base -b datasets/extra \\
      -o datasets/merged --classes pitted rolled
        """,
    )

    parser.add_argument("-a", type=str, required=True, help="数据集 A 目录")
    parser.add_argument("-b", type=str, required=True, help="数据集 B 目录")
    parser.add_argument("-o", "--output", type=str, required=True, help="输出目录")
    parser.add_argument(
        "--map-mode", type=str, default="union",
        choices=["union", "intersect"],
        help="类别映射策略（默认: union）",
    )
    parser.add_argument("--resplit", action="store_true", help="合并后重新随机划分")
    parser.add_argument(
        "--ratio", "-r", type=float, nargs="+", default=[0.7, 0.2, 0.1],
        help="重划分比例（默认: 0.7 0.2 0.1）",
    )
    parser.add_argument(
        "--splits", "-s", nargs="+", default=["train", "val", "test"],
        help="split 名称列表（默认: train val test）",
    )
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认: 42）")
    parser.add_argument(
        "--classes", "-c", nargs="+", default=None,
        help="只合并 B 中指定类别（如 --classes pitted scratches），其他类别丢弃",
    )

    args = parser.parse_args()

    # 校验
    for path, label in [(args.a, "A"), (args.b, "B")]:
        if not os.path.exists(path):
            print(f"[错误] 数据集 {label} 不存在: {path}")
            sys.exit(1)
        if not os.path.exists(os.path.join(path, "data.yaml")):
            print(f"[警告] 数据集 {label} 缺少 data.yaml")

    if args.resplit and len(args.ratio) != len(args.splits):
        print(f"[错误] --ratio ({len(args.ratio)}) 与 --splits ({len(args.splits)}) 数量不一致")
        sys.exit(1)

    # 加载数据集信息
    info_a = load_dataset_info(args.a)
    info_b = load_dataset_info(args.b)

    if not info_a["class_names"] and not info_b["class_names"]:
        print("[错误] 两个数据集都没有 data.yaml，无法合并")
        sys.exit(1)

    # 构建类别映射
    merged_classes, b_to_merged, a_to_merged = build_class_mapping(
        info_a["class_names"],
        info_b["class_names"],
        args.map_mode,
    )

    # 解析 B 的类别筛选
    b_filter_ids = None
    if args.classes:
        b_name_to_id = {name: cid for cid, name in info_b["class_names"].items()}
        b_filter_ids = set()
        for cls_name in args.classes:
            if cls_name in b_name_to_id:
                b_filter_ids.add(b_name_to_id[cls_name])
            else:
                print(f"[警告] B 中无类别 '{cls_name}'，已忽略")
        if not b_filter_ids:
            print("[错误] 指定类别均不在 B 中")
            sys.exit(1)
        print(f"\n  B 类别筛选: {args.classes} → class_id={b_filter_ids}")
        print(f"  筛选后只保留含这些类别的图片，标注中其他类别将被丢弃\n")

    print_merge_report(info_a, info_b, merged_classes, a_to_merged, b_to_merged, args.map_mode)

    # 执行合并
    split_names = args.splits if args.resplit else ["train", "val", "test"]

    if args.resplit:
        total = merge_with_resplit(
            args.a, args.b, args.output,
            merged_classes, a_to_merged, b_to_merged,
            args.ratio, split_names, args.seed,
            b_filter_class_ids=b_filter_ids,
        )
    elif b_filter_ids:
        # 直接合并 + 类别筛选
        samples_a = collect_samples(args.a)
        samples_b = collect_samples(args.b)
        total = 0
        for split in ["train", "val", "test"]:
            sa = [s for s in samples_a if s[2] == split]
            sb = [s for s in samples_b if s[2] == split]
            if sa:
                n = copy_with_remap(sa, args.a, args.output, a_to_merged, "a", split)
                total += n
            if sb:
                n = copy_with_remap(sb, args.b, args.output, b_to_merged, "b", split, b_filter_ids)
                total += n
    else:
        total = direct_merge(
            args.a, args.b, args.output,
            merged_classes, a_to_merged, b_to_merged,
        )

    # 生成 data.yaml
    write_data_yaml(args.output, merged_classes, split_names)

    print(f"合并完成: {total} 张图像 → {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
