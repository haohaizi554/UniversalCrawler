# 示例 3：批量搜索
# 这个脚本演示如何批量搜索多个关键词

from ucrawl import UcrawlSDK, RuleSelection

def main(controller, **kwargs):
    """批量搜索示例。"""
    sdk = UcrawlSDK(save_dir=controller.current_save_dir, verbose=True)

    # 要搜索的关键词列表
    keywords = kwargs.get("keywords", "测试1,测试2,测试3").split(",")
    source = kwargs.get("source", "douyin")
    max_per_keyword = int(kwargs.get("max_per_keyword", 5))

    results = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue

        print(f"\n🔍 搜索: {kw}")
        result = sdk.search(
            source,
            kw,
            max_items=max_per_keyword,
            selection=RuleSelection(all_items=True)
        )

        results.append({
            "keyword": kw,
            "count": len(result["items"]),
            "items": result["items"],
        })
        print(f"  ✅ 找到 {len(result['items'])} 个视频")

    # 输出汇总
    print("\n📊 总计:")
    print(f"  关键词: {len(results)}")
    total_items = sum(r["count"] for r in results)
    print(f"  视频数: {total_items}")

    return 0
