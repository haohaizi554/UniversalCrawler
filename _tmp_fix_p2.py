# -*- coding: utf-8 -*-
import sys

p1 = r'd:\desktop\project\UniversalCrawlerProplus\app\core\guardrails\crawl_budget.py'
with open(p1, 'rb') as f:
    data = f.read()
old1 = b'        normalized_amount = max(1, int(amount))\n'
new1 = (
    b'        normalized_amount = int(amount)\n'
    b'        if normalized_amount <= 0:\n'
    b'            raise ValueError(f"consume amount must be positive, got {amount}")\n'
)
assert data.count(old1) == 1, 'crawl_budget: expected 1 match, got %d' % data.count(old1)
data = data.replace(old1, new1, 1)
with open(p1, 'wb') as f:
    f.write(data)
print('P2-4 crawl_budget.py: OK')

p2 = r'd:\desktop\project\UniversalCrawlerProplus\app\core\guardrails\rate_limiter.py'
with open(p2, 'rb') as f:
    data = f.read()
old2 = b'        self.tokens_per_second = max(0.01, float(tokens_per_second))\n'
new2 = (
    b'        self.tokens_per_second = float(tokens_per_second)\n'
    b'        if self.tokens_per_second <= 0:\n'
    b'            raise ValueError(f"tokens_per_second must be positive, got {tokens_per_second}")\n'
)
assert data.count(old2) == 1, 'rate_limiter: expected 1 match, got %d' % data.count(old2)
data = data.replace(old2, new2, 1)
with open(p2, 'wb') as f:
    f.write(data)
print('P2-5 rate_limiter.py: OK')

p3 = r'd:\desktop\project\UniversalCrawlerProplus\app\services\app_state.py'
with open(p3, 'rb') as f:
    data = f.read()
old3 = (
    b'        if depth >= self.MAX_PUBLISH_DEPTH:\n'
    b'            debug_logger.log(\n'
)
comment = (
    '            # \u6291\u5236\u5206\u652f\u4e0d\u9012\u589e _publish_depth\uff1a_publish_depth \u8ddf\u8e2a\u7684\u662f "app_state.changed"\n'
    '            # \u4e8b\u4ef6\u7684\u9012\u5f52\u6df1\u5ea6\uff0c\u800c\u6b64\u5206\u652f\u53d1\u5e03\u7684\u662f "app_state.publish_suppressed" \u5143\u4e8b\u4ef6\uff0c\n'
    '            # \u4e0d\u5c5e\u4e8e change \u9012\u5f52\u8c03\u7528\u94fe\u3002\u76f4\u63a5 return \u4e0d\u4f1a\u589e\u52a0 change \u9012\u5f52\u6df1\u5ea6\uff0c\n'
    '            # \u56e0\u6b64\u65e0\u9700\u9012\u589e\uff1b\u82e5\u9012\u589e\u53cd\u800c\u4f1a\u5728\u65e0 try/finally \u4fdd\u62a4\u65f6\u5bfc\u81f4\u8ba1\u6570\u6cc4\u6f0f\u3002\n'
)
new3 = (
    b'        if depth >= self.MAX_PUBLISH_DEPTH:\n'
    + comment.encode('utf-8')
    + b'            debug_logger.log(\n'
)
assert data.count(old3) == 1, 'app_state: expected 1 match, got %d' % data.count(old3)
data = data.replace(old3, new3, 1)
with open(p3, 'wb') as f:
    f.write(data)
print('P2-6 app_state.py: OK')

print('All edits applied successfully.')