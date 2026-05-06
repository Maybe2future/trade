# -*- coding: utf-8 -*-
"""
QVeris API 客户端

当前主要用法：
- search: 搜索合适工具
- execute_query: 用 free-form query 调用工具
- execute_df: 将返回结果中的 markdown 表格解析成 DataFrame
"""

from __future__ import annotations

import io
import json
import logging
import urllib.parse
import urllib.request

import pandas as pd

from config import QVERIS_CONFIG

logger = logging.getLogger(__name__)


class QVerisClient:
    def __init__(self, api_key=None, base_url=None, timeout=None):
        self.api_key = api_key or QVERIS_CONFIG['api_key']
        self.base_url = (base_url or QVERIS_CONFIG['base_url']).rstrip('/')
        self.timeout = timeout or QVERIS_CONFIG['timeout']

    @property
    def enabled(self):
        return bool(QVERIS_CONFIG['enabled'] and self.api_key)

    def _post(self, path, payload):
        if not self.enabled:
            raise RuntimeError('QVeris 未启用或缺少 API Key')

        req = urllib.request.Request(
            f'{self.base_url}{path}',
            data=json.dumps(payload).encode(),
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())

    def search(self, query, limit=5):
        return self._post('/search', {'query': query, 'limit': limit})

    def execute_tool(self, tool_id, parameters):
        qs = urllib.parse.urlencode({'tool_id': tool_id})
        return self._post(f'/tools/execute?{qs}', {'parameters': parameters})

    def execute_query(self, tool_id, query):
        return self.execute_tool(tool_id, {'query': query})

    @staticmethod
    def _extract_markdown_table(payload):
        result = payload.get('result') or {}
        if 'truncated_content' in result:
            try:
                inner = json.loads(result['truncated_content'])
                rows = inner.get('results') or []
                if rows:
                    return rows[0].get('table_markdown')
            except Exception:
                logger.exception('解析 QVeris truncated_content 失败')

        data = result.get('data') or {}
        rows = data.get('results') or []
        if rows:
            return rows[0].get('table_markdown')
        return None

    @staticmethod
    def markdown_table_to_df(markdown):
        if not markdown:
            return pd.DataFrame()

        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        if len(lines) < 2:
            return pd.DataFrame()

        data_lines = []
        for i, line in enumerate(lines):
            if not line.startswith('|') or not line.endswith('|'):
                continue
            if i == 1:
                continue
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            data_lines.append(cells)

        if not data_lines:
            return pd.DataFrame()

        header = data_lines[0]
        rows = data_lines[1:]
        return pd.DataFrame(rows, columns=header)

    def execute_df(self, tool_id, query):
        payload = self.execute_query(tool_id, query)
        markdown = self._extract_markdown_table(payload)
        return self.markdown_table_to_df(markdown)
