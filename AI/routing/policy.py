"""Validation of immutable AI requests against routing policies."""

from __future__ import annotations

from AI.core.models import AIRequest, ProviderCapability

from .exceptions import RequestValidationError
from .models import RoutingPolicy


class RequestPolicyValidator:
    """Apply bounded, deterministic request rules without provider execution."""

    def validate(self, request: AIRequest, policy: RoutingPolicy) -> AIRequest:
        """Return the request when it satisfies the supplied routing policy."""

        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy")
        if len(request.prompt) > policy.maximum_prompt_characters:
            raise RequestValidationError(
                "request prompt exceeds the routing policy maximum"
            )
        if len(request.system_prompt) > policy.maximum_system_prompt_characters:
            raise RequestValidationError(
                "request system prompt exceeds the routing policy maximum"
            )
        required = self.effective_capabilities(request, policy)
        if policy.allowed_capabilities:
            disallowed = tuple(
                item for item in required if item not in policy.allowed_capabilities
            )
            if disallowed:
                names = ", ".join(item.value for item in disallowed)
                raise RequestValidationError(
                    f"request contains policy-disallowed capabilities [{names}]"
                )
        return request

    @staticmethod
    def effective_capabilities(
        request: AIRequest,
        policy: RoutingPolicy,
    ) -> tuple[ProviderCapability, ...]:
        """Return stable request and policy requirements without duplicates."""

        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy")
        return tuple(
            dict.fromkeys(
                (*request.required_capabilities, *policy.required_capabilities)
            )
        )


RoutingPolicyValidator = RequestPolicyValidator


__all__ = ["RequestPolicyValidator", "RoutingPolicyValidator"]
