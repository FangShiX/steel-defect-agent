"""
LabelMe JSON → YOLO TXT 数据集格式转换脚本

功能：
    将 LabelMe 格式的 JSON 标注文件转换为 YOLO 格式的 TXT 标注文件
    支持完整的数据集处理流程：转换 + 划分 + yaml生成

LabelMe 格式说明：
    LabelMe 标注工具生成的 JSON 文件包含：
    - imagePath: 图像文件路径
    - imageWidth: 图像宽度
    - imageHeight: 图像高度
    - shapes: 标注形状列表，每个形状包含：
        - label: 类别名称
        - shape_type: 形状类型（rectangle/polygon/circle等）
        - points: 坐标点列表

    本脚本只处理 shape_type 为 "rectangle" 的标注
    LabelMe rectangle points: [[x1, y1], [x2, y2]]（两个对角点，像素坐标）
    YOLO bbox 格式：[x_center, y_center, width, height]（归一化坐标）

使用方式：
    cd backend
    python tools/convert_labelme.py

配置说明（修改下方配置区域）：
    - LABELME_JSON_DIR: LabelMe JSON 文件所在目录
    - CLASS_MAPPING: 类别名称到数字ID的映射
    - OUTPUT_DIR: YOLO 格式输出目录

输出目录结构：
    yolo_dataset/
    ├── data.yaml
    ├── images/
    │   ├── train/
    │   ├── val/
    │   └── test/
    └── labels/
        ├── train/
        ├── val/
        └── test/
"""

import os
import sys
import shutil
import random

# tools/ → backend/ → project_root/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 配置区域（根据你的数据集修改）────────────────────
# LabelMe JSON 文件所在目录
LABELME_JSON_DIR = os.path.join(
    PROJECT_ROOT, "datasets/ssdd/raw/labelme_annotations"
)

# 原始图片目录（与 LabelMe JSON 中 imagePath 对应的图片位置）
# 如果 imagePath 是相对路径，图片应放在此目录下
RAW_IMAGE_DIR = os.path.join(PROJECT_ROOT, "datasets/ssdd/raw/images")

# YOLO 格式输出目录
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "datasets/ssdd/yolo_dataset")

# 类别映射（格式：{类别名称: 类别ID}）
CLASS_MAPPING = {
    "aircraft": 0,
    "oiltank": 1,
    "overpass": 2,
    "playground": 3,
}

# 数据集划分比例
TRAIN_RATIO = 0.8
VAL_RATIO = 0.1
# TEST_RATIO = 0.1（剩余部分）

# 随机种子（保证划分结果可重复）
RANDOM_SEED = 42

# 支持的图片扩展名
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def labelme_to_yolo(json_dir: str, output_dir: str, class_mapping: dict) -> dict:
    """
    将 LabelMe JSON 格式转换为 YOLO TXT 格式

    参数：
        json_dir: LabelMe JSON 文件所在目录
        output_dir: YOLO TXT 输出目录
        class_mapping: 类别映射字典 {类别名称: 类别ID}

    返回：
        转换统计信息字典 {"total": 总数, "converted": 成功数, "skipped": 跳过数, "errors": 错误列表, "image_files": 图像文件列表}

    转换流程：
        1. 遍历 json_dir 下所有 .json 文件
        2. 解析每个 JSON 获取图像尺寸和标注形状
        3. 只处理 shape_type 为 "rectangle" 的标注
        4. 从 points 中提取边界框（取最小外接矩形）
        5. 转换为 YOLO 归一化坐标
        6. 每张图像输出一个 .txt 文件
    """
    import json
    from pathlib import Path

    os.makedirs(output_dir, exist_ok=True)
    stats = {"total": 0, "converted": 0, "skipped": 0, "errors": [], "image_files": []}

    # 获取所有 JSON 文件
    json_files = list(Path(json_dir).glob("*.json"))
    if not json_files:
        print(f"  [警告] 目录 {json_dir} 下未找到 .json 文件")
        return stats

    print(f"  LabelMe 转换开始：{len(json_files)} 个 JSON 文件")

    # 遍历每个 JSON 文件
    for json_file in json_files:
        stats["total"] += 1
        try:
            # 读取 JSON 文件
            with open(json_file, "r", encoding="utf-8") as f:
                labelme_data = json.load(f)

            # 获取图像尺寸
            img_width = labelme_data.get("imageWidth", 0)
            img_height = labelme_data.get("imageHeight", 0)

            # 检查图像尺寸有效性
            if img_width <= 0 or img_height <= 0:
                print(f"  [警告] JSON {json_file.name} 图像尺寸无效，跳过")
                stats["skipped"] += 1
                continue

            # 获取图像文件名
            image_path = labelme_data.get("imagePath", "")
            image_filename = os.path.basename(image_path)
            stats["image_files"].append(image_filename)

            # 转换标注
            yolo_lines = []
            for shape in labelme_data.get("shapes", []):
                # 只处理矩形标注（其他形状如 polygon 不支持）
                if shape.get("shape_type") != "rectangle":
                    continue

                # 获取类别名称
                class_name = shape.get("label", "").strip()
                if class_name not in class_mapping:
                    print(f"  [警告] JSON {json_file.name} 中类别 '{class_name}' 不在映射表中，跳过")
                    continue

                class_id = class_mapping[class_name]
                points = shape.get("points", [])

                # 检查点数量
                if len(points) < 2:
                    continue

                # 从 points 中提取最小和最大坐标
                # 处理两种情况：
                # 1. 只有 2 个点（左上角和右下角）
                # 2. 多个点（取最小外接矩形）
                all_x = [p[0] for p in points]
                all_y = [p[1] for p in points]
                xmin = min(all_x)
                ymin = min(all_y)
                xmax = max(all_x)
                ymax = max(all_y)

                # 边界值裁剪：确保坐标不超出图像范围
                xmin = max(0, min(xmin, img_width))
                ymin = max(0, min(ymin, img_height))
                xmax = max(0, min(xmax, img_width))
                ymax = max(0, min(ymax, img_height))

                # 过滤无效框（宽或高为 0）
                if xmax <= xmin or ymax <= ymin:
                    continue

                # 像素坐标 → YOLO 归一化坐标
                x_center = (xmin + xmax) / 2.0 / img_width
                y_center = (ymin + ymax) / 2.0 / img_height
                width = (xmax - xmin) / img_width
                height = (ymax - ymin) / img_height

                yolo_lines.append(
                    f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
                )

            # 保存 YOLO 标注文件
            txt_file = Path(output_dir) / f"{json_file.stem}.txt"
            with open(txt_file, "w", encoding="utf-8") as f:
                f.write("\n".join(yolo_lines))

            stats["converted"] += 1

        except json.JSONDecodeError as e:
            print(f"  [错误] JSON 解析失败 {json_file.name}: {str(e)}")
            stats["errors"].append(str(json_file.name))
            stats["skipped"] += 1
        except Exception as e:
            print(f"  [错误] LabelMe 转换异常 {json_file.name}: {str(e)}")
            stats["errors"].append(str(json_file.name))
            stats["skipped"] += 1

    print(f"  转换结果: 总计 {stats['total']}, 成功 {stats['converted']}, 跳过 {stats['skipped']}")
    return stats


def split_dataset(image_files, temp_label_dir):
    """
    按比例划分数据集并复制文件

    参数：
        image_files: 图像文件名列表
        temp_label_dir: 临时标注目录

    返回：
        None
    """
    # 设置随机种子，保证划分结果可重复
    random.seed(RANDOM_SEED)
    random.shuffle(image_files)

    # 计算划分索引
    total = len(image_files)
    train_end = int(total * TRAIN_RATIO)
    val_end = train_end + int(total * VAL_RATIO)

    splits = {
        "train": image_files[:train_end],
        "val": image_files[train_end:val_end],
        "test": image_files[val_end:],
    }

    # 复制图片和标注到对应目录
    for split_name, files in splits.items():
        img_out = os.path.join(OUTPUT_DIR, "images", split_name)
        lbl_out = os.path.join(OUTPUT_DIR, "labels", split_name)
        os.makedirs(img_out, exist_ok=True)
        os.makedirs(lbl_out, exist_ok=True)

        for filename in files:
            # 复制图片
            src_image = os.path.join(RAW_IMAGE_DIR, filename)
            if os.path.exists(src_image):
                dst_image = os.path.join(img_out, filename)
                shutil.copy2(src_image, dst_image)

                # 复制标注（如果存在）
                basename = os.path.splitext(filename)[0]
                label_file = os.path.join(temp_label_dir, f"{basename}.txt")
                if os.path.exists(label_file):
                    shutil.copy2(label_file, os.path.join(lbl_out, f"{basename}.txt"))
                else:
                    open(os.path.join(lbl_out, f"{basename}.txt"), "w").close()
            else:
                # 图片不存在，尝试从 JSON 目录查找
                for ext in IMAGE_EXTS:
                    alt_image_path = os.path.join(LABELME_JSON_DIR, basename + ext)
                    if os.path.exists(alt_image_path):
                        shutil.copy2(alt_image_path, os.path.join(img_out, filename))
                        label_file = os.path.join(temp_label_dir, f"{basename}.txt")
                        if os.path.exists(label_file):
                            shutil.copy2(label_file, os.path.join(lbl_out, f"{basename}.txt"))
                        else:
                            open(os.path.join(lbl_out, f"{basename}.txt"), "w").close()
                        break

        print(f"  {split_name}: {len(files)} 个")


def generate_yaml():
    """生成 YOLO 数据集配置文件"""
    # 获取类别列表
    class_names = sorted(CLASS_MAPPING.keys(), key=lambda x: CLASS_MAPPING[x])

    # 构建 YAML 内容
    yaml_content = f"""path: ./{os.path.basename(OUTPUT_DIR)}
train: images/train
val: images/val
test: images/test
nc: {len(class_names)}
names:
"""
    for i, name in enumerate(class_names):
        yaml_content += f"  {i}: {name}\n"

    # 写入 YAML 文件
    yaml_path = os.path.join(OUTPUT_DIR, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    print(f"  配置文件已生成: {yaml_path}")


def main():
    """主函数：执行完整的 LabelMe → YOLO 转换流程"""
    print("=" * 70)
    print("      LabelMe → YOLO 数据集转换流程")
    print("=" * 70)

    # 检查 LabelMe JSON 目录是否存在
    if not os.path.exists(LABELME_JSON_DIR):
        print(f"\n[错误] LabelMe JSON 目录不存在: {LABELME_JSON_DIR}")
        print("请检查配置区域中的 LABELME_JSON_DIR 路径")
        sys.exit(1)

    # 检查原始图片目录是否存在
    if not os.path.exists(RAW_IMAGE_DIR):
        print(f"\n[错误] 原始图片目录不存在: {RAW_IMAGE_DIR}")
        print("请检查配置区域中的 RAW_IMAGE_DIR 路径")
        sys.exit(1)

    # ── 步骤1：LabelMe转YOLO格式 ──
    print("\n[1] LabelMe转YOLO格式")

    # 创建临时标注目录（用于存放转换后的TXT文件）
    temp_label_dir = os.path.join(OUTPUT_DIR, "temp_labels")
    os.makedirs(temp_label_dir, exist_ok=True)

    # 执行转换
    stats = labelme_to_yolo(LABELME_JSON_DIR, temp_label_dir, CLASS_MAPPING)

    if stats["total"] == 0:
        print("\n[错误] 未找到任何 JSON 文件，请检查 LABELME_JSON_DIR 目录")
        shutil.rmtree(temp_label_dir, ignore_errors=True)
        sys.exit(1)

    # ── 步骤2：划分数据集 ──
    print("\n[2] 划分数据集")
    split_dataset(stats["image_files"], temp_label_dir)

    # ── 步骤3：生成data.yaml ──
    print("\n[3] 生成data.yaml")
    generate_yaml()

    # 清理临时目录
    shutil.rmtree(temp_label_dir, ignore_errors=True)

    # 输出完成信息
    print("\n" + "=" * 70)
    print(f"  处理完成！输出目录: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
