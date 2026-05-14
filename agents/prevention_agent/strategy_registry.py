"""
agents/prevention_agent/strategy_registry.py
─────────────────────────────────────────────────────────────────
Central registry that maps every DarkPatternCode to its strategy class.

Usage:
    strategy = STRATEGY_REGISTRY.get("DP01")
    if strategy:
        patches = await strategy.build_patches(evidence, enrichment)
"""
from __future__ import annotations

from agents.prevention_agent.strategies.base import BaseStrategy
from agents.prevention_agent.strategies.dp01_false_urgency          import FalseUrgencyStrategy
from agents.prevention_agent.strategies.dp02_confirm_shaming        import ConfirmShamingStrategy
from agents.prevention_agent.strategies.dp03_disguised_ads          import DisguisedAdsStrategy
from agents.prevention_agent.strategies.dp04_trick_question         import TrickQuestionStrategy
from agents.prevention_agent.strategies.dp05_drip_pricing           import DripPricingStrategy
from agents.prevention_agent.strategies.dp06_bait_switch            import BaitSwitchStrategy
from agents.prevention_agent.strategies.dp07_basket_sneaking        import BasketSneakingStrategy
from agents.prevention_agent.strategies.dp08_subscription_trap      import SubscriptionTrapStrategy
from agents.prevention_agent.strategies.dp09_nagging                import NaggingStrategy
from agents.prevention_agent.strategies.dp10_saas_billing           import SaasBillingStrategy
from agents.prevention_agent.strategies.dp11_rogue_malicious        import RogueMaliciousStrategy
from agents.prevention_agent.strategies.dp12_interface_interference import InterfaceInterferenceStrategy
from agents.prevention_agent.strategies.dp13_forced_action          import ForcedActionStrategy

# Maps pattern_code → instantiated strategy object
STRATEGY_REGISTRY: dict[str, BaseStrategy] = {
    "DP01": FalseUrgencyStrategy(),
    "DP02": ConfirmShamingStrategy(),
    "DP03": DisguisedAdsStrategy(),
    "DP04": TrickQuestionStrategy(),
    "DP05": DripPricingStrategy(),
    "DP06": BaitSwitchStrategy(),
    "DP07": BasketSneakingStrategy(),
    "DP08": SubscriptionTrapStrategy(),
    "DP09": NaggingStrategy(),
    "DP10": SaasBillingStrategy(),
    "DP11": RogueMaliciousStrategy(),
    "DP12": InterfaceInterferenceStrategy(),
    "DP13": ForcedActionStrategy(),
}
