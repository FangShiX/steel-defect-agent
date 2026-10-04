#!/usr/bin/env python3
"""
YOLO 数据集标签修复工具（通用版）

功能：
    1. 检测标签中超出 nc 范围的 class_id
    2. 通过 --remap 自定义类别 ID 映射合并
    3. 自动检测 data.yaml 中拼写相似的可疑类别名
    4. 修复后自动更新 data.yaml，移除空类别并重新编号
    5. 支持 --dry-run 预览模式，不实际修改文件

常见场景：
    - Roboflow 导出数据集中 scraches/scratches 拼写问题
    - 合并不同来源数据集后 class_id 偏移
    - 清理标签中意外出现的无效 class_id

使用方式：
    cd backend

    # 预览模式：检测问题但不修改
    python tools/fix_scratches.py /tmp/dataset --dry-run

    # 自动检测并交互确认修复
    python tools/fix_scratches.py /tmp/dataset

    # 指定类别 ID 重映射（old_id:new_id）
    python tools/fix_scratches.py /tmp/dataset --remap 5:6 6:5

    # 丢弃指定类别（移除该类别所有标注）
    python tools/fix_scratches.py /tmp/dataset --drop 6

    # 强制重新编号（移除 gaps）
    python tools/fix_scratches.py /tmp/dataset --renumber

    # 自动模式（不交互确认）
    python tools/fix_scratches.py /tmp/dataset --yes
"""

import argparse
import os
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


def similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0~1)"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def load_data_yaml(dataset_dir: Path) -> tuple:
    """加载 data.yaml，返回 (nc, names_dict, raw_lines)"""
    yaml_path = dataset_dir / "data.yaml"
    if not yaml_path.exists():
        return 0, {}, []

    content = yaml_path.read_text(encoding="utf-8")
    raw_lines = content.split("\n")

    nc = 0
    names = {}
    in_names = False

    for line in raw_lines:
        stripped = line.strip()
        if stripped.startswith("nc:"):
            try:
                nc = int(stripped.split(":")[1].strip())
            except ValueError:
                pass
        elif stripped.startswith("names:"):
            in_names = True
            continue
        elif in_names and stripped:
            if stripped[0].isdigit():
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    try:
                        names[int(parts[0].strip())] = parts[1].strip()
                    except ValueError:
                        pass
            elif not stripped.startswith(" "):
                in_names = False

    return nc, names, raw_lines


def scan_labels(dataset_dir: Path) -> dict:
    """扫描所有标注文件，返回 {class_id: count}"""
    usage = defaultdict(int)
    labels_dir = dataset_dir / "labels"
    if not labels_dir.exists():
        return usage

    for txt_file in sorted(labels_dir.rglob("*.txt")):
        content = txt_file.read_text(encoding="utf-8").strip()
        if not content:
            continue
        for line in content.split("\n"):
            parts = line.strip().split()
            if not parts:
                continue
            try:
                usage[int(parts[0])] += 1
            except ValueError:
                pass
    return usage


def detect_suspicious_names(names: dict, threshold: float = 0.6) -> list:
    """
    检测 data.yaml 中拼写相似的可疑类别名对
    返回 [(id1, name1, id2, name2, similarity), ...]
    """
    suspicious = []
    items = sorted(names.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            id1, n1 = items[i]
            id2, n2 = items[j]
            sim = similarity(n1, n2)
            if sim > threshold and sim < 1.0:
                suspicious.append((id1, n1, id2, n2, sim))
    return suspicious


def fix_labels(
    dataset_dir: Path,
    remap: dict = None,
    drop_ids: set = None,
    dry_run: bool = False,
) -> dict:
    """
    修复所有标注文件中的类别 ID

    Args:
        dataset_dir: 数据集目录
        remap: {old_id: new_id} 映射
        drop_ids: 要删除的 class_id 集合
        dry_run: 仅预览不修改

    Returns:
        {old_class_id: (before_count, after_count)}
    """
    if remap is None:
        remap = {}
    if drop_ids is None:
        drop_ids = set()

    # 合并 drop 到 remap（drop = 删除该行）
    stats = defaultdict(lambda: [0, 0])  # {old_id: [before, after]}

    labels_dir = dataset_dir / "labels"
    if not labels_dir.exists():
        return stats

    for txt_file in sorted(labels_dir.rglob("*.txt")):
        content = txt_file.read_text(encoding="utf-8").strip()
        if not content:
            continue

        new_lines = []
        file_changed = False

        for line in content.split("\n"):
            parts = line.strip().split()
            if len(parts) != 5:
                new_lines.append(line)
                continue

            try:
                class_id = int(parts[0])
            except ValueError:
                new_lines.append(line)
                continue

            stats[class_id][0] += 1

            if class_id in drop_ids:
                file_changed = True
                continue  # 丢弃该行

            if class_id in remap:
                parts[0] = str(remap[class_id])
                class_id = remap[class_id]
                file_changed = True

            stats[class_id][1] += 1
            new_lines.append(" ".join(parts))

        if file_changed and not dry_run:
            txt_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return dict(stats)


def renumber_labels(dataset_dir: Path, old_to_new: dict, dry_run: bool = False):
    """按映射关系对所有标注文件重新编号"""
    labels_dir = dataset_dir / "labels"
    if not labels_dir.exists():
        return

    for txt_file in sorted(labels_dir.rglob("*.txt")):
        content = txt_file.read_text(encoding="utf-8").strip()
        if not content:
            continue

        new_lines = []
        changed = False
        for line in content.split("\n"):
            parts = line.strip().split()
            if len(parts) != 5:
                new_lines.append(line)
                continue
            try:
                cid = int(parts[0])
                if cid in old_to_new:
                    parts[0] = str(old_to_new[cid])
                    changed = True
            except ValueError:
                pass
            new_lines.append(" ".join(parts))

        if changed and not dry_run:
            txt_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def write_data_yaml(dataset_dir: Path, nc: int, names: dict, dry_run: bool = False):
    """写入新的 data.yaml"""
    if dry_run:
        return

    yaml_path = dataset_dir / "data.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(f"path: .\n")
        f.write(f"train: images/train\n")
        f.write(f"val: images/val\n")
        f.write(f"test: images/test\n")
        f.write(f"\n")
        f.write(f"nc: {nc}\n")
        f.write(f"names:\n")
        for idx in sorted(names.keys()):
            f.write(f"  {idx}: {names[idx]}\n")


def print_report(issues: list, label_usage: dict, nc: int, names: dict):
    """打印检测报告"""
    print(f"\n{'='*60}")
    print("  标签诊断报告")
    print(f"{'='*60}")
    print(f"  data.yaml: nc={nc}, 类别={dict(sorted(names.items()))}")

    print(f"\n  实际标签中的 class_id 分布:")
    for cid in sorted(label_usage.keys()):
        name = names.get(cid, f"<未知>")
        flag = ""
        if cid >= nc:
            flag = "  ← 超出范围!"
        print(f"    class_id={cid:2d} ({name:20s}): {label_usage[cid]:6d} 个{flag}")

    if issues:
        print(f"\n  发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"    {issue}")
    else:
        print(f"\n  ✓ 未发现问题")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="YOLO 数据集标签修复工具（通用版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 预览模式
  python tools/fix_scratches.py datasets/ssdd --dry-run

  # 指定类别映射
  python tools/fix_scratches.py datasets/ssdd --remap 5:6 6:5

  # 丢弃某个 class_id
  python tools/fix_scratches.py datasets/ssdd --drop 6

  # 自动模式
  python tools/fix_scratches.py datasets/ssdd --yes
        """,
    )

    parser.add_argument("dataset", type=str, help="数据集目录路径")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不修改文件")
    parser.add_argument(
        "--remap", nargs="*", default=[],
        help="类别 ID 重映射，格式 old_id:new_id（如 --remap 5:6 6:5）",
    )
    parser.add_argument("--drop", nargs="*", type=int, default=[], help="丢弃的 class_id 列表")
    parser.add_argument("--renumber", action="store_true", help="强制重新连续编号（移除 gaps）")
    parser.add_argument("--similarity", type=float, default=0.6,
                       help="可疑名称检测的相似度阈值（默认: 0.6）")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认，直接执行")

    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    if not dataset_dir.exists():
        print(f"[错误] 数据集目录不存在: {dataset_dir}")
        sys.exit(1)

    # ── 加载 data.yaml ──
    nc, names, raw_lines = load_data_yaml(dataset_dir)
    if not names:
        print("[错误] data.yaml 中无类别定义")
        sys.exit(1)

    # ── 扫描标签 ──
    label_usage = scan_labels(dataset_dir)
    if not label_usage:
        print("[错误] 未找到任何标注文件")
        sys.exit(1)

    # ── 检测问题 ──
    issues = []

    # 1. 超出范围的 class_id
    out_of_range = [cid for cid in label_usage if cid >= nc]
    if out_of_range:
        issues.append(
            f"class_id 超出范围 (nc={nc}): {sorted(out_of_range)}，"
            f"共 {sum(label_usage[c] for c in out_of_range)} 个标注"
        )

    # 2. 未使用的 class_id（data.yaml 中定义了但标签中没出现）
    unused = [cid for cid in sorted(names.keys()) if cid not in label_usage]
    if unused:
        issues.append(f"data.yaml 中已定义但标签中未使用: {unused}")

    # 3. 相似名称检测
    suspicious = detect_suspicious_names(names, args.similarity)
    if suspicious:
        for id1, n1, id2, n2, sim in suspicious:
            issues.append(f"可疑相似名称: [{id1}]{n1} ↔ [{id2}]{n2} (相似度 {sim:.0%})")

    # ── 打印报告 ──
    print_report(issues, label_usage, nc, names)

    if not issues and not args.remap and not args.drop and not args.renumber:
        print("✓ 数据集标签正常，无需修复")
        return

    if args.dry_run:
        if args.remap:
            print(f"[预览] 将应用重映射: {args.remap}")
        if args.drop:
            print(f"[预览] 将丢弃 class_id: {args.drop}")
        if args.renumber:
            print(f"[预览] 将重新连续编号")
        print("[预览] 未修改任何文件，去掉 --dry-run 以实际执行")
        return

    # ── 确认 ──
    if not args.yes:
        print("\n将要执行以下操作:")
        if args.remap:
            print(f"  重映射: {args.remap}")
        if args.drop:
            print(f"  丢弃 class_id: {args.drop}")
        if args.renumber:
            print(f"  重新连续编号")
        resp = input("确认执行? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("已取消")
            return

    # ── 构建 remap 字典 ──
    remap = {}
    for item in args.remap:
        try:
            old, new = item.split(":")
            remap[int(old)] = int(new)
        except ValueError:
            print(f"[警告] 忽略无效映射: {item}")

    drop_ids = set(args.drop)

    # ── 执行修复 ──
    print("\n正在修复标签...")
    stats = fix_labels(dataset_dir, remap, drop_ids)

    # 统计变化
    total_before = sum(v[0] for v in stats.values())
    total_after = sum(v[1] for v in stats.values())
    print(f"  标注总数: {total_before} → {total_after}")

    for cid in sorted(stats.keys()):
        before, after = stats[cid]
        if before != after:
            print(f"  class_id={cid}: {before} → {after}")

    # ── 重建 data.yaml ──
    # 重新扫描以获取修复后的实际 class_id 使用情况
    final_usage = scan_labels(dataset_dir)
    used_ids = sorted(final_usage.keys())

    if args.renumber or drop_ids or remap:
        # 构建新的连续编号映射
        old_to_new = {}
        new_names = {}
        for new_id, old_id in enumerate(used_ids):
            old_to_new[old_id] = new_id
            new_names[new_id] = names.get(old_id, f"class_{old_id}")

        nc_new = len(new_names)

        if old_to_new != {k: k for k in old_to_new}:
            print(f"\n重新编号: {old_to_new}")
            renumber_labels(dataset_dir, old_to_new)

        print(f"\n更新 data.yaml: nc={nc_new}")
        print(f"  类别: {dict(sorted(new_names.items()))}")
        write_data_yaml(dataset_dir, nc_new, new_names)
    else:
        # 只更新 nc
        nc_new = len(names)
        write_data_yaml(dataset_dir, nc_new, names)

    print("\n修复完成")


if __name__ == "__main__":
    main()
