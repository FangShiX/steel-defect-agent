"""
Data Agent 工具 — 查询检测历史 / 统计数据

所有工具函数在 LangGraph 节点中被调用，需要 db session 和 user_id。
使用工具工厂模式：get_data_tools(db_session_factory) 返回绑定到当前请求的 tool 列表。
"""

import json
from datetime import datetime, timedelta

from langchain_core.tools import tool


def _make_data_tools(get_db, user_id: int):
    """创建绑定到当前用户和 DB 的 Data Agent 工具"""

    @tool
    def query_detection_history(limit: int = 10, days: int = 30) -> str:
        """
        查询最近的检测历史记录。用于用户询问"最近检测了多少"、"最近的检测结果"等问题。

        Args:
            limit: 返回的记录数量，默认 10
            days: 查询最近多少天，默认 30

        Returns:
            JSON 字符串，包含检测任务列表及其摘要
        """
        from app.database.session import SessionLocal
        from app.services.history_service import history_service

        db = SessionLocal()
        try:
            tasks, total = history_service.list_tasks(
                db=db,
                user_id=user_id,
                page=1,
                page_size=min(limit, 20),
            )
            result = []
            for t in tasks:
                result.append({
                    "id": t.id,
                    "task_type": t.task_type,
                    "status": t.status,
                    "total_images": t.total_images or 0,
                    "total_objects": t.total_objects or 0,
                    "created_at": t.created_at.isoformat() if t.created_at else "",
                    "scene_name": t.scene.display_name if t.scene else "",
                })
            return json.dumps({"count": len(result), "tasks": result}, ensure_ascii=False)
        finally:
            db.close()

    @tool
    def get_detection_statistics(days: int = 30) -> str:
        """
        获取检测统计数据。用于用户询问"检测统计"、"各类缺陷分布"、"检测趋势"等问题。

        Args:
            days: 统计最近多少天，默认 30

        Returns:
            JSON 字符串，包含 total_tasks, total_images, total_objects,
            avg_inference_time, class_distribution, daily_trend
        """
        from app.database.session import SessionLocal
        from app.services.history_service import history_service

        db = SessionLocal()
        try:
            stats = history_service.get_statistics(db=db, user_id=user_id, days=days)
            # 将不可序列化的对象转换为基本类型
            safe_stats = {
                "total_tasks": stats.get("total_tasks", 0),
                "total_images": stats.get("total_images", 0),
                "total_objects": stats.get("total_objects", 0),
                "avg_inference_time": round(stats.get("avg_inference_time", 0) or 0, 2),
                "class_distribution": stats.get("class_distribution", {}),
                "daily_trend": [
                    {"date": str(d.get("date", "")), "count": d.get("count", 0)}
                    for d in stats.get("daily_trend", [])
                ],
            }
            return json.dumps(safe_stats, ensure_ascii=False)
        finally:
            db.close()

    return [query_detection_history, get_detection_statistics]
