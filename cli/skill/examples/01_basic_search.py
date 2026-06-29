# 示例 1：基本搜索
# 这个脚本演示如何使用 SDK 搜索视频

from ucrawl import UcrawlSDK

def main(controller, **kwargs):
    """基本搜索示例。"""
    sdk = UcrawlSDK(save_dir=controller.current_save_dir, verbose=True)

    source = kwargs.get("source", "douyin")
    keyword = kwargs.get("keyword", "测试")
    max_items = int(kwargs.get("max", 10))

    print(f"🔍 开始搜索: {source} - {keyword}")
    result = sdk.search(
        source,
        keyword,
        max_items=max_items,
        selection="all"
    )

    print(f"✅ 找到 {len(result['items'])} 个视频")
    for item in result["items"]:
        print(f"  - {item['title']}: {item['status']}")

    return 0
