"""仅会话内的模型与主题选择；不持有采集器、快照或状态写入接口。"""

from joi_observer.config import ModelConfig
from joi_observer.tui.layout import ViewSelection


class SessionViewActions:
    """实现 ViewActions 的本地选择控制器；构造和所有操作均无 I/O。

    models 是经过配置加载器验证的不可变模型序列，id 唯一，顺序在会话内
    不变；同名、同类型或同端点的不同 id 仍是独立项。不重新验证配置，
    不发现模型、不读健康状态、不保存滚动偏移、不持久化选择。

    初始选择首个配置 id，空序列为 None；目标为每个实例从 hologram 开始。
    模型失败、恢复、快照刷新和窗口缩放不改变选择。仅暴露 selection 与
    on_key；不提供更改模型集合或启用其他服务的操作。

    通过私有配置序号移动选择，每次变更生成新的不可变选择值。
    """

    def __init__(self, models: tuple[ModelConfig, ...]) -> None:
        self._models = models
        self._index = 0
        self._view = ViewSelection(models[0].id if models else None)

    def selection(self) -> ViewSelection:
        """返回当前不可变选择，不读取外部状态或修改会话。

        非空模型序列始终返回其中一个 id，空序列始终为 None；theme 只为
        moonlight/hologram。连续读取值相等；之后的按键不能修改已返回的值。
        首次读取与后续读取具有相同语义，不得通过读取推进选择。
        """
        return self._view

    def on_key(self, key: str) -> None:
        """处理终端已归一化的键名，原地更新会话，返回 None。

        up/down 按配置顺序移动一项，到首尾停留、不循环；零或一个模型时
        安全无动作。t 在 moonlight/hologram 间切换，保留 model_id；导航
        保留 theme。空模型时 t 仍有效，实例之间互不影响。

        left/right/enter/p/tab、q/interrupt 及其他字符串均无动作；不解析
        原始转义字节，不把大小写或其他键名当别名。q/interrupt 由应用全局
        处理；服务始终为 vLLM，WebUI 不可进入。操作不触发采样、清历史、
        日志、文件或配置写入，不创建异步任务。实际颜色由终端呈现层负责。
        """
        if key == "t":
            theme = "hologram" if self._view.theme == "moonlight" else "moonlight"
            self._view = ViewSelection(self._view.model_id, theme)
        elif self._models and key in ("up", "down"):
            offset = -1 if key == "up" else 1
            self._index = min(max(self._index + offset, 0), len(self._models) - 1)
            self._view = ViewSelection(self._models[self._index].id, self._view.theme)
