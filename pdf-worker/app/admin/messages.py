ERROR_MESSAGES = {
    "UPLOAD_TOO_LARGE": "文件超过允许大小，请选择不超过 100 MB 的文件。",
    "EMPTY_FILE": "上传的文件为空，请重新选择。",
    "INVALID_PDF_FILE": "无法打开这个 PDF，文件可能已损坏。",
    "PDF_ENCRYPTED": "该 PDF 已加密或需要密码，暂时无法处理。",
    "PDF_PAGE_OUT_OF_RANGE": "页码超出范围，请检查后重新填写。",
    "QR_DOES_NOT_FIT_PAGE": "当前页面无法放下所选尺寸的二维码，请减小二维码或边距。",
    "BINDING_NOT_FOUND": "没有找到该解析资料，可能已被停用或删除。",
    "VERSION_NOT_FOUND": "没有找到该历史版本。",
    "INVALID_QR_MODE": "请选择二维码更新方式。",
    "RESOURCE_CONFLICT": "这份资料刚刚被其他管理员更新，请刷新页面，确认当前发布版本后再重试。",
    "VERSION_STATUS_INVALID": "当前答案版本状态已经变化，请刷新页面后重试。",
    "VERSION_NOT_DRAFT": "这份答案已经不是草稿，请返回资料详情刷新状态。",
    "ASSET_MISSING": "答案文件不存在，无法发布，请重新上传或联系技术人员。",
    "ASSET_SIZE_MISMATCH": "答案文件完整性检查失败，无法发布。",
    "ASSET_HASH_MISMATCH": "答案文件完整性检查失败，无法发布。",
}


def chinese_error(code: str, fallback: str = "系统处理失败，请稍后重试。") -> str:
    return ERROR_MESSAGES.get(code, fallback)
