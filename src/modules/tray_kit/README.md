# tray_kit（reme-helper 形态）

单实例互斥体：acquire_single_instance(mutex_name)（抢；False=已占用；守卫失败放行）、
single_instance_free(mutex_name)（探测不持有，诊断参数用）；模块级持锁句柄。

与模板 T7 的差异（TEMPLATE-LOCAL-OVERRIDE，已申报）：互斥体名调用方显式传入
（APP_ID + "-tray"，全局命名空间）；warn_duplicate_instance / quit 文件协议 /
菜单签名重画留在 main.py（UI 文案走 t()、退出确认 UX 是 1.2.4 的产品语义）。
single_instance_free 已反向沉淀进模板 1.0.1。
