# 多格式训练数据集导入

`POST /api/training/datasets/upload` 接受 ZIP 格式的 YOLO、VOC、COCO 和 LabelMe 目标检测数据集，并统一输出 YOLO 检测目录。

## 请求字段

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `file` | 必填 | 最大 500 MB 的 ZIP |
| `dataset_format` | `auto` | `auto`、`yolo`、`voc`、`coco` 或 `labelme` |
| `train_ratio` | `0.8` | 没有显式划分元数据时的训练集比例 |
| `val_ratio` | `0.1` | 验证集比例，必须大于 0 |
| `test_ratio` | `0.1` | 测试集比例，可为 0 |
| `split_seed` | `42` | 确定性哈希划分种子 |

三个比例之和必须为 1。转换成功响应中的 `conversion` 包含源格式、类别、各 split 图片数、图片总数和标注框总数。

## 内容驱动发现

导入器不根据 `images`、`annotations`、`train_images` 等任意目录名判断数据含义：

- VOC 使用 XML 的 `path` 或 `filename` 引用图片。
- COCO 使用 `images[].file_name` 和 ID 关系。
- LabelMe 使用 `imagePath`。
- YOLO 使用 `data.yaml` 定位 split，再以唯一文件 stem 配对 TXT 标签。

引用无效时，仅允许唯一文件名或 stem 匹配。一对多时返回 `AMBIGUOUS_IMAGE`、`AMBIGUOUS_LABEL` 等结构化错误，不猜测目录用途。所有引用必须位于解压目录内。

## 标准化结果

```text
data.yaml
images/{train,val,test}/
labels/{train,val,test}/
```

转换在隐藏暂存目录中执行。格式、类别、坐标和配对校验全部通过后才原子发布并登记到数据库；失败时清理暂存内容。

## 高级训练配置

`POST /api/training/start` 新增 `train_config`。该对象采用严格白名单，未知字段会返回 422，不能覆盖 `data`、`project`、`name` 等受保护参数。支持学习率调度、warmup、早停、AMP、缓存、确定性、多尺度及常见几何/颜色增强参数。完整配置保存在 `training_tasks.train_config`，任务查询和重试会返回并复用它。
