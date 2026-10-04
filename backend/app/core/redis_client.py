"""
Redis 客户端封装
用于 Agent 短期会话上下文、视频检测/训练的实时进度、以及其他临时任务状态。
这里存的都是"可以丢"的短生命周期数据——最终结果仍然落库到 PostgreSQL（对应任务文档步骤 12）。
"""
import json
import threading

import redis

from app.config.settings import settings

# 短生命周期数据默认过期时间（秒）
DEFAULT_TTL = 3600  # 1 小时


class RedisClient:
    """Redis 客户端封装，全局单例复用一个连接池"""

    def __init__(self):
        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._memory_cache = {}
        self._memory_lock = threading.Lock()

    def ping(self) -> bool:
        try:
            return self.client.ping()
        except redis.RedisError:
            return False

    # ── 通用 key-value（JSON 序列化） ────────────────────

    def set_json(self, key: str, value: dict, ttl: int = DEFAULT_TTL) -> None:
        serialized = json.dumps(value, ensure_ascii=False)
        try:
            self.client.set(key, serialized, ex=ttl)
        except redis.RedisError:
            with self._memory_lock:
                self._memory_cache[key] = serialized

    def get_json(self, key: str) -> dict | None:
        try:
            raw = self.client.get(key)
        except redis.RedisError:
            raw = None
        if raw is None:
            with self._memory_lock:
                raw = self._memory_cache.get(key)
        return json.loads(raw) if raw else None

    def delete(self, key: str) -> None:
        try:
            self.client.delete(key)
        except redis.RedisError:
            pass
        with self._memory_lock:
            self._memory_cache.pop(key, None)

    def acquire_lock(self, key: str, token: str, ttl: int) -> bool:
        """Acquire a Redis-only distributed lock; never fall back to process memory."""
        try:
            return bool(self.client.set(key, token, nx=True, ex=ttl))
        except redis.RedisError:
            return False

    def release_lock(self, key: str, token: str) -> None:
        """Release only the lock held by this caller, preserving a renewed lock."""
        try:
            self.client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
                1, key, token,
            )
        except redis.RedisError:
            pass

    # ── 视频检测进度：video:progress:{task_id} ───────────

    def set_video_progress(self, task_id: int, current_frame: int, total_frames: int, ttl: int = DEFAULT_TTL) -> None:
        self.set_json(
            f"video:progress:{task_id}",
            {"current_frame": current_frame, "total_frames": total_frames,
             "percent": round(current_frame / total_frames * 100, 2) if total_frames else 0},
            ttl=ttl,
        )

    def get_video_progress(self, task_id: int) -> dict | None:
        return self.get_json(f"video:progress:{task_id}")

    def set_video_task(self, task_id: int, value: dict, ttl: int = DEFAULT_TTL) -> None:
        self.set_json(f"video_task:{task_id}", value, ttl=ttl)

    def get_video_task(self, task_id: int) -> dict | None:
        return self.get_json(f"video_task:{task_id}")

    # ── 训练实时进度：train:progress:{task_id}（比 training_metrics 表更细粒度，batch 级别）──

    def set_training_progress(self, task_id: int, current_batch: int, total_batches: int, loss: float | None = None, ttl: int = DEFAULT_TTL) -> None:
        self.set_json(
            f"train:progress:{task_id}",
            {"current_batch": current_batch, "total_batches": total_batches, "loss": loss},
            ttl=ttl,
        )

    def get_training_progress(self, task_id: int) -> dict | None:
        return self.get_json(f"train:progress:{task_id}")

    # ── Agent 短期会话上下文：chat:context:{session_id} ──

    def set_chat_context(self, session_id: int, messages: list[dict], ttl: int = DEFAULT_TTL) -> None:
        """
        存最近若干轮对话，供 Agent 拼接上下文用，不是聊天记录的权威存储
        （权威存储是 PostgreSQL 的 chat_messages 表）
        """
        self.set_json(f"chat:context:{session_id}", {"messages": messages}, ttl=ttl)

    def get_chat_context(self, session_id: int) -> list[dict]:
        data = self.get_json(f"chat:context:{session_id}")
        return data["messages"] if data else []


# 全局单例
redis_client = RedisClient()
