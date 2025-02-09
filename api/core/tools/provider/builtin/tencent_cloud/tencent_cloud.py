from typing import Any

from core.tools.errors import ToolProviderCredentialValidationError
from core.tools.provider.builtin_tool_provider import BuiltinToolProviderController
from core.tools.provider.builtin.tencent_cloud.tools.tencent_cls import TencentClsTool

class TencentCloudProvider(BuiltinToolProviderController):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        # try:
        #     TencentClsTool().fork_tool_runtime(
        #         runtime={
        #             "credentials": credentials,
        #         }
        #     ).invoke(user_id="", tool_parameters={"topicid": "topicid", "query": "query", "region": "region", "from": "from", "to": "to"})
        # except Exception as e:
        #     raise ToolProviderCredentialValidationError(str(e))
        TencentClsTool()