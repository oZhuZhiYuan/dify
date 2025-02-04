import json
from core.tools.tool.builtin_tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage

from typing import Any, Dict, List, Union
from dateutil import parser
from core.tools.provider.builtin.tencent_cloud._tencent_cloud_base import YunApiClient

class TencentClsTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
    ) -> Union[ToolInvokeMessage, list[ToolInvokeMessage]]:
        """
        invoke tools
        """
        secret_id = self.runtime.credentials.get("secret_id", "")
        if not secret_id:
            raise ValueError("invalid tencent cls secret_id")
        
        secret_key = self.runtime.credentials.get("secret_key", "")
        if not secret_key:
            raise ValueError("invalid tencent cls secret_key")
        
        topicid = tool_parameters.get("topicid", "")
        if not topicid:
            raise ValueError("Please input topicid")
        
        query = tool_parameters.get("query", "")
        if not query:
            raise ValueError("Please input query")
        
        region = tool_parameters.get("region", "")
        if not region:
            raise ValueError("Please input region")
        
        from_ = tool_parameters.get("from", "")
        if not from_:
            raise ValueError("Please input from")
        
        to = tool_parameters.get("to", "")
        if not to:
            raise ValueError("Please input to")
        
        # from 和 to 从RFC3339 转成Unix时间戳（毫秒）
        from_unix = self.rfc3339_to_unix_timestamp(from_)
        to_unix = self.rfc3339_to_unix_timestamp(to)

        client = YunApiClient("cls.tencentcloudapi.com", "cls", "2020-10-16", secret_id, secret_key, region)
        payload = {
            "TopicId": topicid,
            "From": from_unix,
            "To": to_unix,
            "Query": query,
            "Sort": "asc",
            "Limit": 150,
        }
        try:
            resp = client.send( "SearchLog", payload)
            if 'Error' in resp.get('Response'):
                result_text = resp['Response']['Error']['Message']
                return self.create_text_message(result_text)
            
            result_text = json.dumps(resp['Response']["Results"])
            return self.create_text_message(result_text)
        except Exception as e:
            raise ValueError(f"invoke tencent cls failed: {e}")
        
    
    def rfc3339_to_unix_timestamp(self, rfc3339: str) -> int:
        dt = parser.isoparse(rfc3339)
        return int(dt.timestamp() * 1000)
    
    def generate_query_url(self):
        return
    