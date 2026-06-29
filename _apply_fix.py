import sys
sys.stdout.reconfigure(encoding="utf-8")

p1 = r"d:\desktop\project\UniversalCrawlerProplus\app\core\guardrails\crawl_budget.py"
with open(p1, "rb") as f:
    data1 = f.read()

old1 = 'class BudgetExhausted(RuntimeError):\n    """Raised when a crawl would exceed its configured request budget."""\n'.encode("utf-8")
new1 = 'class BudgetExhausted(RuntimeError):\n    """Raised when a crawl would exceed its configured request budget."""\n\n\nclass RateLimitCancelled(Exception):\n    """\u9650\u901f\u5668\u4e3b\u52a8\u53d6\u6d88\u8bf7\u6c42\uff08\u533a\u522b\u4e8e\u9884\u7b97\u8017\u5c3d\uff09\u3002"""\n    pass\n'.encode("utf-8")

c1 = data1.count(old1)
print("crawl_budget.py: found", c1, "occurrence(s) of BudgetExhausted class def")
if c1 != 1:
    print("ERROR: expected 1")
    sys.exit(1)
data1 = data1.replace(old1, new1, 1)
with open(p1, "wb") as f:
    f.write(data1)
print("crawl_budget.py: OK")

p2 = r"d:\desktop\project\UniversalCrawlerProplus\app\spiders\base.py"
with open(p2, "rb") as f:
    data2 = f.read()

old_imp = "from app.core.guardrails import BudgetExhausted, CrawlBudget, RateLimiter, sanitize\r\n".encode("utf-8")
new_imp = "from app.core.guardrails import BudgetExhausted, CrawlBudget, RateLimiter, sanitize\r\nfrom app.core.guardrails.crawl_budget import RateLimitCancelled\r\n".encode("utf-8")
c2a = data2.count(old_imp)
print("base.py import: found", c2a)
if c2a != 1:
    print("ERROR: expected 1 import")
    sys.exit(1)
data2 = data2.replace(old_imp, new_imp, 1)
print("base.py import: OK")

old_g = '        if allowed is False:\r\n            raise BudgetExhausted(f"Request cancelled before rate-limit permit for {platform}.")\r\n'.encode("utf-8")
new_g = '        if allowed is False:\r\n            raise RateLimitCancelled(f"Request cancelled before rate-limit permit for {platform}.")\r\n'.encode("utf-8")
c2b = data2.count(old_g)
print("base.py guard: found", c2b)
if c2b != 1:
    print("ERROR: expected 1 guard")
    sys.exit(1)
data2 = data2.replace(old_g, new_g, 1)
print("base.py guard: OK")

old_run = '        try:\r\n            self._run_impl()\r\n        except Exception:\r\n            import logging\r\n            logging.getLogger(__name__).exception("Spider _run_impl failed")\r\n        finally:\r\n            self.sig_finished.emit()\r\n'.encode("utf-8")
new_run = '        try:\r\n            self._run_impl()\r\n        except BudgetExhausted:\r\n            import logging\r\n            logging.getLogger(__name__).info("Spider budget exhausted, stopping gracefully.")\r\n        except Exception:\r\n            import logging\r\n            logging.getLogger(__name__).exception("Spider _run_impl failed")\r\n        finally:\r\n            self.sig_finished.emit()\r\n'.encode("utf-8")
c3 = data2.count(old_run)
print("base.py run: found", c3)
if c3 != 1:
    print("ERROR: expected 1 run")
    sys.exit(1)
data2 = data2.replace(old_run, new_run, 1)
print("base.py run: OK")

with open(p2, "wb") as f:
    f.write(data2)
print("base.py: written")
print("ALL DONE")
