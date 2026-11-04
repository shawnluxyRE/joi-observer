"""服务呈现元数据与页脚契约；不负责启用服务、路由或处理按键。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServicePresentation:
    """当前服务的静态呈现描述，供服务区域与页脚共同使用。

    service_id 是内部稳定标识，title 是服务标题，navigation_label 是
    上下箭头之后的操作说明。值由服务定义提供，为非空单行文字，不来自
    采集响应或用户配置。描述本身不意味着服务已启用或可以切换。
    """

    service_id: str
    title: str
    navigation_label: str


VLLM_SERVICE = ServicePresentation("vllm", "vLLM", "Select model")


def footer_text(service: ServicePresentation) -> str:
    """用当前服务的导航说明组成单行页脚，无 I/O 或状态修改。

    返回 '↑↓ {service.navigation_label}    t Theme    q Quit'；箭头、四空格
    分隔与全局主题/退出提示固定。Select model 是 vLLM 描述的值，不能
    在通用页脚中固定为所有服务的操作。不同描述仅替换导航说明，不自行
    推断行为或启用服务。调用方保证描述合法，外层布局负责宽度裁切。
    """
    return f"↑↓ {service.navigation_label}    t Theme    q Quit"
