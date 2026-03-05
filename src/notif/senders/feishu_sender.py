from typing import Any

import httpx
import stencil

from notif.models import WebhookConfig
from tools.logger import logger


class FeishuSender:
	def __init__(self, config: WebhookConfig):
		"""
		初始化飞书发送器

		Args:
			config: 飞书 Webhook 配置
		"""
		self.config = config

	async def send(self, title: str | None, content: str, context_data: dict | None = None):
		"""
		发送飞书消息

		Args:
			title: 消息标题，为 None 或空字符串时不展示标题
			content: 消息内容
			context_data: 模板渲染的上下文数据

		Raises:
			Exception: 当 HTTP 响应状态码不是 2xx 时抛出异常
		"""
		# 获取消息类型（确保 platform_settings 不为 None）
		platform_settings = self.config.platform_settings or {}
		configured_type = platform_settings.get('message_type')

		# 确定消息类型：只接受 card 和 card_v2，其他情况使用 text
		is_card = configured_type in ['card', 'card_v2']
		message_type = configured_type if is_card else 'text'

		# 动态渲染 color_theme（如果包含模板语法）
		# 默认根据签到结果自动选择颜色（全部成功=绿色，部分成功=橙色，全部失败=红色）
		default_color_theme = (
			'{% if all_success %}green{% else %}{% if partial_success %}orange{% else %}red{% endif %}{% endif %}'
		)
		color_theme = platform_settings.get('color_theme') or default_color_theme
		if context_data and ('{%' in color_theme or '{{' in color_theme):
			try:
				template_obj = stencil.Template(color_theme)
				context = stencil.Context(context_data)
				rendered = template_obj.render(context)
				if rendered:
					color_theme = rendered.strip()
			except Exception as e:
				logger.warning(f'渲染 color_theme 失败（{e}），使用原始值：{color_theme}')

		# 构建请求数据
		if is_card:
			if message_type == 'card_v2':
				card_data = self._build_rich_card_v2(
					title=title,
					color_theme=color_theme,
					context_data=context_data or {},
				)
			else:
				# card v1: 简单 markdown 卡片
				card_data: dict[str, Any] = {
					'elements': [
						{
							'tag': 'markdown',
							'content': content,
							'text_align': 'left',
						},
					],
				}
				if title:
					card_data['header'] = {
						'template': color_theme,
						'title': {
							'content': title,
							'tag': 'plain_text',
						},
					}

			data = {
				'msg_type': 'interactive',
				'card': card_data,
			}
		else:
			# 纯文本模式
			text_content = f'{title}\n{content}' if title else content
			data = {
				'msg_type': 'text',
				'content': {'text': text_content},
			}

		async with httpx.AsyncClient(timeout=30.0) as client:
			response = await client.post(self.config.webhook, json=data)

			# 检查响应状态码
			if not response.is_success:
				raise Exception(f'飞书推送失败，HTTP 状态码：{response.status_code}，响应内容：{response.text[:200]}')

			# 检查飞书 API 响应体中的错误码（HTTP 200 也可能包含业务错误）
			try:
				result = response.json()
				code = result.get('code')
				if code != 0:
					raise Exception(
						f'飞书推送失败，错误码：{code}，消息：{result.get("msg", "")}，响应：{response.text[:200]}'
					)
			except Exception as e:
				if '飞书推送失败' in str(e):
					raise
				# 响应体不是 JSON，忽略解析错误

	def _build_rich_card_v2(
		self,
		title: str | None,
		color_theme: str,
		context_data: dict,
	) -> dict:
		"""构建飞书卡片 JSON 2.0 富文本消息"""
		all_success = context_data.get('all_success', False)
		partial_success = context_data.get('partial_success', False)
		stats = context_data.get('stats')
		timestamp = context_data.get('timestamp', '')
		success_accounts = context_data.get('success_accounts', [])
		failed_accounts = context_data.get('failed_accounts', [])

		success_count = stats.success_count if stats else 0
		failed_count = stats.failed_count if stats else 0
		total_count = stats.total_count if stats else 0

		# 状态文字和 header icon
		if all_success:
			status_text = '**✅ 所有账号全部签到成功！**'
			icon_token = 'check-circle_outlined'
			success_color = 'green'
		elif partial_success:
			status_text = '**⚠️ 部分账号签到成功**'
			icon_token = 'alert-circle_outlined'
			success_color = 'orange'
		else:
			status_text = '**❌ 所有账号签到失败**'
			icon_token = 'close-circle_outlined'
			success_color = 'red'

		elements = []

		# 状态文字
		elements.append({
			'content': status_text,
			'margin': '0px',
			'tag': 'markdown',
			'text_size': 'normal',
		})

		# 统计列（成功比例 / 失败比例）
		elements.append({
			'columns': [
				{
					'background_style': 'grey-50',
					'elements': [
						{
							'content': f"## <font color='{success_color}'>{success_count}/{total_count}</font>",
							'tag': 'markdown',
							'text_align': 'center',
						},
						{
							'content': "<font color='grey'>成功比例</font>",
							'tag': 'markdown',
							'text_align': 'center',
							'text_size': 'normal',
						},
					],
					'horizontal_align': 'left',
					'padding': '12px 12px 12px 12px',
					'tag': 'column',
					'vertical_align': 'top',
					'vertical_spacing': '8px',
					'weight': 1,
					'width': 'weighted',
				},
				{
					'background_style': 'grey-50',
					'elements': [
						{
							'content': f"## <font color='red'>{failed_count}/{total_count}</font>",
							'tag': 'markdown',
							'text_align': 'center',
						},
						{
							'content': "<font color='grey'>失败比例</font>",
							'tag': 'markdown',
							'text_align': 'center',
							'text_size': 'normal',
						},
					],
					'horizontal_align': 'left',
					'padding': '12px 12px 12px 12px',
					'tag': 'column',
					'vertical_align': 'top',
					'vertical_spacing': '8px',
					'weight': 1,
					'width': 'weighted',
				},
			],
			'flex_mode': 'stretch',
			'horizontal_align': 'left',
			'horizontal_spacing': '12px',
			'margin': '0px',
			'tag': 'column_set',
		})

		# 图片
		elements.append({
			'corner_radius': '8px',
			'fallback_img_key': 'img_v3_02r5_d46c633a-f0e7-458a-959e-670863031d5g',
			'img_key': 'img_v3_02vg_0fb92bdd-67f8-4792-80f7-22946491635g',
			'margin': '0px',
			'scale_type': 'fit_horizontal',
			'tag': 'img',
		})

		# 执行时间
		elements.append({
			'content': f'**执行时间** ：{timestamp}',
			'margin': '0px',
			'tag': 'markdown',
			'text_size': 'normal',
		})

		# 成功账号表格（只在有成功账号时显示）
		if success_accounts:
			success_rows = []
			for acc in success_accounts:
				success_rows.append({
					'account': acc.name,
					'used': f'{acc.used:.4f}' if acc.used is not None else '-',
					'quota': f'{acc.quota:.4f}' if acc.quota is not None else '-',
				})
			elements.append({
				'columns': [
					{
						'data_type': 'text',
						'display_name': '账号',
						'horizontal_align': 'left',
						'name': 'account',
						'width': 'auto',
					},
					{
						'data_type': 'text',
						'display_name': '已用（$）',
						'horizontal_align': 'left',
						'name': 'used',
						'width': 'auto',
					},
					{
						'data_type': 'text',
						'display_name': '剩余（$）',
						'horizontal_align': 'left',
						'name': 'quota',
						'width': 'auto',
					},
				],
				'header_style': {'background_style': 'none', 'bold': True},
				'margin': '0px',
				'rows': success_rows,
				'tag': 'table',
			})

		# 失败账号表格（只在有失败账号时显示）
		if failed_accounts:
			failed_rows = [{'account': acc.name, 'error': acc.error or '未知错误'} for acc in failed_accounts]
			elements.append({
				'columns': [
					{
						'data_type': 'text',
						'display_name': '账号',
						'horizontal_align': 'left',
						'name': 'account',
						'width': 'auto',
					},
					{
						'data_type': 'text',
						'display_name': '错误原因',
						'horizontal_align': 'left',
						'name': 'error',
						'width': 'auto',
					},
				],
				'header_style': {'background_style': 'none', 'bold': True},
				'margin': '0px',
				'rows': failed_rows,
				'tag': 'table',
			})

		# 查看报告按钮
		elements.append({
			'behaviors': [
				{
					'android_url': '',
					'default_url': 'https://anyrouter.top/console',
					'ios_url': '',
					'pc_url': '',
					'type': 'open_url',
				}
			],
			'margin': '4px 0px 4px 0px',
			'tag': 'button',
			'text': {
				'content': '查看详细报告',
				'tag': 'plain_text',
			},
			'type': 'primary_filled',
			'width': 'fill',
		})

		return {
			'schema': '2.0',
			'config': {'update_multi': True},
			'header': {
				'icon': {
					'tag': 'standard_icon',
					'token': icon_token,
				},
				'padding': '12px 16px 12px 16px',
				'subtitle': {
					'content': '',
					'tag': 'plain_text',
				},
				'template': color_theme,
				'title': {
					'content': title or 'Anyrouter签到结果通知',
					'tag': 'plain_text',
				},
			},
			'body': {
				'direction': 'vertical',
				'elements': elements,
			},
		}
