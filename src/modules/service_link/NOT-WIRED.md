# NOT WIRED YET / 尚未接线

This folder is a byte-identical copy of the family template module (README +
`__init__.py` + `service_link.py`), staged under `src/modules/service_link/`,
but **nothing imports it**: `grep -rn "service_link" src/ tests/ scripts/`
finds only this folder. The G4.2 ADOPTED graceful-shutdown path is still pending
(REVIEW.md finding #8), so the live quit flow keeps terminating the attached
service by pid.

本模块是模板正本拷贝（整文件夹已采纳），但**全仓库没有任何调用点**——G4.2 的
ADOPTED 优雅关闭分支尚未接入（REVIEW 发现 #8）。**不要把它当成活代码**；
接线完成之日删除本文件。

This file is reme-local (it has no template counterpart) and is not part of the
template comparison set; the three template files in this folder stay byte-identical
to `my-diy-tool-template/modules/service_link/`.
