# joi-observer

一个面向 Ubuntu Server 的终端监控工具，通过 TUI 实时展示服务器硬件状态与LLM服务负载。

- **硬件监控**：GPU 利用率、显存、温度与功耗，以及 CPU、内存、磁盘和网络指标。
- **vLLM 监控**：各模型的运行与排队请求数、Token 吞吐、延迟和 KV Cache 使用率。
- **服务扩展**：后续可接入 Open WebUI 等服务。
