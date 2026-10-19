"""发票命名字段的本地格式校验，不用于查验发票真伪。"""
import datetime
from decimal import Decimal
import re
import unicodedata

FIELDS = ("buyer", "amount", "date", "invoice_no")


def validate_invoice(item):
    """返回规范化字段、阻止命名的错误、允许省略字段的提醒。不修改原记录。"""
    values = {field: unicodedata.normalize("NFKC", str(item.get(field) or "")).strip()
              for field in FIELDS}
    errors, warnings = {}, {}
    buyer = values["buyer"]
    if not buyer:
        errors["buyer"] = "缺少购买方名称"
    elif re.search(r"[\x00-\x1f]", buyer):
        errors["buyer"] = "购买方名称包含控制字符，请删除后重试"
    elif not re.sub(r'[<>:"/\\|?*\s.\x00-\x1f]', "", buyer):
        errors["buyer"] = "购买方名称不能仅包含空格或文件名禁用字符"

    raw_amount = values["amount"]
    if not raw_amount:
        errors["amount"] = "缺少金额"
    else:
        amount = re.sub(r"^[¥￥]\s*", "", raw_amount)
        if re.fullmatch(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?", amount):
            values["amount"] = format(Decimal(amount.replace(",", "")), ".2f")
        else:
            errors["amount"] = "金额格式不正确：请输入数字，最多两位小数（支持负数）"

    date = values["date"]
    if not date:
        warnings["date"] = "缺少开票日期，命名时省略"
    else:
        match = re.fullmatch(r"([0-9]{4})([0-9]{2})([0-9]{2})", date)
        if not match:
            match = re.fullmatch(r"([0-9]{4})[年./-]([0-9]{1,2})[月./-]([0-9]{1,2})日?", date)
        try:
            if match is None:
                raise ValueError()
            values["date"] = datetime.date(*(int(part) for part in match.groups())).strftime("%Y%m%d")
        except ValueError:
            errors["date"] = "开票日期无效：请使用真实日期，如 20261020 或 2026-10-20"

    number = re.sub(r"\s+", "", values["invoice_no"])
    if not number:
        warnings["invoice_no"] = "缺少发票号码，命名时省略"
    elif not re.fullmatch(r"[0-9]{8,20}", number):
        errors["invoice_no"] = "发票号码格式不正确：本工具支持 8～20 位数字，请核对原票"
    else:
        values["invoice_no"] = number
    return values, errors, warnings


def update_validation(item):
    values, errors, warnings = validate_invoice(item)
    # 无效输入保持原样以便修改；有效字段才规范化，不猜测或修补识别字符。
    for field in FIELDS:
        if field not in errors:
            item[field] = values[field]
    item["validation_errors"] = errors
    item["validation_warnings"] = warnings
    item["status"] = "失败" if errors else "成功"
    item["error"] = "；".join(errors.values())
    return not errors
