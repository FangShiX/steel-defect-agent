"""
LangGraph 多 Agent 系统 — 状态定义

使用 TypedDict 定义 AgentState：
- messages:   对话历史（自动追加，LangGraph 的 add_messages reducer）
- next_agent: Supervisor 路由目标
- current_agent: 当前活跃 Agent（前端展示用）
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """多 Agent 系统的共享状态"""
    messages: Annotated[list, add_messages]
    next_agent: str          # "detection" | "data" | "general" | "training" | "FINISH"
    current_agent: str       # 当前正在执行的 Agent 名称（前端展示）
    user_id: int             # 当前用户 ID（工具鉴权/过滤用）
    attachment_hint: str     # 附件后缀与 MIME，用于确定路由边界


# Agent 路由常量
AGENT_DETECTION = "detection"
AGENT_DATA = "data"
AGENT_GENERAL = "general"
AGENT_TRAINING = "training"
AGENT_FINISH = "FINISH"

AGENT_LABELS = {
    AGENT_DETECTION:   "检测 Agent",
    AGENT_DATA:        "数据 Agent",
    AGENT_GENERAL:     "通用 Agent",
    AGENT_TRAINING:    "训练 Agent",
}
