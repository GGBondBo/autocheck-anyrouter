"""
飞书卡片 v2 真实发送测试
运行方式：python tests/test_feishu_card_v2.py
"""

import asyncio
import sys
import types
from dataclasses import dataclass
from pathlib import Path

# ── 添加 src 到路径 ──────────────────────────────────────────────
src = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(src))

# ── 预注册 stub，阻止 __init__.py 触发额外依赖 ───────────────────
for pkg in ['core', 'notif']:
	if pkg not in sys.modules:
		sys.modules[pkg] = types.ModuleType(pkg)


# ── 直接定义所需数据类 ──────────────────────────────────────────
@dataclass
class AccountResult:
	name: str
	status: str
	quota: float | None = None
	used: float | None = None
	balance_changed: bool | None = None
	error: str | None = None


@dataclass
class NotificationStats:
	success_count: int
	failed_count: int
	total_count: int


@dataclass
class NotificationTemplate:
	title: str | None = None
	content: str = ''


@dataclass
class WebhookConfig:
	webhook: str
	platform_settings: dict | None = None
	template: NotificationTemplate | None = None


# ── 注册到 sys.modules 供 feishu_sender.py 的 import 解析 ───────
_notif_models = types.ModuleType('notif.models')
_notif_models.WebhookConfig = WebhookConfig  # type: ignore[attr-defined]
sys.modules['notif.models'] = _notif_models
sys.modules['notif.models.webhook_config'] = types.SimpleNamespace(WebhookConfig=WebhookConfig)  # type: ignore[assignment]

# ── 导入 FeishuSender（直接加载文件，不走包 __init__）─────────────
import importlib.util

_spec = importlib.util.spec_from_file_location(
	'feishu_sender',
	src / 'notif/senders/feishu_sender.py',
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
FeishuSender = _mod.FeishuSender

# ── 测试数据 webhook URL ────────────────────────────────────────
WEBHOOK_URL = 'https://open.feishu.cn/open-apis/bot/v2/hook/2e1fef62-02ba-4b6e-a69a-99488f21f038'


def build_context(accounts: list) -> dict:
	success_accounts = [a for a in accounts if a.status == 'success']
	failed_accounts = [a for a in accounts if a.status != 'success']
	success_count = len(success_accounts)
	failed_count = len(failed_accounts)
	stats = NotificationStats(
		success_count=success_count,
		failed_count=failed_count,
		total_count=len(accounts),
	)
	return {
		'stats': stats,
		'timestamp': '2026-03-05 10:30:00',
		'success_accounts': success_accounts,
		'failed_accounts': failed_accounts,
		'all_success': failed_count == 0,
		'all_failed': success_count == 0,
		'partial_success': success_count > 0 and failed_count > 0,
	}


async def run(label: str, accounts: list):
	print(f'\n=== 测试：{label} ===')
	config = WebhookConfig(
		webhook=WEBHOOK_URL,
		platform_settings={'message_type': 'card_v2'},
	)
	ctx = build_context(accounts)
	await FeishuSender(config).send(title='Anyrouter签到结果通知', content='', context_data=ctx)
	print('✅ 发送成功')


async def main():
	await run(
		'全部成功',
		[
			AccountResult(name='user-abc@gmail.com', status='success', quota=28.5123, used=1.4877),
			AccountResult(name='user-xyz@gmail.com', status='success', quota=30.0000, used=0.0000),
		],
	)
	await run(
		'部分成功',
		[
			AccountResult(name='user-abc@gmail.com', status='success', quota=28.5123, used=1.4877),
			AccountResult(name='user-xyz@gmail.com', status='failed', error='登录失败：Cookie 已过期'),
		],
	)
	await run(
		'全部失败',
		[
			AccountResult(name='user-abc@gmail.com', status='failed', error='网络连接超时'),
			AccountResult(name='user-xyz@gmail.com', status='failed', error='认证失败：Token 无效'),
		],
	)
	print('\n所有测试完成！')


if __name__ == '__main__':
	asyncio.run(main())
