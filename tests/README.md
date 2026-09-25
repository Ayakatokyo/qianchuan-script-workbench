# 独立离线测试

从仓库根运行 `python3 tools/test.py`；可用 `python3 tools/test.py tests.test_name` 定向运行。安装测试依赖：`python3 -m pip install -r requirements-dev.txt`。正式运行依赖另见 requirements.txt。

测试来自拆分前规划工程的合成用例，源文件哈希、适配点、未迁范围见 MIGRATION.json。业务断言保留；只适配仓库根路径、独立打包入口、旧模块名称及不属于当前技能的历史测试范围。

sitecustomize.py 仅为测试提供旧 `short_video_foundation` 名称，每个别名都指向本仓 `scripts`，不合并兄弟仓，不加载 dev/legacy。测试禁止 socket 网络连接，RPA/API 使用原合成网关，视频由本机 FFmpeg 生成，ASR 使用 fixture；requirements-dev.txt 包含运行库用于本地媒体处理，但不会下载真实 ASR 模型。这里的通过不代表真实平台、客户快照或真实模型验收。

真实客户快照和原环境门禁保留在管理仓历史里，未复制客户数据。原多技能打包/文档一致性/父仓目录规则不适用于独立仓；独立构建、包字节和隔离复制验证由迁移验收记录追踪。
