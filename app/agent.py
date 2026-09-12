from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import re
from time import perf_counter
from urllib.parse import quote

from app.audit import audit_answer
from app.config import get_settings
from app.deepseek_client import refine_with_deepseek
from app.models import EvidenceRecord, RetrievalResult
from app.retrieval import retrieve


VALID_LANGUAGES = {"zh", "en"}
VALID_OUTPUT_STYLES = {"brief", "evidence_brief", "investigation_dossier", "policy_analogy", "timeline"}
MODE_LABELS = {
    "general": {"zh": "综合证据扫描", "en": "General Evidence Scan"},
    "trace_person": {"zh": "追一个人", "en": "Trace a Person"},
    "explore_place": {"zh": "寻一处地", "en": "Explore a Place"},
    "reconstruct_event": {"zh": "还原一件事", "en": "Reconstruct an Event"},
    "read_document": {"zh": "读懂一份文献", "en": "Read a Document"},
    "city_memory": {"zh": "城市记忆漫游", "en": "City Memory Walk"},
    "family_memory": {"zh": "家族线索寻踪", "en": "Family Memory Trace"},
    "shanghai_world": {"zh": "上海与世界专题", "en": "Shanghai and the World"},
    "currency_settlement": {"zh": "货币、信用与结算制度", "en": "Money, Credit, and Settlement Systems"},
    "treaty_ports": {"zh": "口岸、海关与近代金融", "en": "Ports, Customs, and Modern Finance"},
    "silk_road": {"zh": "丝路通道与外交网络", "en": "Silk Road Corridors and Diplomatic Networks"},
    "dynastic_history": {"zh": "王朝制度变迁", "en": "Dynastic Institutional Change"},
    "world_trade": {"zh": "世界贸易比较", "en": "World Trade Comparison"},
    "belt_road": {"zh": "古今通道治理类比", "en": "Historical Corridor-Governance Analogy"},
}
MODE_PROFILES = {
    "general": {
        "zh": {
            "scope": "跨货币、贸易、外交与治理材料做第一轮证据扫描。",
            "lens": "先判断问题属于哪类历史机制，再给出证据链和可疑边界。",
            "focus": ["货币", "贸易", "外交", "治理", "证据"],
        },
        "en": {
            "scope": "Runs a first-pass scan across monetary, trade, diplomatic, and governance records.",
            "lens": "Classifies the historical mechanism first, then returns an evidence chain and uncertainty boundary.",
            "focus": ["money", "trade", "diplomacy", "governance", "evidence"],
        },
    },
    "trace_person": {
        "zh": {
            "scope": "从一个人物姓名、别名或相关线索出发，重建人物、机构、地点、事件和文献网络。",
            "lens": "先做身份与别名消歧，再检查人物与机构、地点、事件、文献之间的证据关系。",
            "focus": ["人物", "传记", "别名", "机构", "地点", "事件", "文献", "数字画像"],
        },
        "en": {
            "scope": "Starts from a person name, alias, or clue and rebuilds a people-organization-place-event-document network.",
            "lens": "Resolve identity and aliases first, then inspect evidence-backed links among people, institutions, places, events, and documents.",
            "focus": ["person", "biography", "alias", "organization", "place", "event", "document", "portrait"],
        },
    },
    "explore_place": {
        "zh": {
            "scope": "从旧址、道路、建筑或地名出发，追踪地点的历史名称、机构占用、人物活动与事件痕迹。",
            "lens": "把地名当作可变化的历史实体，优先检查名称、时间、空间和证据出处。",
            "focus": ["地名", "旧址", "道路", "历史建筑", "空间轨迹", "机构", "事件"],
        },
        "en": {
            "scope": "Starts from an old address, road, building, or place name and traces names, occupants, people, and events.",
            "lens": "Treat the place name as a changing historical entity and verify name, time, space, and source provenance.",
            "focus": ["place", "old address", "road", "historic building", "spatial trace", "organization", "event"],
        },
    },
    "reconstruct_event": {
        "zh": {
            "scope": "从一个历史事件、传闻或片段出发，重建时间线、参与者、地点、影响和证据强弱。",
            "lens": "先拆出事件的时间、地点、人物和因果主张，再逐条绑定证据和反证。",
            "focus": ["事件", "时间线", "人物", "地点", "机构", "因果", "影响", "反证"],
        },
        "en": {
            "scope": "Starts from an event, rumor, or fragment and rebuilds timeline, actors, places, impact, and evidence strength.",
            "lens": "Extract time, place, actor, and causal claims first, then bind each claim to supporting and counter evidence.",
            "focus": ["event", "timeline", "person", "place", "organization", "causality", "impact", "counter-evidence"],
        },
    },
    "read_document": {
        "zh": {
            "scope": "从一本书、档案、报刊、家谱或古籍题名出发，解释文献身份、主题、关联人物和可追溯来源。",
            "lens": "把文献当作证据对象，优先确认题名、版本、馆藏类型、关联实体和可打开来源。",
            "focus": ["文献", "题名", "档案", "古籍", "家谱", "报刊", "版本", "出处"],
        },
        "en": {
            "scope": "Starts from a book, archive, newspaper, genealogy, or ancient-text title and explains identity, themes, people, and sources.",
            "lens": "Treat the document as the evidence object and verify title, version, collection type, linked entities, and openable sources.",
            "focus": ["document", "title", "archive", "rare book", "genealogy", "periodical", "version", "source"],
        },
    },
    "city_memory": {
        "zh": {
            "scope": "从旧地址、街区、建筑、老照片、老地图或城市文化线索出发，生成公众可走读、可分享、可复核的城市记忆档案。",
            "lens": "先把地点线索拆成历史名称、现代位置、关联人物/机构/事件和可打开来源，再标注哪些空间判断仍需地名志或地图复核。",
            "focus": ["城市记忆", "旧地址", "外滩", "南京路", "石库门", "里弄", "老地图", "老照片", "公共文化"],
        },
        "en": {
            "scope": "Starts from an old address, street, building, photo, map, or urban-culture clue and builds a walkable, shareable, verifiable city-memory dossier.",
            "lens": "Split place clues into historical names, modern-location checks, linked people/institutions/events, and openable sources, then mark what still needs gazetteer or map review.",
            "focus": ["city memory", "old address", "Bund", "Nanjing Road", "lilong", "old maps", "old photos", "public culture"],
        },
    },
    "family_memory": {
        "zh": {
            "scope": "从姓氏、家谱、旧住址、校友录、亲属姓名或个人物件出发，把私人线索转化为可复核的公共知识档案。",
            "lens": "先做姓名/地名/文献消歧，再把人物关系、地点迁移、文献来源和待考证项分层呈现。",
            "focus": ["家谱", "族谱", "人名", "祖籍", "旧居", "校友录", "亲属", "人物关系", "文献"],
        },
        "en": {
            "scope": "Starts from a surname, genealogy, old address, alumni list, relative name, or family object and turns a private clue into a verifiable public-knowledge dossier.",
            "lens": "Disambiguate names, places, and documents first, then separate relationship claims, place movement, source provenance, and open verification gaps.",
            "focus": ["genealogy", "surname", "old residence", "alumni list", "relative", "relationship", "document"],
        },
    },
    "shanghai_world": {
        "zh": {
            "scope": "保留原贸易专题积累，聚焦上海与世界之间的货币、口岸、商人、海关、银行和航运网络。",
            "lens": "把贸易、金融和通道治理作为一个专题调查，而不是整个产品的边界。",
            "focus": ["上海", "世界贸易", "货币", "口岸", "商人", "海关", "银行", "航运"],
        },
        "en": {
            "scope": "Preserves the earlier trade-history direction around Shanghai's monetary, port, merchant, customs, banking, and shipping networks.",
            "lens": "Treat trade, finance, and corridor governance as a flagship investigation collection rather than the whole product boundary.",
            "focus": ["Shanghai", "world trade", "money", "ports", "merchants", "customs", "banks", "shipping"],
        },
    },
    "currency_settlement": {
        "zh": {
            "scope": "聚焦货币形态、信用中介、汇兑、票号、银行与跨区域结算。",
            "lens": "分析价值计量、可信中介、延期支付和清算网络如何降低交易不确定性。",
            "focus": ["银两", "纸币", "银行", "票号", "汇兑", "结算", "信用"],
        },
        "en": {
            "scope": "Focuses on monetary forms, credit intermediaries, remittance, banks, and settlement.",
            "lens": "Explains how value measurement, trusted intermediaries, delayed payment, and clearing networks reduced uncertainty.",
            "focus": ["silver", "paper money", "banks", "remittance", "settlement", "credit"],
        },
    },
    "treaty_ports": {
        "zh": {
            "scope": "聚焦近代上海、通商口岸、海关、关税、银行、航运与外贸秩序。",
            "lens": "分析口岸制度如何把跨境流动变成可登记、可征税、可融资、可治理的贸易网络。",
            "focus": ["上海", "通商口岸", "海关", "关税", "银行", "航运", "外贸"],
        },
        "en": {
            "scope": "Focuses on modern Shanghai, treaty ports, customs, tariffs, banks, shipping, and foreign trade.",
            "lens": "Shows how port institutions made cross-border flows registrable, taxable, financeable, and governable.",
            "focus": ["Shanghai", "treaty ports", "customs", "tariffs", "banks", "shipping", "foreign trade"],
        },
    },
    "silk_road": {
        "zh": {
            "scope": "聚焦陆上/海上丝路、商路、使节、边疆治理、商人网络与外交信任。",
            "lens": "分析路线安全、外交承认、商人组织和多币种交换如何支撑长期跨区域贸易。",
            "focus": ["丝绸之路", "海上丝路", "商路", "使节", "边疆", "商人网络", "外交"],
        },
        "en": {
            "scope": "Focuses on overland and maritime routes, envoys, frontier governance, merchant networks, and diplomatic trust.",
            "lens": "Explains how route security, diplomatic recognition, merchant organization, and multi-currency exchange supported long-distance trade.",
            "focus": ["Silk Road", "maritime routes", "envoys", "frontiers", "merchant networks", "diplomacy"],
        },
    },
    "dynastic_history": {
        "zh": {
            "scope": "聚焦唐宋元明清等时期的货币、财政、边疆、贸易与国家治理变化。",
            "lens": "按制度阶段比较国家能力、市场扩展、货币信用和跨区域交换的关系。",
            "focus": ["唐", "宋", "元", "明", "清", "纸币", "财政", "边疆", "制度变迁"],
        },
        "en": {
            "scope": "Focuses on monetary, fiscal, frontier, trade, and governance changes across major dynastic periods.",
            "lens": "Compares institutional phases across state capacity, market expansion, monetary credit, and regional exchange.",
            "focus": ["Tang", "Song", "Yuan", "Ming", "Qing", "paper money", "fiscal systems", "frontiers"],
        },
    },
    "world_trade": {
        "zh": {
            "scope": "聚焦中国材料与世界贸易史中的港口、航线、商人网络和制度协调比较。",
            "lens": "把中国证据放进更大的全球交换问题中，比较不同贸易制度如何解决信任、计量和通道治理。",
            "focus": ["世界贸易", "国际贸易", "港口", "航线", "商人", "制度比较"],
        },
        "en": {
            "scope": "Compares Chinese evidence with global trade history through ports, routes, merchant networks, and institutions.",
            "lens": "Places Chinese sources inside broader questions of trust, measurement, and corridor governance.",
            "focus": ["world trade", "international trade", "ports", "routes", "merchants", "institutional comparison"],
        },
    },
    "belt_road": {
        "zh": {
            "scope": "聚焦古代丝路、近代口岸与当代一带一路之间的结构性类比。",
            "lens": "只比较通道治理、信用安排、外交承认和基础设施协调，不把历史材料直接当作政策处方。",
            "focus": ["一带一路", "跨境结算", "港口", "供应链", "丝绸之路", "外交", "制度类比"],
        },
        "en": {
            "scope": "Builds structural analogies between Silk Road, treaty-port, and Belt and Road corridor questions.",
            "lens": "Compares corridor governance, credit arrangements, diplomatic recognition, and infrastructure coordination without turning history into policy prescription.",
            "focus": ["Belt and Road", "settlement", "ports", "supply chains", "Silk Road", "diplomacy", "analogy"],
        },
    },
}
STYLE_LABELS = {
    "evidence_brief": {"zh": "证据链简报", "en": "Evidence-Chain Brief"},
    "investigation_dossier": {"zh": "历史调查档案", "en": "Historical Investigation Dossier"},
    "policy_analogy": {"zh": "历史-现代类比备忘录", "en": "Historical-Modern Analogy Memo"},
    "brief": {"zh": "核心结论摘要", "en": "Executive Summary"},
    "timeline": {"zh": "时间线考证", "en": "Timeline Dossier"},
}
INTENT_LABELS = {
    "evidence": {"zh": "证据识别", "en": "evidence identification"},
    "mechanism": {"zh": "机制解释", "en": "mechanism explanation"},
    "impact": {"zh": "影响分析", "en": "impact analysis"},
    "comparison": {"zh": "比较/类比", "en": "comparison or analogy"},
    "risk": {"zh": "边界与风险", "en": "boundary and risk"},
    "timeline": {"zh": "时间线考证", "en": "timeline verification"},
    "research": {"zh": "综合研究解释", "en": "general research explanation"},
}
KNOWN_RESEARCH_TERMS = [
    "稳定币",
    "稳定价值",
    "跨境结算",
    "跨境支付",
    "跨境贸易",
    "一带一路",
    "丝绸之路",
    "海上丝路",
    "商路",
    "银两",
    "白银",
    "纸币",
    "交子",
    "会子",
    "票号",
    "银行",
    "汇兑",
    "信用",
    "信任",
    "结算",
    "通商口岸",
    "口岸",
    "海关",
    "关税",
    "外滩",
    "旧址",
    "道路",
    "历史建筑",
    "地名",
    "航运",
    "外贸",
    "供应链",
    "港口",
    "上海",
    "南京路",
    "石库门",
    "里弄",
    "杨树浦",
    "提篮桥",
    "张爱玲",
    "宋庆龄",
    "盛宣怀",
    "鲁迅",
    "张骞",
    "轮船招商局",
    "老照片",
    "老地图",
    "城市记忆",
    "城市漫游",
    "家谱",
    "族谱",
    "祖籍",
    "校友录",
    "寻亲",
    "电影",
    "影院",
    "女性",
    "职业教育",
    "公共文化",
    "藏书印",
    "题跋",
    "使节",
    "外交",
    "边疆",
    "西域",
    "中亚",
    "商人网络",
    "茶马互市",
    "唐",
    "宋",
    "元",
    "明",
    "清",
    "王朝",
    "财政",
    "治理",
    "制度",
    "世界贸易",
    "国际贸易",
    "基础设施",
    "档案",
    "古籍",
    "家谱",
    "报刊",
    "文献",
]
GENERIC_QUESTION_TERMS = {
    "历史", "今天", "目前", "现在", "研究", "问题", "证据", "资料",
    "联系", "关系", "相关", "什么", "哪些", "如何", "怎样", "怎么",
}
BROAD_FIT_TERMS = {"贸易", "治理", "制度", "通商", "近代", "上海", "影响", "作用", "联系", "关系", "相关"}


def answer_question(
    question: str,
    top_k: int = 10,
    language: str = "zh",
    mode: str = "general",
    output_style: str = "evidence_brief",
    use_deepseek: bool = False,
) -> dict:
    started_at = perf_counter()
    language = language if language in VALID_LANGUAGES else "zh"
    mode = mode if mode in MODE_LABELS else "general"
    output_style = output_style if output_style in VALID_OUTPUT_STYLES else "evidence_brief"
    evidence = retrieve(question, top_k=top_k, mode=mode)
    answer = build_structured_answer(question, evidence, language=language, mode=mode, output_style=output_style)
    latency_ms = int((perf_counter() - started_at) * 1000)
    answer["audit"] = audit_answer(question, answer, evidence, latency_ms=latency_ms)
    answer["research_profile"] = build_research_profile(
        evidence,
        answer["audit"],
        latency_ms=latency_ms,
        evidence_fit=answer.get("evidence_fit"),
    )
    answer["investigation"] = build_investigation_dossier(
        question=question,
        evidence=evidence,
        language=language,
        mode=mode,
        output_style=output_style,
        question_analysis=answer.get("question_analysis", {}),
        evidence_fit=answer.get("evidence_fit", {}),
        audit=answer["audit"],
        latency_ms=latency_ms,
    )
    answer["one_line_finding"] = answer["investigation"]["finding"]
    answer["data_receipt"] = answer["investigation"]["receipt"]
    answer["award_readiness"] = build_award_readiness(
        question=question,
        evidence=evidence,
        investigation=answer["investigation"],
        audit=answer["audit"],
        evidence_fit=answer.get("evidence_fit", {}),
        language=language,
    )
    answer["professional_briefing"] = build_professional_briefing(
        question=question,
        evidence=evidence,
        investigation=answer["investigation"],
        question_analysis=answer.get("question_analysis", {}),
        evidence_fit=answer.get("evidence_fit", {}),
        audit=answer["audit"],
        award_readiness=answer["award_readiness"],
        language=language,
    )
    answer["source_timeline"] = build_source_timeline(evidence)
    answer["topic_signals"] = build_topic_signals(evidence)
    answer["next_steps"] = build_next_steps(language, answer["audit"])
    settings = get_settings()
    if use_deepseek and settings.use_deepseek:
        answer["deepseek_assist"] = refine_with_deepseek(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            question=question,
            language=language,
            mode_label=answer["mode_label"],
            output_style_label=answer["output_style_label"],
            answer_sections=answer["answer_sections"],
            evidence_cards=answer["evidence_cards"],
            question_analysis=answer["question_analysis"],
            evidence_fit=answer["evidence_fit"],
        )
    else:
        answer["deepseek_assist"] = {
            "enabled": False,
            "status": "disabled",
            "content": "",
        }
    answer["latency_ms"] = latency_ms
    answer["generated_at"] = datetime.now(UTC).isoformat()
    return answer


def build_structured_answer(
    question: str,
    evidence: list[RetrievalResult],
    language: str = "zh",
    mode: str = "general",
    output_style: str = "evidence_brief",
) -> dict:
    question_analysis = analyze_question(question, evidence, mode, language)
    evidence_fit = build_evidence_fit(evidence, question_analysis, language)
    fit_by_record = {item["record_id"]: item for item in evidence_fit.get("cards", [])}
    citations = [
        {
            "record_id": r.record.record_id,
            "title": display_text(r.record.title, max_chars=120),
            "source": r.record.source,
            "date": display_text(r.record.date, max_chars=36),
            "uri": openable_source_url(r.record),
            "source_uri": openable_source_url(r.record),
            "raw_source_uri": display_text(r.record.source_uri, max_chars=240),
            "open_url": openable_source_url(r.record),
            "dataset": r.record.dataset,
            "score": round(r.score, 2),
            "live_api": r.record.is_live_api,
            "evidence_type": r.record.evidence_type,
            "provenance_note": display_text(r.record.provenance_note, max_chars=180),
            "time_span": display_text(r.record.time_span or r.record.date, max_chars=80),
            "geo": r.record.geo,
            "public_tags": [display_text(tag, max_chars=32) for tag in r.record.public_tags[:6]],
            "verification_notes": [display_text(note, max_chars=160) for note in r.record.verification_notes[:4]],
            "lineage": {
                key: display_text(str(value), max_chars=320)
                for key, value in r.record.lineage.items()
                if key in {
                    "provider", "dataset", "query_term", "retrieved_at", "official_uri",
                    "payload_sha256", "normalization", "evidence_id", "source_mode",
                }
            },
            "matched_terms": r.matched_terms,
            "direct_terms": fit_by_record.get(r.record.record_id, {}).get("direct_terms", []),
            "support_strength": fit_by_record.get(r.record.record_id, {}).get("strength_label", ""),
            "fit_reason": fit_by_record.get(r.record.record_id, {}).get("reason", ""),
            "relevance": explain_relevance(r, language, question_analysis),
            "support_claim": evidence_support_claim(r, question_analysis, language),
            "citation": build_citation_text(r),
        }
        for r in evidence
    ]
    evidence_lines = [
        f"{idx + 1}. {display_text(r.record.title, max_chars=120)}: {display_text(r.record.snippet, max_chars=260)}"
        for idx, r in enumerate(evidence[:10])
    ]
    problem_summary = summarize_problem(question, language, question_analysis)
    mechanism = infer_mechanism(question, evidence, language, question_analysis)
    future_questions = infer_future_questions(question, language, question_analysis)
    historical_fact = build_historical_fact(evidence, language, question_analysis)
    interpretation = build_interpretation(question, evidence, language, question_analysis)
    modern_analogy = build_modern_analogy(question, evidence, language, output_style, question_analysis)
    mode_profile = build_mode_profile(question, evidence, mode, language)
    answer_sections = build_answer_sections(
        question=question,
        evidence=evidence,
        language=language,
        mode=mode,
        output_style=output_style,
        problem_summary=problem_summary,
        historical_fact=historical_fact,
        interpretation=interpretation,
        modern_analogy=modern_analogy,
        mechanism=mechanism,
        mode_profile=mode_profile,
        question_analysis=question_analysis,
        evidence_fit=evidence_fit,
    )
    return {
        "question": question,
        "language": language,
        "mode": mode,
        "mode_label": MODE_LABELS[mode][language],
        "mode_profile": mode_profile,
        "output_style": output_style,
        "output_style_label": STYLE_LABELS[output_style][language],
        "question_analysis": question_analysis,
        "evidence_fit": evidence_fit,
        "problem_summary": problem_summary,
        "historical_fact": historical_fact,
        "interpretation": interpretation,
        "modern_analogy": modern_analogy,
        "historical_evidence": evidence_lines,
        "mechanism_comparison": mechanism,
        "modern_analogy_boundary": analogy_boundary(language),
        "uncertainty_note": uncertainty_note(language),
        "future_questions": future_questions,
        "compliance_note": compliance_note(language),
        "pipeline": [
            "Question",
            "Retrieval",
            "Evidence Cards",
            "Structured Answer",
            "Citation and Security Audit",
        ],
        "citations": citations,
        "evidence_cards": citations,
        "answer_sections": answer_sections,
    }


def analyze_question(question: str, evidence: list[RetrievalResult], mode: str, language: str) -> dict:
    intent = detect_question_intent(question)
    focus = infer_question_focus(question, evidence, language)
    terms = extract_question_terms(question, evidence, mode)
    evidence_terms = dominant_terms(evidence, limit=6)
    missing_terms = [
        term
        for term in terms
        if term not in evidence_terms and not any(term.lower() in evidence_signal_text(r.record) for r in evidence)
    ]
    if language == "zh":
        direct_need = {
            "evidence": "用户正在问“有什么材料能支持这个判断”，回答必须先列证据类型和可打开来源。",
            "mechanism": "用户正在问“如何发生”，回答必须给出制度机制链条。",
            "impact": "用户正在问“影响是什么”，回答必须区分贸易、治理、信用或外交层面的影响。",
            "comparison": "用户正在问“能否类比/比较”，回答必须同时写出可比点和不可比边界。",
            "risk": "用户正在问“是否适合/有什么风险”，回答必须先给边界，避免政策、投资或部署建议。",
            "timeline": "用户正在问“何时/如何演变”，回答必须按阶段或时期组织。",
            "research": "用户正在提出综合研究问题，回答必须先定位问题对象，再组织证据链。",
        }[intent]
    else:
        direct_need = {
            "evidence": "The user asks what evidence supports the claim, so the answer must list evidence types and openable sources first.",
            "mechanism": "The user asks how something worked, so the answer must give an institutional mechanism chain.",
            "impact": "The user asks about impact, so the answer must separate effects on trade, governance, credit, or diplomacy.",
            "comparison": "The user asks for comparison or analogy, so the answer must show both comparable and non-comparable parts.",
            "risk": "The user asks about suitability or risk, so the answer must lead with boundaries and avoid policy, investment, or deployment advice.",
            "timeline": "The user asks about timing or evolution, so the answer must be organized by period or phase.",
            "research": "The user asks a broad research question, so the answer must identify the object before building the evidence chain.",
        }[intent]
    return {
        "intent": intent,
        "intent_label": INTENT_LABELS[intent][language],
        "focus": focus["label"],
        "focus_key": focus["key"],
        "terms": terms,
        "evidence_terms": evidence_terms,
        "missing_terms": missing_terms[:5],
        "direct_need": direct_need,
    }


def build_evidence_fit(evidence: list[RetrievalResult], analysis: dict, language: str) -> dict:
    question_terms = [term for term in analysis.get("terms", []) if is_specific_evidence_term(term)]
    if not question_terms:
        question_terms = [term for term in analysis.get("evidence_terms", []) if is_specific_evidence_term(term)]
    question_terms = unique_terms(question_terms)[:10]
    if not evidence:
        label = "无证据" if language == "zh" else "No Evidence"
        summary = (
            "当前没有形成可用于回答该问题的证据卡。"
            if language == "zh"
            else "No evidence cards were retrieved for this question."
        )
        return {
            "score": 0,
            "level": "none",
            "level_label": label,
            "summary": summary,
            "covered_terms": [],
            "missing_terms": question_terms,
            "direct_card_count": 0,
            "total_cards": 0,
            "coverage_ratio": 0.0,
            "cards": [],
        }

    covered: set[str] = set()
    cards = []
    direct_card_count = 0
    for result in evidence:
        text = evidence_signal_text(result.record)
        direct_terms = [term for term in question_terms if term.lower() in text]
        direct_terms = unique_terms(direct_terms)
        covered.update(direct_terms)
        substantive_direct_terms = [term for term in direct_terms if is_substantive_evidence_term(term)]
        if substantive_direct_terms:
            direct_card_count += 1
        matched_specific = [term for term in result.matched_terms if is_specific_evidence_term(term)]
        strength = "direct" if substantive_direct_terms else ("context" if direct_terms or matched_specific else "weak")
        cards.append(
            {
                "record_id": result.record.record_id,
                "direct_terms": direct_terms[:6],
                "substantive_direct_terms": substantive_direct_terms[:6],
                "matched_terms": matched_specific[:6],
                "strength": strength,
                "strength_label": fit_strength_label(strength, language),
                "reason": fit_card_reason(result, direct_terms, strength, language),
            }
        )

    missing_terms = [term for term in question_terms if term not in covered]
    coverage_ratio = weighted_term_coverage_ratio(covered, question_terms)
    direct_card_ratio = direct_card_count / len(evidence)
    open_ratio = sum(1 for result in evidence if is_openable_reference(openable_source_url(result.record))) / len(evidence)
    score = round(min(100, coverage_ratio * 58 + direct_card_ratio * 30 + open_ratio * 12))
    level = "strong" if score >= 72 else "medium" if score >= 46 else "weak"
    level_label = evidence_fit_level_label(level, language)
    covered_text = join_terms(list(covered)[:6], language)
    missing_text = join_terms(missing_terms[:5], language)
    if language == "zh":
        summary = (
            f"证据贴合度为{level_label}：直接覆盖 {len(covered)}/{len(question_terms) or 1} 个问题对象"
            f"{f'（{covered_text}）' if covered_text else ''}，{direct_card_count}/{len(evidence)} 张证据卡能直接回应。"
        )
        if missing_text:
            summary += f" 仍缺少对 {missing_text} 的直接来源。"
    else:
        summary = (
            f"Evidence fit is {level_label}: it directly covers {len(covered)}/{len(question_terms) or 1} question terms"
            f"{f' ({covered_text})' if covered_text else ''}, with {direct_card_count}/{len(evidence)} directly responsive cards."
        )
        if missing_text:
            summary += f" Direct sources are still missing for {missing_text}."
    return {
        "score": score,
        "level": level,
        "level_label": level_label,
        "summary": summary,
        "covered_terms": list(covered),
        "missing_terms": missing_terms[:6],
        "direct_card_count": direct_card_count,
        "total_cards": len(evidence),
        "coverage_ratio": coverage_ratio,
        "cards": cards,
    }


def evidence_signal_text(record: EvidenceRecord) -> str:
    return " ".join(
        [
            record.title,
            record.snippet,
            record.date,
            " ".join(record.persons),
            " ".join(record.places),
            " ".join(record.topics),
            record.evidence_type,
            record.provenance_note,
            " ".join(record.public_tags),
            " ".join(record.verification_notes),
            record.dataset,
        ]
    ).lower()


def is_openable_reference(uri: str) -> bool:
    value = str(uri or "").strip()
    return value.startswith(("http://", "https://", "/source/"))


def is_specific_evidence_term(term: str) -> bool:
    value = display_text(term, max_chars=32).strip()
    if not value:
        return False
    return value not in GENERIC_QUESTION_TERMS | {"近代", "现代", "今天", "目前", "现在"}


def is_substantive_evidence_term(term: str) -> bool:
    value = display_text(term, max_chars=32).strip()
    return is_specific_evidence_term(value) and value not in BROAD_FIT_TERMS


def weighted_term_coverage_ratio(covered: set[str], question_terms: list[str]) -> float:
    if not question_terms:
        return 0.0
    denominator = 0.0
    numerator = 0.0
    for term in question_terms:
        weight = 1.0 if is_substantive_evidence_term(term) else 0.35
        denominator += weight
        if term in covered:
            numerator += weight
    return round(numerator / denominator, 2) if denominator else 0.0


def fit_strength_label(strength: str, language: str) -> str:
    labels = {
        "direct": {"zh": "直接支撑", "en": "Direct"},
        "context": {"zh": "背景支撑", "en": "Context"},
        "weak": {"zh": "弱相关", "en": "Weak"},
    }
    return labels.get(strength, labels["weak"])[language]


def evidence_fit_level_label(level: str, language: str) -> str:
    labels = {
        "strong": {"zh": "强", "en": "Strong"},
        "medium": {"zh": "中", "en": "Medium"},
        "weak": {"zh": "弱", "en": "Weak"},
        "none": {"zh": "无证据", "en": "No Evidence"},
    }
    return labels.get(level, labels["weak"])[language]


def fit_card_reason(result: RetrievalResult, direct_terms: list[str], strength: str, language: str) -> str:
    title = display_text(result.record.title, max_chars=60)
    if language == "zh":
        if strength == "direct":
            return f"《{title}》直接命中 {join_terms(direct_terms, language)}，可优先用于回答问题。"
        if strength == "context":
            return f"《{title}》命中相邻主题，但没有直接覆盖问题中的关键对象，适合作为背景证据。"
        return f"《{title}》与问题关系较弱，正式报告中应谨慎使用或替换。"
    if strength == "direct":
        return f"{title} directly matches {join_terms(direct_terms, language)} and can anchor the answer."
    if strength == "context":
        return f"{title} matches adjacent themes, but not the key question terms directly."
    return f"{title} is weakly related and should be replaced or used cautiously."


def detect_question_intent(question: str) -> str:
    lowered = question.lower()
    checks = [
        ("risk", ["是否适合", "能否直接", "风险", "边界", "监管", "投资", "部署", "安全吗", "risk", "suitable", "should"]),
        ("timeline", ["时间", "时期", "演变", "变化过程", "历史阶段", "先后", "timeline", "period", "evolution", "when"]),
        ("evidence", ["证据", "材料", "来源", "依据", "能证明", "有什么文献", "what evidence", "source", "citation"]),
        ("comparison", ["类比", "比较", "相似", "不同", "对比", "借鉴", "analogy", "compare", "comparison", "similar"]),
        ("impact", ["影响", "作用", "改变", "塑造", "导致", "结果", "impact", "effect", "reshape"]),
        ("mechanism", ["如何", "怎样", "怎么", "机制", "依赖", "支撑", "处理", "how", "mechanism", "support"]),
    ]
    for intent, markers in checks:
        if any(marker in lowered for marker in markers):
            return intent
    return "research"


def extract_question_terms(question: str, evidence: list[RetrievalResult], mode: str) -> list[str]:
    terms = []
    for term in KNOWN_RESEARCH_TERMS + MODE_PROFILES.get(mode, MODE_PROFILES["general"])["zh"]["focus"]:
        if term and term.lower() in question.lower():
            terms.append(term)
    for result in evidence[:4]:
        for term in result.matched_terms[:5]:
            if term and len(term) >= 2 and term not in GENERIC_QUESTION_TERMS and term.lower() in question.lower():
                terms.append(display_text(term, max_chars=24))
    for candidate in re.findall(r"[\u4e00-\u9fff]{2,12}", question):
        cleaned = clean_question_candidate(candidate)
        if cleaned:
            terms.append(cleaned)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", question):
        terms.append(word)
    return unique_terms(terms)[:10]


def clean_question_candidate(candidate: str) -> str:
    if any(marker in candidate for marker in ["什么", "哪些", "怎样", "如何", "怎么", "为什么", "是否", "可以", "能否", "有什么"]):
        return ""
    value = candidate.strip("的了呢吗今天历史上目前现在")
    if value.startswith("之路"):
        value = value[2:]
    if len(value) < 2:
        return ""
    if value in GENERIC_QUESTION_TERMS or value.startswith(("变", "改", "撑", "支撑", "处理", "影响", "改变")):
        return ""
    stop_fragments = ["这个问题", "有什么", "可以从", "找到", "结构性", "解答", "研究", "认为", "希望", "用户", "历史", "今天"]
    if any(fragment == value or fragment in value and len(value) <= len(fragment) + 2 for fragment in stop_fragments):
        return ""
    if len(value) > 6:
        return ""
    return value


def unique_terms(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        cleaned = display_text(value, max_chars=30).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def build_mode_profile(question: str, evidence: list[RetrievalResult], mode: str, language: str) -> dict:
    profile = MODE_PROFILES[mode][language]
    focus = infer_question_focus(question, evidence, language)
    matched_focus = [term for term in profile["focus"] if term.lower() in focus["signal_text"].lower()]
    if language == "zh":
        fit = (
            f"当前问题更偏向「{focus['label']}」；本模式会优先检查{join_terms(profile['focus'][:4], language)}等证据。"
            if matched_focus
            else f"当前问题更偏向「{focus['label']}」；本模式会作为补充视角，帮助检查是否存在跨领域制度线索。"
        )
    else:
        fit = (
            f"The question leans toward {focus['label']}; this mode prioritizes evidence around {join_terms(profile['focus'][:4], language)}."
            if matched_focus
            else f"The question leans toward {focus['label']}; this mode acts as a supplementary lens for cross-domain institutional signals."
        )
    return {
        "label": MODE_LABELS[mode][language],
        "scope": profile["scope"],
        "lens": profile["lens"],
        "focus_terms": profile["focus"],
        "question_focus": focus["label"],
        "fit": fit,
    }


def build_answer_sections(
    *,
    question: str,
    evidence: list[RetrievalResult],
    language: str,
    mode: str,
    output_style: str,
    problem_summary: str,
    historical_fact: str,
    interpretation: str,
    modern_analogy: str,
    mechanism: str,
    mode_profile: dict,
    question_analysis: dict,
    evidence_fit: dict,
) -> list[dict]:
    evidence_text = evidence_digest(evidence, language)
    focus = infer_question_focus(question, evidence, language)
    direct_answer = build_direct_answer(question, evidence, language, question_analysis, evidence_fit)
    evidence_reasoning = build_evidence_reasoning(evidence, language, question_analysis, evidence_fit)
    gap_note = build_gap_note(question_analysis, language, evidence_fit)
    mode_name = MODE_LABELS[mode][language]
    if output_style == "brief":
        return [
            section("直接回答", "Direct Answer", language, direct_answer),
            section("为什么这样判断", "Why This Reading", language, evidence_reasoning),
            section("最小证据集", "Minimum Evidence Set", language, evidence_text),
            section("缺口与边界", "Gaps and Boundary", language, gap_note),
        ]
    if output_style == "investigation_dossier":
        return [
            section("线索判断", "Clue Reading", language, f"{problem_summary} {mode_profile['fit']}"),
            section("证据主张", "Evidence-Bound Claims", language, evidence_reasoning),
            section("关系解释", "Relationship Interpretation", language, f"{direct_answer} {mechanism}"),
            section("争议与空白", "Contestation and Gaps", language, gap_note),
            section("公众叙事边界", "Public Narrative Boundary", language, f"{interpretation} {modern_analogy}"),
        ]
    if output_style == "policy_analogy":
        return [
            section(
                "问题中的类比对象",
                "Analogy Target",
                language,
                analog_target_text(question, mode_profile, focus, language, question_analysis),
            ),
            section(
                "可比机制",
                "Comparable Mechanisms",
                language,
                f"{direct_answer} {mechanism} {modern_analogy}",
            ),
            section(
                "不可比边界",
                "Non-Comparable Boundaries",
                language,
                f"{analogy_boundary(language)} {gap_note}",
            ),
            section(
                "证据如何支撑",
                "Evidence Support",
                language,
                evidence_reasoning,
            ),
        ]
    if output_style == "timeline":
        return [
            section(
                "围绕问题的时间线判断",
                "Timeline Reading",
                language,
                timeline_reading(evidence, mode_name, language, question_analysis),
            ),
            section(
                "阶段性变化与问题对象",
                "Phase Change",
                language,
                phase_change_text(evidence, language, question_analysis),
            ),
            section(
                "关键证据",
                "Key Evidence",
                language,
                evidence_reasoning,
            ),
            section(
                "后续考证",
                "Further Verification",
                language,
                f"{gap_note} 建议继续补充年份更明确的 live API 记录，并对时间轴中的关键节点做人工复核。"
                if language == "zh"
                else f"{gap_note} Add live API records with clearer dates and manually verify the key timeline nodes.",
            ),
        ]
    return [
        section("问题判定", "Question Diagnosis", language, f"{problem_summary} {question_analysis['direct_need']} {mode_profile['fit']}"),
        section("针对性回答", "Targeted Answer", language, direct_answer),
        section("证据链如何回答这个问题", "How Evidence Answers This Question", language, evidence_reasoning),
        section("机制解释", "Mechanism Explanation", language, mechanism),
        section("解释边界", "Interpretive Boundary", language, f"{interpretation} {modern_analogy} {gap_note}"),
    ]


def section(zh_title: str, en_title: str, language: str, body: str) -> dict:
    return {"title": zh_title if language == "zh" else en_title, "body": body}


def infer_question_focus(question: str, evidence: list[RetrievalResult], language: str) -> dict:
    evidence_text = " ".join(r.record.title + " " + r.record.snippet for r in evidence[:4])
    signal_text = " ".join([question, evidence_text])
    question_lower = question.lower()
    evidence_lower = evidence_text.lower()
    buckets = [
        ("currency", "货币与结算", "money and settlement", ["货币", "银", "纸币", "银行", "票号", "汇兑", "结算", "信用", "stablecoin"]),
        ("ports", "口岸海关与贸易治理", "ports, customs, and trade governance", ["海关", "口岸", "港口", "关税", "航运", "外贸", "供应链"]),
        ("routes", "丝路通道与商人网络", "trade corridors and merchant networks", ["丝绸之路", "海上丝路", "商路", "商人", "中亚", "西域", "张骞", "使节", "信任"]),
        ("diplomacy", "外交承认与边疆治理", "diplomacy and frontier governance", ["外交", "使节", "条约", "边疆", "治理", "政策"]),
        ("dynasty", "王朝制度变迁", "dynastic institutional change", ["唐", "宋", "元", "明", "清", "王朝", "财政"]),
        ("urban_memory", "城市记忆与公共文化", "city memory and public culture", ["旧地址", "旧址", "道路", "路名", "地名", "历史建筑", "建筑", "外滩", "南京路", "淮海中路", "霞飞路", "石库门", "里弄", "老照片", "老地图", "电影", "张爱玲", "鲁迅", "宋庆龄", "公共文化"]),
        ("family_memory", "家族线索与个人记忆", "family clues and personal memory", ["家谱", "族谱", "祖籍", "校友录", "旧居", "亲属", "人名", "寻亲", "个人线索"]),
        ("documentary_provenance", "文献版本与出处追踪", "document provenance and version tracing", ["文献", "档案", "古籍", "题跋", "藏书印", "版本", "报刊", "索引", "题名"]),
    ]
    scores = []
    for key, zh, en, terms in buckets:
        score = sum(4 for term in terms if term.lower() in question_lower)
        score += sum(1 for term in terms if term.lower() in evidence_lower)
        scores.append((score, key, zh, en, terms))
    best = max(scores, key=lambda item: item[0])
    label = best[2] if language == "zh" else best[3]
    return {"key": best[1], "label": label, "signal_text": signal_text}


def evidence_digest(evidence: list[RetrievalResult], language: str) -> str:
    if not evidence:
        return "当前没有形成可靠证据链。" if language == "zh" else "No reliable evidence chain was formed."
    items = []
    for idx, result in enumerate(evidence[:4], start=1):
        record = result.record
        title = display_text(record.title, max_chars=80)
        date = display_text(record.date, max_chars=24) if record.date else ("时期未明" if language == "zh" else "undated")
        terms = join_terms(result.matched_terms[:4], language)
        if language == "zh":
            items.append(f"{idx}.《{title}》（{date}）命中 {terms or '相关主题'}，说明{display_text(record.snippet, max_chars=96)}")
        else:
            items.append(f"{idx}. {title} ({date}) matches {terms or 'related themes'} and indicates {display_text(record.snippet, max_chars=96)}")
    return " ".join(items)


def dominant_terms(evidence: list[RetrievalResult], limit: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for result in evidence:
        for term in result.matched_terms:
            signal = normalize_signal(term)
            if signal:
                counter[signal] += 2
        for topic in result.record.topics:
            signal = normalize_signal(topic)
            if signal:
                counter[signal] += 1
    return [term for term, _ in counter.most_common(limit)]


def join_terms(terms: list[str], language: str) -> str:
    cleaned = [display_text(term, max_chars=24) for term in terms if str(term).strip()]
    if not cleaned:
        return ""
    return "、".join(cleaned) if language == "zh" else ", ".join(cleaned)


def concise_finding(focus: dict, evidence_text: str, language: str) -> str:
    if language == "zh":
        return f"本问题属于「{focus['label']}」调查。现有证据链显示：{evidence_text}"
    return f"This is an investigation into {focus['label']}. The evidence chain shows: {evidence_text}"


def build_direct_answer(
    question: str,
    evidence: list[RetrievalResult],
    language: str,
    analysis: dict,
    evidence_fit: dict | None = None,
) -> str:
    terms = join_terms(analysis.get("terms", [])[:5], language)
    evidence_titles = join_terms([r.record.title for r in evidence[:3]], language)
    mechanisms = targeted_mechanism_labels(evidence, language, analysis)
    focus = analysis.get("focus", "")
    intent = analysis.get("intent")
    if language == "zh":
        prefix = f"针对你问的「{display_text(question, max_chars=46)}」，"
        if intent == "evidence":
            return append_fit_boundary(f"{prefix}当前最可用的证据不是单一材料，而是围绕 {terms or focus} 形成的组合证据：{evidence_titles or '当前索引证据不足'}。这些材料分别支撑{join_terms(mechanisms, language) or '制度背景、交易场景和治理条件'}。", evidence_fit, language)
        if intent == "mechanism":
            return append_fit_boundary(f"{prefix}机制链条应围绕 {terms or focus} 来读：{mechanism_chain_for_focus(analysis, language)} 主要证据来自 {evidence_titles or '当前检索结果'}。", evidence_fit, language)
        if intent == "impact":
            return append_fit_boundary(f"{prefix}证据更支持从影响链条理解：{terms or focus}{impact_chain_for_focus(analysis, language)}；主要证据来自 {evidence_titles or '当前检索结果'}。", evidence_fit, language)
        if intent == "comparison":
            return append_fit_boundary(f"{prefix}可比较的是结构机制，而不是历史情境本身：{terms or focus}可与{join_terms(mechanisms, language) or '信任、计量、通道治理'}相连；不可直接比较的是具体政策、市场规模和技术条件。", evidence_fit, language)
        if intent == "risk":
            return append_fit_boundary(f"{prefix}答案应先设边界：现有证据只能说明 {terms or focus} 的历史机制和制度约束，不能推出投资、监管或支付部署建议。可用证据主要来自 {evidence_titles or '当前检索结果'}。", evidence_fit, language)
        if intent == "timeline":
            return append_fit_boundary(f"{prefix}应按阶段看：{terms or focus}在不同材料中表现为{join_terms(mechanisms, language) or '制度安排'}的变化；目前证据能形成相对时间线，但精确年份仍需复核。", evidence_fit, language)
        return append_fit_boundary(f"{prefix}应先围绕 {terms or focus} 建立可核查关系：{mechanism_chain_for_focus(analysis, language)} 证据集中在 {evidence_titles or '当前检索结果'}。", evidence_fit, language)
    prefix = f"For your question, “{display_text(question, max_chars=70)},” "
    if intent == "evidence":
        return append_fit_boundary(f"{prefix}the useful support is a bundle of evidence around {terms or focus}: {evidence_titles or 'the current retrieval set'}. These sources support {join_terms(mechanisms, language) or 'institutional context, exchange settings, and governance conditions'}.", evidence_fit, language)
    if intent == "mechanism":
        return append_fit_boundary(f"{prefix}the mechanism chain should be read around {terms or focus}: {mechanism_chain_for_focus(analysis, language)} The leading evidence comes from {evidence_titles or 'the current retrieval set'}.", evidence_fit, language)
    if intent == "impact":
        return append_fit_boundary(f"{prefix}the evidence points to an impact chain: {terms or focus}{impact_chain_for_focus(analysis, language)}.", evidence_fit, language)
    if intent == "comparison":
        return append_fit_boundary(f"{prefix}the valid comparison is structural rather than contextual: {terms or focus} can be compared through {join_terms(mechanisms, language) or 'trust, measurement, and corridor governance'}, but not through direct policy transfer.", evidence_fit, language)
    if intent == "risk":
        return append_fit_boundary(f"{prefix}the boundary comes first: the evidence can explain historical mechanisms and constraints around {terms or focus}, but not investment, regulatory, or payment-deployment advice.", evidence_fit, language)
    if intent == "timeline":
        return append_fit_boundary(f"{prefix}the answer should be read by phase: {terms or focus} appears as changing {join_terms(mechanisms, language) or 'institutional arrangements'} across the retrieved sources.", evidence_fit, language)
    return append_fit_boundary(f"{prefix}the answer should first establish verifiable relations around {terms or focus}: {mechanism_chain_for_focus(analysis, language)}", evidence_fit, language)


def mechanism_chain_for_focus(analysis: dict, language: str) -> str:
    focus_key = analysis.get("focus_key")
    if language == "zh":
        chains = {
            "currency": "先有可被共同承认的价值计量，再通过票号、银行、汇兑或账簿信用把异地交易变成可延期、可清算、可追索的关系。",
            "ports": "先由口岸和海关建立登记、估值与征税规则，再把贸易流、金融中介和航运保险纳入可治理网络。",
            "routes": "先由路线安全、使节往来和商人网络降低信息不确定性，再让远距离交换形成可重复的信任关系。",
            "diplomacy": "先通过外交承认、边疆管理和条约/使节关系确定交易边界，再影响商路安全与市场准入。",
            "dynasty": "先看国家财政和货币制度如何改变市场容量，再看跨区域交换如何被税制、信用和边疆治理重新组织。",
            "urban_memory": "先确认地名、道路、建筑或文化事件的历史身份，再把人物、机构、文献和现代空间位置分层绑定。",
            "family_memory": "先做姓名、亲属关系、祖籍和旧居消歧，再用家谱、人名规范、书目或报刊记录确认可提交关系。",
            "documentary_provenance": "先确认题名、版本、责任者和馆藏类型，再追踪题跋、藏书印、索引和关联人物地点。",
        }
        return chains.get(focus_key, "先识别价值、流动与权威之间的关系，再判断它们如何共同降低交换不确定性。")
    chains = {
        "currency": "shared value measurement comes first, then remittance firms, banks, exchange, or ledger credit turn distance trade into deferrable, clearable, and accountable relations.",
        "ports": "ports and customs first create registration, valuation, and tariff rules, then connect trade flows with finance, shipping, and insurance.",
        "routes": "route security, envoy contact, and merchant networks first reduce information uncertainty, then make long-distance exchange repeatable and trust-bearing.",
        "diplomacy": "diplomatic recognition, frontier management, and treaty or envoy relations define trade boundaries before shaping route security and market access.",
        "dynasty": "fiscal and monetary institutions reshape market capacity before taxation, credit, and frontier governance reorganize regional exchange.",
        "urban_memory": "historical names, roads, buildings, or cultural events are identified first, then people, institutions, documents, and modern spatial positions are bound in layers.",
        "family_memory": "names, kinship, ancestral place, and old residence are disambiguated first, then genealogy, authority, bibliographic, or periodical records confirm usable relationships.",
        "documentary_provenance": "title, version, responsibility, and collection type are verified first, then inscriptions, seals, indexes, people, and places are traced.",
    }
    return chains.get(focus_key, "identify how value, movement, and authority combine to reduce exchange uncertainty.")


def impact_chain_for_focus(analysis: dict, language: str) -> str:
    focus_key = analysis.get("focus_key")
    if language == "zh":
        chains = {
            "currency": "先影响价值计量和延期支付，再改变信用中介、清算速度与跨区域交易风险",
            "ports": "先改变登记、通关、征税和准入条件，再影响融资、航运、保险和贸易治理",
            "routes": "先影响路线安全、信息传递和外交承认，再改变商人网络中的信任形成与交易半径",
            "diplomacy": "先影响谁被承认为可交易对象，再改变边疆秩序、路线安全和跨区域信任",
            "dynasty": "先影响财政能力和货币供给，再改变市场扩展、信用组织和长距离贸易",
            "urban_memory": "先影响公众如何识别一处地点或文化空间，再改变城市漫游、社区展陈和公共记忆的组织方式",
            "family_memory": "先影响个人线索能否被准确消歧，再改变家族叙事、人物关系和旧址追踪的可信度",
            "documentary_provenance": "先影响文献身份和版本判断，再改变人物、地点、事件关系能否被可靠引用",
        }
        return chains.get(focus_key, "先改变交换中的信任、计量和准入条件，再影响制度协调")
    chains = {
        "currency": "first shaped value measurement and delayed payment, then credit intermediation, clearing speed, and regional transaction risk",
        "ports": "first changed registration, clearance, taxation, and access conditions, then finance, shipping, insurance, and trade governance",
        "routes": "first shaped route security, information flow, and diplomatic recognition, then trust formation and trading radius inside merchant networks",
        "diplomacy": "first shaped who counted as a recognized trading counterpart, then frontier order, route security, and cross-regional trust",
        "dynasty": "first shaped fiscal capacity and monetary supply, then market expansion, credit organization, and long-distance trade",
        "urban_memory": "first shapes how the public identifies a place or cultural site, then changes how city walks, community exhibits, and public memory can be organized",
        "family_memory": "first determines whether personal clues can be disambiguated, then changes the reliability of family narrative, relationship, and old-address tracing",
        "documentary_provenance": "first shapes document identity and version judgment, then determines whether people, places, and events can be cited reliably",
    }
    return chains.get(focus_key, "first reshaped trust, measurement, and access conditions, then institutional coordination")


def append_fit_boundary(text: str, evidence_fit: dict | None, language: str) -> str:
    if not evidence_fit:
        return text
    summary = evidence_fit.get("summary", "")
    if not summary:
        return text
    if language == "zh":
        if evidence_fit.get("level") == "weak":
            return f"{text} 但{summary}，所以结论应写成“部分支持、仍需复核”，不要写成已经完全证明。"
        return f"{text} {summary}"
    if evidence_fit.get("level") == "weak":
        return f"{text} However, {summary.lower()} so the conclusion should be framed as partial support requiring verification."
    return f"{text} {summary}"


def build_evidence_reasoning(
    evidence: list[RetrievalResult],
    language: str,
    analysis: dict,
    evidence_fit: dict | None = None,
) -> str:
    if not evidence:
        return "当前没有足够证据直接回答该问题。" if language == "zh" else "The current index lacks enough evidence to answer the question directly."
    fit_map = {item["record_id"]: item for item in (evidence_fit or {}).get("cards", [])}
    claims = []
    for result in evidence[:12]:
        card_fit = fit_map.get(result.record.record_id, {})
        label = card_fit.get("strength_label")
        claim = evidence_support_claim(result, analysis, language)
        claims.append(f"{label}：{claim}" if language == "zh" and label else f"{label}: {claim}" if label else claim)
    if language == "zh":
        return " ".join(f"{idx + 1}. {claim}" for idx, claim in enumerate(claims))
    return " ".join(f"{idx + 1}. {claim}" for idx, claim in enumerate(claims))


def build_gap_note(analysis: dict, language: str, evidence_fit: dict | None = None) -> str:
    missing = analysis.get("missing_terms") or []
    fit_missing = (evidence_fit or {}).get("missing_terms") or []
    merged_missing = unique_terms(missing + fit_missing)
    fit_summary = (evidence_fit or {}).get("summary", "")
    if language == "zh":
        if merged_missing:
            return f"需要注意：当前证据对 {join_terms(merged_missing[:6], language)} 的直接覆盖不足，因此这些部分应作为后续检索重点。{fit_summary}"
        return "需要注意：当前回答仍是证据引导的解释，正式使用前应打开来源复核题名、时期和馆藏类型。"
    if merged_missing:
        return f"Note that the current evidence does not directly cover {join_terms(merged_missing[:6], language)} strongly enough; use these as follow-up retrieval terms. {fit_summary}"
    return "Note that this remains an evidence-guided interpretation; verify titles, dates, and collection types before formal use."


def mechanism_labels_from_evidence(evidence: list[RetrievalResult], language: str) -> list[str]:
    text = " ".join(r.record.title + " " + r.record.snippet + " " + " ".join(r.record.topics) for r in evidence)
    labels = []
    mapping = [
        ("value", "价值计量", "value measurement", ["银", "纸币", "货币", "结算", "汇兑"]),
        ("credit", "信用中介", "credit intermediation", ["银行", "票号", "信用", "商帮"]),
        ("ports", "口岸与通关治理", "port and customs governance", ["海关", "口岸", "港口", "关税", "航运"]),
        ("routes", "通道与路线安全", "corridor and route security", ["丝绸之路", "海上丝路", "商路", "供应链"]),
        ("diplomacy", "外交承认与边疆治理", "diplomatic recognition and frontier governance", ["外交", "使节", "边疆", "条约", "治理"]),
        ("infrastructure", "基础设施协调", "infrastructure coordination", ["铁路", "电报", "招商", "基础设施"]),
        ("urban_memory", "城市记忆与空间复核", "city memory and spatial verification", ["旧地址", "城市记忆", "外滩", "南京路", "石库门", "里弄", "老地图", "老照片", "地名"]),
        ("family_memory", "家族线索与人物消歧", "family clues and name disambiguation", ["家谱", "族谱", "祖籍", "校友录", "旧居", "亲属", "寻亲"]),
        ("documentary_provenance", "文献出处与版本追踪", "document provenance and version tracing", ["文献", "档案", "古籍", "题跋", "藏书印", "版本", "索引"]),
    ]
    for _, zh, en, terms in mapping:
        if any(term in text for term in terms):
            labels.append(zh if language == "zh" else en)
    return labels[:5]


def targeted_mechanism_labels(evidence: list[RetrievalResult], language: str, analysis: dict) -> list[str]:
    labels = mechanism_labels_from_evidence(evidence, language)
    preferred = {
        "currency": {
            "zh": ["价值计量", "信用中介"],
            "en": ["value measurement", "credit intermediation"],
        },
        "ports": {
            "zh": ["口岸与通关治理", "信用中介", "基础设施协调"],
            "en": ["port and customs governance", "credit intermediation", "infrastructure coordination"],
        },
        "routes": {
            "zh": ["通道与路线安全", "外交承认与边疆治理", "价值计量"],
            "en": ["corridor and route security", "diplomatic recognition and frontier governance", "value measurement"],
        },
        "diplomacy": {
            "zh": ["外交承认与边疆治理", "通道与路线安全"],
            "en": ["diplomatic recognition and frontier governance", "corridor and route security"],
        },
        "dynasty": {
            "zh": ["价值计量", "信用中介", "外交承认与边疆治理"],
            "en": ["value measurement", "credit intermediation", "diplomatic recognition and frontier governance"],
        },
        "urban_memory": {
            "zh": ["城市记忆与空间复核", "文献出处与版本追踪"],
            "en": ["city memory and spatial verification", "document provenance and version tracing"],
        },
        "family_memory": {
            "zh": ["家族线索与人物消歧", "文献出处与版本追踪"],
            "en": ["family clues and name disambiguation", "document provenance and version tracing"],
        },
        "documentary_provenance": {
            "zh": ["文献出处与版本追踪", "家族线索与人物消歧"],
            "en": ["document provenance and version tracing", "family clues and name disambiguation"],
        },
    }.get(analysis.get("focus_key"), {})
    ordered = preferred.get(language, [])
    output = [label for label in ordered if label in labels]
    if analysis.get("focus_key") == "currency" and output:
        return output[:3]
    output.extend(label for label in labels if label not in output and (analysis.get("focus_key") not in {"currency"} or label not in {"外交承认与边疆治理", "diplomatic recognition and frontier governance"}))
    return output[:4]


def evidence_support_claim(result: RetrievalResult, analysis: dict, language: str) -> str:
    record = result.record
    title = display_text(record.title, max_chars=72)
    terms = join_terms(result.matched_terms[:4], language)
    snippet = display_text(record.snippet, max_chars=105)
    intent = analysis.get("intent")
    if language == "zh":
        if intent == "evidence":
            return f"《{title}》可作为直接证据入口，因为它命中 {terms or '相关主题'}，并提供“{snippet}”这一材料线索。"
        if intent == "impact":
            return f"《{title}》说明影响发生在 {terms or '相关制度'} 层面：{snippet}"
        if intent == "comparison":
            return f"《{title}》支撑结构类比中的 {terms or '制度机制'}，但只能说明历史机制，不能直接外推到现代政策。"
        if intent == "timeline":
            date = display_text(record.date or "时期未明", max_chars=30)
            return f"《{title}》（{date}）提供时间线节点，相关线索是 {terms or '制度变化'}：{snippet}"
        if intent == "risk":
            return f"《{title}》帮助界定边界：它能说明 {terms or '历史制度'}，但不能推出投资、监管或部署建议。"
        return f"《{title}》与问题中的 {join_terms(analysis.get('terms', [])[:3], language) or '核心对象'}相关，命中 {terms or '相关主题'}：{snippet}"
    if intent == "evidence":
        return f"{title} is a direct evidence entry because it matches {terms or 'related themes'} and gives this source signal: {snippet}"
    if intent == "impact":
        return f"{title} places the impact at the level of {terms or 'related institutions'}: {snippet}"
    if intent == "comparison":
        return f"{title} supports the structural analogy around {terms or 'institutional mechanisms'}, but not direct policy transfer."
    if intent == "timeline":
        date = display_text(record.date or "undated", max_chars=30)
        return f"{title} ({date}) provides a timeline node around {terms or 'institutional change'}: {snippet}"
    if intent == "risk":
        return f"{title} helps define the boundary: it can explain {terms or 'historical institutions'}, but not investment, regulatory, or deployment advice."
    return f"{title} connects to {join_terms(analysis.get('terms', [])[:3], language) or 'the core object'} and matches {terms or 'related themes'}: {snippet}"


def analog_target_text(question: str, mode_profile: dict, focus: dict, language: str, analysis: dict) -> str:
    terms = join_terms(analysis.get("terms", [])[:5], language)
    if language == "zh":
        return f"可类比对象不是现代政策本身，而是你问题中 {terms or focus['label']} 背后的结构机制：{mode_profile['lens']}"
    return f"The analogy target is not modern policy itself but the structural mechanism behind {terms or focus['label']}: {mode_profile['lens']}"


def timeline_reading(evidence: list[RetrievalResult], mode_name: str, language: str, analysis: dict) -> str:
    dates = [display_text(r.record.date, max_chars=24) for r in evidence if r.record.date]
    terms = join_terms(analysis.get("terms", [])[:4], language)
    if language == "zh":
        if dates:
            return f"围绕 {terms or analysis.get('focus', '')}，在「{mode_name}」模式下当前证据覆盖 {'、'.join(dates[:5])} 等时期，适合先形成相对时间序列，再补充精确年份。"
        return f"围绕 {terms or analysis.get('focus', '')}，当前证据更适合做主题时间线，尚不足以形成精确年份序列。"
    if dates:
        return f"For {terms or analysis.get('focus', '')}, under {mode_name}, the evidence covers periods such as {', '.join(dates[:5])}; use it as a relative sequence before adding exact years."
    return f"For {terms or analysis.get('focus', '')}, the evidence supports a thematic timeline, but not yet an exact year-by-year sequence."


def phase_change_text(evidence: list[RetrievalResult], language: str, analysis: dict) -> str:
    terms = dominant_terms(evidence, limit=6)
    question_terms = join_terms(analysis.get("terms", [])[:4], language)
    if language == "zh":
        return f"阶段变化应围绕用户问题中的 {question_terms or '核心对象'} 展开，并用 {join_terms(terms, language) or '制度主题'} 做证据锚点：先看价值计量与信用安排，再看通道、口岸、外交和治理如何把交换网络稳定下来。"
    return f"Phase change should center on {question_terms or 'the user question core object'} and use {join_terms(terms, language) or 'institutional themes'} as evidence anchors."


def build_research_profile(
    evidence: list[RetrievalResult],
    audit: dict,
    latency_ms: int,
    evidence_fit: dict | None = None,
) -> list[dict]:
    total = len(evidence)
    open_count = sum(1 for r in evidence if is_openable_reference(openable_source_url(r.record)))
    live_count = int(audit.get("live_records") or 0)
    citation_coverage = float(audit.get("citation_coverage") or 0)
    avg_matched_terms = sum(len(r.matched_terms) for r in evidence) / total if total else 0

    source_openness = pct(open_count, total)
    live_ratio = pct(live_count, total)
    evidence_depth = round(min(100, (total / 10) * 100)) if total else 0
    topic_focus = round(min(100, avg_matched_terms * 18))
    response_speed = round(max(12, min(100, 100 - (latency_ms / 42))))
    fit_score = int((evidence_fit or {}).get("score") or 0)
    fit_value = str((evidence_fit or {}).get("level_label") or f"{fit_score}%")

    return [
        {
            "key": "sourceOpenness",
            "value": f"{source_openness}%",
            "score": source_openness,
            "detail_key": "sourceOpennessDetail",
        },
        {
            "key": "citationCoverage",
            "value": f"{round(citation_coverage * 100)}%",
            "score": round(citation_coverage * 100),
            "detail_key": "citationCoverageDetail",
        },
        {
            "key": "evidenceFit",
            "value": fit_value,
            "score": fit_score,
            "detail_key": "evidenceFitDetail",
        },
        {
            "key": "liveSourceRatio",
            "value": f"{live_ratio}%",
            "score": live_ratio,
            "detail_key": "liveSourceRatioDetail",
        },
        {
            "key": "evidenceDepth",
            "value": f"{total}/10",
            "score": evidence_depth,
            "detail_key": "evidenceDepthDetail",
        },
        {
            "key": "topicFocus",
            "value": f"{avg_matched_terms:.1f}x",
            "score": topic_focus,
            "detail_key": "topicFocusDetail",
        },
        {
            "key": "responseSpeed",
            "value": f"{latency_ms} ms",
            "score": response_speed,
            "detail_key": "responseSpeedDetail",
        },
    ]


def build_source_timeline(evidence: list[RetrievalResult]) -> list[dict]:
    entries = []
    for result in evidence[:8]:
        record = result.record
        entries.append(
            {
                "record_id": record.record_id,
                "date": display_text(record.date or "undated", max_chars=36),
                "title": display_text(record.title, max_chars=96),
                "snippet": display_text(record.snippet, max_chars=130),
                "open_url": openable_source_url(record),
                "live_api": record.is_live_api,
                "evidence_type": record.evidence_type,
                "provenance_note": display_text(record.provenance_note, max_chars=150),
                "public_tags": [display_text(tag, max_chars=24) for tag in record.public_tags[:4]],
                "topics": [display_text(topic, max_chars=18) for topic in record.topics[:4]],
                "sort_key": era_sort_key(record.date),
            }
        )
    entries.sort(key=lambda item: (item["sort_key"], item["title"]))
    for entry in entries:
        entry.pop("sort_key", None)
    return entries


def build_topic_signals(evidence: list[RetrievalResult]) -> list[dict]:
    counter: Counter[str] = Counter()
    live_counter: Counter[str] = Counter()
    for result in evidence:
        matched_terms = {normalize_signal(term) for term in result.matched_terms}
        matched_terms = {term for term in matched_terms if term}
        topic_terms = {normalize_signal(topic) for topic in result.record.topics}
        public_terms = {normalize_signal(tag) for tag in result.record.public_tags}
        for term in {term for term in matched_terms | topic_terms | public_terms if term}:
            counter[term] += 2 if term in matched_terms else 1
            if result.record.is_live_api:
                live_counter[term] += 1
    signals = []
    for term, weight in counter.most_common(14):
        signals.append(
            {
                "term": term,
                "weight": weight,
                "live_count": live_counter.get(term, 0),
                "intensity": min(100, 36 + weight * 12),
            }
        )
    return signals


def build_next_steps(language: str, audit: dict) -> list[dict]:
    seed_records = int(audit.get("seed_records") or 0)
    live_records = int(audit.get("live_records") or 0)
    verified_records = int(audit.get("verified_official_records") or live_records)
    if language == "zh":
        source_step = (
            "当前结果已包含可追溯的上海图书馆官方记录；优先打开前 3 个来源复核题名、年代和馆藏类型。"
            if verified_records
            else "当前结果缺少已核验官方记录；先用更窄关键词重新导入，再生成最终简报。"
        )
        if seed_records:
            source_step += " 仍有 demo seed 记录，正式展示前建议替换为 live 来源。"
        return [
            {"title": "来源复核", "body": source_step},
            {"title": "概念加深", "body": "把主题信号云中最高频的 2-3 个词作为下一轮检索词，扩展同一问题的证据覆盖。"},
            {"title": "结论边界", "body": "把历史事实、解释推断和现代类比分开写入报告，避免把历史类比直接当作政策或投资建议。"},
        ]
    source_step = (
        "The answer includes traceable official Shanghai Library records; open the top three sources and verify title, date, and collection type."
        if verified_records
        else "The answer lacks verified official records; re-run ingestion with narrower terms before using it as a final brief."
    )
    if seed_records:
        source_step += " Some demo seed records remain, so replace them with live sources before formal presentation."
    return [
        {"title": "Source Review", "body": source_step},
        {"title": "Concept Deepening", "body": "Use the top two or three topic signals as the next ingestion or retrieval keywords."},
        {"title": "Boundary Control", "body": "Separate historical fact, interpretation, and modern analogy so the brief does not become policy or investment advice."},
    ]


def build_investigation_dossier(
    *,
    question: str,
    evidence: list[RetrievalResult],
    language: str,
    mode: str,
    output_style: str,
    question_analysis: dict,
    evidence_fit: dict,
    audit: dict,
    latency_ms: int,
) -> dict:
    task = infer_investigation_task(question, mode, language, question_analysis)
    entities = build_entity_links(question, evidence, question_analysis, language)
    claims = build_claim_ledger(question, evidence, question_analysis, evidence_fit, language)
    counter_evidence = build_counter_evidence_report(evidence, question_analysis, evidence_fit, audit, language)
    plan = build_investigation_plan(question, task, entities, evidence, question_analysis, language)
    receipt = build_data_use_receipt(evidence, entities, claims, counter_evidence, audit, latency_ms, language)
    graph = build_claim_evidence_graph(question, task, entities, claims, evidence, language)
    replay = build_investigation_replay(plan, evidence, entities, claims, counter_evidence, receipt, language)
    finding = build_investigation_finding(question, task, claims, evidence_fit, counter_evidence, language)
    timeline_events = build_historical_timeline(evidence, claims, question_analysis, language)
    relationship_network = build_relationship_network(task, entities, claims, evidence, language)
    spatial_traces = build_spatial_traces(entities, evidence, language)
    story_mode = build_story_mode(question, task, finding, timeline_events, relationship_network, spatial_traces, counter_evidence, language)
    research_mode = build_research_mode(question, task, plan, claims, counter_evidence, receipt, language)
    follow_up_routes = build_follow_up_routes(question_analysis, entities, counter_evidence, spatial_traces, language)
    quality_gates = build_quality_gates(claims, counter_evidence, receipt, spatial_traces, language)
    return {
        "title": task["label"],
        "task": task,
        "style": output_style,
        "finding": finding,
        "entities": entities,
        "plan": plan,
        "claims": claims,
        "counter_evidence": counter_evidence,
        "receipt": receipt,
        "graph": graph,
        "replay": replay,
        "timeline_events": timeline_events,
        "relationship_network": relationship_network,
        "spatial_traces": spatial_traces,
        "story_mode": story_mode,
        "research_mode": research_mode,
        "follow_up_routes": follow_up_routes,
        "quality_gates": quality_gates,
    }


def infer_investigation_task(question: str, mode: str, language: str, question_analysis: dict | None = None) -> dict:
    question_analysis = question_analysis or {}
    lowered = question.lower()
    task_map = {
        "trace_person": {
            "label": {"zh": "追一个人", "en": "Trace a Person"},
            "entry": {"zh": "人物线索", "en": "person clue"},
            "goal": {"zh": "重建人物、机构、地点、事件和文献之间的证据网络。", "en": "Rebuild the evidence network among people, institutions, places, events, and documents."},
        },
        "explore_place": {
            "label": {"zh": "寻一处地", "en": "Explore a Place"},
            "entry": {"zh": "地点线索", "en": "place clue"},
            "goal": {"zh": "追踪地名、旧址、机构占用、人物活动和事件痕迹。", "en": "Trace names, old addresses, institutional occupancy, people, and events."},
        },
        "reconstruct_event": {
            "label": {"zh": "还原一件事", "en": "Reconstruct an Event"},
            "entry": {"zh": "事件线索", "en": "event clue"},
            "goal": {"zh": "恢复时间线、参与者、地点、因果关系和证据强弱。", "en": "Recover timeline, actors, places, causality, and evidence strength."},
        },
        "read_document": {
            "label": {"zh": "读懂一份文献", "en": "Read a Document"},
            "entry": {"zh": "文献线索", "en": "document clue"},
            "goal": {"zh": "确认文献身份、馆藏类型、关联实体、版本线索和可追溯来源。", "en": "Verify document identity, collection type, linked entities, version signals, and traceable sources."},
        },
        "city_memory": {
            "label": {"zh": "城市记忆漫游", "en": "City Memory Walk"},
            "entry": {"zh": "城市记忆线索", "en": "city-memory clue"},
            "goal": {"zh": "把旧地址、街区、人物、机构、文献和现代空间复核组织成可走读的历史档案。", "en": "Organize old addresses, districts, people, institutions, documents, and spatial review into a walkable historical dossier."},
        },
        "family_memory": {
            "label": {"zh": "家族线索寻踪", "en": "Family Memory Trace"},
            "entry": {"zh": "个人/家族线索", "en": "personal or family clue"},
            "goal": {"zh": "把姓名、亲属关系、旧居、家谱、校友录和文献出处拆成可复核证据链。", "en": "Turn names, kinship, old residences, genealogies, alumni lists, and source provenance into a verifiable evidence chain."},
        },
        "shanghai_world": {
            "label": {"zh": "上海与世界专题", "en": "Shanghai and the World"},
            "entry": {"zh": "专题线索", "en": "thematic clue"},
            "goal": {"zh": "把货币、口岸、商人、海关、银行和航运放进可复核的全球贸易证据网。", "en": "Place money, ports, merchants, customs, banks, and shipping inside a verifiable global-trade evidence network."},
        },
    }
    if mode in task_map:
        key = mode
    elif any(term in lowered for term in ["家谱", "族谱", "祖籍", "校友录", "亲属", "寻亲", "family", "genealogy", "surname"]):
        key = "family_memory"
    elif any(term in lowered for term in ["城市记忆", "老照片", "老地图", "南京路", "石库门", "里弄", "杨树浦", "提篮桥", "city walk"]):
        key = "city_memory"
    elif any(term in lowered for term in ["旧址", "地址", "地名", "道路", "建筑", "外滩", "place", "street", "building"]):
        key = "explore_place"
    elif any(term in lowered for term in ["事件", "发生", "时间线", "影响", "event", "timeline"]):
        key = "reconstruct_event"
    elif any(term in lowered for term in ["文献", "档案", "古籍", "家谱", "报刊", "书", "document", "archive", "newspaper"]):
        key = "read_document"
    elif any(term in lowered for term in ["盛宣怀", "鲁迅", "张骞", "人物", "person", "biography"]):
        key = "trace_person"
    elif mode in {"currency_settlement", "treaty_ports", "silk_road", "world_trade", "belt_road"}:
        key = "shanghai_world"
    else:
        key = "reconstruct_event" if question_analysis.get("intent") == "timeline" else "trace_person"
    profile = task_map[key]
    return {
        "key": key,
        "label": profile["label"][language],
        "entry": profile["entry"][language],
        "goal": profile["goal"][language],
    }


def build_entity_links(
    question: str,
    evidence: list[RetrievalResult],
    analysis: dict,
    language: str,
) -> list[dict]:
    entity_map: dict[str, dict] = {}

    def add(label: str, entity_type: str, *, record_id: str = "", source: str = "evidence", confidence: float = 0.72) -> None:
        cleaned = display_text(label, max_chars=42).strip(" ：:，,。.;；、|")
        if not cleaned or cleaned.lower() in {"none", "undated"}:
            return
        key = f"{entity_type}:{cleaned.lower()}"
        if key not in entity_map:
            entity_map[key] = {
                "id": f"entity-{len(entity_map) + 1}",
                "label": cleaned,
                "type": entity_type,
                "type_label": entity_type_label(entity_type, language),
                "confidence": confidence,
                "sources": [],
                "aliases": [],
                "evidence_count": 0,
                "origin": source,
            }
        item = entity_map[key]
        if record_id and record_id not in item["sources"]:
            item["sources"].append(record_id)
            item["evidence_count"] += 1
        if source == "question":
            item["origin"] = "question"
            item["confidence"] = max(float(item["confidence"]), 0.86)

    for term in analysis.get("terms", [])[:10]:
        add(term, classify_entity_label(term), source="question", confidence=0.86)
    for result in evidence[:8]:
        record = result.record
        for person in record.persons[:5]:
            add(person, "person", record_id=record.record_id)
        for place in record.places[:5]:
            add(place, "place", record_id=record.record_id)
        for topic in record.topics[:6]:
            add(topic, classify_entity_label(topic), record_id=record.record_id, confidence=0.66)
        for term in result.matched_terms[:4]:
            add(term, classify_entity_label(term), record_id=record.record_id, confidence=0.62)

    entities = list(entity_map.values())
    entities.sort(key=lambda item: (item["origin"] == "question", item["evidence_count"], item["confidence"]), reverse=True)
    for item in entities:
        item["confidence"] = round(float(item["confidence"]), 2)
        item["sources"] = item["sources"][:6]
    return entities[:18]


def classify_entity_label(label: str) -> str:
    value = str(label or "")
    if any(term in value for term in ["盛宣怀", "张骞", "鲁迅", "许广平", "张爱玲", "宋庆龄", "人名", "人物", "传记", "亲属"]):
        return "person"
    if any(term in value for term in ["上海", "外滩", "南京路", "石库门", "里弄", "杨树浦", "提篮桥", "西域", "中亚", "江南", "口岸", "港口", "道路", "旧址", "旧居", "地名", "建筑", "路"]):
        return "place"
    if any(term in value for term in ["银行", "海关", "招商", "商行", "书店", "出版社", "学校", "影院", "电影公司", "机构", "公司", "局", "馆"]):
        return "organization"
    if any(term in value for term in ["档案", "古籍", "家谱", "族谱", "报刊", "老照片", "老地图", "藏书印", "题跋", "书", "文献", "索引", "题名", "资料"]):
        return "document"
    if any(term in value for term in ["事件", "战争", "革命", "会议", "运动", "互市", "贸易"]):
        return "event"
    return "concept"


def entity_type_label(entity_type: str, language: str) -> str:
    labels = {
        "person": {"zh": "人物", "en": "Person"},
        "place": {"zh": "地点", "en": "Place"},
        "organization": {"zh": "机构", "en": "Organization"},
        "event": {"zh": "事件", "en": "Event"},
        "document": {"zh": "文献", "en": "Document"},
        "concept": {"zh": "概念", "en": "Concept"},
    }
    return labels.get(entity_type, labels["concept"])[language]


def build_claim_ledger(
    question: str,
    evidence: list[RetrievalResult],
    analysis: dict,
    evidence_fit: dict,
    language: str,
) -> list[dict]:
    fit_map = {item["record_id"]: item for item in evidence_fit.get("cards", [])}
    claims = []
    for idx, result in enumerate(evidence[:8], start=1):
        fit = fit_map.get(result.record.record_id, {})
        strength = fit.get("strength", "context")
        claim_type = "historical_fact" if strength == "direct" else "context"
        confidence = claim_confidence(result, strength)
        if language == "zh":
            text = evidence_support_claim(result, analysis, language)
            audit_note = (
                "该主张有直接问题词和来源链接支撑。"
                if strength == "direct"
                else "该主张更适合作为背景材料，不能单独承载结论。"
            )
        else:
            text = evidence_support_claim(result, analysis, language)
            audit_note = (
                "This claim has direct question-term and source-link support."
                if strength == "direct"
                else "This is background support and should not carry the conclusion alone."
            )
        claims.append(
            {
                "id": f"claim-{idx}",
                "type": claim_type,
                "type_label": claim_type_label(claim_type, language),
                "text": text,
                "support_level": strength,
                "support_label": fit_strength_label(strength, language),
                "confidence": confidence,
                "status": "passed" if strength == "direct" else "review",
                "evidence_ids": [result.record.record_id],
                "evidence_titles": [display_text(result.record.title, max_chars=80)],
                "terms": unique_terms((fit.get("direct_terms") or []) + result.matched_terms[:4])[:6],
                "audit_note": audit_note,
            }
        )

    direct_claims = [claim for claim in claims if claim["support_level"] == "direct"]
    if len(direct_claims) >= 2:
        evidence_ids = []
        titles = []
        for claim in direct_claims[:3]:
            evidence_ids.extend(claim["evidence_ids"])
            titles.extend(claim["evidence_titles"])
        if language == "zh":
            text = f"多条证据共同显示，{join_terms(analysis.get('terms', [])[:4], language) or analysis.get('focus', '该线索')} 不是孤立信息，而是能连接人物、地点、事件或制度主题的调查入口。"
            note = "综合主张必须保留多来源绑定；任意删除关键证据后应降低结论强度。"
        else:
            text = f"Multiple sources indicate that {join_terms(analysis.get('terms', [])[:4], language) or analysis.get('focus', 'the clue')} is not isolated; it can connect people, places, events, or institutional themes."
            note = "The synthetic claim must keep multiple source bindings; removing key evidence should lower conclusion strength."
        claims.insert(
            0,
            {
                "id": "claim-synthesis",
                "type": "relationship_inference",
                "type_label": claim_type_label("relationship_inference", language),
                "text": text,
                "support_level": "direct",
                "support_label": fit_strength_label("direct", language),
                "confidence": round(min(0.9, 0.58 + len(direct_claims) * 0.08), 2),
                "status": "passed",
                "evidence_ids": unique_terms(evidence_ids)[:4],
                "evidence_titles": unique_terms(titles)[:4],
                "terms": analysis.get("terms", [])[:6],
                "audit_note": note,
            },
        )

    missing = evidence_fit.get("missing_terms") or analysis.get("missing_terms") or []
    if missing:
        if language == "zh":
            text = f"当前证据尚不能充分证明 {join_terms(missing[:5], language)}，这些对象应被标记为待考证。"
            note = "这是系统主动暴露的证据空白，不应被改写成确定事实。"
        else:
            text = f"The current evidence does not fully prove {join_terms(missing[:5], language)}; these objects should remain under verification."
            note = "This is an explicitly exposed evidence gap and should not be rewritten as settled fact."
        claims.append(
            {
                "id": "claim-gap",
                "type": "uncertain",
                "type_label": claim_type_label("uncertain", language),
                "text": text,
                "support_level": "weak",
                "support_label": fit_strength_label("weak", language),
                "confidence": 0.32,
                "status": "needs_more_evidence",
                "evidence_ids": [],
                "evidence_titles": [],
                "terms": missing[:6],
                "audit_note": note,
            }
        )
    return claims[:12]


def claim_confidence(result: RetrievalResult, strength: str) -> float:
    base = {"direct": 0.74, "context": 0.55, "weak": 0.34}.get(strength, 0.48)
    score_bonus = min(0.16, max(0, result.score) / 160)
    live_bonus = 0.05 if result.record.is_live_api else 0
    return round(min(0.94, base + score_bonus + live_bonus), 2)


def claim_type_label(claim_type: str, language: str) -> str:
    labels = {
        "historical_fact": {"zh": "历史事实", "en": "Historical Fact"},
        "relationship_inference": {"zh": "关系推断", "en": "Relationship Inference"},
        "context": {"zh": "背景证据", "en": "Context Evidence"},
        "analogy": {"zh": "现代类比", "en": "Modern Analogy"},
        "uncertain": {"zh": "待考证", "en": "Uncertain"},
    }
    return labels.get(claim_type, labels["context"])[language]


def build_counter_evidence_report(
    evidence: list[RetrievalResult],
    analysis: dict,
    evidence_fit: dict,
    audit: dict,
    language: str,
) -> list[dict]:
    items = []
    missing_terms = unique_terms((evidence_fit.get("missing_terms") or []) + (analysis.get("missing_terms") or []))
    if missing_terms:
        items.append(counter_item(
            "gap",
            "证据空白" if language == "zh" else "Evidence Gap",
            f"当前检索没有直接覆盖 {join_terms(missing_terms[:6], language)}。" if language == "zh" else f"The current retrieval does not directly cover {join_terms(missing_terms[:6], language)}.",
            "high" if len(missing_terms) >= 3 else "medium",
            missing_terms[:6],
            [],
            language,
        ))

    weak_cards = [
        card for card in evidence_fit.get("cards", [])
        if card.get("strength") == "weak"
    ]
    if weak_cards:
        items.append(counter_item(
            "weak_support",
            "弱相关证据" if language == "zh" else "Weak Support",
            f"{len(weak_cards)} 张证据卡被判定为弱相关，使用结论前应替换或降权。" if language == "zh" else f"{len(weak_cards)} evidence cards are weakly related and should be replaced or down-weighted before relying on the result.",
            "medium",
            [],
            [card.get("record_id", "") for card in weak_cards],
            language,
        ))

    undated = [result.record.record_id for result in evidence if not result.record.date]
    if undated:
        items.append(counter_item(
            "date_uncertainty",
            "时间不确定" if language == "zh" else "Date Uncertainty",
            f"{len(undated)} 条记录缺少明确年代，时间线应先作为相对序列。" if language == "zh" else f"{len(undated)} records lack clear dates, so the timeline should remain relative.",
            "medium",
            [],
            undated[:6],
            language,
        ))

    if int(audit.get("seed_records") or 0):
        items.append(counter_item(
            "seed_data",
            "演示数据混入" if language == "zh" else "Demo Data Present",
            "结果中仍包含 demo seed 记录；对外展示前应尽量用 live API 来源替换。" if language == "zh" else "The result still contains demo seed records; replace them with live API sources where possible before public presentation.",
            "medium",
            [],
            [result.record.record_id for result in evidence if not result.record.is_live_api][:6],
            language,
        ))

    if not evidence:
        items.append(counter_item(
            "no_evidence",
            "没有检索命中" if language == "zh" else "No Retrieval Match",
            "需要改写线索、扩大关键词或重新导入数据。" if language == "zh" else "Rewrite the clue, broaden terms, or re-run ingestion.",
            "high",
            analysis.get("terms", [])[:6],
            [],
            language,
        ))

    if not items:
        items.append(counter_item(
            "no_conflict",
            "未发现明显反证" if language == "zh" else "No Obvious Counter-Evidence",
            "当前轻量审计没有发现直接冲突；仍建议人工打开前 3 个来源复核。" if language == "zh" else "The lightweight audit found no direct contradiction; still verify the top three sources manually.",
            "low",
            [],
            [],
            language,
        ))
    return items[:5]


def counter_item(
    key: str,
    title: str,
    body: str,
    severity: str,
    terms: list[str],
    evidence_ids: list[str],
    language: str,
) -> dict:
    severity_labels = {
        "high": {"zh": "高", "en": "High"},
        "medium": {"zh": "中", "en": "Medium"},
        "low": {"zh": "低", "en": "Low"},
    }
    return {
        "key": key,
        "title": title,
        "body": body,
        "severity": severity,
        "severity_label": severity_labels.get(severity, severity_labels["medium"])[language],
        "terms": terms,
        "evidence_ids": [value for value in evidence_ids if value],
    }


def build_investigation_plan(
    question: str,
    task: dict,
    entities: list[dict],
    evidence: list[RetrievalResult],
    analysis: dict,
    language: str,
) -> list[dict]:
    datasets = preferred_dataset_families(task["key"], analysis)
    terms = unique_terms(analysis.get("terms", []) + [entity["label"] for entity in entities[:5]])[:8]
    if language == "zh":
        return [
            {"id": "understand", "title": "理解线索", "tool": "Clue Parser", "status": "done", "detail": f"将用户输入识别为{task['entry']}，核心对象为 {join_terms(terms[:5], language) or display_text(question, 36)}。"},
            {"id": "plan", "title": "制订检索计划", "tool": "Historical Evidence Compiler", "status": "done", "detail": f"优先查询 {join_terms(datasets[:5], language)}。"},
            {"id": "search", "title": "检索与归一化", "tool": "Shanghai Library Record Tools", "status": "done", "detail": f"当前本地索引返回 {len(evidence)} 条候选证据，并统一为 EvidenceRecord。"},
            {"id": "link", "title": "实体链接", "tool": "Entity Linker", "status": "done", "detail": f"抽取并连接 {len(entities)} 个实体、主题或文献线索。"},
            {"id": "audit", "title": "主张审计与反证搜索", "tool": "Claim Auditor", "status": "done", "detail": "逐条检查证据贴合度、弱支撑、时间空白和 demo/live 数据边界。"},
            {"id": "present", "title": "生成历史档案", "tool": "Dossier Builder", "status": "done", "detail": "输出可点击证据卡、主张台账、关系图、时间线、回放和数据使用收据。"},
        ]
    return [
        {"id": "understand", "title": "Understand Clue", "tool": "Clue Parser", "status": "done", "detail": f"Classified the input as a {task['entry']} with core objects {join_terms(terms[:5], language) or display_text(question, 44)}."},
        {"id": "plan", "title": "Plan Searches", "tool": "Historical Evidence Compiler", "status": "done", "detail": f"Prioritized {join_terms(datasets[:5], language)}."},
        {"id": "search", "title": "Retrieve and Normalize", "tool": "Shanghai Library Record Tools", "status": "done", "detail": f"The local index returned {len(evidence)} candidate records normalized as EvidenceRecord objects."},
        {"id": "link", "title": "Link Entities", "tool": "Entity Linker", "status": "done", "detail": f"Linked {len(entities)} entities, themes, or document clues."},
        {"id": "audit", "title": "Audit Claims and Counter-Evidence", "tool": "Claim Auditor", "status": "done", "detail": "Checked evidence fit, weak support, date gaps, and demo/live data boundaries."},
        {"id": "present", "title": "Build Dossier", "tool": "Dossier Builder", "status": "done", "detail": "Returned clickable evidence cards, a claim ledger, relationship graph, timeline, replay, and data receipt."},
    ]


def preferred_dataset_families(task_key: str, analysis: dict) -> list[str]:
    base = {
        "trace_person": ["人名规范库", "中国历代人物传记资料库", "盛宣怀档案", "报刊索引", "书目/古籍"],
        "explore_place": ["上海地名志", "道路数据", "历史建筑", "不可移动文物", "历史事件"],
        "reconstruct_event": ["上海历史文化事件", "人名规范库", "上海地名志", "近代报刊索引", "档案"],
        "read_document": ["书目数据", "古籍", "家谱", "盛宣怀档案", "近代报刊索引"],
        "city_memory": ["上海地名志", "道路数据", "历史建筑", "老照片/老地图", "近代报刊索引", "上海历史文化事件"],
        "family_memory": ["家谱/族谱", "人名规范库", "校友录/机构名录", "书目数据", "近代报刊索引", "上海地名志"],
        "shanghai_world": ["盛宣怀档案", "上海历史文化事件", "上海地名志", "近代报刊索引", "书目/古籍"],
    }
    datasets = base.get(task_key, ["人名规范库", "历史地点", "历史事件", "书目/古籍"])
    focus_key = analysis.get("focus_key")
    if focus_key == "currency":
        datasets = ["盛宣怀档案", "近代报刊索引", "书目/古籍", "上海历史文化事件"] + datasets
    if focus_key == "ports":
        datasets = ["上海地名志", "历史建筑", "上海历史文化事件", "近代报刊索引"] + datasets
    if focus_key == "urban_memory":
        datasets = ["上海地名志", "道路数据", "历史建筑", "老照片/老地图", "近代报刊索引"] + datasets
    if focus_key == "family_memory":
        datasets = ["家谱/族谱", "人名规范库", "校友录/机构名录", "上海地名志"] + datasets
    if focus_key == "documentary_provenance":
        datasets = ["书目数据", "古籍", "报刊索引", "家谱/族谱", "档案"] + datasets
    return unique_terms(datasets)


def build_data_use_receipt(
    evidence: list[RetrievalResult],
    entities: list[dict],
    claims: list[dict],
    counter_evidence: list[dict],
    audit: dict,
    latency_ms: int,
    language: str,
) -> dict:
    datasets = unique_terms([display_text(result.record.dataset, max_chars=56) for result in evidence])
    evidence_types = unique_terms([display_text(result.record.evidence_type, max_chars=56) for result in evidence])
    public_tags = unique_terms([tag for result in evidence for tag in result.record.public_tags])
    live_count = int(audit.get("live_records") or 0)
    official_count = int(audit.get("verified_official_records") or live_count)
    total = len(evidence)
    cited = sum(1 for result in evidence if openable_source_url(result.record))
    direct_claims = sum(1 for claim in claims if claim.get("support_level") == "direct")
    weak_claims = sum(1 for claim in claims if claim.get("support_level") == "weak")
    return {
        "datasets_queried": datasets,
        "evidence_types": evidence_types,
        "public_tags": public_tags[:12],
        "records_examined": total,
        "entities_linked": len(entities),
        "claims_checked": len(claims),
        "direct_claims": direct_claims,
        "weak_or_gap_claims": weak_claims,
        "sources_cited": cited,
        "conflicts_detected": sum(1 for item in counter_evidence if item.get("severity") in {"high", "medium"}),
        "live_percentage": pct(live_count, total),
        "official_percentage": pct(official_count, total),
        "citation_coverage": round(float(audit.get("citation_coverage") or 0) * 100),
        "latency_ms": latency_ms,
        "summary": (
            f"本次调查查询/使用 {len(datasets)} 类数据集、{len(evidence_types)} 类证据形态，检查 {total} 条记录，链接 {len(entities)} 个实体，审计 {len(claims)} 条主张。"
            if language == "zh"
            else f"This investigation used {len(datasets)} dataset families and {len(evidence_types)} evidence types, examined {total} records, linked {len(entities)} entities, and audited {len(claims)} claims."
        ),
    }


def build_claim_evidence_graph(
    question: str,
    task: dict,
    entities: list[dict],
    claims: list[dict],
    evidence: list[RetrievalResult],
    language: str,
) -> dict:
    nodes = [
        {"id": "clue", "label": "用户线索" if language == "zh" else "User Clue", "type": "clue", "weight": 1.0},
        {"id": "dossier", "label": task["label"], "type": "dossier", "weight": 0.95},
    ]
    links = [{"source": "clue", "target": "dossier", "relation": "compiled_as"}]

    for entity in entities[:10]:
        nodes.append({"id": entity["id"], "label": entity["label"], "type": entity["type"], "weight": 0.62 + min(0.3, entity.get("evidence_count", 0) * 0.05)})
        links.append({"source": "clue", "target": entity["id"], "relation": "mentions"})

    for idx, result in enumerate(evidence[:10], start=1):
        source_id = f"source-{idx}"
        nodes.append(
            {
                "id": source_id,
                "record_id": result.record.record_id,
                "label": display_text(result.record.title, max_chars=42),
                "type": "source",
                "weight": 0.56 + min(0.26, result.score / 160),
                "href": openable_source_url(result.record),
                "live_api": result.record.is_live_api,
                "evidence_type": result.record.evidence_type,
            }
        )
        links.append({"source": source_id, "target": "dossier", "relation": "supports"})
        for entity in entities[:10]:
            if result.record.record_id in entity.get("sources", []):
                links.append({"source": entity["id"], "target": source_id, "relation": "attested_by"})

    source_lookup = {result.record.record_id: f"source-{idx}" for idx, result in enumerate(evidence[:10], start=1)}
    for claim in claims[:7]:
        nodes.append(
            {
                "id": claim["id"],
                "label": claim["type_label"],
                "type": "claim",
                "weight": 0.52 + float(claim.get("confidence") or 0) * 0.35,
                "status": claim.get("status"),
            }
        )
        links.append({"source": claim["id"], "target": "dossier", "relation": "checked_for"})
        for record_id in claim.get("evidence_ids", [])[:4]:
            source_id = source_lookup.get(record_id)
            if source_id:
                links.append({"source": source_id, "target": claim["id"], "relation": "supports_claim"})

    return {
        "nodes": nodes[:34],
        "links": links[:64],
        "legend": [
            {"type": "clue", "label": "线索" if language == "zh" else "Clue"},
            {"type": "person", "label": "人物" if language == "zh" else "Person"},
            {"type": "place", "label": "地点" if language == "zh" else "Place"},
            {"type": "source", "label": "来源" if language == "zh" else "Source"},
            {"type": "claim", "label": "主张" if language == "zh" else "Claim"},
        ],
    }


def build_investigation_replay(
    plan: list[dict],
    evidence: list[RetrievalResult],
    entities: list[dict],
    claims: list[dict],
    counter_evidence: list[dict],
    receipt: dict,
    language: str,
) -> list[dict]:
    replay = []
    for idx, step in enumerate(plan, start=1):
        if step["id"] == "search":
            artifacts = [display_text(result.record.title, max_chars=52) for result in evidence[:4]]
        elif step["id"] == "link":
            artifacts = [entity["label"] for entity in entities[:6]]
        elif step["id"] == "audit":
            artifacts = [item["title"] for item in counter_evidence[:4]]
        elif step["id"] == "present":
            artifacts = [receipt.get("summary", "")]
        else:
            artifacts = []
        replay.append(
            {
                "index": idx,
                "title": step["title"],
                "tool": step["tool"],
                "status": step["status"],
                "detail": step["detail"],
                "artifacts": artifacts,
            }
        )
    if language == "zh":
        replay.append({"index": len(replay) + 1, "title": "人工复核建议", "tool": "Human Review", "status": "queued", "detail": "公开展示前打开前 3 个来源，复核题名、年代、数据集和证据强度。", "artifacts": []})
    else:
        replay.append({"index": len(replay) + 1, "title": "Human Review Suggestion", "tool": "Human Review", "status": "queued", "detail": "Before public use, open the top three sources and verify title, date, dataset, and evidence strength.", "artifacts": []})
    return replay


def build_historical_timeline(
    evidence: list[RetrievalResult],
    claims: list[dict],
    analysis: dict,
    language: str,
) -> list[dict]:
    claim_lookup = claim_lookup_by_record(claims)
    entries = []
    for idx, result in enumerate(evidence[:10], start=1):
        record = result.record
        claim = claim_lookup.get(record.record_id, {})
        support_label = claim.get("support_label") or fit_strength_label("context", language)
        confidence = claim.get("confidence") or claim_confidence(result, "context")
        if language == "zh":
            body = (
                f"该节点把「{join_terms(analysis.get('terms', [])[:3], language) or '用户线索'}」连接到"
                f"《{display_text(record.title, 52)}》；证据摘要：{display_text(record.snippet, 118)}"
            )
        else:
            body = (
                f"This node links {join_terms(analysis.get('terms', [])[:3], language) or 'the user clue'} to "
                f"{display_text(record.title, 52)}; source signal: {display_text(record.snippet, 118)}"
            )
        entries.append(
            {
                "id": f"timeline-{idx}",
                "record_id": record.record_id,
                "date": display_text(record.date or ("待考" if language == "zh" else "undated"), max_chars=36),
                "title": display_text(record.title, max_chars=86),
                "body": body,
                "support_label": support_label,
                "confidence": round(float(confidence), 2),
                "evidence_type": record.evidence_type,
                "evidence_ids": [record.record_id],
                "open_url": openable_source_url(record),
                "people": [display_text(value, max_chars=24) for value in record.persons[:4]],
                "places": [display_text(value, max_chars=24) for value in record.places[:4]],
                "topics": [display_text(value, max_chars=24) for value in record.topics[:5]],
                "sort_key": era_sort_key(record.date),
            }
        )
    entries.sort(key=lambda item: (item["sort_key"], item["title"]))
    for entry in entries:
        entry.pop("sort_key", None)
    return entries


def claim_lookup_by_record(claims: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for claim in claims:
        if claim.get("id") == "claim-gap":
            continue
        for record_id in claim.get("evidence_ids", []):
            current = lookup.get(record_id)
            if not current or claim_rank(claim) > claim_rank(current):
                lookup[record_id] = claim
    return lookup


def claim_rank(claim: dict) -> tuple[int, float]:
    status_rank = {
        "passed": 4,
        "review": 3,
        "needs_more_evidence": 2,
    }.get(str(claim.get("status") or ""), 1)
    return status_rank, float(claim.get("confidence") or 0)


def build_relationship_network(
    task: dict,
    entities: list[dict],
    claims: list[dict],
    evidence: list[RetrievalResult],
    language: str,
) -> dict:
    nodes = []
    links = []
    for entity in entities[:14]:
        nodes.append(
            {
                "id": entity["id"],
                "label": entity["label"],
                "type": entity["type"],
                "type_label": entity["type_label"],
                "evidence_count": entity.get("evidence_count", 0),
                "confidence": entity.get("confidence", 0),
            }
        )

    source_nodes = []
    for idx, result in enumerate(evidence[:10], start=1):
        source_id = f"network-source-{idx}"
        source_nodes.append(
            {
                "id": source_id,
                "record_id": result.record.record_id,
                "label": display_text(result.record.title, max_chars=56),
                "type": "source",
                "type_label": "来源" if language == "zh" else "Source",
                "open_url": openable_source_url(result.record),
            }
        )
        for entity in entities[:14]:
            if result.record.record_id in entity.get("sources", []):
                links.append(
                    {
                        "source": entity["id"],
                        "target": source_id,
                        "source_label": entity["label"],
                        "target_label": display_text(result.record.title, max_chars=56),
                        "relation": "见于证据" if language == "zh" else "attested by",
                        "record_id": result.record.record_id,
                        "evidence_title": display_text(result.record.title, max_chars=64),
                    }
                )

    co_occurrence_seen: set[tuple[str, str, str]] = set()
    for result in evidence[:10]:
        linked = [entity for entity in entities[:14] if result.record.record_id in entity.get("sources", [])][:7]
        for left_idx, left in enumerate(linked):
            for right in linked[left_idx + 1:]:
                pair = tuple(sorted([left["id"], right["id"]]))
                key = (pair[0], pair[1], result.record.record_id)
                if key in co_occurrence_seen:
                    continue
                co_occurrence_seen.add(key)
                links.append(
                    {
                        "source": pair[0],
                        "target": pair[1],
                        "source_label": left["label"] if pair[0] == left["id"] else right["label"],
                        "target_label": right["label"] if pair[1] == right["id"] else left["label"],
                        "relation": "同现于材料" if language == "zh" else "co-occurs in source",
                        "record_id": result.record.record_id,
                        "evidence_title": display_text(result.record.title, max_chars=64),
                    }
                )

    direct_claims = [claim for claim in claims if claim.get("status") == "passed"]
    if language == "zh":
        summary = f"当前关系网围绕「{task['label']}」链接 {len(nodes)} 个实体、{len(source_nodes)} 个来源和 {len(links)} 条证据关系。"
    else:
        summary = f"The current network for {task['label']} links {len(nodes)} entities, {len(source_nodes)} sources, and {len(links)} evidence relations."
    return {
        "summary": summary,
        "nodes": (nodes + source_nodes)[:24],
        "links": links[:58],
        "claim_count": len(direct_claims),
        "source_count": len(source_nodes),
    }


def build_spatial_traces(
    entities: list[dict],
    evidence: list[RetrievalResult],
    language: str,
) -> list[dict]:
    place_map: dict[str, dict] = {}

    def add_place(label: str, record: EvidenceRecord | None = None) -> None:
        place = display_text(label, max_chars=42).strip(" ：:，,。.;；、|")
        if not place or place.lower() in {"none", "undated"}:
            return
        key = place.lower()
        if key not in place_map:
            place_map[key] = {
                "place": place,
                "evidence_ids": [],
                "source_titles": [],
                "related_people": [],
                "related_topics": [],
                "geo_statuses": [],
            }
        item = place_map[key]
        if record:
            if record.record_id not in item["evidence_ids"]:
                item["evidence_ids"].append(record.record_id)
            title = display_text(record.title, max_chars=58)
            if title and title not in item["source_titles"]:
                item["source_titles"].append(title)
            item["related_people"].extend(record.persons[:3])
            item["related_topics"].extend(record.topics[:4])
            if record.geo.get("status"):
                item["geo_statuses"].append(str(record.geo.get("status")))

    for entity in entities:
        if entity.get("type") == "place":
            add_place(entity["label"])
    for result in evidence[:10]:
        for place in result.record.places[:5]:
            add_place(place, result.record)

    traces = []
    for item in place_map.values():
        evidence_count = len(item["evidence_ids"])
        if language == "zh":
            modern_note = "现代坐标需接入上海地名志、历史建筑或地理编码服务后确认；当前仅展示来源中的地点线索。"
        else:
            modern_note = "Modern coordinates require gazetteer, historic-building, or geocoding verification; this view only shows place clues attested by sources."
        traces.append(
            {
                "place": item["place"],
                "evidence_ids": item["evidence_ids"][:6],
                "source_titles": item["source_titles"][:4],
                "related_people": unique_terms(item["related_people"])[:5],
                "related_topics": unique_terms(item["related_topics"])[:6],
                "coordinates_status": unique_terms(item["geo_statuses"])[0] if item["geo_statuses"] else "needs_geocoding",
                "modern_position_note": modern_note,
                "confidence": round(min(0.88, 0.48 + evidence_count * 0.08), 2),
            }
        )
    traces.sort(key=lambda item: (len(item["evidence_ids"]), item["confidence"], item["place"]), reverse=True)
    return traces[:8]


def build_story_mode(
    question: str,
    task: dict,
    finding: str,
    timeline_events: list[dict],
    relationship_network: dict,
    spatial_traces: list[dict],
    counter_evidence: list[dict],
    language: str,
) -> dict:
    timeline_titles = [event["title"] for event in timeline_events[:3]]
    place_names = [trace["place"] for trace in spatial_traces[:3]]
    high_boundaries = [item["body"] for item in counter_evidence if item.get("severity") in {"high", "medium"}]
    if language == "zh":
        narrative = (
            f"从「{display_text(question, 52)}」出发，文脉镜先把线索归入「{task['label']}」，再沿着"
            f"{join_terms(timeline_titles, language) or '当前命中的证据材料'}展开。{finding} "
            f"空间上，材料目前指向 {join_terms(place_names, language) or '若干待确认地点'}；关系上，"
            f"{relationship_network.get('summary', '')}"
        )
        boundary = high_boundaries[0] if high_boundaries else "故事模式只改写已绑定证据的内容；缺少年代、坐标或来源的部分保留为待考。"
        chapters = [
            {"title": "线索进入", "body": f"用户提供的入口是：{display_text(question, 86)}"},
            {"title": "证据展开", "body": f"优先打开 {join_terms(timeline_titles, language) or '前几条来源'}，按时间与主题形成叙事骨架。"},
            {"title": "边界提示", "body": boundary},
        ]
    else:
        narrative = (
            f"Starting from {display_text(question, 60)}, ContextLens classifies the clue as {task['label']} and follows "
            f"{join_terms(timeline_titles, language) or 'the current evidence set'}. {finding} "
            f"Spatially, the records point to {join_terms(place_names, language) or 'places requiring verification'}; "
            f"relationally, {relationship_network.get('summary', '')}"
        )
        boundary = high_boundaries[0] if high_boundaries else "Story mode rewrites only evidence-bound content; missing dates, coordinates, or sources remain under verification."
        chapters = [
            {"title": "Clue Entry", "body": f"The user entry is: {display_text(question, 92)}"},
            {"title": "Evidence Arc", "body": f"Open {join_terms(timeline_titles, language) or 'the top sources'} first, then build a timeline and theme arc."},
            {"title": "Boundary", "body": boundary},
        ]
    return {
        "title": "故事模式" if language == "zh" else "Story Mode",
        "public_narrative": narrative,
        "narrative_boundary": boundary,
        "chapters": chapters,
    }


def build_research_mode(
    question: str,
    task: dict,
    plan: list[dict],
    claims: list[dict],
    counter_evidence: list[dict],
    receipt: dict,
    language: str,
) -> dict:
    passed_claims = [claim for claim in claims if claim.get("status") == "passed"]
    review_claims = [claim for claim in claims if claim.get("status") != "passed"]
    if language == "zh":
        method = "问题理解 -> 实体识别与消歧 -> 检索计划 -> 多源证据归一化 -> 人物/地点/事件/文献关联 -> 主张审计 -> 反证与空白 -> 可回放档案。"
        citation_protocol = "No claim without provenance：每条重要结论都必须保留 evidence_ids、来源题名、支撑强度和审计状态。"
        notes = [
            {"title": "可提交主张", "body": display_text(passed_claims[0]["text"], 130) if passed_claims else "暂无可提交主张。", "evidence_ids": passed_claims[0].get("evidence_ids", []) if passed_claims else []},
            {"title": "待复核主张", "body": display_text(review_claims[0]["text"], 130) if review_claims else "暂无新增待复核主张。", "evidence_ids": review_claims[0].get("evidence_ids", []) if review_claims else []},
            {"title": "反证/空白", "body": display_text(counter_evidence[0]["body"], 130) if counter_evidence else "轻量审计未发现明显反证。", "evidence_ids": counter_evidence[0].get("evidence_ids", []) if counter_evidence else []},
        ]
    else:
        method = "Question understanding -> entity recognition/disambiguation -> search plan -> multi-source normalization -> person/place/event/document linking -> claim audit -> gaps and counter-evidence -> replayable dossier."
        citation_protocol = "No claim without provenance: every important conclusion keeps evidence_ids, source titles, support strength, and audit status."
        notes = [
            {"title": "Submittable Claim", "body": display_text(passed_claims[0]["text"], 150) if passed_claims else "No submittable claim yet.", "evidence_ids": passed_claims[0].get("evidence_ids", []) if passed_claims else []},
            {"title": "Review Claim", "body": display_text(review_claims[0]["text"], 150) if review_claims else "No new review claim.", "evidence_ids": review_claims[0].get("evidence_ids", []) if review_claims else []},
            {"title": "Counter-Evidence / Gap", "body": display_text(counter_evidence[0]["body"], 150) if counter_evidence else "The lightweight audit found no obvious counter-evidence.", "evidence_ids": counter_evidence[0].get("evidence_ids", []) if counter_evidence else []},
        ]
    return {
        "title": "研究模式" if language == "zh" else "Research Mode",
        "method": method,
        "citation_protocol": citation_protocol,
        "task_key": task["key"],
        "question": display_text(question, max_chars=180),
        "plan_steps": [{"title": step["title"], "tool": step["tool"], "status": step["status"]} for step in plan],
        "notes": notes,
        "receipt_summary": receipt.get("summary", ""),
    }


def build_follow_up_routes(
    analysis: dict,
    entities: list[dict],
    counter_evidence: list[dict],
    spatial_traces: list[dict],
    language: str,
) -> list[dict]:
    missing_terms = unique_terms(
        [term for item in counter_evidence for term in item.get("terms", [])]
        + analysis.get("missing_terms", [])
    )
    top_entities = [entity["label"] for entity in entities[:4]]
    top_places = [trace["place"] for trace in spatial_traces[:3]]
    focus = join_terms(analysis.get("terms", [])[:3] or top_entities[:3], language)
    if language == "zh":
        return [
            {
                "title": "扩展别名与异写",
                "question": f"{focus or '这条线索'}还有哪些历史名称、别名或异写形式？",
                "purpose": "提升实体消歧质量，减少同名误配。",
            },
            {
                "title": "补齐证据空白",
                "question": f"继续检索 {join_terms(missing_terms[:5], language) or focus or '缺失对象'}，哪些来源能直接证明或反驳当前主张？",
                "purpose": "把弱支撑或缺失项转成下一轮可执行检索。",
            },
            {
                "title": "空间复核",
                "question": f"{join_terms(top_places, language) or '相关地点'}在历史地名和现代地图中如何对应？",
                "purpose": "为地图层接入地名志、历史建筑和地理编码服务。",
            },
            {
                "title": "公众叙事",
                "question": f"如果把 {focus or '该线索'} 写成可分享故事，哪些句子必须保留来源脚注？",
                "purpose": "把故事模式与研究模式保持一致。",
            },
        ]
    return [
        {
            "title": "Expand Aliases",
            "question": f"What historical names, aliases, or variant spellings exist for {focus or 'this clue'}?",
            "purpose": "Improve disambiguation and reduce false matches.",
        },
        {
            "title": "Fill Evidence Gaps",
            "question": f"Which sources directly prove or challenge {join_terms(missing_terms[:5], language) or focus or 'the missing objects'}?",
            "purpose": "Turn weak support and missing terms into executable follow-up searches.",
        },
        {
            "title": "Review Space",
            "question": f"How do {join_terms(top_places, language) or 'the related places'} map between historical gazetteers and modern locations?",
            "purpose": "Prepare the map layer for gazetteer, historic-building, and geocoding tools.",
        },
        {
            "title": "Public Narrative",
            "question": f"If {focus or 'this clue'} becomes a shareable story, which sentences require source footnotes?",
            "purpose": "Keep story mode aligned with research mode.",
        },
    ]


def build_quality_gates(
    claims: list[dict],
    counter_evidence: list[dict],
    receipt: dict,
    spatial_traces: list[dict],
    language: str,
) -> list[dict]:
    auditable_claims = [claim for claim in claims if claim.get("id") != "claim-gap"]
    provenance_ok = all(claim.get("evidence_ids") for claim in auditable_claims) if auditable_claims else False
    source_diversity = len(receipt.get("datasets_queried") or [])
    conflicts = int(receipt.get("conflicts_detected") or 0)
    live_percentage = int(receipt.get("official_percentage") or receipt.get("live_percentage") or 0)
    public_tags = len(receipt.get("public_tags") or [])
    geocode_needed = any(trace.get("coordinates_status") == "needs_geocoding" for trace in spatial_traces)

    if language == "zh":
        return [
            quality_gate("claim_provenance", "主张来源绑定", "pass" if provenance_ok else "review", "每条非空白主张都需要绑定至少一条 evidence_id。", language),
            quality_gate("source_diversity", "来源多样性", "pass" if source_diversity >= 2 else "review", f"本次使用 {source_diversity} 类数据集；正式展示建议至少覆盖 2 类来源。", language),
            quality_gate("public_reuse", "公众复用入口", "pass" if public_tags >= 2 else "review", f"本次命中 {public_tags} 类公众标签；建议让线索可转化为城市漫游、家族记忆或文献侦探入口。", language),
            quality_gate("counter_evidence", "反证与空白", "review" if conflicts else "pass", f"发现 {conflicts} 个中高优先级证据边界。", language),
            quality_gate("live_replacement", "官方数据覆盖", "pass" if live_percentage > 0 else "review", f"已核验官方来源占比 {live_percentage}%；demo seed 需在使用前全部核实。", language),
            quality_gate("spatial_precision", "空间精度", "review" if geocode_needed else "pass", "地图展示前需要完成历史地名到现代坐标的复核。", language),
        ]
    return [
        quality_gate("claim_provenance", "Claim Provenance", "pass" if provenance_ok else "review", "Every non-gap claim should bind at least one evidence_id.", language),
        quality_gate("source_diversity", "Source Diversity", "pass" if source_diversity >= 2 else "review", f"This run used {source_diversity} dataset families; formal use should cover at least two.", language),
        quality_gate("public_reuse", "Public Reuse Entry", "pass" if public_tags >= 2 else "review", f"This run matched {public_tags} public-use tags; try to make the clue usable as a city walk, family-memory, or document-detective entry.", language),
        quality_gate("counter_evidence", "Counter-Evidence and Gaps", "review" if conflicts else "pass", f"Found {conflicts} medium/high evidence boundaries.", language),
        quality_gate("live_replacement", "Official Data Coverage", "pass" if live_percentage > 0 else "review", f"Verified official-source ratio is {live_percentage}%; replace all demo seeds before relying on the result.", language),
        quality_gate("spatial_precision", "Spatial Precision", "review" if geocode_needed else "pass", "Map publication requires historical-to-modern place verification.", language),
    ]


def quality_gate(key: str, title: str, status: str, detail: str, language: str) -> dict:
    labels = {
        "pass": {"zh": "通过", "en": "Pass"},
        "review": {"zh": "待复核", "en": "Review"},
        "fail": {"zh": "未通过", "en": "Fail"},
    }
    return {
        "key": key,
        "title": title,
        "status": status,
        "status_label": labels.get(status, labels["review"])[language],
        "detail": detail,
    }


def build_professional_briefing(
    *,
    question: str,
    evidence: list[RetrievalResult],
    investigation: dict,
    question_analysis: dict,
    evidence_fit: dict,
    audit: dict,
    award_readiness: dict,
    language: str,
) -> list[dict]:
    receipt = investigation.get("receipt") or {}
    task = investigation.get("task") or {}
    datasets = receipt.get("datasets_queried") or []
    evidence_types = receipt.get("evidence_types") or []
    public_tags = receipt.get("public_tags") or []
    missing = unique_terms((evidence_fit.get("missing_terms") or []) + (question_analysis.get("missing_terms") or []))
    top_titles = [display_text(result.record.title, max_chars=42) for result in evidence[:4]]
    live_ratio = int(receipt.get("official_percentage") or receipt.get("live_percentage") or 0)
    fit_label = evidence_fit.get("level_label") or evidence_fit.get("level") or ""
    award_score = award_readiness.get("overall_score", 0)
    if language == "zh":
        risk_text = "当前主要风险是人工复核前 3 个来源的题名、年代和馆藏类型。"
        if live_ratio < 60 and missing:
            risk_text = f"仍需替换 demo seed，并优先复核 {join_terms(missing[:5], language)}。"
        elif live_ratio < 60:
            risk_text = "仍需把核心 demo seed 替换为已核验官方记录，再做人工来源复核。"
        elif missing:
            risk_text = f"仍需补齐 {join_terms(missing[:5], language)} 的直接来源。"
        return [
            {
                "key": "researchDesign",
                "title": "研究设计",
                "body": f"本次线索被组织为「{task.get('label', '历史调查')}」：先做对象消歧，再以 {join_terms(question_analysis.get('terms', [])[:5], language) or display_text(question, 40)} 为核心建立人物、地点、文献、事件和主张关系。",
            },
            {
                "key": "dataStrategy",
                "title": "数据策略",
                "body": f"当前调用 {len(evidence)} 条候选证据，覆盖 {len(datasets)} 类数据集和 {len(evidence_types)} 类证据形态；优先证据包括 {join_terms(top_titles, language) or '当前检索结果'}。",
            },
            {
                "key": "evidenceProtocol",
                "title": "证据协议",
                "body": f"每个重要结论必须绑定 evidence_ids、来源题名、支撑强度和审计状态；当前证据贴合度为{fit_label}，引用覆盖率 {round(float(audit.get('citation_coverage') or 0) * 100)}%。",
            },
            {
                "key": "publicProductization",
                "title": "公众化呈现",
                "body": f"该线索命中 {join_terms(public_tags[:6], language) or '公共历史'} 场景，可转化为城市漫游、家族记忆、文献侦探、社区展陈或课堂讲解材料。",
            },
            {
                "key": "submissionRisks",
                "title": "证据使用边界",
                "body": f"Live API 占比为 {live_ratio}%；{risk_text}",
            },
            {
                "key": "curatorialPitch",
                "title": "展陈表达",
                "body": f"档案包含一句话发现、证据图谱、主张台账、反证空白和数据使用收据。启发式原型诊断评分为 {award_score}/100。",
            },
        ]
    risk_text = "the main remaining risk is manual review of the top three source titles, dates, and collection types."
    if live_ratio < 60 and missing:
        risk_text = f"replace demo seeds and review {join_terms(missing[:5], language)}."
    elif live_ratio < 60:
        risk_text = "replace the core demo seed records with verified official records, then manually review sources."
    elif missing:
        risk_text = f"add direct sources for {join_terms(missing[:5], language)}."
    return [
        {
            "key": "researchDesign",
            "title": "Research Design",
            "body": f"The clue is organized as {task.get('label', 'a historical investigation')}: disambiguate objects first, then build people, place, document, event, and claim relations around {join_terms(question_analysis.get('terms', [])[:5], language) or display_text(question, 52)}.",
        },
        {
            "key": "dataStrategy",
            "title": "Data Strategy",
            "body": f"The run uses {len(evidence)} candidate records across {len(datasets)} dataset families and {len(evidence_types)} evidence types; leading sources include {join_terms(top_titles, language) or 'the current retrieval set'}.",
        },
        {
            "key": "evidenceProtocol",
            "title": "Evidence Protocol",
            "body": f"Every important conclusion keeps evidence_ids, source titles, support strength, and audit status; evidence fit is {fit_label}, with {round(float(audit.get('citation_coverage') or 0) * 100)}% citation coverage.",
        },
        {
            "key": "publicProductization",
            "title": "Public Productization",
            "body": f"The clue matches {join_terms(public_tags[:6], language) or 'public-history'} scenarios and can become a city walk, family-memory trace, document-detective route, community exhibit, or classroom explainer.",
        },
        {
            "key": "submissionRisks",
            "title": "Evidence-use Limits",
            "body": f"Live API ratio is {live_ratio}%; {risk_text}",
        },
        {
            "key": "curatorialPitch",
            "title": "Curatorial Pitch",
            "body": f"The dossier links its finding, evidence graph, claim ledger, gaps, and data-use receipt. The heuristic prototype diagnostic score is {award_score}/100.",
        },
    ]


def build_award_readiness(
    *,
    question: str,
    evidence: list[RetrievalResult],
    investigation: dict,
    audit: dict,
    evidence_fit: dict,
    language: str,
) -> dict:
    receipt = investigation.get("receipt") or {}
    gates = investigation.get("quality_gates") or []
    task = (investigation.get("task") or {}).get("key", "")
    public_tag_count = len(receipt.get("public_tags") or [])
    dataset_count = len(receipt.get("datasets_queried") or [])
    evidence_type_count = len(receipt.get("evidence_types") or [])
    records_examined = int(receipt.get("records_examined") or len(evidence))
    direct_claims = int(receipt.get("direct_claims") or 0)
    sources_cited = int(receipt.get("sources_cited") or 0)
    live_percentage = int(receipt.get("official_percentage") or receipt.get("live_percentage") or 0)
    citation_coverage = float(audit.get("citation_coverage") or 0)
    pass_gates = sum(1 for gate in gates if gate.get("status") == "pass")
    review_gates = len(gates) - pass_gates
    replay_steps = len(investigation.get("replay") or [])
    timeline_count = len(investigation.get("timeline_events") or [])
    graph_nodes = len(((investigation.get("graph") or {}).get("nodes")) or [])
    follow_routes = len(investigation.get("follow_up_routes") or [])
    spatial_count = len(investigation.get("spatial_traces") or [])

    public_scope = min(
        100,
        36
        + public_tag_count * 8
        + (14 if task in {"city_memory", "family_memory", "trace_person", "explore_place", "read_document"} else 6)
        + (10 if investigation.get("story_mode", {}).get("public_narrative") else 0)
        + (8 if follow_routes >= 3 else 0),
    )
    library_utilization = min(
        100,
        records_examined * 7
        + dataset_count * 11
        + evidence_type_count * 9
        + live_percentage * 0.25,
    )
    traceability = min(
        100,
        citation_coverage * 38
        + min(28, direct_claims * 8)
        + min(18, sources_cited * 3)
        + pass_gates * 3,
    )
    investigation_depth = min(
        100,
        28
        + min(18, replay_steps * 3)
        + min(16, timeline_count * 2)
        + min(18, graph_nodes)
        + min(10, spatial_count * 3)
        + min(10, follow_routes * 2),
    )
    guardrails = max(
        20,
        min(
            100,
            86
            + pass_gates * 2
            - review_gates * 5
            - int(receipt.get("conflicts_detected") or 0) * 4
            - (8 if audit.get("financial_advice_check") == "guarded" else 0),
        ),
    )
    novelty = min(
        100,
        34
        + (14 if investigation.get("claims") else 0)
        + (14 if investigation.get("counter_evidence") else 0)
        + (12 if investigation.get("relationship_network", {}).get("links") else 0)
        + (12 if investigation.get("story_mode", {}).get("public_narrative") else 0)
        + (10 if investigation.get("research_mode", {}).get("citation_protocol") else 0)
        + (8 if "StableTrade" not in question else 0),
    )
    if live_percentage == 0:
        library_utilization = min(library_utilization, 68)
        traceability = min(traceability, 84)
    elif live_percentage < 50:
        library_utilization = min(library_utilization, 82)

    items = [
        readiness_item("public_reuse", "公众复用吸引力", "Public Reusability", public_scope, public_scope_detail(task, public_tag_count, follow_routes, language), language),
        readiness_item("library_data_use", "图书馆数据利用", "Library Data Use", library_utilization, library_use_detail(dataset_count, evidence_type_count, records_examined, language), language),
        readiness_item("traceability", "主张级可追溯", "Claim Traceability", traceability, traceability_detail(direct_claims, sources_cited, citation_coverage, language), language),
        readiness_item("investigation_depth", "智能体调查深度", "Investigation Depth", investigation_depth, depth_detail(replay_steps, timeline_count, graph_nodes, spatial_count, language), language),
        readiness_item("guardrails", "护栏与审计", "Guardrails and Audit", guardrails, guardrail_detail(pass_gates, review_gates, audit, language), language),
        readiness_item("differentiation", "创新差异化", "Differentiation", novelty, novelty_detail(language), language),
    ]
    overall = round(sum(item["score"] for item in items) / len(items)) if items else 0
    if live_percentage == 0:
        overall = min(overall, 79)
    elif live_percentage < 50:
        overall = min(overall, 86)
    level = "excellent" if overall >= 82 else "strong" if overall >= 68 else "developing"
    if language == "zh":
        summary = f"原型诊断 {overall}/100（{readiness_level_label(level, language)}）：当前优势在于可追溯调查档案与公众入口；使用结论前优先完成官方来源人工复核和空间坐标复核。"
    else:
        summary = f"The heuristic prototype diagnostic score is {overall}/100 ({readiness_level_label(level, language)}): current strengths are traceable dossiers and public-use entry points; before relying on the result, complete manual official-source and spatial verification."
    return {
        "overall_score": overall,
        "level": level,
        "level_label": readiness_level_label(level, language),
        "summary": summary,
        "items": items,
        "action_items": award_action_items(receipt, audit, evidence_fit, language),
    }


def readiness_item(key: str, zh_title: str, en_title: str, score: float, detail: str, language: str) -> dict:
    score_int = round(max(0, min(100, score)))
    return {
        "key": key,
        "title": zh_title if language == "zh" else en_title,
        "score": score_int,
        "status": "pass" if score_int >= 75 else "review" if score_int >= 50 else "weak",
        "status_label": readiness_status_label(score_int, language),
        "detail": detail,
    }


def readiness_status_label(score: int, language: str) -> str:
    if language == "zh":
        return "强" if score >= 75 else "待增强" if score >= 50 else "薄弱"
    return "Strong" if score >= 75 else "Needs Work" if score >= 50 else "Weak"


def readiness_level_label(level: str, language: str) -> str:
    labels = {
        "excellent": {"zh": "优秀", "en": "Excellent"},
        "strong": {"zh": "较强", "en": "Strong"},
        "developing": {"zh": "仍需打磨", "en": "Developing"},
    }
    return labels.get(level, labels["developing"])[language]


def public_scope_detail(task: str, public_tag_count: int, follow_routes: int, language: str) -> str:
    if language == "zh":
        return f"当前任务为 {task or 'unknown'}，命中 {public_tag_count} 类公众标签，并生成 {follow_routes} 条继续追问路线。"
    return f"The task is {task or 'unknown'}, with {public_tag_count} public-use tags and {follow_routes} follow-up routes."


def library_use_detail(dataset_count: int, evidence_type_count: int, records_examined: int, language: str) -> str:
    if language == "zh":
        return f"本次使用 {dataset_count} 类数据集、{evidence_type_count} 类证据形态，检查 {records_examined} 条记录。"
    return f"This run used {dataset_count} dataset families and {evidence_type_count} evidence types across {records_examined} records."


def traceability_detail(direct_claims: int, sources_cited: int, citation_coverage: float, language: str) -> str:
    if language == "zh":
        return f"{direct_claims} 条直接主张、{sources_cited} 个可打开来源，引用覆盖率 {round(citation_coverage * 100)}%。"
    return f"{direct_claims} direct claims, {sources_cited} openable sources, and {round(citation_coverage * 100)}% citation coverage."


def depth_detail(replay_steps: int, timeline_count: int, graph_nodes: int, spatial_count: int, language: str) -> str:
    if language == "zh":
        return f"包含 {replay_steps} 步调查回放、{timeline_count} 个时间线节点、{graph_nodes} 个图谱节点和 {spatial_count} 个空间线索。"
    return f"Includes {replay_steps} replay steps, {timeline_count} timeline nodes, {graph_nodes} graph nodes, and {spatial_count} spatial traces."


def guardrail_detail(pass_gates: int, review_gates: int, audit: dict, language: str) -> str:
    if language == "zh":
        return f"{pass_gates} 个质量闸门通过、{review_gates} 个待复核；不确定性状态为 {audit.get('uncertainty_level', 'unknown')}。"
    return f"{pass_gates} quality gates pass and {review_gates} need review; uncertainty is {audit.get('uncertainty_level', 'unknown')}."


def novelty_detail(language: str) -> str:
    if language == "zh":
        return "差异化来自主张台账、反证提示、调查回放、故事/研究双模式和可打开来源，而不是泛泛 RAG。"
    return "Differentiation comes from claim ledgers, counter-evidence, replay, story/research modes, and openable sources rather than generic RAG."


def award_action_items(receipt: dict, audit: dict, evidence_fit: dict, language: str) -> list[str]:
    actions = []
    if int(receipt.get("official_percentage") or receipt.get("live_percentage") or 0) < 60:
        actions.append("将核心 demo seed 替换为已核验官方记录。" if language == "zh" else "Replace core demo seed records with verified official records.")
    if evidence_fit.get("level") == "weak":
        actions.append("收窄问题对象并补充直接来源。" if language == "zh" else "Narrow the clue and add direct sources.")
    if int(receipt.get("conflicts_detected") or 0):
        actions.append("把中高优先级证据空白转成下一轮检索词。" if language == "zh" else "Turn medium/high evidence gaps into the next retrieval terms.")
    if audit.get("citation_coverage", 0) < 1:
        actions.append("确保前 3 条证据都有可打开来源。" if language == "zh" else "Ensure the top three evidence cards have openable sources.")
    if not actions:
        actions.append("公开展示前打开前 3 个来源做人工复核。" if language == "zh" else "Before public demo, manually review the top three sources.")
    return actions[:4]


def build_investigation_finding(
    question: str,
    task: dict,
    claims: list[dict],
    evidence_fit: dict,
    counter_evidence: list[dict],
    language: str,
) -> str:
    passed = [claim for claim in claims if claim.get("status") == "passed"]
    review_count = sum(1 for item in counter_evidence if item.get("severity") in {"high", "medium"})
    fit_label = evidence_fit.get("level_label") or evidence_fit.get("level") or ""
    first_claim = passed[0]["text"] if passed else ""
    if language == "zh":
        if first_claim:
            return f"这条线索可作为「{task['label']}」入口，证据贴合度为{fit_label}；{display_text(first_claim, 96)} 仍有 {review_count} 个需要复核的证据边界。"
        return "这条线索目前证据不足，应先扩大检索词并补充 live API 记录后再生成历史档案。"
    if first_claim:
        return f"This clue works as a {task['label']} entry with {fit_label} evidence fit; {display_text(first_claim, 112)} There are {review_count} evidence boundaries to review."
    return "The current clue does not have enough evidence yet; broaden search terms and add live API records before building the dossier."


def pct(numerator: int, denominator: int) -> int:
    return round((numerator / denominator) * 100) if denominator else 0


def normalize_signal(value: str) -> str:
    cleaned = display_text(value, max_chars=28).strip(" ：:，,。.;；、|")
    if not cleaned or cleaned.lower() in {"none", "undated"}:
        return ""
    return cleaned


def era_sort_key(date: str) -> int:
    value = str(date or "")
    year = re.search(r"([12][0-9]{3}|[1-9][0-9]{2})", value)
    if year:
        return int(year.group(1))
    era_rank = [
        ("汉", -200),
        ("唐", 700),
        ("宋", 1050),
        ("元", 1300),
        ("明", 1500),
        ("清", 1750),
        ("晚清", 1880),
        ("近代", 1900),
        ("民国", 1915),
    ]
    matches = [rank for token, rank in era_rank if token in value]
    return min(matches) if matches else 9999


def summarize_problem(question: str, language: str = "en", analysis: dict | None = None) -> str:
    analysis = analysis or {}
    terms = join_terms(analysis.get("terms", [])[:5], language)
    intent_label = analysis.get("intent_label", "")
    focus = analysis.get("focus", "")
    if any(term in question for term in ["稳定币", "stablecoin", "结算", "支付"]):
        if language == "zh":
            return f"这个问题在问 {terms or '可信跨境价值转移'} 的{intent_label or '历史解释'}，重点是能否从货币、信用与结算制度中找到可被证据支撑的结构机制。"
        return f"The question asks for {intent_label or 'a historical explanation'} of {terms or 'trusted cross-border value transfer'} through monetary and settlement institutions."
    if any(term in question for term in ["海关", "口岸", "港口", "供应链"]):
        if language == "zh":
            return f"这个问题在问 {terms or '口岸、海关与通道制度'} 如何影响贸易协调，适合从登记、征税、融资、航运和治理能力几个层面回答。"
        return f"The question asks how {terms or 'port, customs, and corridor institutions'} shaped trade coordination through registration, taxation, finance, shipping, and governance."
    if any(term in question for term in ["外交", "一带一路", "丝绸之路", "商路"]):
        if language == "zh":
            return f"这个问题在问 {terms or '贸易路线、外交关系与制度信任'} 如何连接成长期交换网络，核心焦点是 {focus or '通道与信任机制'}。"
        return f"The question asks how {terms or 'trade routes, diplomacy, and institutional trust'} formed durable exchange networks; the focus is {focus or 'corridor and trust mechanisms'}."
    if any(term in question for term in ["旧地址", "城市记忆", "外滩", "南京路", "石库门", "里弄", "老照片", "老地图"]):
        if language == "zh":
            return f"这个问题在问 {terms or '城市记忆线索'} 如何被拆成地点、人物、机构、文献和空间复核路径，重点是让公众能走读、能追问、能打开来源。"
        return f"The question asks how {terms or 'a city-memory clue'} can be split into places, people, institutions, documents, and spatial verification."
    if any(term in question for term in ["家谱", "族谱", "祖籍", "校友录", "亲属", "寻亲"]):
        if language == "zh":
            return f"这个问题在问 {terms or '个人/家族线索'} 如何经过姓名、地点和文献消歧后形成可复核证据链。"
        return f"The question asks how {terms or 'a personal or family clue'} can become a verifiable chain through name, place, and document disambiguation."
    if any(term in question for term in ["张爱玲", "宋庆龄", "鲁迅", "电影", "影院", "公共文化"]):
        if language == "zh":
            return f"这个问题在问 {terms or '公共文化线索'} 如何连接人物、地点、机构、作品和公众叙事边界。"
        return f"The question asks how {terms or 'a public-culture clue'} connects people, places, institutions, works, and narrative boundaries."
    if language == "zh":
        return f"这个问题需要围绕 {terms or focus or '用户提出的研究对象'} 构建历史证据解释，并按「{intent_label or '综合研究解释'}」来组织回答。"
    return f"The question needs a historical evidence explanation around {terms or focus or 'the user research object'}, organized as {intent_label or 'general research explanation'}."


def infer_mechanism(question: str, evidence: list[RetrievalResult], language: str = "en", analysis: dict | None = None) -> str:
    analysis = analysis or {}
    text = " ".join(r.record.title + " " + r.record.snippet for r in evidence)
    parts = []
    if any(term in text for term in ["银", "纸币", "银行", "票号", "汇兑", "结算", "信用"]):
        parts.append(
            "货币与信用机制通过标准化价值、允许延期支付、建立可信中介来降低交易不确定性。"
            if language == "zh"
            else "Money and credit mechanisms reduced uncertainty by standardizing value, enabling delayed payment, and creating trusted intermediaries."
        )
    if any(term in text for term in ["海关", "关税", "口岸", "港口"]):
        parts.append(
            "海关与口岸制度把跨境交换转化为可计量、可征税、可治理的流动。"
            if language == "zh"
            else "Customs and port institutions turned cross-border exchange into measurable, taxable, and administratively legible flows."
        )
    if any(term in text for term in ["丝绸之路", "使节", "外交", "条约", "边疆"]):
        parts.append(
            "外交、路线与边疆制度影响谁可以交易、交换在哪里发生，以及冲突和信任如何被管理。"
            if language == "zh"
            else "Diplomatic and route institutions shaped who could trade, where exchange occurred, and how conflict or trust was managed."
        )
    if any(term in text for term in ["旧地址", "城市记忆", "地名", "老地图", "老照片", "石库门", "里弄", "南京路"]):
        parts.append(
            "城市记忆调查依赖地名消歧、历史空间复核、机构占用和文献出处之间的交叉确认。"
            if language == "zh"
            else "City-memory investigation depends on place-name disambiguation, spatial review, institutional occupancy, and source provenance."
        )
    if any(term in text for term in ["家谱", "族谱", "祖籍", "校友录", "亲属", "寻亲"]):
        parts.append(
            "个人/家族线索需要把姓名、亲属关系、旧居和文献题名分开验证，避免把同名或传闻当作确定关系。"
            if language == "zh"
            else "Personal or family clues require separate checks for names, kinship, old residences, and document titles to avoid false identity links."
        )
    if any(term in text for term in ["张爱玲", "宋庆龄", "鲁迅", "电影", "影院", "公共文化", "出版"]):
        parts.append(
            "公共文化线索适合转化为故事模式，但每个人物、地点、作品或机构关系仍必须回到证据卡。"
            if language == "zh"
            else "Public-culture clues can become story-mode outputs, but every person, place, work, or institution link must return to evidence cards."
        )
    if not parts:
        parts.append(
            "现有证据表明，可信交换依赖能连接价值、流动与权威的制度安排。"
            if language == "zh"
            else "The available evidence suggests that trusted exchange depends on institutions that connect value, movement, and authority."
        )
    terms = join_terms(analysis.get("terms", [])[:4], language)
    if language == "zh":
        return f"围绕 {terms or analysis.get('focus', '该问题')}，机制链条可以概括为：{' '.join(parts)}"
    return f"For {terms or analysis.get('focus', 'this question')}, the mechanism chain is: {' '.join(parts)}"


def build_historical_fact(evidence: list[RetrievalResult], language: str, analysis: dict | None = None) -> str:
    analysis = analysis or {}
    if not evidence:
        return "当前索引没有找到足够证据，应扩大关键词或重新导入数据。" if language == "zh" else "The current index did not return enough evidence; broaden the query or re-run ingestion."
    titles = "；".join(display_text(r.record.title, max_chars=80) for r in evidence[:3])
    terms = join_terms(analysis.get("terms", [])[:4], language)
    if language == "zh":
        return f"围绕 {terms or analysis.get('focus', '该问题')}，检索到的主要证据包括：{titles}。这些材料不是泛泛历史背景，而是为问题中的对象提供具体线索。"
    return f"For {terms or analysis.get('focus', 'this question')}, the leading evidence cards include: {titles}. They provide direct signals for the user's object of inquiry."


def build_interpretation(question: str, evidence: list[RetrievalResult], language: str, analysis: dict | None = None) -> str:
    analysis = analysis or {}
    direct_need = analysis.get("direct_need", "")
    if language == "zh":
        return f"{direct_need} 这些证据不能自动推出政策结论，但可以帮助区分哪些是历史事实、哪些是制度机制、哪些只是现代类比。"
    return f"{direct_need} These evidence cards do not automatically produce policy conclusions, but they help separate historical fact, institutional mechanism, and analogy boundaries."


def build_modern_analogy(question: str, evidence: list[RetrievalResult], language: str, output_style: str, analysis: dict | None = None) -> str:
    analysis = analysis or {}
    terms = join_terms(analysis.get("terms", [])[:4], language)
    if output_style == "policy_analogy":
        if language == "zh":
            return f"可谨慎使用的现代类比是：{terms or '用户问题中的对象'} 往往依赖价值计量、可信中介、通关治理、路线安全与外交承认的组合，而不是单一技术或单一市场机制。"
        return f"A careful modern analogy is that {terms or 'the user object'} usually depends on value measurement, trusted intermediaries, customs governance, route security, and diplomatic recognition rather than one technology or market mechanism."
    if output_style == "timeline":
        if language == "zh":
            return f"当前版本围绕 {terms or '该问题'} 提供证据卡时间线线索；正式时间线仍需要补充更明确的朝代、年份和事件字段。"
        return f"The current version provides timeline signals around {terms or 'this question'}; a fuller timeline needs clearer dynasty, year, and event fields."
    if analysis.get("focus_key") in {"urban_memory", "family_memory", "documentary_provenance"}:
        if language == "zh":
            return f"如果要把 {terms or '该线索'} 写成公众故事，类比和叙事只能围绕来源已经支撑的人物、地点、文献和时间关系展开；缺少来源的部分必须保留为待考。"
        return f"If {terms or 'this clue'} becomes a public story, the narrative should stay within source-backed people, places, documents, and time relations; unsupported parts must remain under verification."
    if language == "zh":
        return f"如果要把 {terms or '该问题'} 放到现代语境中，类比只能限定在信任、计量、通道治理和制度协调层面，不能作为投资、监管或支付实施建议。"
    return f"If {terms or 'this question'} is placed in a modern context, the analogy should stay at the level of trust, measurement, corridor governance, and institutional coordination."


def analogy_boundary(language: str) -> str:
    if language == "zh":
        return "本回答把历史作为比较证据，而不是直接政策处方；它区分历史事实、解释推断与现代类比。"
    return "This response uses history as evidence for comparison, not as a direct policy prescription. It separates historical fact, interpretation, and modern analogy."


def uncertainty_note(language: str) -> str:
    if language == "zh":
        return "对外提交前，应优先使用可追溯的上海图书馆官方记录，并对关键引用做人工复核。"
    return "Before relying on the result, prioritize traceable official Shanghai Library records and manually review key citations."


def compliance_note(language: str) -> str:
    if language == "zh":
        return "文脉镜 ContextLens 是教育与公共知识原型，不提供 investment、trading、legal、regulatory 或 payment-implementation advice。"
    return "ContextLens is an educational and public-knowledge prototype. It does not provide investment, trading, legal, regulatory, or payment-implementation advice."


def explain_relevance(result: RetrievalResult, language: str, analysis: dict | None = None) -> str:
    analysis = analysis or {}
    matched = "、".join(result.matched_terms[:6]) if result.matched_terms else "none"
    terms = join_terms(analysis.get("terms", [])[:4], language)
    if language == "zh":
        return f"命中关键词：{matched}；它与用户问题中的 {terms or analysis.get('focus', '核心对象')} 相关，尤其适合支撑「{analysis.get('intent_label', '研究解释')}」这一回答方向。"
    return f"Matched terms: {matched}; this source connects to {terms or analysis.get('focus', 'the core object')} and supports the {analysis.get('intent_label', 'research explanation')} direction."


def build_citation_text(result: RetrievalResult) -> str:
    record = result.record
    date = f", {record.date}" if record.date else ""
    return f"{display_text(record.title, max_chars=140)}{date}. {record.source}. {openable_source_url(record)}"


def openable_source_url(record: EvidenceRecord) -> str:
    uri = str(record.source_uri or "")
    if is_specific_public_source_uri(uri):
        return canonical_public_source_uri(uri)
    if uri.startswith("http://") or uri.startswith("https://"):
        if is_generic_library_resource(uri):
            return source_detail_url(record)
        return uri
    return source_detail_url(record)


def source_detail_url(record: EvidenceRecord) -> str:
    return f"/source/{quote(record.record_id, safe='')}"


def is_specific_public_source_uri(uri: str) -> bool:
    value = str(uri or "").strip().lower()
    if not value.startswith(("http://", "https://")):
        return False
    if is_generic_library_resource(value):
        return False
    return "data.library.sh.cn/entity/" in value or "data.library.sh.cn/" in value or "data1.library.sh.cn/" in value


def canonical_public_source_uri(uri: str) -> str:
    value = str(uri or "").strip()
    if "data.library.sh.cn/entity" in uri:
        return re.sub(r"^http://", "https://", value, count=1)
    return value


def is_generic_library_resource(uri: str) -> bool:
    value = str(uri or "").strip().lower()
    return value.startswith("https://www.library.sh.cn/resource?type=") or value.startswith("http://www.library.sh.cn/resource?type=")


def display_text(value: str, max_chars: int = 240) -> str:
    cleaned = (
        str(value or "")
        .replace("@chs", "")
        .replace("@cht", "")
        .replace("；；", "；")
        .strip("；,， ")
    )
    cleaned = " ".join(cleaned.replace("\r", " ").replace("\n", " ").split())
    cleaned = prefer_simplified_label(cleaned)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 1)].rstrip() + "…"


def prefer_simplified_label(value: str) -> str:
    parts = [part.strip() for part in value.split("；") if part.strip()]
    if not (1 < len(parts) <= 4 and len(value) <= 180):
        return value
    simplified_chars = set("国银行业会联合准备员关处图书东华发县历货币经济学档案资料丛")
    traditional_chars = set("國銀業會聯準備員關處圖書東華發縣歷貨幣經濟學檔案資料叢")

    def score(part: str) -> tuple[int, int]:
        return (sum(ch in simplified_chars for ch in part) - sum(ch in traditional_chars for ch in part), -len(part))

    best = max(parts, key=score)
    return best if score(best)[0] > 0 else parts[0]


def infer_future_questions(question: str, language: str = "en", analysis: dict | None = None) -> list[str]:
    analysis = analysis or {}
    terms = join_terms(analysis.get("terms", [])[:4], language)
    focus = analysis.get("focus", "")
    if language == "zh":
        return [
            f"围绕 {terms or focus or '该问题'}，还缺少哪些更直接的上海图书馆来源？",
            f"{terms or focus or '该问题'} 中哪些部分是事实证据，哪些只是解释推断？",
            f"如果继续追问，应优先扩大到哪些相邻关键词：{join_terms(analysis.get('evidence_terms', [])[:4], language) or '当前主题信号'}？",
            "哪些证据卡需要在公开演示或提交前人工复核题名、时期和来源链接？",
        ]
    return [
        f"Which more direct Shanghai Library sources are still missing for {terms or focus or 'this question'}?",
        f"Which parts of {terms or focus or 'this question'} are evidence-backed, and which are interpretive?",
        f"Which adjacent retrieval terms should be tried next: {join_terms(analysis.get('evidence_terms', [])[:4], language) or 'the current topic signals'}?",
        "Which evidence cards need manual review of title, period, and source link before a public demo?",
    ]
