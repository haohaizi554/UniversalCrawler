"""Spider 会话兼容入口必须继续导出共享运行时中的同一类型。"""

from app.spiders import runtime
from shared import spider_session_runtime


def test_spider_runtime_reexports_shared_session_types() -> None:
    assert runtime.SpiderLaunchRequest is spider_session_runtime.SpiderLaunchRequest
    assert runtime.SpiderSession is spider_session_runtime.SpiderSession
    assert runtime.SpiderSessionBindings is spider_session_runtime.SpiderSessionBindings
    assert set(runtime.__all__) == {
        "SpiderLaunchRequest",
        "SpiderSession",
        "SpiderSessionBindings",
    }
