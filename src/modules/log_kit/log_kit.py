# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/modules/log_kit/log_kit.py | TEMPLATE-VER: 1.0.2
# TEMPLATE-LOCAL-OVERRIDE: root-logger 模式（main.py 全文 logging.info 直用）+ 显式
#   configure_logging() 装配函数；named-logger 的 get_logger/make_logger 形态见模板。
"""T12｜运行日志（reme-helper 形态）：root logger 单文件 1MB、保留 3 份滚存。

滚动在 Windows 上的坑：另一进程还开着日志文件时改不了名。正常情况下单实例守卫保证
只有一个托盘，但升级期间新旧版本可能同时在跑；这种情况退回普通 FileHandler，
宁可这次不滚，也不要因为日志装不上而启动失败。任何日志失败都不能把主流程弄死。
"""
import logging


def configure_logging(log_path, max_bytes=1 << 20, backups=3) -> None:
    """装一个会自转的日志处理器到 root logger（main.py 模块级调用一次）。"""
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler: logging.Handler
    try:
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(log_path, maxBytes=max_bytes,
                                      backupCount=backups, encoding="utf-8")
    except Exception:  # noqa: BLE001 - 装不上日志不该拦住启动
        handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)


def log(message: str) -> None:
    logging.info(message)
