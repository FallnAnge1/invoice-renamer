"""批量图片 OCR 的结果记录和纯文本导出。"""
from pathlib import Path

from format_converter import _write_output


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
