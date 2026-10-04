"""YOLO 检测配置。"""

# 检测模型默认配置
DEFAULT_CONF_THRESHOLD = 0.25
DEFAULT_IOU_THRESHOLD = 0.45
DEFAULT_IMAGE_SIZE = 640

# Keep this in sync with the browser upload control.  TIFF was supported by the
# existing UI, while WebP is useful for modern browser uploads.
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_BATCH_SIZE = 20

MAX_ZIP_SIZE = 50 * 1024 * 1024
MAX_ZIP_EXTRACTED_SIZE = 200 * 1024 * 1024

ALLOWED_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}
MAX_VIDEO_SIZE = 50 * 1024 * 1024
DEFAULT_VIDEO_FRAME_SAMPLE_RATE = 5
MAX_VIDEO_FRAMES = 1000
DEFAULT_VIDEO_MAX_FRAMES = MAX_VIDEO_FRAMES
VIDEO_PROGRESS_TTL = 3600
