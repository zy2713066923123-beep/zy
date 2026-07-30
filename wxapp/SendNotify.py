# -*- coding: utf-8 -*-
"""
通知桥接模块 (Python, 小写命名) —— wxapp 目录

wxapp/鸿星尔克.py 通过 `from sendNotify import send` 引用本模块。
Linux 大小写敏感，故与 SendNotify.py 分别提供，二者接口一致。

统一桥接青龙内置 notify.py；无 notify 环境时降级为仅打印，绝不抛异常影响主流程。
"""

import functools
import io
import sys


def send(title, content=""):
    """发送通知，桥接青龙内置 notify.send。任何异常都被吞掉，不影响业务。"""
    text = "" if content is None else str(content)
    if not text.strip():
        return
    try:
        import notify  # 青龙面板内置
        notify.send(str(title), text)
    except Exception as exc:  # noqa: BLE001
        print(f"[通知] 推送失败或环境未配置 notify：{exc}")


class _Tee(io.TextIOBase):
    """同时写入原始 stdout 和内存缓冲，用于捕获脚本输出。"""

    def __init__(self, origin, buffer):
        self._origin = origin
        self._buffer = buffer

    def write(self, s):
        try:
            self._origin.write(s)
        except Exception:  # noqa: BLE001
            pass
        self._buffer.write(s)
        return len(s)

    def flush(self):
        try:
            self._origin.flush()
        except Exception:  # noqa: BLE001
            pass


def capture_output(title="脚本运行结果"):
    """装饰器：捕获被装饰函数运行期间的所有 print 输出并汇总推送。"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            buffer = io.StringIO()
            origin = sys.stdout
            sys.stdout = _Tee(origin, buffer)
            try:
                return func(*args, **kwargs)
            finally:
                sys.stdout = origin
                try:
                    content = buffer.getvalue().strip()
                    if content:
                        send(title, content)
                except Exception as exc:  # noqa: BLE001
                    print(f"[通知] 汇总推送失败：{exc}")

        return wrapper

    return decorator
