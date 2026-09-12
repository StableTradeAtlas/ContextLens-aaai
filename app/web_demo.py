from __future__ import annotations

import json
import os
import hashlib
from collections import Counter
from datetime import UTC, datetime
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse

from app.agent import answer_question, display_text, openable_source_url, source_detail_url
from app.config import LOG_DIR, get_settings
from app.ingest import ingest
from app.storage import count_records, count_records_by_source, get_record, load_last_ingest_report, load_records


HOST = "127.0.0.1"
VERSION = "0.3-contextlens"
MAX_QUESTION_LENGTH = 800


def get_port() -> int:
    for key in ("CONTEXTLENS_PORT", "STABLETRADE_PORT"):
        value = os.environ.get(key)
        if not value:
            continue
        try:
            return int(value)
        except ValueError:
            return 8765
    return 8765


MODES = [
    {
        "id": "trace_person",
        "zh": "追一个人",
        "en": "Trace a Person",
        "desc_zh": "从姓名、别名或相关线索出发，重建人物、地点、机构、事件和文献网络。",
        "desc_en": "Start from a name, alias, or clue and rebuild the person-place-organization-event-document network.",
        "lens_zh": "先做身份与别名消歧，再把每条人物关系绑定到可打开证据。",
        "lens_en": "Resolve identity and aliases first, then bind each relationship to openable evidence.",
        "terms": ["人物", "传记", "别名", "机构", "地点", "事件", "文献"],
    },
    {
        "id": "explore_place",
        "zh": "寻一处地",
        "en": "Explore a Place",
        "desc_zh": "从旧址、道路、建筑或地名出发，追踪历史名称、空间变化、机构占用和事件痕迹。",
        "desc_en": "Start from an old address, road, building, or place name and trace names, spatial change, occupants, and events.",
        "lens_zh": "把地点视为会随时间变化的历史实体，优先核对名称、年代、空间和来源。",
        "lens_en": "Treat the place as a changing historical entity and verify name, date, space, and source.",
        "terms": ["地名", "旧址", "道路", "历史建筑", "空间轨迹", "机构", "事件"],
    },
    {
        "id": "reconstruct_event",
        "zh": "还原一件事",
        "en": "Reconstruct an Event",
        "desc_zh": "从事件、传闻或片段出发，恢复时间线、参与者、地点、影响和证据强弱。",
        "desc_en": "Start from an event, rumor, or fragment and recover timeline, actors, places, impact, and evidence strength.",
        "lens_zh": "先拆出事件主张，再逐条做证据支持和反证检查。",
        "lens_en": "Extract event claims first, then test each one with supporting and counter evidence.",
        "terms": ["事件", "时间线", "人物", "地点", "机构", "因果", "影响", "反证"],
    },
    {
        "id": "read_document",
        "zh": "读懂一份文献",
        "en": "Read a Document",
        "desc_zh": "从书名、档案、报刊、家谱或古籍题名出发，解释文献身份、出处和关联实体。",
        "desc_en": "Start from a title, archive, newspaper, genealogy, or rare book and explain identity, provenance, and linked entities.",
        "lens_zh": "把文献本身作为证据对象，核对题名、版本、馆藏类型和来源链接。",
        "lens_en": "Treat the document as the evidence object and verify title, version, collection type, and source link.",
        "terms": ["文献", "题名", "档案", "古籍", "家谱", "报刊", "版本", "出处"],
    },
    {
        "id": "city_memory",
        "zh": "城市记忆漫游",
        "en": "City Memory Walk",
        "desc_zh": "从旧地址、街区、老照片、老地图或文化地点出发，生成可走读、可分享、可复核的城市记忆档案。",
        "desc_en": "Start from an old address, district, photo, map, or cultural site and build a walkable, shareable, verifiable city-memory dossier.",
        "lens_zh": "先拆出历史名称、现代位置、人物机构、事件文献和空间复核状态。",
        "lens_en": "Extract historical names, modern-location checks, people, institutions, events, documents, and spatial review status.",
        "terms": ["城市记忆", "旧地址", "南京路", "石库门", "里弄", "老照片", "老地图", "公共文化"],
    },
    {
        "id": "family_memory",
        "zh": "家族线索寻踪",
        "en": "Family Memory Trace",
        "desc_zh": "从姓氏、家谱、旧住址、校友录或亲属姓名出发，把私人线索变成可复核证据链。",
        "desc_en": "Start from a surname, genealogy, old residence, alumni list, or relative name and build a verifiable evidence chain.",
        "lens_zh": "先做姓名、地名和文献消歧，再标注关系主张、来源和待考证空白。",
        "lens_en": "Disambiguate names, places, and documents first, then mark relationship claims, sources, and evidence gaps.",
        "terms": ["家谱", "族谱", "人名", "祖籍", "校友录", "旧居", "亲属", "文献"],
    },
    {
        "id": "shanghai_world",
        "zh": "上海与世界专题",
        "en": "Shanghai and the World",
        "desc_zh": "旗舰专题：货币、口岸、商人、海关、银行与航运如何把上海连接到世界。",
        "desc_en": "Flagship collection: how money, ports, merchants, customs, banks, and shipping connected Shanghai to the world.",
        "lens_zh": "保留原贸易专题积累，但作为文脉镜中的一个专题调查。",
        "lens_en": "Preserves the earlier trade-history strengths as one investigation collection inside ContextLens.",
        "terms": ["上海", "世界贸易", "货币", "口岸", "商人", "海关", "银行", "航运"],
    },
]

OUTPUT_STYLES = [
    {
        "id": "investigation_dossier",
        "zh": "历史调查档案",
        "en": "Historical Investigation Dossier",
        "desc_zh": "按线索判断、证据主张、关系解释、争议空白和公众叙事边界组织。",
        "desc_en": "Organizes the output as clue reading, evidence-bound claims, relationship interpretation, gaps, and public narrative boundary.",
    },
    {
        "id": "evidence_brief",
        "zh": "证据链简报",
        "en": "Evidence-Chain Brief",
        "desc_zh": "按问题判定、证据链、机制解释、解释推断和类比边界组织。",
        "desc_en": "Organizes the answer as diagnosis, evidence chain, mechanism, interpretation, and analogy boundary.",
    },
    {
        "id": "policy_analogy",
        "zh": "历史-现代类比备忘录",
        "en": "Historical-Modern Analogy Memo",
        "desc_zh": "突出可比机制、不可比边界和现代使用风险。",
        "desc_en": "Highlights comparable mechanisms, non-comparable boundaries, and modern-use risk.",
    },
    {
        "id": "brief",
        "zh": "核心结论摘要",
        "en": "Executive Summary",
        "desc_zh": "压缩为核心结论、判断理由、最小证据集和使用边界。",
        "desc_en": "Condenses the answer into finding, rationale, minimum evidence set, and use boundary.",
    },
    {
        "id": "timeline",
        "zh": "时间线考证",
        "en": "Timeline Dossier",
        "desc_zh": "按时期、阶段变化、关键证据和后续考证组织。",
        "desc_en": "Organizes the answer by period, phase change, key evidence, and further verification.",
    },
]

QUESTION_CARDS = [
    {
        "category_zh": "追一个人",
        "category_en": "Trace a Person",
        "zh": "盛宣怀与上海的铁路、银行和航运有什么联系？",
        "en": "How was Sheng Xuanhuai connected with Shanghai railways, banks, and shipping?",
        "mode": "trace_person",
    },
    {
        "category_zh": "寻一处地",
        "category_en": "Explore a Place",
        "zh": "外滩某栋历史建筑经历过哪些机构和人物？",
        "en": "Which institutions and people can be traced from a historic building on the Bund?",
        "mode": "explore_place",
    },
    {
        "category_zh": "追一个人",
        "category_en": "Trace a Person",
        "zh": "张骞这一人物如何出现在后世文献与丝路叙事中？",
        "en": "How does Zhang Qian appear in later documents and Silk Road narratives?",
        "mode": "trace_person",
    },
    {
        "category_zh": "上海与世界专题",
        "category_en": "Shanghai and the World",
        "zh": "一张晚清汇票如何连接商人、银行、口岸与海外贸易？",
        "en": "How can a late-Qing remittance note connect merchants, banks, ports, and overseas trade?",
        "mode": "shanghai_world",
    },
    {
        "category_zh": "寻一处地",
        "category_en": "Explore a Place",
        "zh": "我家旧地址附近发生过什么历史事件？",
        "en": "What historical events happened near my family's old address?",
        "mode": "explore_place",
    },
    {
        "category_zh": "追一个人",
        "category_en": "Trace a Person",
        "zh": "鲁迅在上海期间与哪些人物、地点和刊物相关？",
        "en": "Which people, places, and publications are linked to Lu Xun in Shanghai?",
        "mode": "trace_person",
    },
    {
        "category_zh": "城市记忆漫游",
        "category_en": "City Memory Walk",
        "zh": "南京路的百货公司、报刊广告和市民生活可以串成怎样的城市记忆路线？",
        "en": "How can Nanjing Road department stores, newspaper ads, and everyday life become a city-memory route?",
        "mode": "city_memory",
    },
    {
        "category_zh": "家族线索寻踪",
        "category_en": "Family Memory Trace",
        "zh": "如果我只知道家谱中的一个姓名和上海旧地址，下一步该查哪些证据？",
        "en": "If I only know a genealogy name and an old Shanghai address, which evidence should I check next?",
        "mode": "family_memory",
    },
    {
        "category_zh": "公共文化",
        "category_en": "Public Culture",
        "zh": "张爱玲的作品、出版机构和上海公寓能如何形成文学地景档案？",
        "en": "How can Zhang Ailing's works, publishers, and Shanghai apartments form a literary-place dossier?",
        "mode": "city_memory",
    },
]

UI_COPY = {
    "zh": {
        "home": "调查台",
        "ask": "档案",
        "evidence": "证据",
        "atlas": "3D 图谱",
        "knowledge": "知识构建",
        "security": "安全审计",
        "heroTitle": "文脉镜 ContextLens",
        "heroSubtitle": "从一条线索重建一段历史",
        "heroStatement": "文脉镜是面向上海图书馆开放数据的可复核历史发现智能体。用户输入一个人物、地点、事件、文献或旧地址，系统会生成检索计划、证据图谱、主张台账、反证提示和可回放的历史档案。",
        "notGeneric": "不是 AI 讲历史",
        "sourceLayer": "跨数据源历史证据调查",
        "auditLayer": "主张级出处与反证审计",
        "workbenchTitle": "你想追寻哪条历史线索？",
        "firstScreenLead": "输入一个人、一处旧址、一件事、一本书，或一段你看到的历史文字。",
        "questionLabel": "输入一个人、一处旧址、一件事、一本书，或一段你看到的历史文字。",
        "intakeKicker": "ContextLens Clue Intake",
        "cluePreviewTitle": "线索预检",
        "cluePreviewReady": "可生成档案",
        "cluePreviewNeedsMore": "建议补充线索",
        "clueDetectedType": "可能入口",
        "clueSpecificity": "具体度",
        "clueObjectCoverage": "对象覆盖",
        "clueResearchIntent": "研究意图",
        "clueSuggestedTerms": "建议补充",
        "awardHighlights": "证据概览",
        "highlightProvenance": "主张级出处",
        "highlightReplay": "调查回放",
        "highlightDualMode": "故事/研究双模式",
        "advancedSettings": "高级调查设置",
        "protocolFold": "智能体将执行",
        "examplesFold": "示例线索库",
        "emptyOutputTitle": "等待生成历史调查档案",
        "emptyOutputHint": "档案将包含一行结论、时间线、人物关系、空间轨迹、证据卡、争议空白、继续追问和可回放审计。",
        "previewFinding": "一句话发现",
        "previewTimeline": "历史时间线",
        "previewNetwork": "人物关系网",
        "previewSpace": "空间轨迹",
        "previewAudit": "证据审计",
        "previewExport": "可分享档案",
        "resultPageKicker": "Search Dossier",
        "resultPageTitle": "历史调查档案全屏视图",
        "resultPageSubtitle": "这里仅展示本次搜索生成的数据、证据、关系和审计结果。返回后可以修改线索并重新生成。",
        "backToWorkbench": "返回修改线索",
        "resultQuestion": "当前线索",
        "resultRecordCount": "证据记录",
        "resultClaimCount": "审计主张",
        "resultSourceCount": "可打开来源",
        "resultTimelineCount": "时间线节点",
        "resultGateStatus": "质量闸门",
        "evidenceInDossier": "搜索证据卡",
        "modeLabel": "调查任务",
        "styleLabel": "输出风格",
        "modeBriefTitle": "当前研究框架",
        "researchLens": "分析视角",
        "retrievalTerms": "优先检索词",
        "outputStructure": "输出结构",
        "questionIntent": "识别意图",
        "detectedTerms": "识别对象",
        "evidenceFit": "证据贴合度",
        "evidenceFitDetail": "问题对象被证据直接覆盖的程度",
        "supportStrength": "支撑强度",
        "awardReadiness": "原型诊断",
        "awardReadinessNote": "依据证据覆盖、出处完整度和交互功能计算的启发式原型诊断；不代表历史事实准确率。",
        "overallScore": "综合分",
        "actionItems": "下一步加强",
        "sourcePassport": "来源护照",
        "evidenceType": "证据类型",
        "provenanceNote": "出处说明",
        "timeSpan": "时间跨度",
        "publicTags": "公众标签",
        "verificationNotes": "复核备注",
        "evidenceTypes": "证据形态",
        "publicUseTags": "公众应用标签",
        "dataCatalog": "数据目录概览",
        "datasetFamilies": "数据集族",
        "evidenceTypeCatalog": "证据类型",
        "publicUseCatalog": "公众场景",
        "dataVolumePlan": "当前 demo seed 已扩展为跨人物、地点、事件、文献、地图、影像、家谱、报刊、机构和城市生活的多场景证据池。",
        "executiveSummary": "执行摘要",
        "professionalBriefing": "专业研究设计",
        "researchDesign": "研究设计",
        "dataStrategy": "数据策略",
        "evidenceProtocol": "证据协议",
        "publicProductization": "公众化呈现",
        "submissionRisks": "证据使用边界",
        "curatorialPitch": "展陈表达",
        "dossierNav": "档案导航",
        "depthLabel": "证据数量",
        "deepseekAssist": "DeepSeek 快速辅助",
        "deepseekAssistNote": "只基于上海图书馆证据做快速补充，不替代本地证据链。",
        "deepseekConfigured": "DeepSeek 已配置",
        "deepseekNotConfigured": "DeepSeek 未配置",
        "deepseekResult": "DeepSeek 辅助分析",
        "deepseekDisabled": "未启用 DeepSeek 辅助。",
        "deepseekError": "DeepSeek 辅助暂不可用，已保留本地证据回答。",
        "run": "生成历史调查档案",
        "ready": "准备就绪。若 live API 不可用，系统会使用透明 demo seed 记录。",
        "pipelineTitle": "调查闭环",
        "suggested": "Examples / 示例线索",
        "answerTitle": "历史调查档案",
        "resultGraphTitle": "主张-证据关系图",
        "resultGraphNote": "拖拽旋转关系图；点击来源节点可打开证据链接。",
        "resultGraphQuestion": "问题",
        "resultGraphMode": "研究模式",
        "resultGraphAnswer": "回答",
        "resultGraphAudit": "审计",
        "resultGraphSource": "来源",
        "resultGraphOpen": "打开来源",
        "emptyOutput": "输入一条历史线索或点击示例后生成调查档案。",
        "problem": "问题摘要",
        "fact": "历史事实",
        "interpretation": "解释推断",
        "analogy": "现代类比",
        "mechanism": "机制比较",
        "future": "后续研究问题",
        "citationCheck": "引用检查",
        "uncertainty": "不确定性",
        "dataSource": "数据来源",
        "openOriginal": "打开原始来源",
        "copyCitation": "复制引用",
        "drawerTitle": "证据详情",
        "close": "关闭",
        "matched": "匹配关键词",
        "relevance": "相关性说明",
        "date": "日期/时期",
        "people": "人物",
        "places": "地点",
        "topics": "主题",
        "score": "相关分数",
        "sourceType": "数据集/来源类型",
        "sourceUri": "上海图书馆 URI",
        "rawSourceUri": "原始来源 URI",
        "openableUrl": "可打开来源链接",
        "liveStatus": "Live API 状态",
        "knowledgeTitle": "证据编译状态",
        "knowledgeNote": "当前版本不把“AI+RAG+知识图谱”当作卖点本身，而是把线索编译为可执行检索、实体链接、主张级证据、反证搜索和调查回放。",
        "records": "记录总数",
        "liveRecords": "Live API 记录",
        "seedRecords": "Demo seed 记录",
        "lastIngest": "最后导入",
        "apiConfigured": "API key 已配置",
        "apiNotConfigured": "API key 未配置",
        "securityTitle": "安全审计面板",
        "securityNote": "API key 只从 .env 或环境变量读取，不进入前端；原始数据、日志、SQLite 和 .env 已被 gitignore；用户输入不会执行 shell。",
        "latency": "延迟",
        "evidenceCount": "证据数量",
        "financeBoundary": "金融建议边界",
        "warnings": "警告",
        "noWarnings": "没有新的警告。",
        "clickEvidence": "点击任意证据卡查看来源、匹配词和引用。",
        "atlasTitle": "3D 调查协议图谱",
        "atlasNote": "拖拽旋转图谱，悬停或点击节点查看从线索理解到主张审计的历史证据调查链路。",
        "atlasHint": "拖拽旋转 · 滚动缩放 · 点击节点聚焦",
        "atlasLoading": "正在加载 3D 图谱...",
        "atlasFallback": "3D 图谱未加载。浏览器不支持 canvas 时，其他 MVP 功能仍可正常使用。",
        "atlasFocus": "当前聚焦",
        "atlasApi": "线索解析",
        "atlasRaw": "检索计划",
        "atlasRecord": "证据规范化",
        "atlasIndex": "实体链接",
        "atlasRetrieval": "证据图谱",
        "atlasCards": "主张台账",
        "atlasAnswer": "历史档案",
        "atlasAudit": "反证审计",
        "atlasApiDesc": "识别人物、地点、事件、文献、时间和别名线索。",
        "atlasRawDesc": "把模糊问题转成跨数据源检索计划和优先关键词。",
        "atlasRecordDesc": "不同来源被清洗成统一 EvidenceRecord，保留来源和原始字段。",
        "atlasIndexDesc": "连接人物、地点、机构、事件、文献和主题信号。",
        "atlasRetrievalDesc": "围绕问题生成可点击的局部证据网络。",
        "atlasCardsDesc": "把重要结论拆成逐条可验证主张。",
        "atlasAnswerDesc": "输出一句话发现、时间线、关系解释和公众叙事边界。",
        "atlasAuditDesc": "主动标出弱支撑、缺失项、时间不确定和 demo/live 数据边界。",
        "investigationTitle": "调查档案",
        "oneLineFinding": "一句话发现",
        "historicalTimeline": "历史时间线",
        "relationshipNetwork": "人物关系网",
        "spatialTrace": "空间轨迹",
        "storyMode": "故事模式",
        "researchMode": "研究模式",
        "followUpRoutes": "继续追问",
        "qualityGates": "证据质量闸门",
        "openEvidenceNode": "打开节点来源",
        "coordinatesStatus": "坐标状态",
        "modernPositionNote": "现代位置说明",
        "citationProtocol": "引用协议",
        "entitiesLinked": "实体链接",
        "claimLedger": "主张级证据台账",
        "counterEvidence": "反证与空白",
        "investigationReplay": "调查回放",
        "dataReceipt": "数据使用收据",
        "evidenceSandbox": "证据沙盒",
        "toggleEvidence": "切换证据",
        "activeEvidence": "当前启用证据",
        "claimConfidence": "置信度",
        "claimStatus": "审计状态",
        "entryType": "入口类型",
        "taskGoal": "调查目标",
        "recordsExamined": "检查记录",
        "claimsChecked": "审计主张",
        "conflictsDetected": "反证/空白",
        "livePercentage": "Live 占比",
        "sourcesCited": "引用来源",
        "questionTooLong": "问题过长，请控制在 800 字以内。",
        "copied": "引用已复制。",
        "copyFailed": "复制失败，请手动复制。",
        "researchSignals": "研究信号",
        "researchSignalsNote": "这些指标由本次检索证据实时生成，用于判断回答是否适合继续写入报告或展示。",
        "sourceOpenness": "可打开来源",
        "sourceOpennessDetail": "证据链接是否指向可打开网页",
        "citationCoverage": "引用覆盖率",
        "citationCoverageDetail": "证据卡是否具备来源 URI",
        "liveSourceRatio": "Live 来源占比",
        "liveSourceRatioDetail": "来自上海图书馆 live API 的记录比例",
        "evidenceDepth": "证据深度",
        "evidenceDepthDetail": "当前回答使用的证据数量",
        "topicFocus": "主题聚焦",
        "topicFocusDetail": "平均匹配词密度",
        "responseSpeed": "响应速度",
        "responseSpeedDetail": "本地检索与回答生成耗时",
        "topicSignals": "主题信号云",
        "sourceTimeline": "证据时间轴",
        "researchNextSteps": "下一步研究动作",
        "exports": "导出",
        "copyBrief": "复制 Markdown 简报",
        "downloadJson": "下载 JSON 结果",
        "briefCopied": "研究简报已复制。",
        "jsonDownloaded": "JSON 结果已下载。",
        "openTimelineSource": "打开时间轴来源",
    },
    "en": {
        "home": "Workbench",
        "ask": "Dossier",
        "evidence": "Evidence",
        "atlas": "3D Atlas",
        "knowledge": "Knowledge Build",
        "security": "Security Audit",
        "heroTitle": "ContextLens 文脉镜",
        "heroSubtitle": "Rebuild history from one clue",
        "heroStatement": "ContextLens is a verifiable historical-discovery agent for Shanghai Library open data. Enter a person, place, event, document, or old address, and it returns a search plan, evidence graph, claim ledger, counter-evidence notes, and replayable historical dossier.",
        "notGeneric": "Not AI storytelling",
        "sourceLayer": "Cross-dataset evidence investigation",
        "auditLayer": "Claim-level provenance and counter-evidence",
        "workbenchTitle": "Which Historical Clue Do You Want To Follow?",
        "firstScreenLead": "Enter a person, an old address, an event, a book, or a fragment of historical text.",
        "questionLabel": "Enter a person, an old address, an event, a book, or a fragment of historical text.",
        "intakeKicker": "ContextLens Clue Intake",
        "cluePreviewTitle": "Clue Preflight",
        "cluePreviewReady": "Ready for dossier",
        "cluePreviewNeedsMore": "Add more clues",
        "clueDetectedType": "Likely Entry",
        "clueSpecificity": "Specificity",
        "clueObjectCoverage": "Object Coverage",
        "clueResearchIntent": "Research Intent",
        "clueSuggestedTerms": "Suggested Additions",
        "awardHighlights": "Evidence Overview",
        "highlightProvenance": "Claim provenance",
        "highlightReplay": "Investigation replay",
        "highlightDualMode": "Story/research modes",
        "advancedSettings": "Advanced Investigation Settings",
        "protocolFold": "Agent Will Perform",
        "examplesFold": "Example Clue Library",
        "emptyOutputTitle": "Waiting To Generate Historical Dossier",
        "emptyOutputHint": "The dossier will include a one-line finding, timeline, relationship network, spatial trace, evidence cards, gaps, follow-up routes, and replayable audit.",
        "previewFinding": "One-line finding",
        "previewTimeline": "Historical timeline",
        "previewNetwork": "Relationship network",
        "previewSpace": "Spatial trace",
        "previewAudit": "Evidence audit",
        "previewExport": "Shareable dossier",
        "resultPageKicker": "Search Dossier",
        "resultPageTitle": "Full-Screen Historical Investigation Dossier",
        "resultPageSubtitle": "This page shows only the data, evidence, relationships, and audit generated by the current search. Return to edit the clue and run again.",
        "backToWorkbench": "Back To Edit Clue",
        "resultQuestion": "Current Clue",
        "resultRecordCount": "Evidence Records",
        "resultClaimCount": "Audited Claims",
        "resultSourceCount": "Openable Sources",
        "resultTimelineCount": "Timeline Nodes",
        "resultGateStatus": "Quality Gates",
        "evidenceInDossier": "Search Evidence Cards",
        "modeLabel": "Investigation Task",
        "styleLabel": "Output Style",
        "modeBriefTitle": "Current Research Framework",
        "researchLens": "Analytic Lens",
        "retrievalTerms": "Priority Retrieval Terms",
        "outputStructure": "Output Structure",
        "questionIntent": "Detected Intent",
        "detectedTerms": "Detected Objects",
        "evidenceFit": "Evidence Fit",
        "evidenceFitDetail": "How directly the evidence covers the question terms",
        "supportStrength": "Support",
        "awardReadiness": "Prototype Diagnostics",
        "awardReadinessNote": "Heuristic prototype diagnostics based on evidence coverage, source links, and interface features; this is not a historical accuracy measure.",
        "overallScore": "Overall Score",
        "actionItems": "Next Strengthening Steps",
        "sourcePassport": "Source Passport",
        "evidenceType": "Evidence Type",
        "provenanceNote": "Provenance Note",
        "timeSpan": "Time Span",
        "publicTags": "Public Tags",
        "verificationNotes": "Verification Notes",
        "evidenceTypes": "Evidence Types",
        "publicUseTags": "Public-Use Tags",
        "dataCatalog": "Data Catalog Overview",
        "datasetFamilies": "Dataset Families",
        "evidenceTypeCatalog": "Evidence Types",
        "publicUseCatalog": "Public Scenarios",
        "dataVolumePlan": "The current demo seed pool spans people, places, events, documents, maps, images, genealogies, periodicals, institutions, and urban daily life.",
        "executiveSummary": "Executive Summary",
        "professionalBriefing": "Professional Research Design",
        "researchDesign": "Research Design",
        "dataStrategy": "Data Strategy",
        "evidenceProtocol": "Evidence Protocol",
        "publicProductization": "Public Productization",
        "submissionRisks": "Evidence-use Limits",
        "curatorialPitch": "Curatorial Pitch",
        "dossierNav": "Dossier Navigation",
        "depthLabel": "Evidence Count",
        "deepseekAssist": "DeepSeek Fast Assist",
        "deepseekAssistNote": "Uses only Shanghai Library evidence for fast auxiliary analysis; it does not replace the local evidence chain.",
        "deepseekConfigured": "DeepSeek configured",
        "deepseekNotConfigured": "DeepSeek not configured",
        "deepseekResult": "DeepSeek Auxiliary Analysis",
        "deepseekDisabled": "DeepSeek assist is disabled.",
        "deepseekError": "DeepSeek assist is unavailable; the local evidence answer is preserved.",
        "run": "Generate Historical Dossier",
        "ready": "Ready. Transparent demo seed records are available if live API data is unavailable.",
        "pipelineTitle": "Investigation Loop",
        "suggested": "Examples",
        "answerTitle": "Historical Investigation Dossier",
        "resultGraphTitle": "Claim-Evidence Graph",
        "resultGraphNote": "Drag to rotate the graph; click source nodes to open evidence links.",
        "resultGraphQuestion": "Question",
        "resultGraphMode": "Research Mode",
        "resultGraphAnswer": "Answer",
        "resultGraphAudit": "Audit",
        "resultGraphSource": "Source",
        "resultGraphOpen": "Open Source",
        "emptyOutput": "Enter a historical clue or click an example to generate a dossier.",
        "problem": "Problem Summary",
        "fact": "Historical Fact",
        "interpretation": "Interpretation",
        "analogy": "Modern Analogy",
        "mechanism": "Mechanism Comparison",
        "future": "Future Questions",
        "citationCheck": "Citation Check",
        "uncertainty": "Uncertainty",
        "dataSource": "Data Source",
        "openOriginal": "Open Original Source",
        "copyCitation": "Copy Citation",
        "drawerTitle": "Evidence Detail",
        "close": "Close",
        "matched": "Matched Keywords",
        "relevance": "Relevance Explanation",
        "date": "Date/Period",
        "people": "People",
        "places": "Places",
        "topics": "Topics",
        "score": "Score",
        "sourceType": "Dataset/Source Type",
        "sourceUri": "Shanghai Library URI",
        "rawSourceUri": "Raw Source URI",
        "openableUrl": "Openable Source Link",
        "liveStatus": "Live API Status",
        "knowledgeTitle": "Evidence Compiler Status",
        "knowledgeNote": "This version does not present AI + RAG + knowledge graph as novelty by itself. It compiles clues into executable search, entity linking, claim-level evidence, counter-evidence search, and investigation replay.",
        "records": "Total Records",
        "liveRecords": "Live API Records",
        "seedRecords": "Demo Seed Records",
        "lastIngest": "Last Ingestion",
        "apiConfigured": "API key configured",
        "apiNotConfigured": "API key not configured",
        "securityTitle": "Security Audit Panel",
        "securityNote": "The API key is loaded only from .env or environment variables and never reaches the frontend. Raw data, logs, SQLite, and .env are gitignored. User input never triggers shell execution.",
        "latency": "Latency",
        "evidenceCount": "Evidence Count",
        "financeBoundary": "Financial-Advice Boundary",
        "warnings": "Warnings",
        "noWarnings": "No new warnings.",
        "clickEvidence": "Click any evidence card to inspect source, matched terms, and citation.",
        "atlasTitle": "3D Investigation Protocol",
        "atlasNote": "Drag to rotate the atlas, then hover or click nodes to inspect the path from clue parsing to claim audit.",
        "atlasHint": "Drag to rotate · Scroll to zoom · Click a node to focus",
        "atlasLoading": "Loading 3D atlas...",
        "atlasFallback": "The 3D atlas did not load. If canvas is unavailable, the rest of the MVP still works.",
        "atlasFocus": "Current Focus",
        "atlasApi": "Clue Parsing",
        "atlasRaw": "Search Plan",
        "atlasRecord": "Evidence Normalization",
        "atlasIndex": "Entity Linking",
        "atlasRetrieval": "Evidence Graph",
        "atlasCards": "Claim Ledger",
        "atlasAnswer": "Historical Dossier",
        "atlasAudit": "Counter-Evidence Audit",
        "atlasApiDesc": "Identifies people, places, events, documents, dates, and alias clues.",
        "atlasRawDesc": "Compiles a vague clue into cross-dataset search tasks and priority terms.",
        "atlasRecordDesc": "Heterogeneous records are normalized as EvidenceRecord objects while preserving source fields.",
        "atlasIndexDesc": "Links people, places, institutions, events, documents, and topic signals.",
        "atlasRetrievalDesc": "Creates a clickable local evidence network around the question.",
        "atlasCardsDesc": "Breaks conclusions into individually verifiable claims.",
        "atlasAnswerDesc": "Returns a one-line finding, timeline, relationship interpretation, and public narrative boundary.",
        "atlasAuditDesc": "Surfaces weak support, missing terms, date uncertainty, and demo/live data boundaries.",
        "investigationTitle": "Investigation Dossier",
        "oneLineFinding": "One-Line Finding",
        "historicalTimeline": "Historical Timeline",
        "relationshipNetwork": "Relationship Network",
        "spatialTrace": "Spatial Trace",
        "storyMode": "Story Mode",
        "researchMode": "Research Mode",
        "followUpRoutes": "Follow-Up Routes",
        "qualityGates": "Evidence Quality Gates",
        "openEvidenceNode": "Open node source",
        "coordinatesStatus": "Coordinate Status",
        "modernPositionNote": "Modern Position Note",
        "citationProtocol": "Citation Protocol",
        "entitiesLinked": "Entity Links",
        "claimLedger": "Claim-Level Evidence Ledger",
        "counterEvidence": "Counter-Evidence and Gaps",
        "investigationReplay": "Investigation Replay",
        "dataReceipt": "Data-Use Receipt",
        "evidenceSandbox": "Evidence Sandbox",
        "toggleEvidence": "Toggle evidence",
        "activeEvidence": "Active evidence",
        "claimConfidence": "Confidence",
        "claimStatus": "Audit Status",
        "entryType": "Entry Type",
        "taskGoal": "Investigation Goal",
        "recordsExamined": "Records Examined",
        "claimsChecked": "Claims Checked",
        "conflictsDetected": "Counter-Evidence/Gaps",
        "livePercentage": "Live Ratio",
        "sourcesCited": "Sources Cited",
        "questionTooLong": "Question is too long. Please keep it under 800 characters.",
        "copied": "Citation copied.",
        "copyFailed": "Copy failed. Please copy manually.",
        "researchSignals": "Research Signals",
        "researchSignalsNote": "These indicators are derived from the current retrieval set to show whether the answer is ready for reporting or presentation.",
        "sourceOpenness": "Openable Sources",
        "sourceOpennessDetail": "Whether evidence links resolve to open web pages",
        "citationCoverage": "Citation Coverage",
        "citationCoverageDetail": "Whether evidence cards include source URIs",
        "liveSourceRatio": "Live Source Ratio",
        "liveSourceRatioDetail": "Share of records from the Shanghai Library live API",
        "evidenceDepth": "Evidence Depth",
        "evidenceDepthDetail": "Evidence count used in this answer",
        "topicFocus": "Topic Focus",
        "topicFocusDetail": "Average matched-term density",
        "responseSpeed": "Response Speed",
        "responseSpeedDetail": "Local retrieval and answer latency",
        "topicSignals": "Topic Signal Cloud",
        "sourceTimeline": "Evidence Timeline",
        "researchNextSteps": "Next Research Moves",
        "exports": "Export",
        "copyBrief": "Copy Markdown Brief",
        "downloadJson": "Download JSON Result",
        "briefCopied": "Research brief copied.",
        "jsonDownloaded": "JSON result downloaded.",
        "openTimelineSource": "Open timeline source",
    },
}


HTML = r"""<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>文脉镜 ContextLens</title>
  <style>
    :root {
      --ink:#111827;
      --ink-2:#20314d;
      --blue:#173b6c;
      --blue-2:#24558f;
      --gold:#b7832f;
      --red:#9f2f28;
      --jade:#14746f;
      --paper:#f4f7fb;
      --surface:#ffffff;
      --line:#d8dde6;
      --muted:#64748b;
      --shadow:0 14px 36px rgba(23, 49, 89, .12);
    }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body {
      margin:0;
      background:var(--paper);
      color:var(--ink);
      font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", Arial, sans-serif;
      line-height:1.5;
      overflow-x:hidden;
    }
    button, select, textarea { font:inherit; }
    a { color:inherit; }
    .topbar {
      position:sticky;
      top:0;
      z-index:20;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:18px;
      padding:13px clamp(18px, 4vw, 56px);
      background:rgba(255, 255, 255, .93);
      border-bottom:1px solid var(--line);
      backdrop-filter:blur(14px);
    }
    .brand {
      display:flex;
      align-items:center;
      gap:10px;
      min-width:max-content;
      font-weight:800;
      color:var(--blue);
    }
    .mark {
      width:32px;
      height:32px;
      border-radius:7px;
      background:linear-gradient(135deg, var(--blue), var(--jade));
      border:2px solid rgba(183, 131, 47, .55);
    }
    nav {
      display:flex;
      justify-content:center;
      flex-wrap:wrap;
      gap:6px;
    }
    nav a {
      text-decoration:none;
      color:#334155;
      padding:8px 10px;
      border-radius:7px;
      font-size:14px;
      font-weight:700;
    }
    nav a:hover { background:#edf2f7; color:var(--blue); }
    .language-toggle {
      display:flex;
      padding:3px;
      border:1px solid var(--line);
      border-radius:8px;
      background:#f8fafc;
    }
    .language-toggle button {
      border:0;
      background:transparent;
      color:#475569;
      border-radius:6px;
      padding:7px 10px;
      cursor:pointer;
      font-weight:800;
    }
    .language-toggle button.active { background:var(--blue); color:white; }
    .hero {
      background:linear-gradient(135deg, #10213d, #173b6c 54%, #145f67);
      color:white;
      padding:54px clamp(18px, 5vw, 72px) 44px;
      border-bottom:5px solid var(--gold);
    }
    .hero-inner {
      max-width:1200px;
      margin:auto;
      display:grid;
      grid-template-columns:minmax(0, 1.35fr) minmax(280px, .65fr);
      gap:36px;
      align-items:end;
    }
    .eyebrow {
      color:#f5d28e;
      text-transform:uppercase;
      letter-spacing:0;
      font-size:12px;
      font-weight:900;
      margin:0 0 10px;
    }
    h1 {
      margin:0;
      font-size:44px;
      line-height:1.08;
      letter-spacing:0;
    }
    .hero p {
      max-width:920px;
      margin:18px 0 0;
      color:#e8eef8;
      font-size:18px;
    }
    .hero-metrics {
      display:grid;
      gap:10px;
    }
    .metric-tile {
      border:1px solid rgba(255,255,255,.24);
      background:rgba(255,255,255,.1);
      border-radius:8px;
      padding:13px 14px;
    }
    .metric-tile strong { display:block; font-size:14px; }
    .metric-tile span { color:#d7e2f4; font-size:13px; }
    main { max-width:1280px; margin:auto; padding:28px clamp(16px, 4vw, 52px) 52px; }
    .section { scroll-margin-top:84px; margin-top:34px; }
    .clue-workbench {
      margin-top:0;
      min-height:calc(100vh - 78px);
      display:flex;
      flex-direction:column;
      justify-content:center;
    }
    .clue-workbench .section-title {
      align-items:flex-start;
      margin-bottom:18px;
    }
    .clue-workbench .section-title h1 {
      max-width:620px;
      color:var(--ink-2);
      font-size:44px;
      line-height:1.08;
    }
    .clue-workbench .section-title p {
      max-width:560px;
      color:#475569;
      font-size:15px;
    }
    .clue-workbench textarea {
      min-height:132px;
      font-size:16px;
    }
    .atlas-band {
      margin:34px calc(50% - 50vw) 0;
      width:100vw;
      min-height:590px;
      background:#07192d;
      color:white;
      position:relative;
      overflow:hidden;
      border-top:1px solid rgba(255,255,255,.12);
      border-bottom:1px solid rgba(255,255,255,.12);
    }
    .atlas-band::before {
      content:"";
      position:absolute;
      inset:0;
      background:
        linear-gradient(90deg, rgba(7,25,45,.97), rgba(9,36,64,.82) 48%, rgba(12,53,58,.94)),
        linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,0));
      pointer-events:none;
      z-index:0;
    }
    .atlas-inner {
      position:relative;
      z-index:1;
      max-width:1280px;
      margin:auto;
      padding:34px clamp(16px, 4vw, 52px) 40px;
      display:grid;
      grid-template-columns:minmax(300px, .55fr) minmax(420px, 1fr);
      gap:24px;
      align-items:center;
      min-height:590px;
    }
    .atlas-copy h2 {
      margin:0;
      color:white;
      font-size:clamp(28px, 4vw, 48px);
      line-height:1.04;
      letter-spacing:0;
    }
    .atlas-copy p {
      color:#dbe7f6;
      margin:14px 0 0;
      font-size:16px;
    }
    .atlas-chip-row {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:18px;
    }
    .atlas-chip {
      border:1px solid rgba(255,255,255,.24);
      background:rgba(255,255,255,.1);
      color:#f8fbff;
      border-radius:999px;
      padding:7px 10px;
      font-size:12px;
      font-weight:800;
    }
    .atlas-focus {
      margin-top:20px;
      border-left:4px solid var(--gold);
      padding:12px 0 12px 14px;
      color:#f8fbff;
      min-height:92px;
    }
    .atlas-focus strong {
      display:block;
      color:#f5d28e;
      margin-bottom:5px;
    }
    .atlas-stage {
      position:relative;
      min-height:500px;
      height:min(58vw, 560px);
    }
    #atlasCanvas {
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      display:block;
      cursor:grab;
      touch-action:none;
    }
    #atlasCanvas:active { cursor:grabbing; }
    .atlas-tooltip {
      position:absolute;
      top:18px;
      left:18px;
      max-width:min(320px, calc(100% - 36px));
      color:white;
      border:1px solid rgba(255,255,255,.2);
      background:rgba(7, 25, 45, .72);
      backdrop-filter:blur(10px);
      border-radius:8px;
      padding:11px 12px;
      pointer-events:none;
    }
    .atlas-tooltip strong { display:block; color:#f5d28e; margin-bottom:4px; }
    .atlas-status {
      position:absolute;
      right:18px;
      bottom:18px;
      color:#dbe7f6;
      font-size:12px;
      font-weight:800;
      background:rgba(7,25,45,.7);
      border:1px solid rgba(255,255,255,.18);
      border-radius:999px;
      padding:7px 10px;
    }
    .section-title {
      display:flex;
      justify-content:space-between;
      align-items:end;
      gap:18px;
      margin-bottom:14px;
    }
    .section-title h2 {
      margin:0;
      color:var(--ink-2);
      font-size:24px;
      letter-spacing:0;
    }
    .section-title p {
      margin:0;
      color:var(--muted);
      max-width:720px;
      font-size:14px;
    }
    .workbench {
      display:grid;
      grid-template-columns:minmax(480px, .92fr) minmax(520px, 1.08fr);
      gap:20px;
      align-items:stretch;
    }
    .surface {
      background:var(--surface);
      border:1px solid var(--line);
      border-radius:8px;
      box-shadow:var(--shadow);
      padding:18px;
      min-width:0;
    }
    .intake-surface,
    .dossier-preview-surface {
      min-height:760px;
    }
    .dossier-preview-surface {
      border-top:5px solid var(--blue);
      display:flex;
      flex-direction:column;
    }
    .intake-surface {
      display:flex;
      flex-direction:column;
      gap:12px;
      border-top:5px solid var(--gold);
    }
    .intake-head {
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:center;
      border-bottom:1px solid #e3e9f1;
      padding-bottom:11px;
    }
    .intake-head span {
      color:var(--red);
      font-size:12px;
      font-weight:900;
    }
    .intake-head strong {
      color:var(--ink-2);
      font-size:14px;
    }
    label {
      display:block;
      color:#334155;
      font-size:13px;
      font-weight:800;
      margin-bottom:7px;
    }
    textarea {
      width:100%;
      min-height:156px;
      resize:vertical;
      border:1px solid #cbd5e1;
      border-radius:8px;
      padding:13px;
      color:#111827;
      background:#fbfdff;
      line-height:1.55;
    }
    textarea:focus, select:focus {
      outline:3px solid rgba(36, 85, 143, .18);
      border-color:var(--blue-2);
    }
    .clue-preview {
      border:1px solid #d7dfeb;
      border-left:4px solid var(--jade);
      border-radius:8px;
      background:linear-gradient(135deg, #fbfdff, #edf8f5);
      padding:12px;
    }
    .preview-head {
      display:flex;
      justify-content:space-between;
      gap:10px;
      align-items:center;
      margin-bottom:10px;
    }
    .preview-head strong {
      color:var(--ink-2);
      font-size:14px;
    }
    .preview-status {
      border-radius:999px;
      padding:5px 9px;
      background:#eaf8f4;
      color:#0f5f55;
      font-size:12px;
      font-weight:900;
      white-space:nowrap;
    }
    .preview-status.needs-more {
      background:#fff8e7;
      color:#6f480b;
    }
    .preview-metrics {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:8px;
    }
    .preview-metric {
      min-width:0;
      border:1px solid #dbe4ef;
      border-radius:8px;
      background:white;
      padding:9px;
    }
    .preview-metric span {
      display:block;
      color:var(--muted);
      font-size:11px;
      font-weight:800;
      margin-bottom:4px;
    }
    .preview-metric strong {
      display:block;
      color:var(--ink-2);
      font-size:13px;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .preview-meter {
      height:7px;
      margin-top:7px;
      overflow:hidden;
      border-radius:999px;
      background:#e6edf5;
    }
    .preview-meter i {
      display:block;
      height:100%;
      border-radius:inherit;
      background:linear-gradient(90deg, var(--gold), var(--jade));
    }
    .preview-tags {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
      margin-top:10px;
    }
    .award-strip {
      display:grid;
      grid-template-columns:1.05fr repeat(3, minmax(0, 1fr));
      gap:8px;
      align-items:stretch;
    }
    .award-strip strong,
    .award-strip span {
      border:1px solid #d7dfeb;
      border-radius:8px;
      padding:9px 10px;
      background:#fbfdff;
      color:#334155;
      font-size:12px;
      font-weight:900;
      min-width:0;
    }
    .award-strip strong {
      background:#fff8e7;
      color:#5b3b06;
    }
    .fold-stack {
      display:grid;
      gap:10px;
    }
    .fold-panel {
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      overflow:hidden;
    }
    .fold-panel summary {
      min-height:44px;
      padding:12px 13px;
      cursor:pointer;
      color:var(--ink-2);
      font-size:13px;
      font-weight:900;
      list-style:none;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
    }
    .fold-panel summary::-webkit-details-marker { display:none; }
    .fold-panel summary::after {
      content:"+";
      width:22px;
      height:22px;
      border-radius:999px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      background:#eef3f8;
      color:var(--blue);
      font-weight:900;
      flex:0 0 auto;
    }
    .fold-panel[open] summary::after {
      content:"-";
      background:#eaf8f4;
      color:#0f5f55;
    }
    .fold-body {
      border-top:1px solid #e3e9f1;
      padding:12px;
    }
    .controls {
      display:grid;
      grid-template-columns:1fr 1fr 110px;
      gap:12px;
    }
    .mode-brief {
      margin-top:12px;
      border:1px solid #d7dfeb;
      border-left:4px solid var(--blue);
      border-radius:8px;
      background:linear-gradient(135deg, #fbfdff, #eef7f4);
      padding:12px;
    }
    .mode-brief strong {
      display:block;
      color:var(--ink-2);
      margin-bottom:5px;
      font-size:14px;
    }
    .mode-brief p {
      margin:0;
      color:#334155;
      font-size:13px;
    }
    .mode-brief-grid {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:10px;
      margin-top:10px;
    }
    .mode-brief-grid div {
      min-width:0;
      border-top:1px solid #dbe4ef;
      padding-top:8px;
    }
    .mode-brief-grid b {
      display:block;
      color:var(--red);
      font-size:11px;
      letter-spacing:0;
      text-transform:uppercase;
      margin-bottom:4px;
    }
    .assist-toggle {
      display:flex;
      align-items:flex-start;
      gap:9px;
      margin-top:12px;
      padding:10px 11px;
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      cursor:pointer;
    }
    .assist-toggle input {
      margin-top:3px;
      accent-color:var(--blue);
    }
    .assist-toggle span {
      display:block;
      color:var(--ink-2);
      font-weight:900;
      font-size:13px;
    }
    .assist-toggle small {
      display:block;
      color:var(--muted);
      font-size:12px;
      margin-top:2px;
    }
    .assist-toggle.disabled {
      opacity:.62;
      cursor:not-allowed;
    }
    .deepseek-block {
      border:1px solid #d4e4ef;
      border-left:4px solid var(--jade);
      background:linear-gradient(135deg, #fbfdff, #edf8f5);
      border-radius:8px;
      padding:13px;
      white-space:pre-wrap;
    }
    select {
      width:100%;
      border:1px solid #cbd5e1;
      border-radius:8px;
      background:white;
      color:#111827;
      padding:10px;
    }
    .primary-row {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      margin-top:2px;
    }
    .primary {
      border:0;
      background:var(--blue);
      color:white;
      border-radius:8px;
      padding:11px 16px;
      font-weight:900;
      cursor:pointer;
    }
    .primary:hover { background:#0f2f58; }
    .status { color:var(--muted); font-size:13px; }
    .pipeline {
      display:grid;
      grid-template-columns:repeat(5, minmax(0, 1fr));
      gap:8px;
      margin-top:18px;
    }
    .step {
      min-height:58px;
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#f8fafc;
      padding:10px;
      color:#334155;
      font-size:12px;
      font-weight:800;
      text-align:center;
      display:flex;
      align-items:center;
      justify-content:center;
    }
    .step.active { border-color:var(--gold); background:#fff8e7; color:#5b3b06; }
    .question-grid {
      display:grid;
      grid-template-columns:repeat(2, minmax(0, 1fr));
      gap:10px;
      margin-top:12px;
    }
    .question-card, .evidence-card {
      width:100%;
      border:1px solid var(--line);
      border-left:4px solid var(--gold);
      border-radius:8px;
      background:white;
      padding:13px;
      text-align:left;
      cursor:pointer;
      color:var(--ink);
    }
    .question-card:hover, .evidence-card:hover {
      border-color:#b9c5d5;
      box-shadow:0 10px 22px rgba(23, 49, 89, .11);
      transform:translateY(-1px);
    }
    .category {
      color:var(--red);
      font-size:12px;
      font-weight:900;
      margin-bottom:5px;
    }
    .question-card div:last-child { font-size:14px; font-weight:750; }
    .output {
      border-top:5px solid var(--blue);
    }
    .output-empty {
      color:var(--muted);
      min-height:650px;
      padding:18px;
      border:1px dashed #cad5e2;
      border-radius:8px;
      background:#f8fafc;
      display:flex;
      flex-direction:column;
      justify-content:center;
      gap:14px;
    }
    .output-empty strong {
      display:block;
      color:var(--ink-2);
      font-size:22px;
    }
    .output-empty p {
      max-width:620px;
      color:#475569;
      margin:0;
    }
    .dossier-preview-grid {
      display:grid;
      grid-template-columns:repeat(2, minmax(0, 1fr));
      gap:10px;
      margin-top:4px;
    }
    .dossier-preview-grid span {
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:white;
      color:#1f3f65;
      padding:12px;
      font-size:13px;
      font-weight:900;
    }
    .results-page {
      display:none;
      min-height:calc(100vh - 78px);
      margin-top:0;
    }
    .results-page:not([hidden]) { display:block; }
    body.results-mode .clue-workbench,
    body.results-mode #atlas,
    body.results-mode #evidence,
    body.results-mode #knowledge,
    body.results-mode #security,
    body.results-mode footer {
      display:none;
    }
    body.results-mode main {
      max-width:none;
      padding-top:28px;
    }
    body.results-mode nav {
      display:none;
    }
    .results-shell {
      max-width:1320px;
      margin:auto;
    }
    .results-head {
      display:flex;
      justify-content:space-between;
      align-items:flex-start;
      gap:20px;
      border:1px solid var(--line);
      border-left:5px solid var(--gold);
      border-radius:8px;
      background:white;
      box-shadow:var(--shadow);
      padding:18px;
      margin-bottom:14px;
    }
    .results-head h2 {
      margin:0;
      color:var(--ink-2);
      font-size:30px;
      line-height:1.15;
    }
    .results-head p {
      color:#475569;
      margin:8px 0 0;
      max-width:760px;
    }
    .result-actions {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      justify-content:flex-end;
    }
    .results-cockpit {
      display:grid;
      grid-template-columns:1.4fr repeat(5, minmax(0, 1fr));
      gap:10px;
      margin-bottom:14px;
    }
    .result-stat {
      min-width:0;
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      padding:12px;
    }
    .result-stat.primary-stat {
      border-left:4px solid var(--blue);
      background:linear-gradient(135deg, #fbfdff, #edf6f4);
    }
    .result-stat span {
      display:block;
      color:var(--muted);
      font-size:12px;
      font-weight:800;
      margin-bottom:5px;
    }
    .result-stat strong {
      display:block;
      color:var(--ink-2);
      font-size:20px;
      line-height:1.2;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .result-output {
      min-height:auto;
      display:block;
    }
    .inline-evidence-board {
      margin-top:10px;
    }
    .answer-block {
      border-top:1px solid #e5eaf0;
      padding-top:14px;
      margin-top:14px;
    }
    .answer-block:first-child {
      border-top:0;
      padding-top:0;
      margin-top:0;
    }
    .answer-block h3 {
      color:var(--blue);
      font-size:15px;
      margin:0 0 8px;
    }
    .dossier-nav {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      padding:10px;
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#f8fafc;
      margin-bottom:14px;
    }
    .dossier-nav a {
      text-decoration:none;
      border:1px solid #d7dfeb;
      border-radius:999px;
      background:white;
      color:#1f3f65;
      padding:7px 10px;
      font-size:12px;
      font-weight:900;
    }
    .dossier-nav a:hover {
      border-color:var(--blue-2);
      background:#edf6f4;
    }
    .executive-grid,
    .briefing-grid {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:10px;
      margin-top:10px;
    }
    .executive-card,
    .briefing-card {
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      padding:12px;
      min-width:0;
    }
    .executive-card.primary-card {
      grid-column:span 2;
      border-left:5px solid var(--gold);
      background:linear-gradient(135deg, #fffdf7, #eef7f4);
    }
    .executive-card strong,
    .briefing-card strong {
      display:block;
      color:var(--ink-2);
      font-size:13px;
      margin-bottom:5px;
    }
    .executive-card p,
    .briefing-card p {
      color:#334155;
      font-size:13px;
      margin:0;
    }
    .briefing-card {
      border-left:4px solid var(--blue-2);
    }
    .answer-block p { margin:0; color:#263448; }
    .finding-panel {
      border:1px solid #d7dfeb;
      border-left:5px solid var(--gold);
      border-radius:8px;
      background:linear-gradient(135deg, #fffdf7, #eef7f4);
      padding:14px;
      margin-bottom:14px;
    }
    .finding-panel strong {
      display:block;
      color:var(--red);
      font-size:12px;
      text-transform:uppercase;
      letter-spacing:0;
      margin-bottom:5px;
    }
    .finding-panel p {
      color:#14243a;
      font-size:15px;
      font-weight:750;
    }
    .dossier-grid {
      display:grid;
      grid-template-columns:repeat(2, minmax(0, 1fr));
      gap:10px;
      margin-top:10px;
    }
    .dossier-cell,
    .claim-card,
    .counter-item,
    .replay-step {
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      padding:11px;
      min-width:0;
    }
    .dossier-cell strong,
    .claim-card strong,
    .counter-item strong,
    .replay-step strong {
      display:block;
      color:var(--ink-2);
      font-size:13px;
      margin-bottom:4px;
    }
    .dossier-cell p,
    .claim-card p,
    .counter-item p,
    .replay-step p {
      color:#334155;
      font-size:13px;
    }
    .entity-list {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:10px;
    }
    .entity-chip {
      display:inline-flex;
      align-items:center;
      gap:6px;
      border:1px solid #d7dfeb;
      border-radius:999px;
      background:#f8fafc;
      padding:7px 10px;
      color:#1f3f65;
      font-size:12px;
      font-weight:900;
      max-width:100%;
    }
    .entity-chip span {
      color:var(--muted);
      font-weight:800;
    }
    .claim-grid,
    .counter-grid,
    .replay-list {
      display:grid;
      gap:10px;
      margin-top:10px;
    }
    .network-list,
    .spatial-grid,
    .quality-grid,
    .follow-grid,
    .mode-pair {
      display:grid;
      gap:10px;
      margin-top:10px;
    }
    .network-list,
    .spatial-grid,
    .quality-grid {
      grid-template-columns:repeat(2, minmax(0, 1fr));
    }
    .mode-pair {
      grid-template-columns:1fr 1fr;
    }
    .timeline-node {
      border-left:4px solid var(--gold);
    }
    .network-edge,
    .spatial-card,
    .quality-gate,
    .follow-route,
    .mode-card {
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      padding:11px;
      min-width:0;
    }
    .network-edge {
      border-left:4px solid var(--blue-2);
    }
    .spatial-card {
      border-left:4px solid var(--jade);
    }
    .quality-gate.pass {
      border-left:4px solid var(--jade);
      background:#f7fdfb;
    }
    .quality-gate.review,
    .quality-gate.fail {
      border-left:4px solid var(--gold);
      background:#fffdf7;
    }
    .quality-gate.fail {
      border-left-color:var(--red);
      background:#fffafa;
    }
    .follow-route {
      border-left:4px solid var(--red);
    }
    .mode-card {
      border-left:4px solid var(--blue);
    }
    .network-edge strong,
    .spatial-card strong,
    .quality-gate strong,
    .follow-route strong,
    .mode-card strong {
      display:block;
      color:var(--ink-2);
      font-size:13px;
      margin-bottom:5px;
    }
    .network-edge p,
    .spatial-card p,
    .quality-gate p,
    .follow-route p,
    .mode-card p {
      color:#334155;
      font-size:13px;
      margin:0;
    }
    .claim-card {
      border-left:4px solid var(--jade);
      transition:opacity .18s ease, filter .18s ease;
    }
    .claim-card.review { border-left-color:var(--gold); }
    .claim-card.needs_more_evidence { border-left-color:var(--red); }
    .claim-card.disabled {
      opacity:.45;
      filter:saturate(.55);
    }
    .claim-meta {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
      margin-top:8px;
    }
    .counter-item {
      border-left:4px solid var(--red);
      background:#fffafa;
    }
    .counter-item.low {
      border-left-color:var(--jade);
      background:#f7fdfb;
    }
    .replay-step {
      display:grid;
      grid-template-columns:42px minmax(0, 1fr);
      gap:10px;
      align-items:start;
    }
    .replay-step .index {
      width:34px;
      height:34px;
      border-radius:999px;
      display:flex;
      align-items:center;
      justify-content:center;
      background:var(--blue);
      color:white;
      font-weight:900;
    }
    .sandbox-row {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:10px;
    }
    .mini-toggle {
      border:1px solid #d7dfeb;
      background:#f8fafc;
      color:#21476f;
      border-radius:999px;
      padding:7px 10px;
      font-size:12px;
      font-weight:900;
      cursor:pointer;
    }
    .mini-toggle.active {
      background:#eaf8f4;
      border-color:#9dd7c9;
      color:#0f5f55;
    }
    .answer-toolbar {
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:12px;
      padding:12px;
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:linear-gradient(135deg, #f8fafc, #edf6f4);
      margin-bottom:14px;
    }
    .answer-toolbar strong {
      display:block;
      color:var(--ink-2);
      font-size:14px;
    }
    .answer-toolbar span {
      color:var(--muted);
      font-size:12px;
      font-weight:750;
    }
    .toolbar-actions {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      justify-content:flex-end;
    }
    .research-cockpit {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:10px;
      margin-top:10px;
    }
    .signal-card {
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      padding:11px;
      min-width:0;
    }
    .signal-card strong {
      display:flex;
      align-items:baseline;
      justify-content:space-between;
      gap:8px;
      color:var(--ink-2);
      font-size:13px;
    }
    .signal-value {
      color:var(--blue);
      font-size:17px;
      font-weight:900;
      white-space:nowrap;
    }
    .signal-card p {
      margin:5px 0 9px;
      color:var(--muted);
      font-size:12px;
    }
    .meter {
      height:7px;
      border-radius:999px;
      background:#e5ebf2;
      overflow:hidden;
    }
    .meter span {
      display:block;
      height:100%;
      min-width:6px;
      border-radius:inherit;
      background:linear-gradient(90deg, var(--gold), var(--jade));
    }
    .topic-cloud {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:10px;
    }
    .topic-signal {
      border:1px solid #d7dfeb;
      background:#f8fafc;
      color:#1f3f65;
      border-radius:999px;
      padding:7px 10px;
      font-weight:900;
      cursor:pointer;
    }
    .topic-signal:hover {
      border-color:var(--blue-2);
      background:#edf6f4;
    }
    .timeline {
      position:relative;
      display:grid;
      gap:10px;
      margin-top:12px;
      padding-left:18px;
    }
    .timeline::before {
      content:"";
      position:absolute;
      left:5px;
      top:6px;
      bottom:6px;
      width:2px;
      background:linear-gradient(var(--gold), var(--jade));
    }
    .timeline-item {
      position:relative;
      border:1px solid #d7dfeb;
      border-radius:8px;
      background:#fbfdff;
      padding:10px 11px;
    }
    .timeline-item::before {
      content:"";
      position:absolute;
      left:-19px;
      top:15px;
      width:10px;
      height:10px;
      border-radius:50%;
      background:var(--gold);
      border:2px solid white;
      box-shadow:0 0 0 1px rgba(183,131,47,.4);
    }
    .timeline-item header {
      display:flex;
      justify-content:space-between;
      gap:10px;
      align-items:start;
    }
    .timeline-date {
      color:var(--red);
      font-size:12px;
      font-weight:900;
      white-space:nowrap;
    }
    .timeline-item h4 {
      margin:0;
      color:var(--ink-2);
      font-size:14px;
      letter-spacing:0;
    }
    .timeline-item p {
      margin:6px 0 0;
      color:#334155;
      font-size:13px;
    }
    .timeline-item a {
      display:inline-block;
      margin-top:7px;
      color:var(--blue);
      font-size:12px;
      font-weight:900;
      text-decoration:none;
    }
    .next-step-grid {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:10px;
      margin-top:10px;
    }
    .next-step {
      border-top:3px solid var(--gold);
      background:#fbfdff;
      padding:10px 11px;
      border-radius:8px;
    }
    .next-step strong {
      display:block;
      color:var(--ink-2);
      margin-bottom:4px;
      font-size:13px;
    }
    .next-step p {
      color:#334155;
      font-size:13px;
    }
    .result-graph {
      position:relative;
      min-height:390px;
      height:430px;
      border:1px solid #cdd8e6;
      border-radius:8px;
      overflow:hidden;
      background:linear-gradient(135deg, #07192d, #0d2948 55%, #123d43);
      margin-top:10px;
    }
    .result-graph canvas {
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      display:block;
      cursor:grab;
      touch-action:none;
    }
    .result-graph canvas:active { cursor:grabbing; }
    .result-graph-link-layer {
      position:absolute;
      inset:0;
      pointer-events:none;
    }
    .result-node-link {
      position:absolute;
      transform:translate(-50%, -50%);
      max-width:145px;
      min-width:76px;
      min-height:34px;
      display:flex;
      align-items:center;
      justify-content:center;
      text-align:center;
      padding:6px 9px;
      border-radius:999px;
      border:1px solid rgba(245, 210, 142, .8);
      background:rgba(7, 25, 45, .76);
      color:#f8fbff;
      text-decoration:none;
      font-size:12px;
      font-weight:900;
      line-height:1.15;
      box-shadow:0 10px 22px rgba(0,0,0,.24);
      pointer-events:auto;
      overflow:hidden;
      text-overflow:ellipsis;
    }
    .result-node-link:hover,
    .result-node-link:focus {
      background:#f5d28e;
      color:#08243f;
      outline:0;
    }
    .result-node-link.evidence-link {
      border-color:rgba(125, 211, 252, .86);
    }
    .result-graph-hint {
      position:absolute;
      left:12px;
      bottom:12px;
      max-width:calc(100% - 24px);
      color:#dbe7f6;
      background:rgba(7, 25, 45, .7);
      border:1px solid rgba(255,255,255,.18);
      border-radius:999px;
      padding:7px 10px;
      font-size:12px;
      font-weight:800;
      pointer-events:none;
    }
    .evidence-list {
      display:grid;
      gap:10px;
      margin-top:10px;
    }
    .evidence-card { border-left-color:var(--jade); }
    .evidence-card h4 {
      margin:0 0 8px;
      color:#123a45;
      font-size:16px;
      letter-spacing:0;
    }
    .tag-row {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
      margin:8px 0;
    }
    .tag {
      display:inline-flex;
      align-items:center;
      min-height:24px;
      padding:3px 8px;
      border-radius:999px;
      background:#edf4ff;
      color:#21476f;
      font-size:12px;
      font-weight:800;
    }
    .tag.live { background:#eaf8f4; color:#0f5f55; }
    .tag.seed { background:#fff5df; color:#705016; }
    .muted { color:var(--muted); font-size:13px; }
    .evidence-board {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:12px;
    }
    .knowledge-grid, .security-grid {
      display:grid;
      grid-template-columns:repeat(4, minmax(0, 1fr));
      gap:12px;
    }
    .data-catalog {
      display:grid;
      grid-template-columns:repeat(3, minmax(0, 1fr));
      gap:12px;
      margin-top:12px;
    }
    .catalog-card {
      border:1px solid var(--line);
      border-radius:8px;
      background:white;
      padding:14px;
      min-width:0;
    }
    .catalog-card strong {
      display:block;
      color:var(--ink-2);
      margin-bottom:8px;
      font-size:13px;
    }
    .catalog-list {
      display:grid;
      gap:6px;
    }
    .catalog-row {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      padding:7px 8px;
      border-radius:8px;
      background:#f8fafc;
      color:#334155;
      font-size:12px;
      font-weight:800;
    }
    .catalog-row span:first-child {
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .catalog-row span:last-child {
      color:var(--blue);
      font-weight:900;
      white-space:nowrap;
    }
    .stat {
      background:white;
      border:1px solid var(--line);
      border-radius:8px;
      padding:14px;
      min-width:0;
      overflow:hidden;
    }
    .stat strong {
      display:block;
      color:var(--blue);
      font-size:clamp(18px, 5vw, 26px);
      line-height:1.1;
      overflow-wrap:anywhere;
    }
    .stat span { color:var(--muted); font-size:13px; font-weight:800; }
    .pipeline-wide {
      display:grid;
      grid-template-columns:repeat(7, minmax(0, 1fr));
      gap:8px;
      margin-top:14px;
    }
    .security-list {
      display:grid;
      gap:8px;
      margin-top:12px;
    }
    .audit-pill {
      display:flex;
      justify-content:space-between;
      gap:12px;
      border:1px solid var(--line);
      border-radius:8px;
      padding:10px 12px;
      background:white;
    }
    .audit-pill strong { color:var(--blue); }
    .warning {
      border:1px solid #f0d891;
      background:#fff8e3;
      color:#5d4300;
      border-radius:8px;
      padding:10px 12px;
      margin-top:8px;
    }
    .drawer-overlay {
      position:fixed;
      inset:0;
      background:rgba(15, 23, 42, .42);
      z-index:40;
      opacity:0;
      pointer-events:none;
      transition:opacity .18s ease;
    }
    .drawer-overlay.open { opacity:1; pointer-events:auto; }
    .drawer {
      position:fixed;
      top:0;
      right:0;
      bottom:0;
      width:min(560px, 94vw);
      max-width:100vw;
      background:white;
      border-left:1px solid var(--line);
      box-shadow:-16px 0 42px rgba(15, 23, 42, .18);
      z-index:50;
      transform:translateX(102%);
      transition:transform .2s ease;
      display:flex;
      flex-direction:column;
    }
    .drawer.open { transform:translateX(0); }
    .drawer-head {
      padding:18px;
      border-bottom:1px solid var(--line);
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:center;
    }
    .drawer-head h2 { margin:0; color:var(--blue); font-size:20px; }
    .ghost {
      border:1px solid var(--line);
      border-radius:8px;
      background:white;
      color:#334155;
      padding:9px 12px;
      cursor:pointer;
      font-weight:800;
    }
    .drawer-body {
      padding:18px;
      overflow:auto;
    }
    .detail-row {
      padding:10px 0;
      border-bottom:1px solid #edf1f5;
    }
    .detail-row strong {
      display:block;
      color:#334155;
      font-size:12px;
      text-transform:uppercase;
      letter-spacing:0;
      margin-bottom:4px;
    }
    .drawer-actions {
      display:flex;
      gap:10px;
      padding:14px 18px 18px;
      border-top:1px solid var(--line);
    }
    footer {
      margin-top:42px;
      color:var(--muted);
      font-size:12px;
      text-align:center;
    }
    @media (max-width: 980px) {
      .hero-inner, .workbench, .atlas-inner { grid-template-columns:1fr; }
      .knowledge-grid, .security-grid, .data-catalog, .evidence-board, .network-list, .spatial-grid, .quality-grid, .mode-pair, .results-cockpit, .executive-grid, .briefing-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); }
      .pipeline, .pipeline-wide { grid-template-columns:repeat(2, minmax(0, 1fr)); }
      .intake-surface, .dossier-preview-surface, .output { min-height:auto; }
      .output-empty { min-height:420px; }
      .results-head { flex-direction:column; }
      .result-actions { justify-content:flex-start; }
      .atlas-stage { height:520px; }
    }
    @media (max-width: 640px) {
      .topbar { position:static; align-items:flex-start; flex-direction:column; }
      nav { justify-content:flex-start; }
      .controls, .mode-brief-grid, .question-grid, .knowledge-grid, .security-grid, .data-catalog, .evidence-board, .research-cockpit, .next-step-grid, .dossier-grid, .network-list, .spatial-grid, .quality-grid, .follow-grid, .mode-pair, .preview-metrics, .award-strip, .dossier-preview-grid, .results-cockpit, .executive-grid, .briefing-grid { grid-template-columns:1fr; }
      .executive-card.primary-card { grid-column:auto; }
      .clue-workbench { min-height:auto; justify-content:flex-start; }
      h1, .clue-workbench .section-title h1 { font-size:32px; }
      .answer-toolbar { align-items:flex-start; flex-direction:column; }
      .toolbar-actions { justify-content:flex-start; }
      .hero { padding-top:34px; }
      .primary-row { align-items:flex-start; flex-direction:column; }
      .atlas-band { min-height:720px; }
      .atlas-inner { min-height:720px; }
      .atlas-stage { min-height:420px; height:440px; }
      .result-graph { height:480px; }
      .result-node-link { max-width:118px; font-size:11px; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand"><span class="mark" aria-hidden="true"></span><span>文脉镜 ContextLens</span></div>
    <nav aria-label="Main navigation">
      <a href="#home" data-i18n="home">首页</a>
      <a href="#resultsPage" data-i18n="ask">档案</a>
      <a href="#evidence" data-i18n="evidence">证据</a>
      <a href="#atlas" data-i18n="atlas">3D 图谱</a>
      <a href="#knowledge" data-i18n="knowledge">知识构建</a>
      <a href="#security" data-i18n="security">安全审计</a>
    </nav>
    <div class="language-toggle" aria-label="Language">
      <button id="langZh" class="active" type="button">中文</button>
      <button id="langEn" type="button">English</button>
    </div>
  </header>

  <main>
    <section class="section clue-workbench" id="home">
      <div class="section-title">
        <h1 data-i18n="workbenchTitle">你想追寻哪条历史线索？</h1>
        <p><span data-i18n="firstScreenLead"></span><br><span data-i18n="ready" id="status"></span></p>
      </div>
      <div class="workbench">
        <div class="surface intake-surface">
          <div class="intake-head">
            <span data-i18n="intakeKicker"></span>
            <strong>文脉镜 ContextLens</strong>
          </div>
          <label for="question" data-i18n="questionLabel">研究问题</label>
          <textarea id="question" maxlength="800">盛宣怀与上海的铁路、银行和航运有什么联系？</textarea>
          <div class="clue-preview" id="cluePreview"></div>
          <div class="award-strip" aria-label="Judging highlights">
            <strong data-i18n="awardHighlights"></strong>
            <span data-i18n="highlightProvenance"></span>
            <span data-i18n="highlightReplay"></span>
            <span data-i18n="highlightDualMode"></span>
          </div>

          <details class="fold-panel" open>
            <summary><span data-i18n="advancedSettings"></span></summary>
            <div class="fold-body">
              <div class="controls">
                <div>
                  <label for="mode" data-i18n="modeLabel"></label>
                  <select id="mode"></select>
                </div>
                <div>
                  <label for="style" data-i18n="styleLabel"></label>
                  <select id="style"></select>
                </div>
                <div>
                  <label for="topK" data-i18n="depthLabel"></label>
                  <select id="topK">
                    <option value="6">6</option>
                    <option value="8">8</option>
                    <option value="10" selected>10</option>
                    <option value="12">12</option>
                  </select>
                </div>
              </div>
              <div class="mode-brief" id="modeBrief"></div>
              <label class="assist-toggle disabled" id="deepseekAssistWrap">
                <input type="checkbox" id="deepseekAssist" disabled />
                <span>
                  <span data-i18n="deepseekAssist">DeepSeek 快速辅助</span>
                  <small id="deepseekAssistNote" data-i18n="deepseekAssistNote"></small>
                </span>
              </label>
            </div>
          </details>

          <div class="primary-row">
            <button class="primary" id="askBtn" type="button" data-i18n="run"></button>
            <span class="status"><span id="charCount">0</span>/800</span>
          </div>

          <div class="fold-stack">
            <details class="fold-panel" open>
              <summary><span data-i18n="protocolFold"></span></summary>
              <div class="fold-body">
                <div class="pipeline" id="miniPipeline"></div>
              </div>
            </details>
            <details class="fold-panel" open>
              <summary><span data-i18n="examplesFold"></span></summary>
              <div class="fold-body">
                <div class="question-grid" id="questionCards"></div>
              </div>
            </details>
          </div>
        </div>
        <div class="surface dossier-preview-surface">
          <div class="section-title" style="margin-bottom:12px;">
            <h2 data-i18n="answerTitle"></h2>
            <p data-i18n="emptyOutputHint"></p>
          </div>
          <div class="output-empty">
            <strong data-i18n="emptyOutputTitle"></strong>
            <p data-i18n="emptyOutputHint"></p>
            <div class="dossier-preview-grid">
              <span data-i18n="previewFinding"></span>
              <span data-i18n="previewTimeline"></span>
              <span data-i18n="previewNetwork"></span>
              <span data-i18n="previewSpace"></span>
              <span data-i18n="previewAudit"></span>
              <span data-i18n="previewExport"></span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="section results-page" id="resultsPage" hidden>
      <div class="results-shell">
        <div class="results-head">
          <div>
            <p class="eyebrow" data-i18n="resultPageKicker"></p>
            <h2 data-i18n="resultPageTitle">历史调查档案全屏视图</h2>
            <p data-i18n="resultPageSubtitle"></p>
          </div>
          <div class="result-actions">
            <button class="ghost" id="backToWorkbench" type="button" data-i18n="backToWorkbench"></button>
          </div>
        </div>
        <div class="results-cockpit" id="resultCockpit"></div>
        <div class="surface output result-output" id="dossier">
          <div class="section-title" style="margin-bottom:12px;">
            <h2 data-i18n="answerTitle"></h2>
            <p id="answerMeta"></p>
          </div>
          <div id="output"></div>
        </div>
      </div>
    </section>

    <section class="atlas-band section" id="atlas">
      <div class="atlas-inner">
        <div class="atlas-copy">
          <p class="eyebrow" data-i18n="atlasHint"></p>
          <h2 data-i18n="atlasTitle">3D 知识构建图谱</h2>
          <p data-i18n="atlasNote"></p>
          <div class="atlas-chip-row">
            <span class="atlas-chip">Clue</span>
            <span class="atlas-chip">Plan</span>
            <span class="atlas-chip">Entity Link</span>
            <span class="atlas-chip">Claim Ledger</span>
            <span class="atlas-chip">Counter-Evidence</span>
          </div>
          <div class="atlas-focus" id="atlasFocus">
            <strong data-i18n="atlasFocus">当前聚焦</strong>
            <span data-i18n="atlasLoading">正在加载 3D 图谱...</span>
          </div>
        </div>
        <div class="atlas-stage" id="atlasStage">
          <canvas id="atlasCanvas" aria-label="3D knowledge build atlas"></canvas>
          <div class="atlas-tooltip" id="atlasTooltip">
            <strong data-i18n="atlasTitle"></strong>
            <span data-i18n="atlasLoading"></span>
          </div>
          <div class="atlas-status" id="atlasStatus" data-i18n="atlasLoading">正在加载 3D 图谱...</div>
        </div>
      </div>
    </section>

    <section class="section" id="evidence">
      <div class="section-title">
        <h2 data-i18n="evidence">证据</h2>
        <p data-i18n="clickEvidence"></p>
      </div>
      <div class="evidence-board" id="evidenceBoard"></div>
    </section>

    <section class="section" id="knowledge">
      <div class="section-title">
        <h2 data-i18n="knowledgeTitle">知识构建状态</h2>
        <p data-i18n="knowledgeNote"></p>
      </div>
      <div class="knowledge-grid" id="knowledgeStats"></div>
      <div class="data-catalog" id="dataCatalog"></div>
      <div class="pipeline-wide" id="knowledgePipeline"></div>
    </section>

    <section class="section" id="security">
      <div class="section-title">
        <h2 data-i18n="securityTitle">安全审计面板</h2>
        <p data-i18n="securityNote"></p>
      </div>
      <div class="security-grid" id="securityStats"></div>
      <div class="security-list" id="warnings"></div>
    </section>

    <footer>文脉镜 ContextLens. Educational and public-knowledge prototype only.</footer>
  </main>

  <div class="drawer-overlay" id="drawerOverlay"></div>
  <aside class="drawer" id="drawer" aria-hidden="true">
    <div class="drawer-head">
      <h2 data-i18n="drawerTitle">证据详情</h2>
      <button class="ghost" id="closeDrawer" type="button" data-i18n="close">关闭</button>
    </div>
    <div class="drawer-body" id="drawerBody"></div>
    <div class="drawer-actions">
      <button class="primary" id="openSource" type="button" data-i18n="openOriginal"></button>
      <button class="ghost" id="copyCitation" type="button" data-i18n="copyCitation"></button>
    </div>
  </aside>

  <script>
  const appData = REPLACE_APP_DATA;
  const state = {
    lang: "zh",
    health: null,
    lastAnswer: null,
    evidenceCache: new Map(),
    mutedEvidence: new Set(),
    drawerRecord: null
  };
  const atlasSpecs = [
    { id:"api", icon:"cloud", labelKey:"atlasApi", descKey:"atlasApiDesc", color:0xd7a943, position:[-4.2, 1.55, 0.1] },
    { id:"raw", icon:"json", labelKey:"atlasRaw", descKey:"atlasRawDesc", color:0x9f2f28, position:[-3.0, -1.2, -1.0] },
    { id:"record", icon:"record", labelKey:"atlasRecord", descKey:"atlasRecordDesc", color:0x56a3d9, position:[-1.6, .62, .95] },
    { id:"index", icon:"database", labelKey:"atlasIndex", descKey:"atlasIndexDesc", color:0x14a58f, position:[-.25, -1.35, .2] },
    { id:"retrieval", icon:"search", labelKey:"atlasRetrieval", descKey:"atlasRetrievalDesc", color:0xf2c86b, position:[1.28, .9, -.86] },
    { id:"cards", icon:"cards", labelKey:"atlasCards", descKey:"atlasCardsDesc", color:0x7dd3fc, position:[2.45, -1.05, .86] },
    { id:"answer", icon:"report", labelKey:"atlasAnswer", descKey:"atlasAnswerDesc", color:0xb7d97a, position:[3.72, .72, -.18] },
    { id:"audit", icon:"shield", labelKey:"atlasAudit", descKey:"atlasAuditDesc", color:0xf28c8c, position:[4.55, -1.55, .74] }
  ];
  const atlas = {
    initialized:false,
    loading:false,
    fallback:false,
    selectedId:"api",
    hovered:null,
    nodes:[],
    sprites:[],
    line:null,
    group:null,
    scene:null,
    camera:null,
    renderer:null,
    raycaster:null,
    pointer:null,
    dragging:false,
    moved:false,
    lastX:0,
    lastY:0,
    rotX:.08,
    rotY:-.28,
    zoom:9.2
  };
  const els = {
    langZh: document.getElementById("langZh"),
    langEn: document.getElementById("langEn"),
    mode: document.getElementById("mode"),
    modeBrief: document.getElementById("modeBrief"),
    style: document.getElementById("style"),
    deepseekAssist: document.getElementById("deepseekAssist"),
    deepseekAssistWrap: document.getElementById("deepseekAssistWrap"),
    deepseekAssistNote: document.getElementById("deepseekAssistNote"),
    topK: document.getElementById("topK"),
    question: document.getElementById("question"),
    cluePreview: document.getElementById("cluePreview"),
    askBtn: document.getElementById("askBtn"),
    status: document.getElementById("status"),
    output: document.getElementById("output"),
    answerMeta: document.getElementById("answerMeta"),
    resultsPage: document.getElementById("resultsPage"),
    resultCockpit: document.getElementById("resultCockpit"),
    backToWorkbench: document.getElementById("backToWorkbench"),
    charCount: document.getElementById("charCount"),
    questionCards: document.getElementById("questionCards"),
    evidenceBoard: document.getElementById("evidenceBoard"),
    knowledgeStats: document.getElementById("knowledgeStats"),
    dataCatalog: document.getElementById("dataCatalog"),
    knowledgePipeline: document.getElementById("knowledgePipeline"),
    securityStats: document.getElementById("securityStats"),
    warnings: document.getElementById("warnings"),
    miniPipeline: document.getElementById("miniPipeline"),
    atlasStage: document.getElementById("atlasStage"),
    atlasCanvas: document.getElementById("atlasCanvas"),
    atlasTooltip: document.getElementById("atlasTooltip"),
    atlasFocus: document.getElementById("atlasFocus"),
    atlasStatus: document.getElementById("atlasStatus"),
    drawer: document.getElementById("drawer"),
    drawerOverlay: document.getElementById("drawerOverlay"),
    drawerBody: document.getElementById("drawerBody"),
    closeDrawer: document.getElementById("closeDrawer"),
    openSource: document.getElementById("openSource"),
    copyCitation: document.getElementById("copyCitation")
  };

  function t(key) {
    return (appData.copy[state.lang] && appData.copy[state.lang][key]) || key;
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, m => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[m]));
  }

  function optionLabel(item) {
    return state.lang === "zh" ? item.zh : item.en;
  }

  function initSelects() {
    els.mode.innerHTML = appData.modes.map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(optionLabel(m))}</option>`).join("");
    els.mode.value = state.lastAnswer ? state.lastAnswer.mode : "trace_person";
    els.style.innerHTML = appData.output_styles.map(s => `<option value="${escapeHtml(s.id)}">${escapeHtml(optionLabel(s))}</option>`).join("");
    els.style.value = state.lastAnswer ? state.lastAnswer.output_style : "investigation_dossier";
  }

  function updateCopy() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach(node => {
      node.textContent = t(node.getAttribute("data-i18n"));
    });
    els.langZh.classList.toggle("active", state.lang === "zh");
    els.langEn.classList.toggle("active", state.lang === "en");
    initSelects();
    renderModeBrief();
    renderQuestionCards();
    renderCluePreview();
    renderPipelines();
    refreshAtlasLanguage();
    renderHealth();
    renderSecurity(state.lastAnswer && state.lastAnswer.audit);
    if (state.lastAnswer) {
      renderAnswer(state.lastAnswer);
      renderEvidenceBoard(state.lastAnswer.evidence_cards || []);
      renderResultCockpit(state.lastAnswer);
    }
  }

  function renderModeBrief() {
    if (!els.modeBrief) return;
    const mode = appData.modes.find(item => item.id === els.mode.value) || appData.modes[0];
    const style = appData.output_styles.find(item => item.id === els.style.value) || appData.output_styles[0];
    const label = optionLabel(mode);
    const desc = state.lang === "zh" ? mode.desc_zh : mode.desc_en;
    const lens = state.lang === "zh" ? mode.lens_zh : mode.lens_en;
    const styleDesc = state.lang === "zh" ? style.desc_zh : style.desc_en;
    const terms = (mode.terms || []).slice(0, 8).map(term => `<span class="tag">${escapeHtml(term)}</span>`).join("");
    els.modeBrief.innerHTML = `
      <strong>${escapeHtml(t("modeBriefTitle"))}: ${escapeHtml(label)}</strong>
      <p>${escapeHtml(desc || "")}</p>
      <div class="mode-brief-grid">
        <div><b>${escapeHtml(t("researchLens"))}</b><p>${escapeHtml(lens || "")}</p></div>
        <div><b>${escapeHtml(t("outputStructure"))}</b><p>${escapeHtml(styleDesc || "")}</p></div>
      </div>
      <div class="tag-row" style="margin-bottom:0;"><b style="width:100%;color:var(--red);font-size:11px;text-transform:uppercase;">${escapeHtml(t("retrievalTerms"))}</b>${terms}</div>
    `;
  }

  function renderPipelines() {
    const compact = state.lang === "zh"
      ? ["线索", "计划", "检索", "主张", "反证"]
      : ["Clue", "Plan", "Search", "Claims", "Audit"];
    els.miniPipeline.innerHTML = compact.map((step, idx) => `<div class="step ${idx === 0 ? "active" : ""}">${escapeHtml(step)}</div>`).join("");
    const full = state.lang === "zh"
      ? ["线索解析", "检索计划", "EvidenceRecord", "实体链接", "证据图谱", "主张台账", "反证审计"]
      : ["Clue parsing", "Search plan", "EvidenceRecord", "Entity linking", "Evidence graph", "Claim ledger", "Counter-evidence audit"];
    els.knowledgePipeline.innerHTML = full.map(step => `<div class="step">${escapeHtml(step)}</div>`).join("");
  }

  async function initAtlas3d() {
    if (atlas.initialized || atlas.loading || !els.atlasCanvas) return;
    atlas.loading = true;
    els.atlasStatus.textContent = t("atlasLoading");
    setAtlasFocus(atlasSpecs[0]);
    buildAtlasScene();
    atlas.initialized = true;
    atlas.loading = false;
    atlas.fallback = false;
    refreshAtlasLanguage();
  }

  function buildAtlasScene() {
    const canvas = els.atlasCanvas;
    atlas.ctx = canvas.getContext("2d");
    atlas.projected = [];
    atlas.stars = Array.from({ length: 190 }, () => ({
      x: Math.random(),
      y: Math.random(),
      r: Math.random() * 1.6 + .35,
      a: Math.random() * .5 + .22
    }));
    canvas.addEventListener("pointerdown", onAtlasPointerDown);
    canvas.addEventListener("pointermove", onAtlasPointerMove);
    canvas.addEventListener("pointerup", onAtlasPointerUp);
    canvas.addEventListener("pointerleave", onAtlasPointerUp);
    canvas.addEventListener("wheel", onAtlasWheel, { passive:false });
    window.addEventListener("resize", resizeAtlas);
    resizeAtlas();
    animateAtlas();
  }

  function roundRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + width, y, x + width, y + height, radius);
    ctx.arcTo(x + width, y + height, x, y + height, radius);
    ctx.arcTo(x, y + height, x, y, radius);
    ctx.arcTo(x, y, x + width, y, radius);
    ctx.closePath();
  }

  function resizeAtlas() {
    if (!atlas.ctx || !els.atlasStage) return;
    const rect = els.atlasStage.getBoundingClientRect();
    atlas.width = Math.max(320, Math.floor(rect.width));
    atlas.height = Math.max(360, Math.floor(rect.height));
    atlas.dpr = Math.min(window.devicePixelRatio || 1, 2);
    els.atlasCanvas.width = Math.floor(atlas.width * atlas.dpr);
    els.atlasCanvas.height = Math.floor(atlas.height * atlas.dpr);
    els.atlasCanvas.style.width = `${atlas.width}px`;
    els.atlasCanvas.style.height = `${atlas.height}px`;
    atlas.ctx.setTransform(atlas.dpr, 0, 0, atlas.dpr, 0, 0);
  }

  function animateAtlas() {
    if (!atlas.ctx) return;
    requestAnimationFrame(animateAtlas);
    if (!atlas.dragging) atlas.rotY += .003;
    drawAtlas();
  }

  function drawAtlas() {
    const ctx = atlas.ctx;
    const width = atlas.width || els.atlasCanvas.clientWidth;
    const height = atlas.height || els.atlasCanvas.clientHeight;
    ctx.clearRect(0, 0, width, height);
    const bg = ctx.createLinearGradient(0, 0, width, height);
    bg.addColorStop(0, "rgba(5, 19, 36, .86)");
    bg.addColorStop(.5, "rgba(9, 35, 59, .52)");
    bg.addColorStop(1, "rgba(5, 50, 58, .68)");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    atlas.stars.forEach(star => {
      ctx.beginPath();
      ctx.fillStyle = `rgba(216, 231, 252, ${star.a})`;
      ctx.arc(star.x * width, star.y * height, star.r, 0, Math.PI * 2);
      ctx.fill();
    });

    const projected = atlasSpecs.map((spec, idx) => ({ spec, idx, ...projectPoint(spec.position) }));
    atlas.projected = projected;
    ctx.lineCap = "round";
    for (let i = 0; i < projected.length - 1; i += 1) {
      drawAtlasLink(ctx, projected[i], projected[i + 1]);
    }
    [...projected].sort((a, b) => a.z - b.z).forEach(point => drawAtlasNode(ctx, point));
  }

  function onAtlasPointerDown(event) {
    atlas.dragging = true;
    atlas.moved = false;
    atlas.lastX = event.clientX;
    atlas.lastY = event.clientY;
    els.atlasCanvas.setPointerCapture && els.atlasCanvas.setPointerCapture(event.pointerId);
  }

  function onAtlasPointerMove(event) {
    if (atlas.dragging) {
      const dx = event.clientX - atlas.lastX;
      const dy = event.clientY - atlas.lastY;
      if (Math.abs(dx) + Math.abs(dy) > 3) atlas.moved = true;
      atlas.rotY += dx * .008;
      atlas.rotX += dy * .005;
      atlas.rotX = Math.max(-.72, Math.min(.72, atlas.rotX));
      atlas.lastX = event.clientX;
      atlas.lastY = event.clientY;
      return;
    }
    updateAtlasHover(event);
  }

  function onAtlasPointerUp(event) {
    if (atlas.dragging && !atlas.moved) {
      const picked = pickAtlasNode(event);
      if (picked) selectAtlasNode(picked);
    }
    atlas.dragging = false;
    updateAtlasHover(event);
  }

  function onAtlasWheel(event) {
    event.preventDefault();
    atlas.zoom += event.deltaY * .004;
    atlas.zoom = Math.max(6.5, Math.min(13.5, atlas.zoom));
  }

  function updateAtlasHover(event) {
    const picked = pickAtlasNode(event);
    atlas.hovered = picked;
    els.atlasCanvas.style.cursor = picked ? "pointer" : "grab";
    if (picked) {
      const spec = picked.spec;
      els.atlasTooltip.innerHTML = `<strong>${escapeHtml(t(spec.labelKey))}</strong><span>${escapeHtml(t(spec.descKey))}</span>`;
    }
  }

  function pickAtlasNode(event) {
    const rect = els.atlasCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let best = null;
    let bestDistance = Infinity;
    for (const point of atlas.projected || []) {
      const distance = Math.hypot(point.x - x, point.y - y);
      if (distance < point.hit && distance < bestDistance) {
        best = point;
        bestDistance = distance;
      }
    }
    return best;
  }

  function selectAtlasNode(node) {
    atlas.selectedId = node.spec.id;
    setAtlasFocus(node.spec);
  }

  function setAtlasFocus(spec) {
    if (!els.atlasFocus || !spec) return;
    els.atlasFocus.innerHTML = `<strong>${escapeHtml(t("atlasFocus"))}: ${escapeHtml(t(spec.labelKey))}</strong><span>${escapeHtml(t(spec.descKey))}</span>`;
  }

  function refreshAtlasLanguage() {
    if (!els.atlasStatus) return;
    const selected = atlasSpecs.find(spec => spec.id === atlas.selectedId) || atlasSpecs[0];
    setAtlasFocus(selected);
    els.atlasStatus.textContent = atlas.initialized ? t("atlasHint") : t("atlasLoading");
    if (!atlas.initialized) {
      els.atlasTooltip.innerHTML = `<strong>${escapeHtml(t("atlasTitle"))}</strong><span>${escapeHtml(t("atlasLoading"))}</span>`;
      return;
    }
    const hoverSpec = atlas.hovered?.spec || selected;
    els.atlasTooltip.innerHTML = `<strong>${escapeHtml(t(hoverSpec.labelKey))}</strong><span>${escapeHtml(t(hoverSpec.descKey))}</span>`;
  }

  function projectPoint(position) {
    const [x0, y0, z0] = position;
    const cx = Math.cos(atlas.rotX);
    const sx = Math.sin(atlas.rotX);
    const cy = Math.cos(atlas.rotY);
    const sy = Math.sin(atlas.rotY);
    const x1 = x0 * cy - z0 * sy;
    const z1 = x0 * sy + z0 * cy;
    const y1 = y0 * cx - z1 * sx;
    const z2 = y0 * sx + z1 * cx;
    const perspective = atlas.zoom / (atlas.zoom + z2);
    const scale = Math.min(atlas.width, atlas.height) * .112 * perspective;
    return {
      x: atlas.width / 2 + x1 * scale,
      y: atlas.height / 2 + y1 * scale,
      z: z2,
      scale,
      depth: perspective,
      hit: Math.max(26, 34 * perspective)
    };
  }

  function drawAtlasLink(ctx, a, b) {
    const gradient = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
    gradient.addColorStop(0, "rgba(245, 210, 142, .28)");
    gradient.addColorStop(.5, "rgba(125, 211, 252, .72)");
    gradient.addColorStop(1, "rgba(245, 210, 142, .28)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = Math.max(2, (a.depth + b.depth) * 2.1);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    const midX = (a.x + b.x) / 2;
    const midY = (a.y + b.y) / 2 - 34 * ((a.depth + b.depth) / 2);
    ctx.quadraticCurveTo(midX, midY, b.x, b.y);
    ctx.stroke();
  }

  function drawAtlasNode(ctx, point) {
    const spec = point.spec;
    const selected = spec.id === atlas.selectedId;
    const hovered = atlas.hovered?.spec?.id === spec.id;
    const radius = (selected || hovered ? 23 : 18) * point.depth;
    const color = `#${spec.color.toString(16).padStart(6, "0")}`;
    ctx.save();
    ctx.globalAlpha = Math.max(.62, Math.min(1, point.depth));
    drawIconNode(ctx, {
      x:point.x,
      y:point.y,
      radius,
      color,
      icon:spec.icon,
      active:selected || hovered
    });
    drawAtlasLabel(ctx, point, radius);
    ctx.restore();
  }

  function colorAlpha(color, alpha) {
    if (/^#[0-9a-f]{6}$/i.test(color)) {
      const value = Math.round(Math.max(0, Math.min(1, alpha)) * 255).toString(16).padStart(2, "0");
      return `${color}${value}`;
    }
    return color;
  }

  function applyIconPathStyle(ctx, color, active) {
    ctx.fillStyle = "rgba(8, 36, 63, .92)";
    ctx.strokeStyle = active ? "#f5d28e" : color;
    ctx.lineWidth = active ? 2.6 : 1.7;
  }

  function drawIconNode(ctx, options) {
    const x = options.x;
    const y = options.y;
    const r = Math.max(10, options.radius);
    const color = options.color || "#7dd3fc";
    const icon = options.icon || "record";
    const active = Boolean(options.active);
    ctx.save();
    const glow = ctx.createRadialGradient(x, y, 2, x, y, r * 3.25);
    glow.addColorStop(0, colorAlpha(color, active ? .92 : .72));
    glow.addColorStop(.34, colorAlpha(color, active ? .38 : .22));
    glow.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, y, r * 3.25, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "rgba(3, 12, 24, .28)";
    ctx.beginPath();
    ctx.ellipse(x, y + r * .92, r * 1.15, r * .24, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.shadowColor = colorAlpha(color, active ? .72 : .5);
    ctx.shadowBlur = active ? r * .86 : r * .54;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (icon === "cloud") drawCloudIcon(ctx, x, y, r, color, active);
    else if (icon === "json") drawJsonIcon(ctx, x, y, r, color, active);
    else if (icon === "database") drawDatabaseIcon(ctx, x, y, r, color, active);
    else if (icon === "search") drawSearchIcon(ctx, x, y, r, color, active);
    else if (icon === "cards") drawCardsIcon(ctx, x, y, r, color, active);
    else if (icon === "report") drawReportIcon(ctx, x, y, r, color, active);
    else if (icon === "shield") drawShieldIcon(ctx, x, y, r, color, active);
    else if (icon === "question") drawQuestionIcon(ctx, x, y, r, color, active);
    else if (icon === "compass") drawCompassIcon(ctx, x, y, r, color, active);
    else if (icon === "book") drawBookIcon(ctx, x, y, r, color, active);
    else drawRecordIcon(ctx, x, y, r, color, active);

    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(245, 210, 142, .5)";
    ctx.lineWidth = 1.05;
    ctx.beginPath();
    ctx.ellipse(x, y, r * 1.62, r * .38, Math.PI * .08, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  function drawCloudIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    ctx.beginPath();
    ctx.moveTo(x - r * .9, y + r * .18);
    ctx.bezierCurveTo(x - r * .98, y - r * .2, x - r * .64, y - r * .5, x - r * .28, y - r * .43);
    ctx.bezierCurveTo(x - r * .08, y - r * .9, x + r * .52, y - r * .76, x + r * .56, y - r * .3);
    ctx.bezierCurveTo(x + r * .94, y - r * .28, x + r * 1.04, y + r * .22, x + r * .7, y + r * .38);
    ctx.lineTo(x - r * .68, y + r * .38);
    ctx.bezierCurveTo(x - r * .82, y + r * .38, x - r * .93, y + r * .3, x - r * .9, y + r * .18);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(248,251,255,.86)";
    ctx.lineWidth = Math.max(1.1, r * .08);
    ctx.beginPath();
    ctx.moveTo(x - r * .32, y + r * .38);
    ctx.lineTo(x - r * .32, y + r * .62);
    ctx.lineTo(x + r * .36, y + r * .62);
    ctx.lineTo(x + r * .36, y + r * .38);
    ctx.stroke();
    ctx.fillStyle = colorAlpha(color, .95);
    [x - r * .32, x + r * .02, x + r * .36].forEach(dotX => {
      ctx.beginPath();
      ctx.arc(dotX, y + r * .64, r * .07, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function drawJsonIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    roundRect(ctx, x - r * .72, y - r * .98, r * 1.44, r * 1.92, r * .2);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = colorAlpha(color, .72);
    ctx.lineWidth = Math.max(1, r * .07);
    ctx.beginPath();
    ctx.moveTo(x + r * .38, y - r * .98);
    ctx.lineTo(x + r * .72, y - r * .64);
    ctx.lineTo(x + r * .38, y - r * .64);
    ctx.closePath();
    ctx.stroke();
    ctx.fillStyle = "rgba(248,251,255,.92)";
    ctx.font = `700 ${Math.max(13, Math.round(r * .72))}px Arial, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("{ }", x, y + r * .02);
    ctx.strokeStyle = colorAlpha(color, .82);
    ctx.lineWidth = Math.max(1, r * .06);
    ctx.beginPath();
    ctx.moveTo(x - r * .42, y + r * .54);
    ctx.lineTo(x + r * .42, y + r * .54);
    ctx.stroke();
  }

  function drawRecordIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    roundRect(ctx, x - r * 1.05, y - r * .72, r * 2.1, r * 1.48, r * .2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = colorAlpha(color, .28);
    roundRect(ctx, x - r * .88, y - r * .54, r * 1.76, r * .3, r * .08);
    ctx.fill();
    ctx.strokeStyle = "rgba(248,251,255,.78)";
    ctx.lineWidth = Math.max(1, r * .055);
    for (let i = 0; i < 3; i += 1) {
      const rowY = y - r * .02 + i * r * .28;
      ctx.beginPath();
      ctx.moveTo(x - r * .78, rowY);
      ctx.lineTo(x + r * .78, rowY);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(x - r * .18, y - r * .52);
    ctx.lineTo(x - r * .18, y + r * .58);
    ctx.moveTo(x + r * .38, y - r * .52);
    ctx.lineTo(x + r * .38, y + r * .58);
    ctx.stroke();
  }

  function drawDatabaseIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    ctx.beginPath();
    ctx.moveTo(x - r * .82, y - r * .52);
    ctx.lineTo(x - r * .82, y + r * .48);
    ctx.bezierCurveTo(x - r * .82, y + r * .86, x + r * .82, y + r * .86, x + r * .82, y + r * .48);
    ctx.lineTo(x + r * .82, y - r * .52);
    ctx.bezierCurveTo(x + r * .82, y - r * .16, x - r * .82, y - r * .16, x - r * .82, y - r * .52);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = colorAlpha(color, .28);
    ctx.beginPath();
    ctx.ellipse(x, y - r * .52, r * .82, r * .3, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(248,251,255,.7)";
    ctx.lineWidth = Math.max(1, r * .055);
    [-.05, .46].forEach(offset => {
      ctx.beginPath();
      ctx.ellipse(x, y + r * offset, r * .82, r * .28, 0, 0, Math.PI);
      ctx.stroke();
    });
  }

  function drawSearchIcon(ctx, x, y, r, color, active) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(-.14);
    applyIconPathStyle(ctx, color, active);
    roundRect(ctx, -r * .82, -r * .7, r * 1.42, r * 1.22, r * .22);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    ctx.strokeStyle = "rgba(248,251,255,.9)";
    ctx.lineWidth = Math.max(2, r * .13);
    ctx.beginPath();
    ctx.arc(x - r * .18, y - r * .08, r * .42, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x + r * .15, y + r * .25);
    ctx.lineTo(x + r * .64, y + r * .72);
    ctx.stroke();
    ctx.strokeStyle = colorAlpha(color, .82);
    ctx.lineWidth = Math.max(1, r * .05);
    ctx.beginPath();
    ctx.moveTo(x - r * .34, y - r * .08);
    ctx.lineTo(x - r * .03, y - r * .08);
    ctx.stroke();
  }

  function drawCardsIcon(ctx, x, y, r, color, active) {
    const offsets = [[-.28, -.2], [-.1, -.05], [.1, .12]];
    offsets.forEach((offset, idx) => {
      applyIconPathStyle(ctx, color, active && idx === offsets.length - 1);
      ctx.fillStyle = idx === offsets.length - 1 ? "rgba(8, 36, 63, .94)" : "rgba(8, 36, 63, .64)";
      roundRect(ctx, x - r * .78 + r * offset[0], y - r * .62 + r * offset[1], r * 1.42, r * 1.12, r * .16);
      ctx.fill();
      ctx.stroke();
    });
    ctx.strokeStyle = "rgba(248,251,255,.78)";
    ctx.lineWidth = Math.max(1, r * .055);
    for (let i = 0; i < 3; i += 1) {
      ctx.beginPath();
      ctx.moveTo(x - r * .36, y - r * .13 + i * r * .24);
      ctx.lineTo(x + r * .5, y - r * .13 + i * r * .24);
      ctx.stroke();
    }
  }

  function drawReportIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    roundRect(ctx, x - r * .72, y - r * 1.02, r * 1.44, r * 2.02, r * .16);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = colorAlpha(color, .32);
    ctx.beginPath();
    ctx.moveTo(x + r * .34, y - r * 1.02);
    ctx.lineTo(x + r * .72, y - r * .64);
    ctx.lineTo(x + r * .34, y - r * .64);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(248,251,255,.78)";
    ctx.lineWidth = Math.max(1, r * .06);
    for (let i = 0; i < 3; i += 1) {
      ctx.beginPath();
      ctx.moveTo(x - r * .42, y - r * .28 + i * r * .28);
      ctx.lineTo(x + r * .42, y - r * .28 + i * r * .28);
      ctx.stroke();
    }
    ctx.fillStyle = colorAlpha(color, .9);
    roundRect(ctx, x - r * .42, y + r * .44, r * .24, r * .3, r * .04);
    ctx.fill();
    roundRect(ctx, x - r * .06, y + r * .28, r * .24, r * .46, r * .04);
    ctx.fill();
    roundRect(ctx, x + r * .3, y + r * .1, r * .24, r * .64, r * .04);
    ctx.fill();
  }

  function drawShieldIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    ctx.beginPath();
    ctx.moveTo(x, y - r * 1.02);
    ctx.lineTo(x + r * .78, y - r * .68);
    ctx.lineTo(x + r * .64, y + r * .28);
    ctx.bezierCurveTo(x + r * .48, y + r * .76, x + r * .12, y + r * .95, x, y + r * 1.05);
    ctx.bezierCurveTo(x - r * .12, y + r * .95, x - r * .48, y + r * .76, x - r * .64, y + r * .28);
    ctx.lineTo(x - r * .78, y - r * .68);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(248,251,255,.92)";
    ctx.lineWidth = Math.max(2, r * .12);
    ctx.beginPath();
    ctx.moveTo(x - r * .32, y + r * .02);
    ctx.lineTo(x - r * .08, y + r * .28);
    ctx.lineTo(x + r * .38, y - r * .28);
    ctx.stroke();
  }

  function drawQuestionIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    roundRect(ctx, x - r * .92, y - r * .72, r * 1.84, r * 1.36, r * .26);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - r * .18, y + r * .62);
    ctx.lineTo(x - r * .38, y + r * .98);
    ctx.lineTo(x + r * .22, y + r * .62);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(248,251,255,.95)";
    ctx.font = `800 ${Math.max(16, Math.round(r * .92))}px Arial, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("?", x, y - r * .02);
  }

  function drawCompassIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    ctx.beginPath();
    ctx.moveTo(x, y - r * 1.05);
    ctx.lineTo(x + r * .96, y);
    ctx.lineTo(x, y + r * 1.05);
    ctx.lineTo(x - r * .96, y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = colorAlpha(color, .86);
    ctx.beginPath();
    ctx.moveTo(x + r * .12, y - r * .72);
    ctx.lineTo(x + r * .28, y + r * .18);
    ctx.lineTo(x - r * .48, y + r * .58);
    ctx.lineTo(x - r * .18, y - r * .12);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "rgba(248,251,255,.84)";
    ctx.lineWidth = Math.max(1, r * .055);
    ctx.beginPath();
    ctx.moveTo(x, y - r * .72);
    ctx.lineTo(x, y + r * .72);
    ctx.moveTo(x - r * .72, y);
    ctx.lineTo(x + r * .72, y);
    ctx.stroke();
  }

  function drawBookIcon(ctx, x, y, r, color, active) {
    applyIconPathStyle(ctx, color, active);
    ctx.beginPath();
    ctx.moveTo(x, y - r * .72);
    ctx.bezierCurveTo(x - r * .32, y - r * .94, x - r * .74, y - r * .82, x - r * .98, y - r * .56);
    ctx.lineTo(x - r * .98, y + r * .72);
    ctx.bezierCurveTo(x - r * .58, y + r * .46, x - r * .22, y + r * .5, x, y + r * .78);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x, y - r * .72);
    ctx.bezierCurveTo(x + r * .32, y - r * .94, x + r * .74, y - r * .82, x + r * .98, y - r * .56);
    ctx.lineTo(x + r * .98, y + r * .72);
    ctx.bezierCurveTo(x + r * .58, y + r * .46, x + r * .22, y + r * .5, x, y + r * .78);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(248,251,255,.72)";
    ctx.lineWidth = Math.max(1, r * .055);
    ctx.beginPath();
    ctx.moveTo(x, y - r * .62);
    ctx.lineTo(x, y + r * .72);
    ctx.stroke();
    [-.48, .22].forEach(offset => {
      ctx.beginPath();
      ctx.moveTo(x + r * offset, y - r * .3);
      ctx.lineTo(x + r * (offset > 0 ? .74 : -.74), y - r * .16);
      ctx.moveTo(x + r * offset, y + r * .08);
      ctx.lineTo(x + r * (offset > 0 ? .74 : -.74), y + r * .22);
      ctx.stroke();
    });
  }

  function drawAtlasLabel(ctx, point, radius) {
    const label = t(point.spec.labelKey);
    ctx.font = "800 13px Arial, sans-serif";
    const width = Math.min(178, Math.max(82, ctx.measureText(label).width + 22));
    const height = 30;
    const x = point.x - width / 2;
    const y = point.y + radius + 10;
    ctx.fillStyle = "rgba(7, 25, 45, .78)";
    roundRect(ctx, x, y, width, height, 8);
    ctx.fill();
    ctx.strokeStyle = "rgba(245, 210, 142, .78)";
    ctx.lineWidth = 1.2;
    roundRect(ctx, x, y, width, height, 8);
    ctx.stroke();
    ctx.fillStyle = "#f8fbff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, point.x, y + height / 2, width - 12);
  }

  function renderCluePreview() {
    if (!els.cluePreview) return;
    const clue = analyzeClue(els.question.value || "");
    const statusClass = clue.ready ? "" : "needs-more";
    els.cluePreview.innerHTML = `
      <div class="preview-head">
        <strong>${escapeHtml(t("cluePreviewTitle"))}</strong>
        <span class="preview-status ${statusClass}">${escapeHtml(clue.ready ? t("cluePreviewReady") : t("cluePreviewNeedsMore"))}</span>
      </div>
      <div class="preview-metrics">
        ${previewMetric(t("clueDetectedType"), clue.entryLabel, clue.entryScore)}
        ${previewMetric(t("clueSpecificity"), `${clue.specificity}%`, clue.specificity)}
        ${previewMetric(t("clueObjectCoverage"), `${clue.coverage}%`, clue.coverage)}
      </div>
      <div class="preview-tags">
        <span class="tag live">${escapeHtml(t("clueResearchIntent"))}: ${escapeHtml(clue.intent)}</span>
        <span class="tag">${escapeHtml(t("clueSuggestedTerms"))}: ${escapeHtml(clue.suggestions.join(" / "))}</span>
        ${clue.terms.slice(0, 6).map(term => `<span class="tag seed">${escapeHtml(term)}</span>`).join("")}
      </div>
    `;
  }

  function previewMetric(label, value, score) {
    const pct = Math.max(0, Math.min(100, Number(score || 0)));
    return `<div class="preview-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <div class="preview-meter" aria-hidden="true"><i style="width:${pct}%"></i></div>
    </div>`;
  }

  function analyzeClue(text) {
    const value = String(text || "").trim();
    const lower = value.toLowerCase();
    const categories = [
      { key:"person", zh:"人物", en:"Person", terms:["盛宣怀","鲁迅","张骞","人物","先生","女士","传记","person","lu xun"] },
      { key:"place", zh:"地点/旧址", en:"Place / Old Address", terms:["上海","外滩","旧址","旧地址","道路","建筑","里弄","地点","地名","place","address","bund"] },
      { key:"event", zh:"事件", en:"Event", terms:["事件","发生","运动","战争","会议","通商","影响","event","happened"] },
      { key:"document", zh:"文献", en:"Document", terms:["文献","书","档案","报刊","索引","家谱","题名","刊物","document","book","archive"] },
      { key:"network", zh:"关系网络", en:"Relationship Network", terms:["关系","连接","相关","哪些","机构","银行","商人","口岸","航运","network","connect"] },
      { key:"city", zh:"城市记忆", en:"City Memory", terms:["城市记忆","南京路","石库门","老照片","老地图","杨树浦","提篮桥","城市漫游","city walk","old photo","old map"] },
      { key:"family", zh:"家族线索", en:"Family Clue", terms:["家谱","族谱","祖籍","校友录","亲属","寻亲","姓氏","family","genealogy","surname"] },
      { key:"culture", zh:"公共文化", en:"Public Culture", terms:["张爱玲","宋庆龄","鲁迅","电影","影院","出版","女性","职业教育","public culture","film","literary"] },
    ];
    const hits = categories.filter(cat => cat.terms.some(term => lower.includes(term.toLowerCase()) || value.includes(term)));
    const entry = hits[0] || categories.find(cat => cat.key === "network");
    const terms = extractClueTerms(value);
    const hasQuestionShape = /[？?如何哪些什么怎样怎么]/.test(value);
    const specificity = Math.min(100, Math.round(value.length * 1.8 + terms.length * 8 + (hasQuestionShape ? 12 : 0)));
    const coverage = Math.min(100, Math.round(hits.length * 18 + terms.length * 7 + (/[0-9一二三四五六七八九十晚近民清汉唐宋元明]/.test(value) ? 10 : 0)));
    const ready = specificity >= 48 && coverage >= 38;
    const intent = inferClientIntent(value);
    const suggestions = suggestClueAdditions(value, hits.map(item => item.key));
    return {
      ready,
      entryLabel: state.lang === "zh" ? entry.zh : entry.en,
      entryScore: Math.min(100, 46 + hits.length * 16),
      specificity,
      coverage,
      intent,
      suggestions,
      terms,
    };
  }

  function extractClueTerms(text) {
    const stop = new Set(["什么","哪些","如何","怎么","怎样","是否","一个","一处","一件","一本","一段","历史","线索","期间","附近"]);
    const terms = [];
    const chinese = text.match(/[\u4e00-\u9fff]{2,8}/g) || [];
    chinese.forEach(item => {
      if (!stop.has(item) && !terms.includes(item)) terms.push(item);
    });
    const latin = text.match(/[A-Za-z][A-Za-z\s.-]{1,28}/g) || [];
    latin.forEach(item => {
      const cleaned = item.trim();
      if (cleaned && !terms.includes(cleaned)) terms.push(cleaned);
    });
    return terms.slice(0, 8);
  }

  function inferClientIntent(text) {
    const value = String(text || "");
    if (/关系|连接|相关|网络/.test(value)) return state.lang === "zh" ? "关系追踪" : "relationship tracing";
    if (/发生|事件|时间|经历/.test(value)) return state.lang === "zh" ? "时间线重建" : "timeline reconstruction";
    if (/旧址|旧地址|附近|地点|外滩|道路|建筑/.test(value)) return state.lang === "zh" ? "空间考证" : "spatial verification";
    if (/城市记忆|南京路|石库门|里弄|老照片|老地图|城市漫游/.test(value)) return state.lang === "zh" ? "城市记忆漫游" : "city-memory walk";
    if (/家谱|族谱|祖籍|校友录|亲属|寻亲|姓氏/.test(value)) return state.lang === "zh" ? "家族线索寻踪" : "family-memory trace";
    if (/张爱玲|宋庆龄|鲁迅|电影|影院|出版|公共文化/.test(value)) return state.lang === "zh" ? "公共文化调查" : "public-culture investigation";
    if (/文献|书|档案|报刊|刊物|索引/.test(value)) return state.lang === "zh" ? "文献溯源" : "document tracing";
    return state.lang === "zh" ? "综合调查" : "general investigation";
  }

  function suggestClueAdditions(text, keys) {
    const value = String(text || "");
    const zh = state.lang === "zh";
    const suggestions = [];
    if (!/[0-9一二三四五六七八九十晚近民清汉唐宋元明]/.test(value)) suggestions.push(zh ? "年代" : "date/period");
    if (!keys.includes("place")) suggestions.push(zh ? "地点" : "place");
    if (!keys.includes("person")) suggestions.push(zh ? "人物/别名" : "person/alias");
    if (!keys.includes("document")) suggestions.push(zh ? "文献题名" : "document title");
    suggestions.push(zh ? "待验证来源" : "source to verify");
    return suggestions.slice(0, 4);
  }

  function renderQuestionCards() {
    els.questionCards.innerHTML = appData.question_cards.map(card => {
      const category = state.lang === "zh" ? card.category_zh : card.category_en;
      const text = state.lang === "zh" ? card.zh : card.en;
      return `<button class="question-card" type="button" data-mode="${escapeHtml(card.mode)}" data-question="${escapeHtml(text)}">
        <div class="category">${escapeHtml(category)}</div>
        <div>${escapeHtml(text)}</div>
      </button>`;
    }).join("");
    els.questionCards.querySelectorAll(".question-card").forEach(card => {
      card.addEventListener("click", () => {
        els.question.value = card.getAttribute("data-question");
        els.mode.value = card.getAttribute("data-mode");
        updateCharCount();
        renderCluePreview();
        document.getElementById("home").scrollIntoView({ block: "start" });
      });
    });
  }

  function updateCharCount() {
    els.charCount.textContent = String(els.question.value.length);
  }

  async function fetchHealth() {
    try {
      const r = await fetch("/api/health");
      state.health = await r.json();
      renderHealth();
    } catch (err) {
      state.health = { ok:false, records:0, live_records:0, seed_records:0 };
      renderHealth();
    }
  }

  function renderHealth() {
    const h = state.health || {};
    const report = h.last_ingest_report || {};
    const apiText = h.api_key_configured ? t("apiConfigured") : t("apiNotConfigured");
    const deepseekText = h.deepseek_configured ? t("deepseekConfigured") : t("deepseekNotConfigured");
    const last = report.timestamp || "not yet";
    const stats = [
      [t("records"), h.records || 0],
      [t("liveRecords"), h.live_records || 0],
      [t("seedRecords"), h.seed_records || 0],
      [t("lastIngest"), last],
    ];
    els.knowledgeStats.innerHTML = stats.map(([label, value]) => `<div class="stat"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
    renderDataCatalog(h.catalog_summary || {});
    if (els.deepseekAssist) {
      els.deepseekAssist.disabled = !h.deepseek_configured;
      els.deepseekAssistWrap.classList.toggle("disabled", !h.deepseek_configured);
      if (!h.deepseek_configured) els.deepseekAssist.checked = false;
      els.deepseekAssistNote.textContent = `${t("deepseekAssistNote")} ${deepseekText}.`;
    }
    els.status.textContent = `${t("ready")} ${apiText}. ${deepseekText}.`;
  }

  function renderDataCatalog(summary) {
    if (!els.dataCatalog) return;
    const cards = [
      [t("datasetFamilies"), summary.datasets || []],
      [t("evidenceTypeCatalog"), summary.evidence_types || []],
      [t("publicUseCatalog"), summary.public_tags || []],
    ];
    els.dataCatalog.innerHTML = cards.map(([title, rows]) => `<article class="catalog-card">
      <strong>${escapeHtml(title)}</strong>
      <div class="catalog-list">
        ${(rows || []).slice(0, 8).map(row => `<div class="catalog-row"><span>${escapeHtml(row.label || row[0] || "")}</span><span>${escapeHtml(row.count ?? row[1] ?? 0)}</span></div>`).join("")}
      </div>
    </article>`).join("") + `<article class="catalog-card"><strong>${escapeHtml(t("dataVolumePlan"))}</strong><p class="muted">${escapeHtml(summary.total_records ? `${summary.total_records} records indexed for the local prototype.` : "")}</p></article>`;
  }

  async function askAgent() {
    const question = els.question.value.trim();
    if (question.length > 800) {
      els.status.textContent = t("questionTooLong");
      return;
    }
    if (!question) {
      els.status.textContent = state.lang === "zh" ? "请输入一个研究问题。" : "Please enter a research question.";
      return;
    }
    els.askBtn.disabled = true;
    els.status.textContent = state.lang === "zh" ? "正在检索证据并生成回答..." : "Retrieving evidence and generating answer...";
    try {
      const payload = {
        question,
        language: state.lang,
        mode: els.mode.value,
        output_style: els.style.value,
        top_k: Number(els.topK.value || 10),
        use_deepseek: Boolean(els.deepseekAssist && els.deepseekAssist.checked)
      };
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await r.json();
      if (!r.ok) {
        throw new Error(data.error || "Request failed");
      }
      state.lastAnswer = data;
      state.evidenceCache.clear();
      state.mutedEvidence = new Set();
      (data.evidence_cards || []).forEach(card => state.evidenceCache.set(card.record_id, card));
      renderAnswer(data);
      renderEvidenceBoard(data.evidence_cards || []);
      renderSecurity(data.audit);
      showResultsPage(data);
      els.status.textContent = state.lang === "zh" ? "已生成。" : "Generated.";
      await fetchHealth();
    } catch (err) {
      els.output.className = "output-empty";
      els.output.textContent = err.message || "Request failed";
      els.status.textContent = state.lang === "zh" ? "生成失败，请检查本地服务。" : "Generation failed. Please check the local service.";
    } finally {
      els.askBtn.disabled = false;
    }
  }

  function showResultsPage(data) {
    if (!els.resultsPage) return;
    els.resultsPage.hidden = false;
    document.body.classList.add("results-mode");
    renderResultCockpit(data);
    window.scrollTo({ top:0, behavior:"smooth" });
  }

  function returnToWorkbench() {
    document.body.classList.remove("results-mode");
    if (els.resultsPage) els.resultsPage.hidden = true;
    document.getElementById("home").scrollIntoView({ block:"start" });
    els.question.focus();
  }

  function renderResultCockpit(data) {
    if (!els.resultCockpit) return;
    const inv = data.investigation || {};
    const receipt = inv.receipt || {};
    const gates = inv.quality_gates || [];
    const passedGates = gates.filter(gate => gate.status === "pass").length;
    const sourceCount = receipt.sources_cited ?? (data.citations || []).length;
    const rows = [
      { label:t("resultQuestion"), value:data.question || "", primary:true },
      { label:t("resultRecordCount"), value:receipt.records_examined ?? (data.evidence_cards || []).length },
      { label:t("resultClaimCount"), value:receipt.claims_checked ?? (inv.claims || []).length },
      { label:t("resultSourceCount"), value:sourceCount },
      { label:t("resultTimelineCount"), value:(inv.timeline_events || []).length },
      { label:t("resultGateStatus"), value:`${passedGates}/${gates.length}` },
      { label:t("awardReadiness"), value:`${data.award_readiness?.overall_score ?? 0}/100` },
    ];
    els.resultCockpit.innerHTML = rows.map(row => `<div class="result-stat ${row.primary ? "primary-stat" : ""}">
      <span>${escapeHtml(row.label)}</span>
      <strong title="${escapeHtml(row.value)}">${escapeHtml(row.value)}</strong>
    </div>`).join("");
  }

  function renderAnswer(data) {
    const evidence = data.evidence_cards || data.citations || [];
    els.answerMeta.textContent = `${escapeHtml(data.mode_label || "")} | ${escapeHtml(data.output_style_label || data.output_style || "")} | ${escapeHtml(data.latency_ms ?? 0)} ms`;
    els.output.className = "";
    els.output.innerHTML = `
      ${renderAnswerToolbar(data)}
      ${renderDossierNav(data)}
      ${renderExecutiveSummary(data)}
      ${renderAwardReadiness(data)}
      ${renderProfessionalBriefing(data)}
      ${renderModeProfile(data)}
      ${renderStructuredSections(data)}
      ${renderResultGraphShell()}
      ${renderInvestigationDossier(data)}
      ${renderResearchProfile(data)}
      ${renderSourceTimeline(data)}
      ${renderTopicSignals(data)}
      ${renderDeepSeekAssist(data)}
      <div class="answer-block" id="evidenceInDossier">
        <h3>${escapeHtml(t("evidenceInDossier"))}</h3>
        <div class="evidence-list">${evidence.map(renderEvidenceCard).join("") || `<p class="muted">${escapeHtml(t("emptyOutput"))}</p>`}</div>
      </div>
      <div class="answer-block">
        <h3>${escapeHtml(t("future"))}</h3>
        <ol>${(data.future_questions || []).map(q => `<li>${escapeHtml(q)}</li>`).join("")}</ol>
      </div>
      ${renderNextSteps(data)}
      ${answerBlock(t("uncertainty"), data.uncertainty_note)}
    `;
    bindEvidenceClicks(els.output);
    bindAnswerActions(data);
    initResultGraph(data);
  }

  function renderInvestigationDossier(data) {
    const inv = data.investigation || {};
    if (!inv.finding) return "";
    return `
      <div class="answer-block" id="investigationModules">
        <h3>${escapeHtml(t("investigationTitle"))}: ${escapeHtml(inv.title || "")}</h3>
        <div class="dossier-grid">
          <div class="dossier-cell"><strong>${escapeHtml(t("entryType"))}</strong><p>${escapeHtml(inv.task?.entry || "")}</p></div>
          <div class="dossier-cell"><strong>${escapeHtml(t("taskGoal"))}</strong><p>${escapeHtml(inv.task?.goal || "")}</p></div>
        </div>
      </div>
      ${renderHistoricalTimeline(inv)}
      ${renderRelationshipNetwork(inv)}
      ${renderSpatialTraces(inv)}
      ${renderStoryResearchModes(inv)}
      ${renderQualityGates(inv)}
      ${renderFollowUpRoutes(inv)}
      ${renderEntityLinks(inv)}
      ${renderClaimLedger(inv)}
      ${renderCounterEvidence(inv)}
      ${renderEvidenceSandbox(data)}
      ${renderInvestigationReplay(inv)}
      ${renderDataReceipt(inv)}
    `;
  }

  function renderDossierNav(data) {
    return `<nav class="dossier-nav" aria-label="${escapeHtml(t("dossierNav"))}">
      <a href="#executiveSummary">${escapeHtml(t("executiveSummary"))}</a>
      <a href="#awardReadiness">${escapeHtml(t("awardReadiness"))}</a>
      <a href="#professionalBriefing">${escapeHtml(t("professionalBriefing"))}</a>
      <a href="#investigationModules">${escapeHtml(t("investigationTitle"))}</a>
      <a href="#resultGraph">${escapeHtml(t("resultGraphTitle"))}</a>
      <a href="#evidenceInDossier">${escapeHtml(t("evidenceInDossier"))}</a>
    </nav>`;
  }

  function renderExecutiveSummary(data) {
    const inv = data.investigation || {};
    const fit = data.evidence_fit || {};
    const receipt = inv.receipt || data.data_receipt || {};
    const audit = data.audit || {};
    const topEvidence = (data.evidence_cards || []).slice(0, 3).map(card => card.title).filter(Boolean);
    const actionItems = data.award_readiness?.action_items || [];
    return `<div class="answer-block" id="executiveSummary">
      <h3>${escapeHtml(t("executiveSummary"))}</h3>
      <div class="executive-grid">
        <article class="executive-card primary-card">
          <strong>${escapeHtml(t("oneLineFinding"))}</strong>
          <p>${escapeHtml(inv.finding || data.one_line_finding || "")}</p>
        </article>
        <article class="executive-card">
          <strong>${escapeHtml(t("evidenceFit"))}</strong>
          <p>${escapeHtml(fit.summary || "")}</p>
        </article>
        <article class="executive-card">
          <strong>${escapeHtml(t("dataReceipt"))}</strong>
          <p>${escapeHtml(receipt.summary || "")}</p>
        </article>
        <article class="executive-card">
          <strong>${escapeHtml(t("sourcePassport"))}</strong>
          <p>${escapeHtml((receipt.evidence_types || []).slice(0, 5).join(" / ") || "")}</p>
        </article>
        <article class="executive-card">
          <strong>${escapeHtml(t("submissionRisks"))}</strong>
          <p>${escapeHtml((audit.warnings || actionItems || []).slice(0, 2).join("；") || data.uncertainty_note || "")}</p>
        </article>
        <article class="executive-card">
          <strong>${escapeHtml(t("evidenceInDossier"))}</strong>
          <p>${escapeHtml(topEvidence.join("；") || "")}</p>
        </article>
      </div>
    </div>`;
  }

  function renderAwardReadiness(data) {
    const award = data.award_readiness || {};
    const items = award.items || [];
    if (!items.length) return "";
    return `<div class="answer-block" id="awardReadiness">
      <h3>${escapeHtml(t("awardReadiness"))}</h3>
      <p class="muted">${escapeHtml(award.summary || t("awardReadinessNote"))}</p>
      <div class="research-cockpit">
        <div class="signal-card">
          <strong><span>${escapeHtml(t("overallScore"))}</span><span class="signal-value">${escapeHtml(award.overall_score ?? 0)}/100</span></strong>
          <p>${escapeHtml(award.level_label || "")}</p>
          <div class="meter" aria-hidden="true"><span style="width:${Math.max(0, Math.min(100, Number(award.overall_score || 0)))}%"></span></div>
        </div>
        ${items.map(item => {
          const score = Math.max(0, Math.min(100, Number(item.score || 0)));
          return `<div class="signal-card">
            <strong><span>${escapeHtml(item.title || "")}</span><span class="signal-value">${score}</span></strong>
            <p>${escapeHtml(item.detail || item.status_label || "")}</p>
            <div class="meter" aria-hidden="true"><span style="width:${score}%"></span></div>
          </div>`;
        }).join("")}
      </div>
      ${(award.action_items || []).length ? `<h4 style="margin:14px 0 8px;">${escapeHtml(t("actionItems"))}</h4><ol>${award.action_items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ol>` : ""}
    </div>`;
  }

  function renderProfessionalBriefing(data) {
    const items = data.professional_briefing || [];
    if (!items.length) return "";
    return `<div class="answer-block" id="professionalBriefing">
      <h3>${escapeHtml(t("professionalBriefing"))}</h3>
      <div class="briefing-grid">
        ${items.map(item => `<article class="briefing-card">
          <strong>${escapeHtml(item.title || t(item.key) || "")}</strong>
          <p>${escapeHtml(item.body || "")}</p>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderHistoricalTimeline(inv) {
    const events = inv.timeline_events || [];
    if (!events.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("historicalTimeline"))}</h3>
      <div class="timeline">
        ${events.map(event => `<article class="timeline-item timeline-node" data-record-id="${escapeHtml((event.evidence_ids || [event.record_id || ""])[0] || "")}">
          <header>
            <h4>${escapeHtml(event.title || "")}</h4>
            <span class="timeline-date">${escapeHtml(event.date || "")}</span>
          </header>
          <p>${escapeHtml(event.body || "")}</p>
          <div class="tag-row">
            <span class="tag live">${escapeHtml(event.support_label || "")}</span>
            <span class="tag">${escapeHtml(t("claimConfidence"))}: ${escapeHtml(Math.round(Number(event.confidence || 0) * 100))}%</span>
            ${(event.people || []).slice(0, 3).map(item => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
            ${(event.places || []).slice(0, 3).map(item => `<span class="tag seed">${escapeHtml(item)}</span>`).join("")}
          </div>
          ${event.open_url ? `<a href="${escapeHtml(event.open_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("openEvidenceNode"))}</a>` : ""}
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderRelationshipNetwork(inv) {
    const network = inv.relationship_network || {};
    const links = network.links || [];
    if (!links.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("relationshipNetwork"))}</h3>
      <p class="muted">${escapeHtml(network.summary || "")}</p>
      <div class="network-list">
        ${links.slice(0, 8).map(link => `<article class="network-edge" data-record-id="${escapeHtml(link.record_id || "")}">
          <strong>${escapeHtml(link.relation || "")}</strong>
          <p>${escapeHtml(link.evidence_title || "")}</p>
          <div class="tag-row">
            <span class="tag">${escapeHtml(link.source_label || link.source || "")}</span>
            <span class="tag live">${escapeHtml(link.target_label || link.target || "")}</span>
          </div>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderSpatialTraces(inv) {
    const traces = inv.spatial_traces || [];
    if (!traces.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("spatialTrace"))}</h3>
      <div class="spatial-grid">
        ${traces.slice(0, 6).map(trace => `<article class="spatial-card" data-record-id="${escapeHtml((trace.evidence_ids || [])[0] || "")}">
          <strong>${escapeHtml(trace.place || "")}</strong>
          <p>${escapeHtml(t("coordinatesStatus"))}: ${escapeHtml(trace.coordinates_status || "")}</p>
          <p class="muted" style="margin-top:6px;">${escapeHtml(t("modernPositionNote"))}: ${escapeHtml(trace.modern_position_note || "")}</p>
          <div class="tag-row">
            ${(trace.related_people || []).slice(0, 4).map(item => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
            ${(trace.related_topics || []).slice(0, 4).map(item => `<span class="tag live">${escapeHtml(item)}</span>`).join("")}
          </div>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderStoryResearchModes(inv) {
    const story = inv.story_mode || {};
    const research = inv.research_mode || {};
    if (!story.public_narrative && !research.method) return "";
    return `<div class="answer-block">
      <div class="mode-pair">
        <article class="mode-card">
          <strong>${escapeHtml(t("storyMode"))}</strong>
          <p>${escapeHtml(story.public_narrative || "")}</p>
          <p class="muted" style="margin-top:8px;">${escapeHtml(story.narrative_boundary || "")}</p>
        </article>
        <article class="mode-card">
          <strong>${escapeHtml(t("researchMode"))}</strong>
          <p>${escapeHtml(research.method || "")}</p>
          <p class="muted" style="margin-top:8px;"><b>${escapeHtml(t("citationProtocol"))}</b>: ${escapeHtml(research.citation_protocol || "")}</p>
        </article>
      </div>
    </div>`;
  }

  function renderQualityGates(inv) {
    const gates = inv.quality_gates || [];
    if (!gates.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("qualityGates"))}</h3>
      <div class="quality-grid">
        ${gates.map(gate => `<article class="quality-gate ${escapeHtml(gate.status || "review")}">
          <strong>${escapeHtml(gate.title || "")} · ${escapeHtml(gate.status_label || gate.status || "")}</strong>
          <p>${escapeHtml(gate.detail || "")}</p>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderFollowUpRoutes(inv) {
    const routes = inv.follow_up_routes || [];
    if (!routes.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("followUpRoutes"))}</h3>
      <div class="follow-grid">
        ${routes.map(route => `<article class="follow-route">
          <strong>${escapeHtml(route.title || "")}</strong>
          <p>${escapeHtml(route.question || "")}</p>
          <p class="muted" style="margin-top:7px;">${escapeHtml(route.purpose || "")}</p>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderEntityLinks(inv) {
    const entities = inv.entities || [];
    if (!entities.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("entitiesLinked"))}</h3>
      <div class="entity-list">
        ${entities.slice(0, 16).map(entity => `<span class="entity-chip">
          ${escapeHtml(entity.label || "")}
          <span>${escapeHtml(entity.type_label || entity.type || "")} · ${escapeHtml(entity.evidence_count || 0)}</span>
        </span>`).join("")}
      </div>
    </div>`;
  }

  function renderClaimLedger(inv) {
    const claims = inv.claims || [];
    if (!claims.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("claimLedger"))}</h3>
      <div class="claim-grid">
        ${claims.map(claim => {
          const evidenceIds = claim.evidence_ids || [];
          const muted = isClaimMuted(evidenceIds);
          const terms = (claim.terms || []).slice(0, 5).map(term => `<span class="tag">${escapeHtml(term)}</span>`).join("");
          const titles = (claim.evidence_titles || []).slice(0, 3).map(title => `<span class="tag live">${escapeHtml(title)}</span>`).join("");
          return `<article class="claim-card ${escapeHtml(claim.status || "review")} ${muted ? "disabled" : ""}" data-claim-id="${escapeHtml(claim.id || "")}">
            <strong>${escapeHtml(claim.type_label || "")}: ${escapeHtml(claim.support_label || "")}</strong>
            <p>${escapeHtml(claim.text || "")}</p>
            <div class="claim-meta">
              <span class="tag">${escapeHtml(t("claimConfidence"))}: ${escapeHtml(Math.round(Number(claim.confidence || 0) * 100))}%</span>
              <span class="tag">${escapeHtml(t("claimStatus"))}: ${escapeHtml(claim.status || "")}</span>
              ${terms}
              ${titles}
            </div>
            <p class="muted" style="margin-top:7px;">${escapeHtml(claim.audit_note || "")}</p>
          </article>`;
        }).join("")}
      </div>
    </div>`;
  }

  function isClaimMuted(evidenceIds) {
    if (!evidenceIds || !evidenceIds.length) return false;
    return evidenceIds.every(id => state.mutedEvidence.has(id));
  }

  function renderCounterEvidence(inv) {
    const items = inv.counter_evidence || [];
    if (!items.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("counterEvidence"))}</h3>
      <div class="counter-grid">
        ${items.map(item => `<article class="counter-item ${escapeHtml(item.severity || "")}">
          <strong>${escapeHtml(item.title || "")} · ${escapeHtml(item.severity_label || "")}</strong>
          <p>${escapeHtml(item.body || "")}</p>
          <div class="tag-row">
            ${(item.terms || []).slice(0, 5).map(term => `<span class="tag">${escapeHtml(term)}</span>`).join("")}
            ${(item.evidence_ids || []).slice(0, 4).map(id => `<span class="tag seed">${escapeHtml(id)}</span>`).join("")}
          </div>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderEvidenceSandbox(data) {
    const evidence = data.evidence_cards || [];
    if (!evidence.length) return "";
    const activeCount = evidence.filter(card => !state.mutedEvidence.has(card.record_id)).length;
    return `<div class="answer-block">
      <h3>${escapeHtml(t("evidenceSandbox"))}</h3>
      <p class="muted">${escapeHtml(t("activeEvidence"))}: ${activeCount}/${evidence.length}</p>
      <div class="sandbox-row">
        ${evidence.map((card, idx) => {
          const active = !state.mutedEvidence.has(card.record_id);
          return `<button class="mini-toggle ${active ? "active" : ""}" type="button" data-toggle-evidence="${escapeHtml(card.record_id)}">
            ${escapeHtml(t("toggleEvidence"))} ${idx + 1}
          </button>`;
        }).join("")}
      </div>
    </div>`;
  }

  function renderInvestigationReplay(inv) {
    const replay = inv.replay || [];
    if (!replay.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("investigationReplay"))}</h3>
      <div class="replay-list">
        ${replay.map(step => `<article class="replay-step">
          <div class="index">${escapeHtml(step.index || "")}</div>
          <div>
            <strong>${escapeHtml(step.title || "")} · ${escapeHtml(step.tool || "")}</strong>
            <p>${escapeHtml(step.detail || "")}</p>
            <div class="tag-row">${(step.artifacts || []).slice(0, 5).map(item => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>
          </div>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderDataReceipt(inv) {
    const receipt = inv.receipt || {};
    if (!Object.keys(receipt).length) return "";
    const rows = [
      [t("recordsExamined"), receipt.records_examined ?? 0],
      [t("entitiesLinked"), receipt.entities_linked ?? 0],
      [t("claimsChecked"), receipt.claims_checked ?? 0],
      [t("sourcesCited"), receipt.sources_cited ?? 0],
      [t("conflictsDetected"), receipt.conflicts_detected ?? 0],
      [t("livePercentage"), `${receipt.live_percentage ?? 0}%`],
    ];
    return `<div class="answer-block">
      <h3>${escapeHtml(t("dataReceipt"))}</h3>
      <p class="muted">${escapeHtml(receipt.summary || "")}</p>
      <div class="dossier-grid">
        ${rows.map(([label, value]) => `<div class="dossier-cell"><strong>${escapeHtml(label)}</strong><p>${escapeHtml(value)}</p></div>`).join("")}
      </div>
      <div class="tag-row">
        ${(receipt.datasets_queried || []).map(dataset => `<span class="tag live">${escapeHtml(dataset)}</span>`).join("")}
        ${(receipt.evidence_types || []).map(kind => `<span class="tag">${escapeHtml(t("evidenceTypes"))}: ${escapeHtml(kind)}</span>`).join("")}
        ${(receipt.public_tags || []).map(tag => `<span class="tag seed">${escapeHtml(t("publicUseTags"))}: ${escapeHtml(tag)}</span>`).join("")}
      </div>
    </div>`;
  }

  function answerBlock(title, body) {
    return `<div class="answer-block"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p></div>`;
  }

  function renderStructuredSections(data) {
    const sections = data.answer_sections || [];
    if (sections.length) {
      return sections.map(item => answerBlock(item.title || "", item.body || "")).join("");
    }
    return [
      answerBlock(t("problem"), data.problem_summary),
      answerBlock(t("fact"), data.historical_fact),
      answerBlock(t("interpretation"), data.interpretation),
      answerBlock(t("analogy"), data.modern_analogy),
      answerBlock(t("mechanism"), data.mechanism_comparison)
    ].join("");
  }

  function renderModeProfile(data) {
    const profile = data.mode_profile || {};
    const analysis = data.question_analysis || {};
    const fit = data.evidence_fit || {};
    if (!profile.scope && !profile.lens) return "";
    const terms = (profile.focus_terms || []).slice(0, 8).map(term => `<span class="tag">${escapeHtml(term)}</span>`).join("");
    const detected = (analysis.terms || []).slice(0, 8).map(term => `<span class="tag live">${escapeHtml(term)}</span>`).join("");
    return `<div class="answer-block">
      <h3>${escapeHtml(t("modeBriefTitle"))}: ${escapeHtml(profile.label || data.mode_label || "")}</h3>
      <p>${escapeHtml(profile.fit || profile.scope || "")}</p>
      <div class="mode-brief-grid">
        <div><b>${escapeHtml(t("researchLens"))}</b><p>${escapeHtml(profile.lens || "")}</p></div>
        <div><b>${escapeHtml(t("questionIntent"))}</b><p>${escapeHtml(analysis.intent_label || "")}</p></div>
        <div><b>${escapeHtml(t("evidenceFit"))}</b><p>${escapeHtml(fit.summary || "")}</p></div>
        <div><b>${escapeHtml(t("detectedTerms"))}</b><div class="tag-row" style="margin-bottom:0;">${detected}</div></div>
        <div><b>${escapeHtml(t("retrievalTerms"))}</b><div class="tag-row" style="margin-bottom:0;">${terms}</div></div>
      </div>
    </div>`;
  }

  function renderDeepSeekAssist(data) {
    const assist = data.deepseek_assist || {};
    if (assist.status === "ok" && assist.content) {
      return `<div class="answer-block">
        <h3>${escapeHtml(t("deepseekResult"))}</h3>
        <div class="deepseek-block">${escapeHtml(assist.content)}</div>
      </div>`;
    }
    if (assist.enabled && assist.status === "error") {
      return `<div class="answer-block"><div class="warning">${escapeHtml(t("deepseekError"))}</div></div>`;
    }
    return "";
  }

  function renderAnswerToolbar(data) {
    return `<div class="answer-toolbar">
      <div>
        <strong>${escapeHtml(t("exports"))}</strong>
        <span>${escapeHtml(data.generated_at || "")}</span>
      </div>
      <div class="toolbar-actions">
        <button class="ghost" id="copyBriefBtn" type="button">${escapeHtml(t("copyBrief"))}</button>
        <button class="primary" id="downloadJsonBtn" type="button">${escapeHtml(t("downloadJson"))}</button>
      </div>
    </div>`;
  }

  function renderResearchProfile(data) {
    const profile = data.research_profile || [];
    if (!profile.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("researchSignals"))}</h3>
      <p class="muted">${escapeHtml(t("researchSignalsNote"))}</p>
      <div class="research-cockpit">
        ${profile.map(item => {
          const score = Math.max(0, Math.min(100, Number(item.score || 0)));
          return `<div class="signal-card">
            <strong><span>${escapeHtml(t(item.key))}</span><span class="signal-value">${escapeHtml(item.value)}</span></strong>
            <p>${escapeHtml(t(item.detail_key))}</p>
            <div class="meter" aria-hidden="true"><span style="width:${score}%"></span></div>
          </div>`;
        }).join("")}
      </div>
    </div>`;
  }

  function renderTopicSignals(data) {
    const signals = data.topic_signals || [];
    if (!signals.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("topicSignals"))}</h3>
      <div class="topic-cloud">
        ${signals.map(signal => {
          const size = 12 + Math.min(8, Math.max(0, Number(signal.intensity || 0) - 30) / 10);
          return `<button class="topic-signal" type="button" data-topic-signal="${escapeHtml(signal.term)}" style="font-size:${size}px">${escapeHtml(signal.term)}</button>`;
        }).join("")}
      </div>
    </div>`;
  }

  function renderSourceTimeline(data) {
    const timeline = data.source_timeline || [];
    if (!timeline.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("sourceTimeline"))}</h3>
      <div class="timeline">
        ${timeline.map(item => `<article class="timeline-item">
          <header>
            <h4>${escapeHtml(item.title)}</h4>
            <span class="timeline-date">${escapeHtml(item.date || "undated")}</span>
          </header>
          <p>${escapeHtml(item.snippet || "")}</p>
          <div class="tag-row">
            ${item.evidence_type ? `<span class="tag live">${escapeHtml(item.evidence_type)}</span>` : ""}
            ${(item.public_tags || []).slice(0, 3).map(tag => `<span class="tag seed">${escapeHtml(tag)}</span>`).join("")}
            ${(item.topics || []).slice(0, 4).map(topic => `<span class="tag">${escapeHtml(topic)}</span>`).join("")}
          </div>
          <a href="${escapeHtml(item.open_url || "https://www.library.sh.cn/")}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("openTimelineSource"))}</a>
        </article>`).join("")}
      </div>
    </div>`;
  }

  function renderNextSteps(data) {
    const steps = data.next_steps || [];
    if (!steps.length) return "";
    return `<div class="answer-block">
      <h3>${escapeHtml(t("researchNextSteps"))}</h3>
      <div class="next-step-grid">
        ${steps.map(step => `<div class="next-step"><strong>${escapeHtml(step.title)}</strong><p>${escapeHtml(step.body)}</p></div>`).join("")}
      </div>
    </div>`;
  }

  function bindAnswerActions(data) {
    const copyBtn = document.getElementById("copyBriefBtn");
    const downloadBtn = document.getElementById("downloadJsonBtn");
    copyBtn && copyBtn.addEventListener("click", () => copyMarkdownBrief(data));
    downloadBtn && downloadBtn.addEventListener("click", () => downloadAnswerJson(data));
    els.output.querySelectorAll("[data-topic-signal]").forEach(button => {
      button.addEventListener("click", () => {
        const term = button.getAttribute("data-topic-signal") || "";
        const current = els.question.value.trim();
        if (term && !current.includes(term)) {
          els.question.value = `${current} ${term}`.trim();
          updateCharCount();
          els.status.textContent = state.lang === "zh" ? `已把「${term}」加入研究问题。` : `Added "${term}" to the research question.`;
        }
      });
    });
    els.output.querySelectorAll("[data-toggle-evidence]").forEach(button => {
      button.addEventListener("click", () => {
        const id = button.getAttribute("data-toggle-evidence");
        if (!id || !state.lastAnswer) return;
        if (state.mutedEvidence.has(id)) {
          state.mutedEvidence.delete(id);
        } else {
          state.mutedEvidence.add(id);
        }
        renderAnswer(state.lastAnswer);
      });
    });
  }

  async function copyMarkdownBrief(data) {
    try {
      await navigator.clipboard.writeText(formatMarkdownBrief(data));
      els.status.textContent = t("briefCopied");
    } catch (err) {
      els.status.textContent = t("copyFailed");
    }
  }

  function downloadAnswerJson(data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type:"application/json" });
    const a = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    a.href = URL.createObjectURL(blob);
    a.download = `contextlens-dossier-${stamp}.json`;
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(a.href);
    a.remove();
    els.status.textContent = t("jsonDownloaded");
  }

  function formatMarkdownBrief(data) {
    const evidence = data.evidence_cards || data.citations || [];
    const sections = data.answer_sections || [];
    const inv = data.investigation || {};
    const lines = [
      `# ContextLens Historical Investigation Brief`,
      ``,
      `**Clue:** ${data.question || ""}`,
      `**Task:** ${data.mode_label || data.mode || ""}`,
      `**Output Style:** ${data.output_style_label || data.output_style || ""}`,
      `**Generated:** ${data.generated_at || ""}`,
      ``,
      ...(data.award_readiness
        ? [
            `## ${t("awardReadiness")}`,
            `${data.award_readiness.summary || ""}`,
            ...(data.award_readiness.items || []).map(item => `- ${item.title || ""}: ${item.score || 0}/100 (${item.status_label || ""})`),
            ``,
          ]
        : []),
      ...(inv.finding
        ? [
            `## ${t("oneLineFinding")}`,
            inv.finding,
            ``,
            `## ${t("historicalTimeline")}`,
            ...(inv.timeline_events || []).map((event, idx) => `${idx + 1}. ${event.date || ""} - ${event.title || ""} (${event.support_label || ""})`),
            ``,
            `## ${t("relationshipNetwork")}`,
            inv.relationship_network?.summary || "",
            ...(inv.relationship_network?.links || []).slice(0, 8).map((link, idx) => `${idx + 1}. ${link.source_label || link.source || ""} -> ${link.target_label || link.target || ""}: ${link.relation || ""}`),
            ``,
            `## ${t("spatialTrace")}`,
            ...(inv.spatial_traces || []).slice(0, 6).map((trace, idx) => `${idx + 1}. ${trace.place || ""} - ${trace.coordinates_status || ""}`),
            ``,
            `## ${t("storyMode")}`,
            inv.story_mode?.public_narrative || "",
            ``,
            `## ${t("qualityGates")}`,
            ...(inv.quality_gates || []).map(gate => `- [${gate.status_label || gate.status || ""}] ${gate.title || ""}: ${gate.detail || ""}`),
            ``,
            `## ${t("followUpRoutes")}`,
            ...(inv.follow_up_routes || []).map((route, idx) => `${idx + 1}. ${route.question || ""}`),
            ``,
            `## ${t("dataReceipt")}`,
            inv.receipt?.summary || "",
            ``,
            `## ${t("claimLedger")}`,
            ...(inv.claims || []).map((claim, idx) => `${idx + 1}. [${claim.support_label || ""}/${claim.status || ""}] ${claim.text || ""}`),
            ``,
          ]
        : []),
      ...(sections.length
        ? sections.flatMap(item => [`## ${item.title || ""}`, item.body || "", ``])
        : [
            `## ${t("problem")}`,
            data.problem_summary || "",
            ``,
            `## ${t("fact")}`,
            data.historical_fact || "",
            ``,
            `## ${t("interpretation")}`,
            data.interpretation || "",
            ``,
            `## ${t("analogy")}`,
            data.modern_analogy || "",
            ``,
            `## ${t("mechanism")}`,
            data.mechanism_comparison || "",
            ``,
          ]),
      ...(data.deepseek_assist?.status === "ok" && data.deepseek_assist?.content
        ? [`## ${t("deepseekResult")}`, data.deepseek_assist.content, ``]
        : []),
      `## ${t("evidence")}`,
      ...evidence.map((card, idx) => `${idx + 1}. ${card.title || "Untitled"} [${card.evidence_type || card.dataset || ""}] - ${card.open_url || card.uri || ""}`),
      ``,
      `## ${t("uncertainty")}`,
      data.uncertainty_note || "",
    ];
    return lines.join("\\n");
  }

  function renderResultGraphShell() {
    return `<div class="answer-block">
      <h3>${escapeHtml(t("resultGraphTitle"))}</h3>
      <p class="muted" style="margin-bottom:10px;">${escapeHtml(t("resultGraphNote"))}</p>
      <div class="result-graph" id="resultGraph">
        <canvas id="resultGraphCanvas" aria-label="${escapeHtml(t("resultGraphTitle"))}"></canvas>
        <div class="result-graph-link-layer" id="resultGraphLinks"></div>
        <div class="result-graph-hint">${escapeHtml(t("resultGraphNote"))}</div>
      </div>
    </div>`;
  }

  function initResultGraph(data) {
    const canvas = document.getElementById("resultGraphCanvas");
    const layer = document.getElementById("resultGraphLinks");
    const host = document.getElementById("resultGraph");
    if (!canvas || !layer || !host) return;
    const graph = {
      canvas,
      layer,
      host,
      ctx: canvas.getContext("2d"),
      dpr: Math.min(window.devicePixelRatio || 1, 2),
      width: 0,
      height: 0,
      rotX: .24,
      rotY: -.34,
      zoom: 9.4,
      dragging: false,
      moved: false,
      lastX: 0,
      lastY: 0,
      nodes: buildResultGraphNodes(data),
      links: [],
      anchors: new Map(),
      frame: 0,
      stopped: false
    };
    graph.links = buildResultGraphLinks(data, graph.nodes);
    const previous = state.resultGraph;
    if (previous) {
      previous.stopped = true;
      previous.frame && cancelAnimationFrame(previous.frame);
      previous.resize && window.removeEventListener("resize", previous.resize);
    }
    state.resultGraph = graph;
    graph.nodes.forEach(node => {
      const a = document.createElement("a");
      a.href = node.href;
      a.className = `result-node-link ${node.kind === "evidence" ? "evidence-link" : ""}`;
      a.textContent = node.label;
      a.title = `${node.label} - ${node.kind === "evidence" ? t("resultGraphOpen") : t("resultGraphSource")}`;
      if (node.external) {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      }
      a.addEventListener("pointerdown", event => event.stopPropagation());
      graph.layer.appendChild(a);
      graph.anchors.set(node.id, a);
    });
    const resize = () => resizeResultGraph(graph);
    graph.resize = resize;
    resize();
    window.addEventListener("resize", resize);
    canvas.addEventListener("pointerdown", event => onResultGraphPointerDown(event, graph));
    canvas.addEventListener("pointermove", event => onResultGraphPointerMove(event, graph));
    canvas.addEventListener("pointerup", () => onResultGraphPointerUp(graph));
    canvas.addEventListener("pointerleave", () => onResultGraphPointerUp(graph));
    canvas.addEventListener("wheel", event => onResultGraphWheel(event, graph), { passive:false });
    animateResultGraph(graph);
  }

  function buildResultGraphNodes(data) {
    const investigationNodes = data.investigation?.graph?.nodes || [];
    if (investigationNodes.length) {
      const groups = new Map();
      investigationNodes.slice(0, 24).forEach(node => {
        const type = node.type || "concept";
        if (!groups.has(type)) groups.set(type, []);
        groups.get(type).push(node);
      });
      const order = ["clue", "dossier", "person", "place", "organization", "event", "document", "concept", "source", "claim"];
      const output = [];
      order.forEach((type, groupIndex) => {
        const group = groups.get(type) || [];
        group.forEach((node, idx) => {
          const ring = type === "clue" || type === "dossier" ? .35 : type === "source" ? 3.25 : type === "claim" ? 2.7 : 2.1;
          const offset = order.indexOf(type) * .47;
          const angle = (Math.PI * 2 * (idx / Math.max(1, group.length))) + offset;
          const yBand = type === "claim" ? -1.35 : type === "source" ? 1.25 : type === "dossier" ? .34 : type === "clue" ? -.28 : ((groupIndex % 3) - 1) * .58;
          output.push({
            id:node.id,
            recordId:node.record_id,
            label:shortNodeLabel(node.label || node.id),
            kind:type === "source" ? "evidence" : type,
            icon:iconForGraphType(type, node),
            href:node.href || (type === "source" && node.record_id ? `/source/${encodeURIComponent(node.record_id)}` : "#dossier"),
            external:Boolean(node.href || type === "source"),
            color:colorForGraphType(type, node),
            pos:type === "clue" ? [0, -.35, 0] : type === "dossier" ? [0, .8, .25] : [Math.cos(angle) * ring, yBand, Math.sin(angle) * 1.35],
            size:Math.max(.72, Math.min(1.28, Number(node.weight || .8))),
            score:node.weight
          });
        });
      });
      return output;
    }
    const evidence = (data.evidence_cards || []).slice(0, 6);
    const nodes = [
      {
        id:"question",
        label:t("resultGraphQuestion"),
        kind:"core",
        icon:"question",
        href:"#home",
        external:false,
        color:"#f5d28e",
        pos:[0, 0, 0],
        size:1.38
      },
      {
        id:"mode",
        label:data.mode_label || t("resultGraphMode"),
        kind:"mode",
        icon:"compass",
        href:"#home",
        external:false,
        color:"#7dd3fc",
        pos:[-2.6, 1.35, -.55],
        size:.92
      },
      {
        id:"answer",
        label:t("resultGraphAnswer"),
        kind:"answer",
        icon:"report",
        href:"#dossier",
        external:false,
        color:"#b7d97a",
        pos:[2.8, .72, .5],
        size:1
      },
      {
        id:"audit",
        label:t("resultGraphAudit"),
        kind:"audit",
        icon:"shield",
        href:"#security",
        external:false,
        color:"#f28c8c",
        pos:[2.35, -1.55, -.45],
        size:.92
      }
    ];
    const radius = 3.25;
    evidence.forEach((card, idx) => {
      const angle = -Math.PI * .82 + (Math.PI * 1.64) * (idx / Math.max(1, evidence.length - 1));
      const z = idx % 2 === 0 ? .92 : -.9;
      nodes.push({
        id:`evidence-${idx}`,
        recordId:card.record_id,
        label:shortNodeLabel(card.title || `${t("resultGraphSource")} ${idx + 1}`),
        kind:"evidence",
        icon:card.live_api ? "book" : "cards",
        href:card.open_url || card.uri || "https://www.library.sh.cn/",
        external:true,
        color:card.live_api ? "#7dd3fc" : "#f5d28e",
        pos:[Math.cos(angle) * radius, Math.sin(angle) * 1.85, z],
        size:.82,
        score:card.score
      });
    });
    return nodes;
  }

  function iconForGraphType(type, node) {
    if (type === "clue") return "question";
    if (type === "dossier") return "report";
    if (type === "person") return "record";
    if (type === "place") return "compass";
    if (type === "source") return node.live_api ? "book" : "cards";
    if (type === "claim") return "shield";
    if (type === "document") return "book";
    return "cards";
  }

  function colorForGraphType(type, node) {
    const colors = {
      clue:"#f5d28e",
      dossier:"#b7d97a",
      person:"#7dd3fc",
      place:"#14a58f",
      organization:"#d7a943",
      event:"#f28c8c",
      document:"#56a3d9",
      concept:"#c4b5fd",
      source:node.live_api ? "#7dd3fc" : "#f5d28e",
      claim:"#f28c8c"
    };
    return colors[type] || "#7dd3fc";
  }

  function buildResultGraphLinks(data, nodes) {
    const graphLinks = data.investigation?.graph?.links || [];
    if (graphLinks.length) {
      const nodeIds = new Set(nodes.map(node => node.id));
      return graphLinks
        .filter(link => nodeIds.has(link.source) && nodeIds.has(link.target))
        .map(link => [link.source, link.target]);
    }
    const links = [];
    for (const node of nodes) {
      if (node.id !== "question") links.push(["question", node.id]);
      if (node.kind === "evidence") {
        links.push([node.id, "answer"]);
        links.push([node.id, "audit"]);
      }
    }
    return links;
  }

  function shortNodeLabel(value) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length > 18 ? `${text.slice(0, 17)}…` : text;
  }

  function resizeResultGraph(graph) {
    const rect = graph.host.getBoundingClientRect();
    graph.width = Math.max(300, Math.floor(rect.width));
    graph.height = Math.max(320, Math.floor(rect.height));
    graph.canvas.width = Math.floor(graph.width * graph.dpr);
    graph.canvas.height = Math.floor(graph.height * graph.dpr);
    graph.canvas.style.width = `${graph.width}px`;
    graph.canvas.style.height = `${graph.height}px`;
    graph.ctx.setTransform(graph.dpr, 0, 0, graph.dpr, 0, 0);
  }

  function animateResultGraph(graph) {
    if (graph.stopped) return;
    graph.frame = requestAnimationFrame(() => animateResultGraph(graph));
    if (!graph.dragging) graph.rotY += .0028;
    drawResultGraph(graph);
  }

  function drawResultGraph(graph) {
    const ctx = graph.ctx;
    ctx.clearRect(0, 0, graph.width, graph.height);
    const bg = ctx.createLinearGradient(0, 0, graph.width, graph.height);
    bg.addColorStop(0, "#07192d");
    bg.addColorStop(.55, "#0d2948");
    bg.addColorStop(1, "#113f43");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, graph.width, graph.height);
    const projected = graph.nodes.map(node => ({ node, ...projectResultPoint(graph, node.pos) }));
    const byId = new Map(projected.map(point => [point.node.id, point]));
    graph.links.forEach(([from, to]) => {
      const a = byId.get(from);
      const b = byId.get(to);
      if (a && b) drawResultLink(ctx, a, b);
    });
    projected.sort((a, b) => a.z - b.z).forEach(point => drawResultNode(ctx, point));
    projected.forEach(point => positionResultAnchor(graph, point));
  }

  function projectResultPoint(graph, position) {
    const [x0, y0, z0] = position;
    const cx = Math.cos(graph.rotX);
    const sx = Math.sin(graph.rotX);
    const cy = Math.cos(graph.rotY);
    const sy = Math.sin(graph.rotY);
    const x1 = x0 * cy - z0 * sy;
    const z1 = x0 * sy + z0 * cy;
    const y1 = y0 * cx - z1 * sx;
    const z2 = y0 * sx + z1 * cx;
    const perspective = graph.zoom / (graph.zoom + z2);
    const scale = Math.min(graph.width, graph.height) * .14 * perspective;
    return {
      x: graph.width / 2 + x1 * scale,
      y: graph.height / 2 + y1 * scale,
      z: z2,
      depth: perspective,
      radius: Math.max(14, 20 * perspective)
    };
  }

  function drawResultLink(ctx, a, b) {
    ctx.strokeStyle = "rgba(125, 211, 252, .42)";
    ctx.lineWidth = Math.max(1.4, (a.depth + b.depth) * 1.45);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  function drawResultNode(ctx, point) {
    const radius = point.radius * point.node.size;
    const color = point.node.color;
    ctx.save();
    ctx.globalAlpha = Math.max(.68, Math.min(1, point.depth));
    drawIconNode(ctx, {
      x:point.x,
      y:point.y,
      radius,
      color,
      icon:point.node.icon,
      active:point.node.kind === "core" || point.node.kind === "answer"
    });
    ctx.restore();
  }

  function positionResultAnchor(graph, point) {
    const anchor = graph.anchors.get(point.node.id);
    if (!anchor) return;
    anchor.style.left = `${point.x}px`;
    anchor.style.top = `${point.y + point.radius * point.node.size + 34}px`;
    anchor.style.opacity = String(Math.max(.72, Math.min(1, point.depth)));
    anchor.style.zIndex = String(Math.round(point.depth * 100));
  }

  function onResultGraphPointerDown(event, graph) {
    graph.dragging = true;
    graph.moved = false;
    graph.lastX = event.clientX;
    graph.lastY = event.clientY;
    graph.canvas.setPointerCapture && graph.canvas.setPointerCapture(event.pointerId);
  }

  function onResultGraphPointerMove(event, graph) {
    if (!graph.dragging) return;
    const dx = event.clientX - graph.lastX;
    const dy = event.clientY - graph.lastY;
    if (Math.abs(dx) + Math.abs(dy) > 3) graph.moved = true;
    graph.rotY += dx * .008;
    graph.rotX += dy * .005;
    graph.rotX = Math.max(-.72, Math.min(.72, graph.rotX));
    graph.lastX = event.clientX;
    graph.lastY = event.clientY;
  }

  function onResultGraphPointerUp(graph) {
    graph.dragging = false;
  }

  function onResultGraphWheel(event, graph) {
    event.preventDefault();
    graph.zoom += event.deltaY * .004;
    graph.zoom = Math.max(6.8, Math.min(13.5, graph.zoom));
  }

  function renderEvidenceCard(card, idx) {
    const title = card.title || "Untitled";
    const matched = (card.matched_terms || []).slice(0, 4).map(term => `<span class="tag">${escapeHtml(term)}</span>`).join("");
    const direct = (card.direct_terms || []).slice(0, 4).map(term => `<span class="tag live">${escapeHtml(term)}</span>`).join("");
    const publicTags = (card.public_tags || []).slice(0, 3).map(term => `<span class="tag seed">${escapeHtml(term)}</span>`).join("");
    return `<button class="evidence-card" type="button" data-record-id="${escapeHtml(card.record_id)}">
      <h4>${escapeHtml(title)}</h4>
      <div class="tag-row">
        <span class="tag">${escapeHtml(card.dataset || "")}</span>
        <span class="tag">${escapeHtml(t("evidenceType"))}: ${escapeHtml(card.evidence_type || "")}</span>
        <span class="tag ${card.live_api ? "live" : "seed"}">${card.live_api ? "live API" : "demo seed"}</span>
        <span class="tag">${escapeHtml(t("score"))}: ${escapeHtml(card.score || 0)}</span>
        <span class="tag">${escapeHtml(t("supportStrength"))}: ${escapeHtml(card.support_strength || "")}</span>
        ${matched}
        ${direct}
        ${publicTags}
      </div>
      <p class="muted">${escapeHtml(card.fit_reason || card.relevance || card.uri || "")}</p>
    </button>`;
  }

  function renderEvidenceBoard(evidence) {
    els.evidenceBoard.innerHTML = evidence.length
      ? evidence.map(renderEvidenceCard).join("")
      : `<div class="surface muted">${escapeHtml(t("clickEvidence"))}</div>`;
    bindEvidenceClicks(els.evidenceBoard);
  }

  function bindEvidenceClicks(root) {
    root.querySelectorAll("[data-record-id]").forEach(node => {
      node.addEventListener("click", () => openEvidence(node.getAttribute("data-record-id")));
    });
  }

  function renderSecurity(audit) {
    const a = audit || {};
    const stats = [
      [t("citationCheck"), a.citation_check || "waiting"],
      [t("evidenceCount"), a.evidence_count ?? 0],
      [t("liveRecords"), a.live_records ?? 0],
      [t("seedRecords"), a.seed_records ?? 0],
      [t("financeBoundary"), a.financial_advice_check || "waiting"],
      [t("uncertainty"), a.uncertainty_level || "waiting"],
      [t("latency"), `${a.latency_ms ?? 0} ms`],
      ["Failure mode", a.failure_mode || "none"],
    ];
    els.securityStats.innerHTML = stats.map(([label, value]) => `<div class="stat"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
    const warnings = a.warnings || [];
    els.warnings.innerHTML = warnings.length
      ? warnings.map(w => `<div class="warning">${escapeHtml(w)}</div>`).join("")
      : `<div class="audit-pill"><span>${escapeHtml(t("warnings"))}</span><strong>${escapeHtml(t("noWarnings"))}</strong></div>`;
  }

  async function openEvidence(recordId) {
    if (!recordId) return;
    const cached = state.evidenceCache.get(recordId) || {};
    try {
      const r = await fetch(`/api/evidence/${encodeURIComponent(recordId)}`);
      const detail = await r.json();
      if (!r.ok) throw new Error(detail.error || "Evidence not found");
      state.drawerRecord = { ...detail, ...cached, matched_terms: cached.matched_terms || detail.matched_terms || [] };
      renderDrawer(state.drawerRecord);
    } catch (err) {
      state.drawerRecord = cached;
      renderDrawer(cached);
    }
    els.drawer.classList.add("open");
    els.drawerOverlay.classList.add("open");
    els.drawer.setAttribute("aria-hidden", "false");
  }

  function renderDrawer(record) {
    const listValue = value => Array.isArray(value) && value.length ? value.join("、") : "none";
    els.drawerBody.innerHTML = `
      <h2 style="margin:0 0 10px;color:var(--ink-2);">${escapeHtml(record.title || "Untitled")}</h2>
      <p class="muted">${escapeHtml(record.snippet || record.relevance || "")}</p>
      ${detailRow(t("sourceType"), record.dataset || record.source || "")}
      ${detailRow(t("evidenceType"), record.evidence_type || "")}
      ${detailRow(t("provenanceNote"), record.provenance_note || "")}
      ${detailRow(t("timeSpan"), record.time_span || record.date || "")}
      ${detailRow(t("sourceUri"), record.source_uri || "")}
      ${detailRow(t("rawSourceUri"), record.raw_source_uri || "")}
      ${detailRow(t("openableUrl"), record.open_url || record.uri || "")}
      ${detailRow(t("matched"), listValue(record.matched_terms))}
      ${detailRow(t("relevance"), record.relevance || "")}
      ${detailRow(t("date"), record.date || "unknown")}
      ${detailRow(t("people"), listValue(record.persons))}
      ${detailRow(t("places"), listValue(record.places))}
      ${detailRow(t("topics"), listValue(record.topics))}
      ${detailRow(t("publicTags"), listValue(record.public_tags))}
      ${detailRow(t("verificationNotes"), listValue(record.verification_notes))}
      ${detailRow(t("liveStatus"), record.live_api ? "live API" : "demo seed")}
      ${detailRow(t("score"), record.score || "not scored")}
    `;
  }

  function detailRow(label, value) {
    return `<div class="detail-row"><strong>${escapeHtml(label)}</strong><div>${escapeHtml(value)}</div></div>`;
  }

  function closeDrawer() {
    els.drawer.classList.remove("open");
    els.drawerOverlay.classList.remove("open");
    els.drawer.setAttribute("aria-hidden", "true");
  }

  function openOriginalSource() {
    const record = state.drawerRecord || {};
    const uri = record.open_url || record.uri || "";
    if (/^(https?:\/\/|\/)/.test(uri)) {
      window.open(uri, "_blank", "noopener,noreferrer");
    } else if (uri) {
      navigator.clipboard && navigator.clipboard.writeText(uri);
      els.status.textContent = state.lang === "zh" ? "非网页 URI 已复制。" : "Non-web URI copied.";
    }
  }

  async function copyCitation() {
    const record = state.drawerRecord || {};
    const citation = record.citation || `${record.title || ""}. ${record.source || ""}. ${record.uri || record.source_uri || ""}`;
    try {
      await navigator.clipboard.writeText(citation);
      els.status.textContent = t("copied");
    } catch (err) {
      els.status.textContent = t("copyFailed");
    }
  }

  els.langZh.addEventListener("click", () => { state.lang = "zh"; updateCopy(); });
  els.langEn.addEventListener("click", () => { state.lang = "en"; updateCopy(); });
  els.askBtn.addEventListener("click", askAgent);
  els.backToWorkbench.addEventListener("click", returnToWorkbench);
  els.question.addEventListener("input", () => {
    updateCharCount();
    renderCluePreview();
  });
  els.mode.addEventListener("change", () => {
    renderModeBrief();
    renderCluePreview();
  });
  els.style.addEventListener("change", renderModeBrief);
  els.closeDrawer.addEventListener("click", closeDrawer);
  els.drawerOverlay.addEventListener("click", closeDrawer);
  els.openSource.addEventListener("click", openOriginalSource);
  els.copyCitation.addEventListener("click", copyCitation);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeDrawer();
  });

  updateCharCount();
  updateCopy();
  fetchHealth();
  initAtlas3d();
  renderEvidenceBoard([]);
  renderSecurity(null);
  </script>
</body>
</html>
"""


def app_data() -> dict:
    return {
        "copy": UI_COPY,
        "modes": MODES,
        "output_styles": OUTPUT_STYLES,
        "question_cards": QUESTION_CARDS,
        "version": VERSION,
        "max_question_length": MAX_QUESTION_LENGTH,
    }


def health_payload() -> dict:
    counts = count_records_by_source()
    settings = get_settings()
    return {
        "ok": True,
        "version": VERSION,
        **counts,
        "catalog_summary": catalog_summary(),
        "api_key_configured": bool(settings.api_key),
        "deepseek_configured": bool(settings.deepseek_api_key) and settings.use_deepseek,
        "deepseek_model": settings.deepseek_model,
        "last_ingest_report": sanitize_report(load_last_ingest_report()),
    }


def catalog_summary() -> dict:
    records = load_records()

    def top_rows(counter: Counter[str], limit: int = 8) -> list[dict]:
        return [{"label": label, "count": count} for label, count in counter.most_common(limit) if label]

    dataset_counter: Counter[str] = Counter(record.dataset for record in records)
    evidence_counter: Counter[str] = Counter(record.evidence_type for record in records)
    tag_counter: Counter[str] = Counter(tag for record in records for tag in record.public_tags)
    return {
        "total_records": len(records),
        "datasets": top_rows(dataset_counter),
        "evidence_types": top_rows(evidence_counter),
        "public_tags": top_rows(tag_counter),
    }


def sanitize_report(report: dict) -> dict:
    if not report:
        return {}
    allowed = {"timestamp", "use_live", "terms", "inserted_live", "inserted_seed", "total_records", "errors"}
    return {key: report.get(key) for key in allowed if key in report}


def evidence_payload(record_id: str) -> dict | None:
    record = get_record(record_id)
    if not record:
        return None
    source_url = openable_source_url(record)
    return {
        "record_id": record.record_id,
        "title": display_text(record.title, max_chars=140),
        "snippet": display_text(record.snippet, max_chars=900),
        "source": record.source,
        "uri": source_url,
        "open_url": source_url,
        "source_uri": source_url,
        "raw_source_uri": display_text(record.source_uri, max_chars=260),
        "dataset": record.dataset,
        "date": display_text(record.date, max_chars=80),
        "evidence_type": record.evidence_type,
        "provenance_note": display_text(record.provenance_note, max_chars=420),
        "time_span": display_text(record.time_span or record.date, max_chars=120),
        "geo": record.geo,
        "public_tags": [display_text(v, max_chars=60) for v in record.public_tags],
        "verification_notes": [display_text(v, max_chars=220) for v in record.verification_notes],
        "persons": [display_text(v, max_chars=60) for v in record.persons],
        "places": [display_text(v, max_chars=60) for v in record.places],
        "topics": [display_text(v, max_chars=60) for v in record.topics],
        "live_api": record.is_live_api,
        "citation": f"{display_text(record.title, max_chars=140)}. {record.source}. {source_url}",
    }


def render_source_page(record_id: str) -> bytes | None:
    record = get_record(record_id)
    if not record:
        return None
    source_url = openable_source_url(record)
    raw_uri = str(record.source_uri or "")
    exact_external = source_url if source_url.startswith(("http://", "https://")) else ""
    raw_json = json.dumps(record.raw, ensure_ascii=False, indent=2)
    rows = [
        ("题名 / Title", record.title),
        ("来源 / Source", record.source),
        ("数据集 / Dataset", record.dataset),
        ("证据类型 / Evidence Type", record.evidence_type),
        ("出处说明 / Provenance Note", record.provenance_note),
        ("时间跨度 / Time Span", record.time_span or record.date or "unknown"),
        ("日期 / Date", record.date or "unknown"),
        ("人物 / People", "、".join(record.persons) or "none"),
        ("地点 / Places", "、".join(record.places) or "none"),
        ("主题 / Topics", "、".join(record.topics) or "none"),
        ("公众标签 / Public Tags", "、".join(record.public_tags) or "none"),
        ("复核备注 / Verification Notes", "；".join(record.verification_notes) or "none"),
        ("原始来源 URI / Raw Source URI", raw_uri or "none"),
        ("本页记录 URL / Record URL", source_detail_url(record)),
    ]
    external_link = (
        f'<a class="button" href="{html_escape(exact_external)}" target="_blank" rel="noopener noreferrer">打开上海图书馆具体实体页</a>'
        if exact_external
        else ""
    )
    api_note = ""
    if raw_uri.startswith("shlib-api://"):
        api_note = (
            "<p class=\"note\">此记录来自上海图书馆 API 查询结果，原始 API key 只保存在本地后端，"
            "不会出现在页面或链接中。本页展示的是该记录的本地可复查缓存与具体 API 路由引用。</p>"
        )
    elif raw_uri.startswith("https://www.library.sh.cn/resource?type="):
        api_note = (
            "<p class=\"note\">此记录是 demo seed/fallback 证据。它不再被当作具体文献来源；"
            "正式展示时建议用 live API 记录替换。</p>"
        )
    rows_html = "".join(
        f"<tr><th>{html_escape(label)}</th><td>{html_escape(str(value))}</td></tr>"
        for label, value in rows
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(display_text(record.title, max_chars=80))} - ContextLens Source</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:#102033; background:#f5f7fb; }}
    main {{ max-width:960px; margin:0 auto; padding:32px 18px 48px; }}
    h1 {{ margin:0 0 10px; color:#123a64; font-size:clamp(24px,4vw,38px); line-height:1.15; }}
    p {{ line-height:1.65; }}
    table {{ width:100%; border-collapse:collapse; background:white; border:1px solid #dbe4ef; border-radius:8px; overflow:hidden; }}
    th, td {{ text-align:left; vertical-align:top; border-bottom:1px solid #e5ebf2; padding:12px; }}
    th {{ width:220px; color:#7f1d1d; background:#fbfdff; }}
    code, pre {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
    pre {{ margin-top:16px; padding:14px; background:#07192d; color:#eef6ff; border-radius:8px; overflow:auto; }}
    .button {{ display:inline-flex; margin:12px 10px 16px 0; padding:10px 13px; border-radius:8px; background:#24558f; color:white; text-decoration:none; font-weight:800; }}
    .note {{ padding:12px; border-left:4px solid #b91c1c; background:#fff7ed; color:#5f3111; border-radius:8px; }}
  </style>
</head>
<body>
  <main>
    <h1>{html_escape(display_text(record.title, max_chars=140))}</h1>
    <p>{html_escape(display_text(record.snippet, max_chars=1000))}</p>
    {external_link}
    {api_note}
    <table>{rows_html}</table>
    <h2>原始 API / 记录字段缓存</h2>
    <pre><code>{html_escape(raw_json[:12000])}</code></pre>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


def write_query_log(answer: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    audit = answer.get("audit", {})
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "query_hash": hashlib.sha256(
            str(answer.get("question", "")).strip().encode("utf-8")
        ).hexdigest(),
        "language": answer.get("language"),
        "mode": answer.get("mode"),
        "output_style": answer.get("output_style"),
        "retrieval_count": audit.get("evidence_count", 0),
        "latency_ms": audit.get("latency_ms"),
        "citation_coverage": audit.get("citation_coverage"),
        "failure_mode": audit.get("failure_mode"),
        "deepseek_status": (answer.get("deepseek_assist") or {}).get("status"),
    }
    with (LOG_DIR / "query_audit.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            html = HTML.replace("REPLACE_APP_DATA", json.dumps(app_data(), ensure_ascii=False))
            self.respond(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/favicon.ico":
            icon = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#07192d"/><path d="M14 39h36M20 31l9 8 15-18" fill="none" stroke="#f5d28e" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
            self.respond(200, icon, "image/svg+xml")
        elif path == "/api/health":
            self.respond_json(health_payload())
        elif path.startswith("/api/evidence/"):
            record_id = unquote(path.removeprefix("/api/evidence/")).strip()
            payload = evidence_payload(record_id)
            if payload is None:
                self.respond_json({"error": "evidence not found"}, status=404)
            else:
                self.respond_json(payload)
        elif path.startswith("/source/"):
            record_id = unquote(path.removeprefix("/source/")).strip()
            page = render_source_page(record_id)
            if page is None:
                self.respond_json({"error": "source record not found"}, status=404)
            else:
                self.respond(200, page, "text/html; charset=utf-8")
        else:
            self.respond_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/ask":
            self.respond_json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("content-length", "0"))
        if length > 12000:
            self.respond_json({"error": "request body too large"}, status=413)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.respond_json({"error": "invalid JSON"}, status=400)
            return
        question = str(payload.get("question", "")).strip()
        if not question:
            self.respond_json({"error": "question is required"}, status=400)
            return
        if len(question) > MAX_QUESTION_LENGTH:
            self.respond_json({"error": f"question exceeds {MAX_QUESTION_LENGTH} characters"}, status=400)
            return
        top_k = clamp_int(payload.get("top_k", 10), low=1, high=16, default=10)
        answer = answer_question(
            question,
            top_k=top_k,
            language=str(payload.get("language", "zh")),
            mode=str(payload.get("mode", "general")),
            output_style=str(payload.get("output_style", "evidence_brief")),
            use_deepseek=bool(payload.get("use_deepseek", False)),
        )
        write_query_log(answer)
        self.respond_json(answer)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def respond_json(self, payload: dict, status: int = 200) -> None:
        self.respond(status, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")

    def respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def clamp_int(value: object, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def main() -> None:
    # Keep the historical module entry point working while routing launches to
    # the focused, map-first flagship experience.
    from app.memory_web import main as run_memory_wormhole

    run_memory_wormhole()


if __name__ == "__main__":
    main()
