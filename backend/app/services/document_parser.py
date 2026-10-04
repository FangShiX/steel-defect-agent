"""
知识文档解析 — 从上传的原始文件里提取纯文本，并切分成适合 embedding 的小块

支持 txt / md（直接按 utf-8 解码）、pdf（pypdf）、docx（python-docx）。
其它格式直接报错，让调用方（api/knowledge.py）返回 400，而不是静默吞掉内容。
"""
import io

from fastapi import HTTPException

SUPPORTED_TYPES = {"txt", "md", "pdf", "docx"}


def guess_file_type(filename: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文档类型: .{ext or '未知'}，目前仅支持 {', '.join(sorted(SUPPORTED_TYPES))}",
        )
    return ext


def extract_text(filename: str, content: bytes) -> str:
    """按文件类型提取纯文本，提取失败时抛 400（文件损坏/加密等）而不是让上传流程崩溃"""
    file_type = guess_file_type(filename)

    try:
        if file_type in ("txt", "md"):
            return content.decode("utf-8", errors="ignore")

        if file_type == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)

        if file_type == "docx":
            import docx

            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文档解析失败（{file_type}）") from exc

    raise HTTPException(status_code=400, detail=f"不支持的文档类型: {file_type}")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    按字符数做滑动窗口切分，overlap 保留一部分上下文避免语义在块边界被切断。
    先按空行分段，尽量不把一个自然段拆散；单段超过 chunk_size 时再做定长切分。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if overlap >= chunk_size:
        overlap = chunk_size // 4

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
        if len(para) <= chunk_size:
            buffer = para
        else:
            # 单个段落本身超长，定长滑窗切分
            start = 0
            while start < len(para):
                end = start + chunk_size
                chunks.append(para[start:end])
                start = end - overlap
            buffer = ""

    if buffer:
        chunks.append(buffer)

    return [c for c in chunks if c.strip()]
