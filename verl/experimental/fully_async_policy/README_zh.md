# 全异步策略训练

此上游实验模块将 rollout 和训练放在独立资源上并发执行。
ProgAgent 的 TaskSync 训练使用自己的入口。

- 入口：[fully_async_main.py](fully_async_main.py)
- 配置：[config/](config/)
- 启动脚本：[shell/](shell/)

修改模型、数据路径及训练与 rollout 的 GPU 分配后使用。
`async_training.staleness_threshold` 控制样本陈旧程度，设为零时同步运行；
`trigger_parameter_sync_step` 控制权重同步间隔，`require_batches` 控制每次取用的批数。
部分 rollout 需要正的 staleness 设置。

其他参数见 [英文说明](README.md)。原实现由
[Meituan Search](https://github.com/meituan-search)贡献。
