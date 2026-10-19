"""批量图片 OCR 的结果记录和纯文本导出。"""
from pathlib import Path

from format_converter import _write_output


def describe_ocr_error(error):
    """将常见读取错误转成可操作的界面提示，避免显示内部临时路径。"""
    message = str(error).strip()
    if "cannot identify image file" in message.lower():
        return "无法读取图片，文件可能损坏或格式不受支持，请检查原文件。"
    if isinstance(error, FileNotFoundError):
        return "找不到照片，文件可能已移动或删除，请重新添加。"
    if "timeout" in message.lower() or "timed out" in message.lower():
        return "识别超时，请检查照片清晰度，或缩小过大的照片后重试。"
    return message[:240] or "识别未完成，请检查照片后重试。"


def new_record(path):
    return {"path": str(Path(path).resolve()), "text": "", "saved_text": "",
            "status": "待识别", "error": "", "language": ""}


def result_text(record):
    """上次文字在重识别失败后仍可导出，明确标注来源状态。"""
    note = ""
    if record["status"] == "失败":
        note = f"[本次识别失败，以下为保留的上次文字或人工内容；{record['error']}]\n"
    return note + record["text"]


def merge_results(records):
    sections = [f"===== {index:03d} · {Path(record['path']).name} =====\n{result_text(record)}"
                for index, record in enumerate(records, 1) if record["text"].strip()]
    return "\n\n".join(sections)


def export_separate(records, folder):
    """每图一份 UTF-8 TXT；同名自动加序号，不覆盖已有文件。"""
    outputs, failures = [], []
    for index, record in enumerate(records):
        if not record["text"].strip():
            continue
        try:
            data = result_text(record).encode("utf-8")
            path = _write_output(folder, Path(record["path"]).stem, ".txt", lambda stream: stream.write(data))
            outputs.append((index, path))
        except OSError as error:
            failures.append(f"{Path(record['path']).name}：{error}")
    return outputs, failures
