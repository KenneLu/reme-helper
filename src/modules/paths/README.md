# paths（reme-helper 形态）

四区路径：APP_DIR / RUN_DIR / LOCAL_DATA_DIR / 诊断区。接口与模板 T2 同名同义：
CONFIG_PATH / LEGACY_CONFIG_PATH / LOG_DIR / LOG_PATH 及图标、退出请求文件的定位常量。

与模板 T2 的差异（TEMPLATE-LOCAL-OVERRIDE，已申报）：
- dev 态 RUN_DIR = 仓库根（模板 = APP_DIR）——诊断输出（--smoke/--release/lang-audit）、
  图标、文档查找都跟「这次运行的那个包」走，构建脚本按发布目录下的 log 读取并清理；
- 增补 DIAG_LOG_DIR / RUN_LOG_DIR / ICON_PATH / TASKBAR_ICON_PATH / 帧表常量 / TRAY_HICON_PIXELS；
- env 覆盖用 REME_HELPER_CONFIG（模板是 <APP>_DATA_DIR 整根重定向 + <APP>_CONFIG）。

播种 seed_config 留在 main.py：它依赖 log() 与「播种+迁移二合一」语义（源文件有两种身份）。
