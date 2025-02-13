import json
import logging
import requests
from collections.abc import Generator
from typing import cast

from tencentcloud.common import credential  # type: ignore
from tencentcloud.common.exception import TencentCloudSDKException  # type: ignore
from tencentcloud.common.profile.client_profile import ClientProfile  # type: ignore
from tencentcloud.common.profile.http_profile import HttpProfile  # type: ignore
from tencentcloud.hunyuan.v20230901 import hunyuan_client, models  # type: ignore

from core.model_runtime.entities.llm_entities import LLMResult, LLMResultChunk, LLMResultChunkDelta
from core.model_runtime.entities.message_entities import (
    AssistantPromptMessage,
    ImagePromptMessageContent,
    PromptMessage,
    PromptMessageContentType,
    PromptMessageTool,
    SystemPromptMessage,
    TextPromptMessageContent,
    ToolPromptMessage,
    UserPromptMessage,
)
from core.model_runtime.errors.invoke import InvokeError
from core.model_runtime.errors.validate import CredentialsValidateFailedError
from core.model_runtime.model_providers.__base.large_language_model import LargeLanguageModel

logger = logging.getLogger(__name__)


class HunyuanLargeLanguageModel(LargeLanguageModel):
    def __init__(self):
        super().__init__()
        self.url = "http://hunyuanapi.woa.com/openapi/v1/chat/completions"

    def _invoke(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        user: str | None = None,
    ) -> LLMResult | Generator:
        # client = self._setup_hunyuan_client(credentials)
        # request = models.ChatCompletionsRequest()
        messages_dict = self._convert_prompt_messages_to_dicts(prompt_messages)
        custom_parameters = {
            "Temperature": model_parameters.get("temperature", 0.0),
            "TopP": model_parameters.get("top_p", 1.0),
            "EnableEnhancement": model_parameters.get("enable_enhance", True),
        }

        params = {
            "Model": model,
            "Messages": messages_dict,
            "Stream": stream,
            "Stop": stop,
            **custom_parameters,
        }
        # add Tools and ToolChoice
        if tools and len(tools) > 0:
            params["ToolChoice"] = "auto"
            params["Tools"] = [
                {
                    "Type": "function",
                    "Function": {
                        "Name": tool.name,
                        "Description": tool.description,
                        "Parameters": json.dumps(tool.parameters),
                    },
                }
                for tool in tools
            ]

        headers = {
            "Authorization": f"Bearer {credentials["api_key"]}",
            "Content-Type": "application/json"
        }        

        response = requests.post(self.url, headers=headers, data=json.dumps(params))
        if response.status_code !=200:
            raise Exception(f"Failed to access LLM API, status code: {response.status_code}, message: {response.text}")

        # request.from_json_string(json.dumps(params))
        # response = client.ChatCompletions(request)

        if stream:
            return self._handle_stream_chat_response(model, credentials, prompt_messages, 
                                                     self._process_response_sse(response))

        return self._handle_chat_response(credentials, model, prompt_messages, response.json)

    def validate_credentials(self, model: str, credentials: dict) -> None:
        """
        Validate credentials
        """
        try:
            params = {
                "Model": model,
                "Messages": [{"Role": "user", "Content": "hello"}],
                "TopP": 1,
                "Temperature": 0,
                "Stream": False,
            }

            headers = {
            "Authorization": f"Bearer {credentials["api_key"]}",
            "Content-Type": "application/json"
            }    

            response = requests.post(self.url, headers=headers, data=json.dumps(params))
            if response.status_code !=200:
                raise Exception(f"Failed to access LLM API, status code: {response.status_code}, message: {response.text}")

        except Exception as e:
            raise CredentialsValidateFailedError(f"Credentials validation failed: {e}")

    def _setup_hunyuan_client(self, credentials):
        secret_id = credentials["secret_id"]
        secret_key = credentials["secret_key"]
        cred = credential.Credential(secret_id, secret_key)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "hunyuan.tencentcloudapi.com"
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        client = hunyuan_client.HunyuanClient(cred, "", clientProfile)
        return client

    def _convert_prompt_messages_to_dicts(self, prompt_messages: list[PromptMessage]) -> list[dict]:
        """Convert a list of PromptMessage objects to a list of dictionaries with 'Role' and 'Content' keys."""
        dict_list = []
        for message in prompt_messages:
            if isinstance(message, AssistantPromptMessage):
                tool_calls = message.tool_calls
                if tool_calls and len(tool_calls) > 0:
                    dict_tool_calls = [
                        {
                            "Id": tool_call.id,
                            "Type": tool_call.type,
                            "Function": {
                                "Name": tool_call.function.name,
                                "Arguments": tool_call.function.arguments
                                if (tool_call.function.arguments == "")
                                else "{}",
                            },
                        }
                        for tool_call in tool_calls
                    ]

                    dict_list.append(
                        {
                            "Role": message.role.value,
                            # fix set content = "" while tool_call request
                            # fix [hunyuan] None, [TencentCloudSDKException] code:InvalidParameter
                            # message:Messages Content and Contents not allowed empty at the same time.
                            "Content": " ",  # message.content if (message.content is not None) else "",
                            "ToolCalls": dict_tool_calls,
                        }
                    )
                else:
                    dict_list.append({"Role": message.role.value, "Content": message.content})
            elif isinstance(message, ToolPromptMessage):
                tool_execute_result = {"result": message.content}
                content = json.dumps(tool_execute_result, ensure_ascii=False)
                dict_list.append({"Role": message.role.value, "Content": content, "ToolCallId": message.tool_call_id})
            elif isinstance(message, UserPromptMessage):
                message = cast(UserPromptMessage, message)
                if isinstance(message.content, str):
                    dict_list.append({"Role": message.role.value, "Content": message.content})
                else:
                    sub_messages = []
                    for message_content in message.content:
                        if message_content.type == PromptMessageContentType.TEXT:
                            message_content = cast(TextPromptMessageContent, message_content)
                            sub_message_dict = {"Type": "text", "Text": message_content.data}
                            sub_messages.append(sub_message_dict)
                        elif message_content.type == PromptMessageContentType.IMAGE:
                            message_content = cast(ImagePromptMessageContent, message_content)
                            sub_message_dict = {
                                "Type": "image_url",
                                "ImageUrl": {"Url": message_content.data},
                            }
                            sub_messages.append(sub_message_dict)
                    dict_list.append({"Role": message.role.value, "Contents": sub_messages})
            else:
                dict_list.append({"Role": message.role.value, "Content": message.content})
        return dict_list

    def _handle_stream_chat_response(self, model, credentials, prompt_messages, resp):
        tool_call = None
        tool_calls = []

        for index, event in enumerate(resp):
            logging.debug("_handle_stream_chat_response, event: %s", event)

            data_str = event["data"]
            if data_str.endswith("[DONE]"):
                continue
            data = json.loads(data_str)

            choices = data.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta", {})
            message_content = delta.get("content", "")
            finish_reason = choice.get("finish_reason", "")

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            response_tool_calls = delta.get("tool_calls")
            if response_tool_calls is not None:
                new_tool_calls = self._extract_response_tool_calls(response_tool_calls)
                if len(new_tool_calls) > 0:
                    new_tool_call = new_tool_calls[0]
                    if tool_call is None:
                        tool_call = new_tool_call
                    elif tool_call.id != new_tool_call.id:
                        tool_calls.append(tool_call)
                        tool_call = new_tool_call
                    else:
                        tool_call.function.name += new_tool_call.function.name
                        tool_call.function.arguments += new_tool_call.function.arguments
                if tool_call is not None and len(tool_call.function.name) > 0 and len(tool_call.function.arguments) > 0:
                    tool_calls.append(tool_call)
                    tool_call = None

            assistant_prompt_message = AssistantPromptMessage(content=message_content, tool_calls=[])
            # rewrite content = "" while tool_call to avoid show content on web page
            if len(tool_calls) > 0:
                assistant_prompt_message.content = ""

            # add tool_calls to assistant_prompt_message
            if finish_reason == "tool_calls":
                assistant_prompt_message.tool_calls = tool_calls
                tool_call = None
                tool_calls = []

            if len(finish_reason) > 0:
                usage = self._calc_response_usage(model, credentials, prompt_tokens, completion_tokens)

                delta_chunk = LLMResultChunkDelta(
                    index=index,
                    role=delta.get("role", "assistant"),
                    message=assistant_prompt_message,
                    usage=usage,
                    finish_reason=finish_reason,
                )
                tool_call = None
                tool_calls = []

            else:
                delta_chunk = LLMResultChunkDelta(
                    index=index,
                    message=assistant_prompt_message,
                )

            yield LLMResultChunk(
                model=model,
                prompt_messages=prompt_messages,
                delta=delta_chunk,
            )

    def _handle_chat_response(self, credentials, model, prompt_messages, response):
        usage = self._calc_response_usage(
            model, credentials, response.usage.prompt_tokens, response.usage.completion_tokens
        )
        assistant_prompt_message = AssistantPromptMessage()
        assistant_prompt_message.content = response.choices[0].message.content
        result = LLMResult(
            model=model,
            prompt_messages=prompt_messages,
            message=assistant_prompt_message,
            usage=usage,
        )

        return result

    def get_num_tokens(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        tools: list[PromptMessageTool] | None = None,
    ) -> int:
        if len(prompt_messages) == 0:
            return 0
        prompt = self._convert_messages_to_prompt(prompt_messages)
        return self._get_num_tokens_by_gpt2(prompt)

    def _convert_messages_to_prompt(self, messages: list[PromptMessage]) -> str:
        """
        Format a list of messages into a full prompt for the Anthropic model

        :param messages: List of PromptMessage to combine.
        :return: Combined string with necessary human_prompt and ai_prompt tags.
        """
        messages = messages.copy()  # don't mutate the original list

        text = "".join(self._convert_one_message_to_text(message) for message in messages)

        # trim off the trailing ' ' that might come from the "Assistant: "
        return text.rstrip()

    def _convert_one_message_to_text(self, message: PromptMessage) -> str:
        """
        Convert a single message to a string.

        :param message: PromptMessage to convert.
        :return: String representation of the message.
        """
        human_prompt = "\n\nHuman:"
        ai_prompt = "\n\nAssistant:"
        tool_prompt = "\n\nTool:"
        content = message.content

        if isinstance(message, UserPromptMessage):
            message_text = f"{human_prompt} {content}"
        elif isinstance(message, AssistantPromptMessage):
            message_text = f"{ai_prompt} {content}"
        elif isinstance(message, ToolPromptMessage):
            message_text = f"{tool_prompt} {content}"
        elif isinstance(message, SystemPromptMessage):
            message_text = content if isinstance(content, str) else ""
        else:
            raise ValueError(f"Got unknown type {message}")

        return message_text

    @property
    def _invoke_error_mapping(self) -> dict[type[InvokeError], list[type[Exception]]]:
        """
        Map model invoke error to unified error
        The key is the error type thrown to the caller
        The value is the error type thrown by the model,
        which needs to be converted into a unified error type for the caller.

        :return: Invoke error mapping
        """
        return {
            InvokeError: [TencentCloudSDKException],
        }

    def _extract_response_tool_calls(self, response_tool_calls: list[dict]) -> list[AssistantPromptMessage.ToolCall]:
        """
        Extract tool calls from response

        :param response_tool_calls: response tool calls
        :return: list of tool calls
        """
        tool_calls = []
        if response_tool_calls:
            for response_tool_call in response_tool_calls:
                response_function = response_tool_call.get("function", {})
                function = AssistantPromptMessage.ToolCall.ToolCallFunction(
                    name=response_function.get("name", ""), arguments=response_function.get("arguments", "")
                )

                tool_call = AssistantPromptMessage.ToolCall(
                    id=response_tool_call.get("id", 0), type="function", function=function
                )
                tool_calls.append(tool_call)

        return tool_calls

    @staticmethod
    def _process_response_sse(resp):
       
        e = {}

        for line in resp.iter_lines():
            if not line:
                yield e
                e = {}
                continue

            line = line.decode('utf-8')

            # comment
            if line[0] == ':':
                continue

            colon_idx = line.find(':')
            key = line[:colon_idx]
            val = line[colon_idx + 1:]
            if key == 'data':
                # The spec allows for multiple data fields per event, concatenated them with "\n".
                if 'data' not in e:
                    e['data'] = val
                else:
                    e['data'] += '\n' + val
            elif key in ('event', 'id'):
                e[key] = val
            elif key == 'retry':
                e[key] = int(val)

    def _create_final_llm_result_chunk(
        self,
        index: int,
        message: AssistantPromptMessage,
        finish_reason: str,
        usage: dict,
        model: str,
        prompt_messages: list[PromptMessage],
        credentials: dict,
        full_content: str,
    ) -> LLMResultChunk:
        # calculate num tokens
        prompt_tokens = usage and usage.get("prompt_tokens")
        if prompt_tokens is None:
            prompt_tokens = self.get_num_tokens(text=prompt_messages[0].content)
        completion_tokens = usage and usage.get("completion_tokens")
        if completion_tokens is None:
            completion_tokens = self.get_num_tokens(text=full_content)

        # transform usage
        usage = self._calc_response_usage(model, credentials, prompt_tokens, completion_tokens)

        return LLMResultChunk(
            model=model,
            prompt_messages=prompt_messages,
            delta=LLMResultChunkDelta(index=index, message=message, finish_reason=finish_reason, usage=usage),
        )