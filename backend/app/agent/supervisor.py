"""
LangGraph Multi-Agent Supervisor — Supervisor + 子 Agent 路由

架构：
  START → supervisor_node → detection_node / data_node / general_node
       → supervisor_node → ... → FINISH

每个子 Agent 是独立的 ReAct Agent（LLM + Tools），Supervisor 负责路由。
"""

import json
import os
from typing import Any, AsyncGenerator, Literal

from langchain_classic.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.agent.data_tools import _make_data_tools
from app.agent.general_tools import _make_general_tools
from app.agent.state import (
    AGENT_DATA,
    AGENT_DETECTION,
    AGENT_FINISH,
    AGENT_GENERAL,
    AGENT_LABELS,
    AgentState,
)
from app.config.settings import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════
# Supervisor 路由决策模型
# ══════════════════════════════════════════════════════════

class RouterDecision(BaseModel):
    """Supervisor 的路由决策"""
    next_agent: Literal["detection", "data", "general", "FINISH"] = Field(
        description="下一步路由的 Agent 名称"
    )
    reason: str = Field(default="", description="简短的路由理由")


# ══════════════════════════════════════════════════════════
# Prompt Templates
# ══════════════════════════════════════════════════════════

_SUPERVISOR_PROMPT = """你是一个工业缺陷检测平台的智能助手主管，负责理解用户意图并分发给专业子 Agent。

## 可用的子 Agent

| Agent | 职责 | 适用场景 |
|-------|------|----------|
| detection | 图片/视频/ZIP 目标检测 | 用户上传图片要求检测、分析缺陷 |
| data | 查询历史检测记录和统计数据 | 用户问"最近检测了多少"、"缺陷统计"、"看板数据" |
| general | 一般性问答和帮助 | 用户问"什么是置信度"、"怎么用"、闲聊打招呼 |

## 路由规则

1. 如果用户提到了图片检测、上传图片、分析缺陷、图片路径 → detection
2. 如果用户询问检测历史、统计、数据、最近检测结果 → data
3. 如果用户只是提问、寻求帮助、打招呼、闲聊 → general
4. 如果用户的问题已经在前一轮被解决，或者只是确认/感谢 → FINISH
5. 用户可能同时问多个问题，优先选择最核心的需求路由

## 当前对话中有图片附件时的判断

- 单张/多张图片 + "检测"/"分析" 意图 → detection
- 只有图片路径没有明确指令 → 也路由到 detection（默认行为）

请根据用户的消息判断下一步交给哪个 Agent。调用 RouterDecision 函数输出你的决定。"""

_DETECTION_SYSTEM = """你是一个专业的目标检测助手，可以帮助用户检测图片中的目标物体。

重要规则：
- 当用户消息中包含 [附件图片路径: xxx] 时，xxx 就是服务端的图片路径，你必须直接使用它调用检测工具
- 当用户消息中包含 `[attachment: ... | path: ...]` 时，使用 `path:` 后的服务端路径调用检测工具
- 不要要求用户再次提供路径，直接使用附件中给出的路径
- 单张图片 → 调用 detect_single_image
- 多张图片 → 调用 detect_batch_images
- ZIP 压缩包 → 调用 detect_zip_images_file
- 视频附件（.mp4/.avi/.mov/.mkv/.wmv/.flv）应路由到检测 Agent，并使用可用的视频检测工具或明确说明当前工具限制

工作流程：
1. 理解用户意图
2. 调用对应检测工具
3. 用自然语言总结检测结果

回复要求：
- 先报告检测到的目标总数
- 列出各类别数量统计
- 简洁专业，使用中文，不要输出emoji"""

_DATA_SYSTEM = """你是一个检测数据分析助手，帮助用户查询历史检测记录和统计数据。

你可以：
- 查询最近的检测历史记录（使用 query_detection_history）
- 获取检测统计数据（使用 get_detection_statistics）- 包含缺陷类型分布、每日趋势等

回复要求：
- 用自然语言解读数据，不要直接输出 JSON
- 如果数据为空，告知用户暂无记录
- 简洁专业，使用中文，不要输出emoji"""

_GENERAL_SYSTEM = """你是一个工业缺陷检测平台的智能助手，帮助用户了解平台功能和相关概念。

你可以：
- 回答关于缺陷类型（划痕、凹坑、锈斑等）的问题
- 解释检测参数（置信度、IoU）的含义
- 介绍平台使用方法（单图检测、批量检测、模型训练等）
- 搜索知识库（使用 search_knowledge 工具）
- 如果消息包含 `[attachment: ... | path: ...]`，必须先调用 `read_attachment` 读取该服务端路径；不要只根据文件名猜测内容
- 对无法解析的格式要明确告知用户，不要声称已经读取或分析了文件

回复要求：
- 使用中文，简洁专业，不要输出emoji
- 如果用户问的问题超出能力范围，诚实告知并提供替代建议"""


# ══════════════════════════════════════════════════════════
# LLM Factory (复用 detection_agent 的模式)
# ══════════════════════════════════════════════════════════

def _make_llm(model: str | None = None):
    api_key = settings.OPENAI_API_KEY
    base_url = settings.OPENAI_BASE_URL
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")
    model_name = model or settings.OPENAI_MODEL
    logger.info("Supervisor LLM: model=%s base_url=%s", model_name, base_url)
    return ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0.1,
    )


def _make_executor(llm, tools, system_prompt: str) -> AgentExecutor:
    """创建 ReAct AgentExecutor"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_openai_tools_agent(llm=llm, tools=tools, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=5,
        return_intermediate_steps=True,
    )


# ══════════════════════════════════════════════════════════
# Supervisor Agent
# ══════════════════════════════════════════════════════════

class SupervisorAgent:
    """LangGraph 多 Agent Supervisor"""

    def __init__(self):
        self._graph = None
        self._llm = None
        logger.info("SupervisorAgent 初始化完成")

    def _get_graph(self, model: str | None, user_id: int):
        """构建（或重建）LangGraph StateGraph"""
        llm = _make_llm(model)

        # ── 子 Agent 工具 ──
        from app.agent.detection_agent import make_detection_tools
        detection_tools = make_detection_tools(user_id)
        data_tools = _make_data_tools(None, user_id)
        general_tools = _make_general_tools(user_id)

        # ── 子 Agent Executors ──
        detection_exec = _make_executor(llm, detection_tools, _DETECTION_SYSTEM)
        data_exec = _make_executor(llm, data_tools, _DATA_SYSTEM)
        general_exec = _make_executor(llm, general_tools, _GENERAL_SYSTEM)

        # ── Supervisor: bind_tools 替代 with_structured_output ──
        # with_structured_output 会设 tool_choice="required"，DeepSeek 思考模式不支持
        # bind_tools 只注册工具不强制调用，模型自己决定，兼容思考模式
        supervisor_llm = llm.bind_tools([RouterDecision])

        # ── 构建图 ──
        builder = StateGraph(AgentState)

        # Supervisor node
        async def supervisor_node(state: AgentState) -> dict:
            messages = state["messages"]
            last_msg = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])

            attachment_hint = state.get("attachment_hint", "")
            if attachment_hint:
                detection_suffixes = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".zip", ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv")
                detection_mime_markers = ("image/", "video/", "application/zip", "application/x-zip")
                attachment_tokens = [token.strip().lower() for token in attachment_hint.split()]
                forced_agent = (
                    AGENT_DETECTION
                    if any(token in detection_suffixes for token in attachment_tokens)
                    or any(token.startswith(marker) for token in attachment_tokens for marker in detection_mime_markers)
                    else AGENT_GENERAL
                )
                logger.info("Supervisor attachment route -> %s", forced_agent)
                return {"next_agent": forced_agent, "current_agent": "supervisor"}

            response = await supervisor_llm.ainvoke([
                ("system", _SUPERVISOR_PROMPT),
                ("human", f"用户消息：{last_msg}\n\n请决定下一个 Agent，使用 route_to_agent 工具。"),
            ])

            # 从 tool_calls 解析路由决策
            if response.tool_calls:
                args = response.tool_calls[0]["args"]
                next_agent = args.get("next_agent", AGENT_GENERAL)
                reason = args.get("reason", "")
            else:
                # fallback：模型未调工具，从文本提取
                text = (response.content or "").strip().lower()
                detected = next((a for a in [AGENT_DETECTION, AGENT_DATA, AGENT_GENERAL] if a in text), AGENT_GENERAL)
                next_agent = detected
                reason = f"文本解析: {text[:50]}"

            logger.info("Supervisor → %s (reason: %s)", next_agent, reason)
            return {"next_agent": next_agent, "current_agent": "supervisor"}

        # Detection node
        async def detection_node(state: AgentState, config: RunnableConfig) -> dict:
            logger.info("🔍 Detection Agent 执行中...")
            result = await detection_exec.ainvoke({
                "input": _last_user_content(state),
                "chat_history": _chat_history_for_subagent(state),
            }, config)
            return _build_subagent_response(state, result, AGENT_DETECTION)

        # Data node
        async def data_node(state: AgentState, config: RunnableConfig) -> dict:
            logger.info("📊 Data Agent 执行中...")
            result = await data_exec.ainvoke({
                "input": _last_user_content(state),
                "chat_history": _chat_history_for_subagent(state),
            }, config)
            return _build_subagent_response(state, result, AGENT_DATA)

        # General node
        async def general_node(state: AgentState, config: RunnableConfig) -> dict:
            logger.info("💬 General Agent 执行中...")
            result = await general_exec.ainvoke({
                "input": _last_user_content(state),
                "chat_history": _chat_history_for_subagent(state),
            }, config)
            return _build_subagent_response(state, result, AGENT_GENERAL)

        # ── 添加节点 ──
        builder.add_node("supervisor", supervisor_node)
        builder.add_node("detection", detection_node)
        builder.add_node("data", data_node)
        builder.add_node("general", general_node)

        builder.set_entry_point("supervisor")

        # ── 条件边：supervisor → 子 Agent 或 FINISH ──
        def route_after_supervisor(state: AgentState) -> str:
            return state.get("next_agent", AGENT_FINISH)

        builder.add_conditional_edges("supervisor", route_after_supervisor, {
            AGENT_DETECTION: "detection",
            AGENT_DATA: "data",
            AGENT_GENERAL: "general",
            AGENT_FINISH: END,
        })

        # ── 子 Agent 执行完后直接结束 ──
        builder.add_edge("detection", END)
        builder.add_edge("data", END)
        builder.add_edge("general", END)

        graph = builder.compile()
        logger.info("Supervisor graph 编译完成，节点: %s", list(graph.nodes.keys()) if hasattr(graph, 'nodes') else "ok")
        return graph

    async def chat_stream(
        self,
        message: str,
        image_paths: list[str] | None = None,
        attachments: list[dict] | None = None,
        model: str | None = None,
        chat_history: list[dict] | None = None,
        user_id: int = 1,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式对话 — 兼容原 DetectionAgent.chat_stream 接口"""

        if attachments:
            paths_text = "\n".join(
                f"[attachment: {item.get('name', 'attachment')} | type: {item.get('content_type', '')} | path: {item.get('path', '')}]"
                for item in attachments
            )
            message = f"{message}\n{paths_text}"
        elif image_paths:
            paths_text = "\n".join(f"[附件图片路径: {p}]" for p in image_paths)
            message = f"{message}\n{paths_text}"

        graph = self._get_graph(model, user_id)

        # 构建初始 state。API 层已经加载了当前用户所属会话的历史，必须
        # 转换为 LangChain 消息后传入图，否则每次请求都会退化为单轮对话。
        from langchain_core.messages import AIMessage, HumanMessage

        history_messages = []
        for item in chat_history or []:
            role = item.get("role") if isinstance(item, dict) else None
            content = item.get("content", "") if isinstance(item, dict) else str(item)
            if role == "user":
                history_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                history_messages.append(AIMessage(content=content))

        initial_state: AgentState = {
            "messages": [*history_messages, HumanMessage(content=message)],
            "next_agent": "",
            "current_agent": "",
            "user_id": user_id,
            "attachment_hint": " ".join(
                f"{item.get('suffix', '')} {item.get('content_type', '')}"
                for item in (attachments or [])
            ),
        }

        try:
            async for event in graph.astream_events(initial_state, version="v2"):
                kind = event["event"]

                # ── Node 进入/退出事件 → agent 切换提示 ──
                if kind == "on_chain_start":
                    node_name = event.get("name", "")
                    if node_name in AGENT_LABELS:
                        yield {
                            "type": "agent_switch",
                            "agent": node_name,
                            "label": AGENT_LABELS[node_name],
                        }

                # ── LLM token 流式输出 ──
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        yield {"type": "text_chunk", "content": chunk.content}

                # ── Tool 调用 ──
                if kind == "on_tool_start":
                    yield {
                        "type": "tool_call",
                        "tool": event["name"],
                        "input": event["data"].get("input", {}),
                        "agent": event.get("metadata", {}).get("langgraph_node", ""),
                    }

                # ── Tool 结果 ──
                if kind == "on_tool_end":
                    output = event["data"].get("output", "")
                    yield {
                        "type": "tool_result",
                        "tool": event.get("name", ""),
                        "result": str(output) if output else "",
                        "agent": event.get("metadata", {}).get("langgraph_node", ""),
                    }

        except Exception as exc:
            logger.exception("Supervisor graph 执行异常")
            # Keep the stream contract structured and do not expose provider
            # errors, prompts, or attachment paths to the browser.
            yield {
                "type": "error",
                "code": "AGENT_EXECUTION_FAILED",
                "status_code": 502,
                "message": "Agent execution failed",
                "retryable": True,
            }


# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════

def _last_user_content(state: AgentState) -> str:
    """获取 messages 中最后一条 human 消息的文本"""
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and getattr(msg, "type", "") == "human":
            return msg.content
    return state["messages"][-1].content if state["messages"] else ""


def _chat_history_for_subagent(state: AgentState) -> list:
    """从 messages 中提取聊天历史（排除最后一条用户消息和 agent_scratchpad）"""
    history = []
    for msg in state["messages"]:
        if hasattr(msg, "type"):
            if msg.type in ("human", "ai"):
                history.append(msg)
    # 返回除最后一条外的历史（最后一条是当前用户输入，放在 input 参数中）
    return history[:-1] if history else []


def _build_subagent_response(state: AgentState, result: dict, agent_name: str) -> dict:
    """构建子 Agent 执行后的状态更新"""
    from langchain_core.messages import AIMessage

    output = result.get("output", "")
    return {
        "messages": [AIMessage(content=output)],
        "current_agent": agent_name,
    }


# 全局单例
supervisor_agent = SupervisorAgent()
