"""LLM agent'lar — CEO, Researcher, Analyst, Lab Scientist, Ops Engineer, Risk Officer.

Tüm agent'lar ``LLMAgentBase``'ten türer. Her birinin SOP'leri kendi modülünde.

Kullanım:
    from price_action.agents import CEOAgent

    ceo = CEOAgent()
    text = await ceo.run("Bugünkü brief'i hazırla")
"""

from __future__ import annotations

from .adversary_engineer import AdversaryEngineerAgent
from .analyst import AnalystAgent
from .audit_base import AuditAgentBase
from .audit_chief import AuditChiefAgent
from .audit_data import AuditDataAgent
from .audit_execution import AuditExecutionAgent
from .audit_ops import AuditOpsAgent
from .audit_research import AuditResearchAgent
from .audit_risk import AuditRiskAgent
from .base import LLMAgentBase, LLMResponse
from .bot_monitor import BotMonitorAgent
from .ceo import CEOAgent
from .data_engineer import DataEngineerAgent
from .lab_scientist import LabScientistAgent
from .market_scout import MarketScoutAgent
from .ops_engineer import OpsAgent
from .researcher import ResearcherAgent
from .risk_officer import RiskOfficerAgent
from .strategy_curator import StrategyCuratorAgent

__all__ = [
    "AdversaryEngineerAgent",
    "AnalystAgent",
    "AuditAgentBase",
    "AuditChiefAgent",
    "AuditDataAgent",
    "AuditExecutionAgent",
    "AuditOpsAgent",
    "AuditResearchAgent",
    "AuditRiskAgent",
    "BotMonitorAgent",
    "CEOAgent",
    "DataEngineerAgent",
    "LLMAgentBase",
    "LLMResponse",
    "LabScientistAgent",
    "MarketScoutAgent",
    "OpsAgent",
    "ResearcherAgent",
    "RiskOfficerAgent",
    "StrategyCuratorAgent",
]
