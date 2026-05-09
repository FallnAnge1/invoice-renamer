#!/usr/bin/env python3
"""识别 PDF 发票中的购买方名称和金额，并重命名文件。

用法:
    python3 rename_invoices.py invoice.pdf           # 处理单个文件
    python3 rename_invoices.py /path/to/invoices/    # 批量处理目录
    python3 rename_invoices.py --dry-run invoice.pdf # 预览模式，不实际重命名
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: str) -> str:
    """用 pdfplumber 提取 PDF 文本，按页拼接返回。"""
    import pdfplumber

    full_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text.append(text)
    return "\n".join(full_text)


def extract_text_via_ocr(pdf_path: str) -> str:
    """将 PDF 转为图片后用 OCR 识别文本（扫描件备选方案）。
    需要: brew install tesseract tesseract-lang
    """
    from pdf2image import convert_from_path
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "tesseract 未安装。安装方法:\n"
            "  brew install tesseract tesseract-lang"
        )

    images = convert_from_path(pdf_path, dpi=300)
    full_text = []
    for img in images:
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        full_text.append(text)
    return "\n".join(full_text)


def find_buyer_name(text: str) -> str | None:
    """从发票文本中提取购买方名称。"""
    patterns = [
        # 标准发票: 购买方名称：XXX公司
        r"购买方名称[：:]\s*(.+?)(?:\n|$)",
        # 格式: "购 名称：XXX 销" (购买方名称在"名称："和" 销"之间)
        r"购\s+名称[：:]\s*(.+?)\s+销",
        # Apple 格式: 买 名称:王冰 售
        r"买\s+名称[：:]\s*(\S+?)\s+售",
        # 纳税人名称：XXX
        r"纳税人名称[：:]\s*([^\n]{4,40})",
        # 通用: 在"购"之后的"名称：XXX" (跨行匹配)
        r"购.{0,50}?名称[：:]\s*([^\n]{2,40})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            name = match.group(1).strip()
            if name and len(name) >= 2 and not any(
                keyword in name
                for keyword in ["地址", "电话", "开户", "账号", "密码", "填写", "售", "销"]
            ):
                return name
    return None


def find_amount(text: str) -> str | None:
    """从发票文本中提取价税合计金额。"""
    patterns = [
        # 价税合计（大写）... ¥1,234.56
        r"价税合计.*?[¥￥]\s*([\d,]+\.\d{2})",
        # (小写) ¥1,234.56
        r"小写.*?[¥￥]\s*([\d,]+\.\d{2})",
        # 合计金额 ¥1,234.56
        r"合计.*?[¥￥]\s*([\d,]+\.\d{2})",
        # ¥1,234.56 出现在价税合计附近
        r"[¥￥]\s*([\d,]+\.\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            amount = match.group(1).replace(",", "")
            return amount
    return None


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符。"""
    # 替换文件系统不允许的字符
    illegal_chars = r'[<>:"/\\|?*]'
    name = re.sub(illegal_chars, "", name)
    # 移除多余空白
    name = re.sub(r"\s+", "", name)
    return name.strip()


def rename_invoice(pdf_path: str, dry_run: bool = False) -> bool:
    """处理单个 PDF 发票文件。返回是否成功识别并重命名。"""
    pdf_path = os.path.abspath(pdf_path)
    logger.info("处理: %s", pdf_path)

    if not os.path.exists(pdf_path):
        logger.error("  文件不存在: %s", pdf_path)
        return False

    # 1. 尝试 pdfplumber 提取文本
    text = extract_text_from_pdf(pdf_path)
    buyer_name = find_buyer_name(text)
    amount = find_amount(text)

    # 2. 如果文本提取失败，回退到 OCR
    if not buyer_name or not amount:
        logger.info("  文本提取不完整，尝试 OCR 识别...")
        try:
            text = extract_text_via_ocr(pdf_path)
            if not buyer_name:
                buyer_name = find_buyer_name(text)
            if not amount:
                amount = find_amount(text)
        except Exception as e:
            logger.warning("  OCR 识别失败: %s", e)

    # 3. 输出结果
    if not buyer_name:
        logger.error("  ✗ 未能识别购买方名称")
        return False
    if not amount:
        logger.error("  ✗ 未能识别金额")
        return False

    logger.info("  购买方: %s", buyer_name)
    logger.info("  金额:   ¥%s", amount)

    # 4. 生成新文件名
    new_name = f"{sanitize_filename(buyer_name)}_{amount}.pdf"
    new_path = os.path.join(os.path.dirname(pdf_path), new_name)

    # 处理重名冲突
    if os.path.exists(new_path):
        base = f"{sanitize_filename(buyer_name)}_{amount}"
        counter = 2
        while os.path.exists(new_path):
            new_name = f"{base}_{counter}.pdf"
            new_path = os.path.join(os.path.dirname(pdf_path), new_name)
            counter += 1

    if dry_run:
        logger.info("  → [预览] 将重命名为: %s", new_name)
    else:
        os.rename(pdf_path, new_path)
        logger.info("  → 已重命名为: %s", new_name)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="识别 PDF 发票中的购买方名称和金额，并重命名文件。"
    )
    parser.add_argument(
        "path",
        help="PDF 文件路径或包含 PDF 文件的目录",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：只显示识别结果，不实际重命名",
    )
    args = parser.parse_args()

    target = os.path.abspath(args.path)

    if os.path.isfile(target):
        if not target.lower().endswith(".pdf"):
            logger.error("仅支持 PDF 文件。")
            sys.exit(1)
        success = rename_invoice(target, dry_run=args.dry_run)
        sys.exit(0 if success else 1)

    elif os.path.isdir(target):
        pdf_files = list(Path(target).glob("*.pdf"))
        if not pdf_files:
            logger.error("目录中没有找到 PDF 文件。")
            sys.exit(1)

        success_count = 0
        fail_count = 0
        for pdf_file in sorted(pdf_files):
            if rename_invoice(str(pdf_file), dry_run=args.dry_run):
                success_count += 1
            else:
                fail_count += 1

        logger.info("\n--- 处理完成 ---")
        logger.info("成功: %d, 失败: %d", success_count, fail_count)

    else:
        logger.error("路径不存在: %s", target)
        sys.exit(1)


if __name__ == "__main__":
    main()
