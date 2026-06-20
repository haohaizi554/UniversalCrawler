# 示例 2：合集下载
# 这个脚本演示如何下载 B 站合集

from ucrawl import UcrawlSDK, PipeSelection

def main(controller, **kwargs):
    """合集下载示例。"""
    sdk = UcrawlSDK(save_dir=controller.current_save_dir, verbose=True)

    bv_id = kwargs.get("bv_id", "BV1xxx")
    # 预加载三轮选择
    # 第 1 轮：选前 3 个分季
    # 第 2 轮：选第 1 季的前 5 个
    # 第 3 轮：选第 2 季的前 3 个
    sel = PipeSelection(preloaded_choices=[
        [0, 1, 2],
        [0, 1, 2, 3, 4],
        [0, 1, 2],
    ])

    print(f"📦 开始下载合集: {bv_id}")
    result = sdk.search(
        "bilibili",
        bv_id,
        selection=sel,
        max_pages=5
    )

    print(f"✅ 下载完成: {len(result['items'])} 个视频")
    for item in result["items"]:
        print(f"  - {item['title']}: {item['status']}")

    return 0
