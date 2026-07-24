from enum import Enum


class PluginCapability(str, Enum):
    USER_INTENT_INTERPRETER = "user_intent_interpreter"
    COMMAND_HANDLER = "command_handler"
    ACTIVITY_PROVIDER = "activity_provider"
    PROMPT_CONTEXT_PROVIDER = "prompt_context_provider"
    MEMORY_POLICY_PROVIDER = "memory_policy_provider"
