# log_kit（reme-helper 形态）

configure_logging(log_path) 装配 root logger（1MB×3 滚动；RotatingFileHandler 装不上时
回退 FileHandler——升级窗口双实例实测坑）；log(message) = logging.info。

与模板 T12 的差异（TEMPLATE-LOCAL-OVERRIDE，已申报）：模板是 named-logger + 闭包形态
（get_logger/make_logger）；reme 全文 121 处 log() 走 root，保持零行为变化。
回退分支已反向沉淀进模板 1.0.2。
