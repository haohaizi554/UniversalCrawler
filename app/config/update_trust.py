"""桌面自动更新器随客户端发布的只读信任策略。

Ed25519 公钥用于验证 ``latest.json``，是当前更新链路始终启用的信任根。
操作系统发布者身份是额外一层校验；取得正式代码签名证书后，可填写公开
身份并启用对应开关。私有签名材料必须始终保存在客户端和仓库之外。
"""

UPDATE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAP2blm/H8iLEcpLyGQeojydA5pkIBANH3nIdnPxeo6S8=
-----END PUBLIC KEY-----"""

# 个人发布阶段暂未配置受信代码签名证书，因此只暂停系统发布者身份校验。
# 安装包大小和 SHA-256 仍由上方 Ed25519 签名清单强制约束。取得证书后，
# 填写发布者与证书指纹，并将此值改为 True 即可恢复现有 Authenticode 接口。
UPDATE_REQUIRE_OS_SIGNATURE = False
UPDATE_TRUSTED_PUBLISHERS: tuple[str, ...] = ()
UPDATE_TRUSTED_THUMBPRINTS: tuple[str, ...] = ()
