@echo off
git add . && git commit -m "强制更新：覆盖远程所有内容" && git push --force-with-lease origin main