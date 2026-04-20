import os
import json
import asyncio
import re
import subprocess
import base64
import time
from pathlib import Path
from ddgs import DDGS

from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.responses import StreamingResponse, JSONResponse
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

load_dotenv()

templates = Jinja2Templates(directory="templates")
DEBATES_DIR = Path("debates")
DEBATES_DIR.mkdir(exist_ok=True)

CLAUDE_MODELS = {
    "claude-opus-4-6": "Claude Opus 4.6",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-sonnet-4-20250514": "Claude Sonnet 4",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
}

GEMINI_MODELS = {
    "gemini-web": "Gemini (웹 - 자동 모델)",
}

GEMINI_RESEARCH_PROMPT = {
    "en": """You are a research analyst. Search the web for the latest information on the following topic and produce a structured research report.

Topic: {topic}

Search for recent news, data, and expert opinions. Then write a structured report with these sections:

## Current Situation
Key facts and recent developments with specific numbers, dates, and sources.

## Bull Case
Concrete data points and arguments supporting a positive/optimistic thesis. Every claim needs a specific figure.

## Bear Case
Concrete data points highlighting risks or negative factors. Every claim needs a specific figure.

## Key Statistics
List 6-10 specific numbers, indicators, or facts most critical to this debate.

## Macro Context
Broader economic, regulatory, or market forces relevant to the topic.

Respond in English.""",

    "ko": """당신은 리서치 애널리스트입니다. 아래 주제에 대해 웹 검색으로 최신 정보를 수집하고 구조화된 리서치 보고서를 작성하세요.

주제: {topic}

최신 뉴스, 데이터, 전문가 의견을 검색한 후 다음 섹션으로 보고서를 작성하세요:

## 현재 상황
구체적인 수치, 날짜, 출처를 포함한 주요 사실과 최근 동향.

## 강세 근거 (Bull Case)
긍정적/낙관적 논거를 뒷받침하는 구체적 데이터. 모든 주장에 수치 필수.

## 약세 근거 (Bear Case)
리스크와 부정적 요인을 부각하는 구체적 데이터. 모든 주장에 수치 필수.

## 핵심 통계
이 토론에서 가장 중요한 수치, 지표, 사실 6-10개 목록.

## 거시적 맥락
관련된 경제적, 규제적, 시장적 요인.

한국어로 응답하세요.""",

    "es": """Eres un analista de investigación. Busca en la web la información más reciente sobre el siguiente tema y produce un informe de investigación estructurado.

Tema: {topic}

Busca noticias recientes, datos y opiniones de expertos. Luego escribe un informe estructurado con estas secciones:

## Situación Actual
Hechos clave y desarrollos recientes con números, fechas y fuentes específicas.

## Caso Alcista (Bull Case)
Datos y argumentos concretos que apoyan una tesis positiva. Cada afirmación necesita una cifra específica.

## Caso Bajista (Bear Case)
Datos concretos que destacan riesgos o factores negativos. Cada afirmación necesita una cifra específica.

## Estadísticas Clave
Lista de 6-10 números, indicadores o hechos más críticos para este debate.

## Contexto Macroeconómico
Fuerzas económicas, regulatorias o de mercado más amplias relevantes al tema.

Responde en español.""",
}

CLAUDE_RESEARCH_PROMPT = {
    "en": """You are a research analyst. Using the web search results and any financial data below, produce a structured research report.

Topic: {topic}

{financial_section}Web search results:
{search_results}

Write a structured report with these sections:

## Current Situation
Key facts and recent developments with specific numbers, dates, and sources.

## Bull Case
Concrete data points and arguments supporting a positive/optimistic thesis. Every claim needs a specific figure.

## Bear Case
Concrete data points highlighting risks or negative factors. Every claim needs a specific figure.

## Key Statistics
List 6-10 specific numbers, indicators, or facts most critical to this debate.

## Macro Context
Broader economic, regulatory, or market forces relevant to the topic.

IMPORTANT: You do NOT have web search tools in this context — the search results above are pre-fetched and are all the external data you have. Write the best report possible using what is provided. If search results are sparse or off-topic, note the data gap but still write the report using the financial data and your knowledge. Do not ask for additional tools or permissions. Respond in English.""",

    "ko": """당신은 리서치 애널리스트입니다. 아래 웹 검색 결과와 금융 데이터를 바탕으로 구조화된 리서치 보고서를 작성하세요.

주제: {topic}

{financial_section}웹 검색 결과:
{search_results}

다음 섹션으로 구성된 보고서를 작성하세요:

## 현재 상황
구체적인 수치, 날짜, 출처를 포함한 주요 사실과 최근 동향.

## 강세 근거 (Bull Case)
긍정적/낙관적 논거를 뒷받침하는 구체적 데이터. 모든 주장에 수치 필수.

## 약세 근거 (Bear Case)
리스크와 부정적 요인을 부각하는 구체적 데이터. 모든 주장에 수치 필수.

## 핵심 통계
이 토론에서 가장 중요한 수치, 지표, 사실 6-10개 목록.

## 거시적 맥락
관련된 경제적, 규제적, 시장적 요인.

중요: 이 컨텍스트에서는 웹 검색 도구가 없습니다 — 위의 검색 결과는 미리 수집된 것으로 사용 가능한 모든 외부 데이터입니다. 제공된 데이터로 최선의 보고서를 작성하세요. 검색 결과가 부실하거나 관련성이 낮더라도, 금융 데이터와 보유 지식을 활용해 보고서를 완성하세요. 추가 도구나 권한을 요청하지 마세요. 한국어로 응답하세요.""",

    "es": """Eres un analista de investigación. Usando los resultados de búsqueda web y datos financieros a continuación, produce un informe de investigación estructurado.

Tema: {topic}

{financial_section}Resultados de búsqueda web:
{search_results}

Escribe un informe estructurado con estas secciones:

## Situación Actual
Hechos clave y desarrollos recientes con números, fechas y fuentes específicas.

## Caso Alcista (Bull Case)
Datos y argumentos concretos que apoyan una tesis positiva. Cada afirmación necesita una cifra específica.

## Caso Bajista (Bear Case)
Datos concretos que destacan riesgos o factores negativos. Cada afirmación necesita una cifra específica.

## Estadísticas Clave
Lista de 6-10 números, indicadores o hechos más críticos para este debate.

## Contexto Macroeconómico
Fuerzas económicas, regulatorias o de mercado más amplias relevantes al tema.

IMPORTANTE: No tienes herramientas de búsqueda web en este contexto — los resultados de búsqueda anteriores son datos externos pre-obtenidos. Escribe el mejor informe posible con lo proporcionado. Si los resultados son escasos o irrelevantes, indica la limitación de datos pero escribe el informe usando los datos financieros y tu conocimiento. No solicites herramientas o permisos adicionales. Responde en español.""",
}

LANG_RESPOND = {
    "en": "Respond in English.",
    "ko": "한국어로 응답하세요.",
    "es": "Responde en español.",
}

CLAUDE_SYSTEM_TEMPLATE = """Debate: Claude vs Gemini | Topic: {topic}

[Research Material]
{research}

Rules: {respond_instruction} Cite specific numbers and statistics from the research material. Challenge your opponent's claims with counter-evidence. 300-500 words. If you need more data on a specific point, end your response with [RESEARCH_REQUEST]: <specific request>."""

GEMINI_SYSTEM_TEMPLATE = """Debate: Gemini vs Claude | Topic: {topic}

[Research Material]
{research}

Rules: {respond_instruction} Cite specific numbers and statistics from the research material. Challenge your opponent's claims with counter-evidence. You may search the web for additional data. 300-500 words."""

ANTI_SYCOPHANCY_RULES = {
    "en": """
- Every claim must be backed by a specific number, statistic, or fact from the research material.
- Do not easily agree with your opponent. If you disagree, rebut with specific counter-evidence and cite the data.
- Do not abandon your position without new evidence. Pressure alone is not a reason to concede.
- Partial agreement is allowed, but explicitly argue the points you still dispute with supporting data.
- Avoid vague hedging ("it depends", "there are pros and cons"). Take a clear stance and defend it.""",
    "ko": """
- 모든 주장은 리서치 자료의 구체적인 수치, 통계, 사실로 뒷받침되어야 합니다.
- 상대방 주장에 쉽게 동의하지 마세요. 반박할 때는 구체적인 반증 데이터를 인용하세요.
- 새로운 증거 없이는 기존 입장을 포기하지 마세요. 압박만으로는 양보할 이유가 없습니다.
- 부분 동의는 허용하지만, 여전히 동의하지 않는 핵심 지점을 데이터로 논증하세요.
- 모호한 표현("경우에 따라 다르다", "장단점이 있다")을 피하고 명확한 입장을 취하세요.""",
    "es": """
- Cada afirmación debe estar respaldada por un número, estadística o hecho específico del material de investigación.
- No estés de acuerdo fácilmente con el oponente. Si rebates, cita evidencia contraria específica.
- No abandones tu posición sin nueva evidencia. La presión sola no es razón para ceder.
- El acuerdo parcial está permitido, pero argumenta explícitamente los puntos en disputa con datos.
- Evita evasivas vagas ("depende", "hay pros y contras"). Toma una postura clara y defiéndela.""",
}

ROLE_PAIRS = {
    "bull_bear": {
        "names": {
            "en": ("Bull (Optimist)", "Bear (Pessimist)"),
            "ko": ("강세론자 (Bull)", "약세론자 (Bear)"),
            "es": ("Alcista (Bull)", "Bajista (Bear)"),
        },
        "claude_role": "You are the Bull (optimist). Focus on positive outlook, growth potential, and opportunity factors. Strongly rebut pessimistic views.",
        "gemini_role": "You are the Bear (pessimist). Focus on risks, downside factors, and threats. Strongly rebut optimistic views.",
    },
    "optimist_pessimist": {
        "names": {
            "en": ("Optimist", "Pessimist"),
            "ko": ("낙관론자", "비관론자"),
            "es": ("Optimista", "Pesimista"),
        },
        "claude_role": "You are the Optimist. Focus on positive aspects, opportunities, and potential for development.",
        "gemini_role": "You are the Pessimist. Focus on problems, risks, and negative aspects.",
    },
    "pro_con": {
        "names": {
            "en": ("Pro", "Con"),
            "ko": ("찬성측", "반대측"),
            "es": ("A favor", "En contra"),
        },
        "claude_role": "You are on the Pro side. Present strong arguments in support of the topic.",
        "gemini_role": "You are on the Con side. Present strong arguments against the topic.",
    },
    "tradition_innovation": {
        "names": {
            "en": ("Traditional View", "Innovative View"),
            "ko": ("전통적 관점", "혁신적 관점"),
            "es": ("Visión Tradicional", "Visión Innovadora"),
        },
        "claude_role": "You represent the traditional/conservative perspective. Emphasize proven methods, stability, and the value of existing order.",
        "gemini_role": "You represent the innovative/progressive perspective. Emphasize change, innovation, and the need for new paradigms.",
    },
}

DEBATE_STRINGS = {
    "en": {
        "opening": "Topic: {topic}\n\nPresent your analysis and opening position. Cite specific statistics and data from the research material. Structure your argument: (1) Current situation with key numbers, (2) Your core thesis, (3) Top 2-3 supporting evidence points.",
        "rebuttal_suffix": "\n\nRebut with specific counter-evidence. Identify the weakest claim in the opponent's argument and challenge it with data. Then reinforce your own position with a new evidence point not yet raised.",
        "gemini_rebuttal": "Here is your opponent (Claude)'s argument:\n\n{response}\n\nRebut with specific counter-evidence. Identify the weakest claim above and challenge it with data from your knowledge or web search. Add a new argument not yet raised in this debate.",
        "gemini_opening_response": "Here is your opponent (Claude)'s opening statement:\n\n{response}\n\nPresent your own independent position with specific data. Do not simply react — build your own evidence-based thesis.",
        "deeper_prefix": "[Deeper topic: {topic}]\n\n",
        "context_restore": """Continuing from a previous debate.

Previous topic: {saved_topic}

Previous research:
{research}

Debate so far:
{transcript}{topic_notice}

We will continue for {rounds} more rounds. When ready, reply "Understood, let's continue.".""",
        "context_topic_notice": "\n\nWe will now continue with a deeper topic: {new_topic}",
        "extra_research_label": "\n\n[Additional Research]\n",
        "thinking_research": "Web Research",
        "thinking_context": "Gemini Context Restore",
        "status_restored": "Previous debate restored.",
        "status_new_topic": " New topic: {topic}.",
        "status_continue_from": " Continuing from round {n}.",
    },
    "ko": {
        "opening": "주제: {topic}\n\n개회 분석과 입장을 제시하세요. 리서치 자료의 구체적인 통계와 데이터를 인용하세요. 다음 구조로 논거를 구성하세요: (1) 핵심 수치를 포함한 현재 상황, (2) 핵심 주장, (3) 상위 2-3개 근거 데이터.",
        "rebuttal_suffix": "\n\n구체적인 반증 데이터로 반론하세요. 상대방 주장에서 가장 약한 부분을 찾아 데이터로 반박하고, 아직 제시되지 않은 새로운 근거를 추가하세요.",
        "gemini_rebuttal": "상대방(Claude)의 주장입니다:\n\n{response}\n\n구체적인 반증 데이터로 반론하세요. 위 주장에서 가장 취약한 부분을 찾아 데이터로 반박하고, 이 토론에서 아직 제시되지 않은 새로운 논거를 추가하세요.",
        "gemini_opening_response": "상대방(Claude)의 개회 발언입니다:\n\n{response}\n\n구체적인 데이터를 바탕으로 독립적인 입장을 제시하세요. 단순히 반응하지 말고 자체적인 증거 기반 논거를 구축하세요.",
        "deeper_prefix": "[심화 주제: {topic}]\n\n",
        "context_restore": """이전 토론을 이어서 진행합니다.

기존 주제: {saved_topic}

이전 자료 조사 결과:
{research}

지금까지의 토론 내용:
{transcript}{topic_notice}

이제 {rounds}라운드 더 이어서 진행합니다. 준비되면 "네, 확인했습니다. 계속 진행하겠습니다."라고 답해주세요.""",
        "context_topic_notice": "\n\n이번에는 심화 주제로 토론을 이어갑니다: {new_topic}",
        "extra_research_label": "\n\n[추가 조사 자료]\n",
        "thinking_research": "웹 리서치",
        "thinking_context": "Gemini 컨텍스트 복원",
        "status_restored": "이전 토론 복원 완료.",
        "status_new_topic": " 새 주제: {topic}.",
        "status_continue_from": " {n}라운드부터 계속합니다.",
    },
    "es": {
        "opening": "Tema: {topic}\n\nPresenta tu análisis inicial y posición. Cita estadísticas y datos específicos del material de investigación. Estructura tu argumento: (1) Situación actual con cifras clave, (2) Tu tesis central, (3) Los 2-3 puntos de evidencia más sólidos.",
        "rebuttal_suffix": "\n\nRebate con evidencia contraria específica. Identifica el argumento más débil del oponente y desafíalo con datos. Luego refuerza tu posición con un nuevo punto de evidencia aún no planteado.",
        "gemini_rebuttal": "Aquí está el argumento de tu oponente (Claude):\n\n{response}\n\nRebate con evidencia contraria específica. Identifica el punto más débil arriba y desafíalo con datos. Agrega un nuevo argumento aún no planteado en este debate.",
        "gemini_opening_response": "Aquí está el discurso de apertura de tu oponente (Claude):\n\n{response}\n\nPresenta tu propia posición independiente con datos específicos. No simplemente reacciones — construye tu propia tesis basada en evidencia.",
        "deeper_prefix": "[Tema más profundo: {topic}]\n\n",
        "context_restore": """Continuando con un debate anterior.

Tema anterior: {saved_topic}

Investigación anterior:
{research}

Debate hasta ahora:
{transcript}{topic_notice}

Continuaremos por {rounds} rondas más. Cuando estés listo, responde "Entendido, continuemos.".""",
        "context_topic_notice": "\n\nAhora continuaremos con un tema más profundo: {new_topic}",
        "extra_research_label": "\n\n[Investigación adicional]\n",
        "thinking_research": "Investigación Web",
        "thinking_context": "Restauración Gemini",
        "status_restored": "Debate anterior restaurado.",
        "status_new_topic": " Nuevo tema: {topic}.",
        "status_continue_from": " Continuando desde ronda {n}.",
    },
}

RESEARCH_REQUEST_MARKERS = ["[RESEARCH_REQUEST]:", "[자료요청]:", "[SOLICITUD_DATOS]:"]

PROMPT_ROLE_LABELS = {
    "en": ("Opponent", "Me"),
    "ko": ("상대방", "나"),
    "es": ("Oponente", "Yo"),
}


RESEARCH_MAX_CHARS = 2000  # truncate research in system prompt to save tokens
CLAUDE_FAST_MODEL = "claude-haiku-4-5-20251001"  # used for simple tasks (conclusion)


def build_system(base_template, topic, research, lang="en", role_desc=None):
    """Build system prompt with optional role + always-on anti-sycophancy.
    Research is truncated to RESEARCH_MAX_CHARS to limit token usage.
    """
    truncated = research[:RESEARCH_MAX_CHARS] + "\n...(truncated)" if len(research) > RESEARCH_MAX_CHARS else research
    respond_instruction = LANG_RESPOND.get(lang, LANG_RESPOND["en"])
    system = base_template.format(topic=topic, research=truncated, respond_instruction=respond_instruction)
    if role_desc:
        system += f"\n\n[Role]\n{role_desc}"
    system += ANTI_SYCOPHANCY_RULES.get(lang, ANTI_SYCOPHANCY_RULES["en"])
    return system


CONCLUSION_PROMPT_TEMPLATE = """You are a neutral moderator summarizing a debate between Claude (Anthropic) and Gemini (Google).

Topic: {topic}

Full debate transcript:
{transcript}

Please provide a comprehensive conclusion that:
1. Summarizes the key points of agreement
2. Summarizes the key points of disagreement
3. Synthesizes the strongest arguments from both sides
4. Provides a balanced final assessment

Format with clear headers and be thorough but concise. {respond_instruction}"""


try:
    import yfinance as yf
    _YFINANCE_AVAILABLE = True
except ImportError:
    _YFINANCE_AVAILABLE = False

# Common uppercase acronyms that are NOT tickers
_NON_TICKERS = {
    'AI', 'US', 'UK', 'EU', 'GDP', 'CEO', 'CFO', 'IPO', 'ETF', 'CPI', 'FED',
    'IMF', 'WHO', 'FBI', 'CIA', 'ESG', 'ROI', 'EPS', 'PE', 'VC', 'IPO', 'M&A',
    'API', 'ML', 'DL', 'LLM', 'NLP', 'AR', 'VR', 'TV', 'PC', 'IT', 'HR',
    'USD', 'EUR', 'JPY', 'KRW', 'CNY', 'GBP', 'AUD',
}


def extract_ticker(topic: str):
    """Try to extract a stock ticker symbol from the topic string."""
    # Match 1-5 uppercase letters, optionally with exchange suffix (.KS, .TO, etc.)
    pattern = r'\b([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b'
    candidates = re.findall(pattern, topic)
    for c in candidates:
        base = c.split('.')[0]
        if base not in _NON_TICKERS and len(base) >= 2:
            return c
    return None


async def fetch_yfinance_data(ticker: str) -> str:
    """Fetch price, technical indicators, and fundamentals from yfinance."""
    def _fetch():
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            name = info.get('longName') or info.get('shortName') or ticker

            lines = [f"=== {name} ({ticker}) — Live Financial Data ==="]

            # Price info
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            prev = info.get('previousClose')
            if price:
                chg = ((price - prev) / prev * 100) if prev else None
                lines.append(f"Price: ${price:.2f}" + (f" ({chg:+.2f}% today)" if chg is not None else ""))
            lines.append(f"52-Week Range: ${info.get('fiftyTwoWeekLow', 'N/A')} – ${info.get('fiftyTwoWeekHigh', 'N/A')}")

            # Valuation
            mcap = info.get('marketCap')
            if mcap:
                lines.append(f"Market Cap: ${mcap/1e9:.2f}B")
            pe = info.get('trailingPE')
            fpe = info.get('forwardPE')
            if pe:  lines.append(f"P/E (TTM): {pe:.1f}" + (f" | Forward P/E: {fpe:.1f}" if fpe else ""))
            eps = info.get('trailingEps')
            if eps: lines.append(f"EPS (TTM): ${eps:.2f}")
            div = info.get('dividendYield')
            if div: lines.append(f"Dividend Yield: {div*100:.2f}%")

            # Revenue / profit
            rev = info.get('totalRevenue')
            margin = info.get('profitMargins')
            if rev:    lines.append(f"Revenue (TTM): ${rev/1e9:.2f}B")
            if margin: lines.append(f"Net Margin: {margin*100:.1f}%")

            # Technical indicators from 3-month history
            hist = stock.history(period="3mo")
            if not hist.empty:
                closes = hist['Close']
                lines.append("\n--- Technical Indicators ---")
                lines.append(f"3M Change: {((closes.iloc[-1]/closes.iloc[0])-1)*100:+.1f}%")

                # SMA 20 / 50
                sma20 = closes.rolling(20).mean().iloc[-1]
                sma50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
                lines.append(f"SMA-20: ${sma20:.2f}" + (f" | SMA-50: ${sma50:.2f}" if sma50 else ""))

                # RSI-14
                delta = closes.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rsi = (100 - 100 / (1 + gain / loss)).iloc[-1]
                lines.append(f"RSI-14: {rsi:.1f} ({'overbought >70' if rsi>70 else 'oversold <30' if rsi<30 else 'neutral'})")

                # Bollinger Bands
                bb_mid = sma20
                bb_std = closes.rolling(20).std().iloc[-1]
                lines.append(f"Bollinger Bands: ${bb_mid-2*bb_std:.2f} / ${bb_mid:.2f} / ${bb_mid+2*bb_std:.2f}")

                # Volume trend
                vol_avg = hist['Volume'].rolling(20).mean().iloc[-1]
                vol_last = hist['Volume'].iloc[-1]
                lines.append(f"Volume vs 20D Avg: {vol_last/vol_avg:.2f}x")

            return "\n".join(lines)
        except Exception as e:
            return f"(yfinance data unavailable for {ticker}: {e})"

    return await asyncio.to_thread(_fetch)


async def search_web(query: str) -> str:
    """Search the web using DuckDuckGo and return formatted results."""
    def _search():
        parts = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=8):
                parts.append(f"**{r.get('title', '')}**\n{r.get('body', '')}")
            try:
                for r in ddgs.news(query, max_results=5):
                    date = r.get('date', '')
                    body = r.get('body', r.get('excerpt', ''))
                    parts.append(f"[News{(' ' + date) if date else ''}] **{r.get('title', '')}**\n{body}")
            except Exception:
                pass
        return "\n\n---\n\n".join(parts)

    return await asyncio.to_thread(_search)


async def research_topic(topic: str, lang: str = "en", model: str = "claude-opus-4-6") -> str:
    """Search the web (+ yfinance if ticker detected) and synthesize with Claude."""
    ticker = extract_ticker(topic)

    # If topic contains a ticker, search with ticker + "stock" for better results
    search_query = f"{ticker} stock analysis" if ticker else topic
    tasks = [search_web(search_query), search_web(topic)]
    if ticker and _YFINANCE_AVAILABLE:
        tasks.append(fetch_yfinance_data(ticker))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge the two search results
    search_parts = []
    for r in results[:2]:
        if not isinstance(r, Exception) and r:
            search_parts.append(str(r))
    combined_search = "\n\n---\n\n".join(search_parts)
    search_text = combined_search[:5000] + "\n...(truncated)" if len(combined_search) > 5000 else combined_search

    financial_section = ""
    if len(results) > 2 and not isinstance(results[2], Exception):
        financial_section = f"{results[2]}\n\n"

    prompt = CLAUDE_RESEARCH_PROMPT.get(lang, CLAUDE_RESEARCH_PROMPT["en"]).format(
        topic=topic,
        search_results=search_text,
        financial_section=financial_section,
    )
    return await call_claude(prompt, model)


async def _handle_data_request(claude_response, existing_research, lang="en", model="claude-opus-4-6"):
    """Parse Claude's response for research request markers and fetch additional data via Gemini."""
    lines = claude_response.split("\n")
    request_line = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        for marker in RESEARCH_REQUEST_MARKERS:
            if stripped.startswith(marker):
                request_line = stripped[len(marker):].strip()
                clean_lines = lines[:i]
                remaining = [l for l in lines[i+1:] if l.strip()]
                clean_lines.extend(remaining)
                claude_response = "\n".join(clean_lines).strip()
                break
        if request_line is not None:
            break

    if not request_line:
        return claude_response, ""

    try:
        extra_prompt = GEMINI_RESEARCH_PROMPT.get(lang, GEMINI_RESEARCH_PROMPT["en"]).format(topic=request_line)
        extra_research = await call_gemini_web(extra_prompt, new_chat=False)
        return claude_response, extra_research
    except Exception:
        return claude_response, ""


class RateLimitError(Exception):
    def __init__(self, message, reset_info=""):
        super().__init__(message)
        self.reset_info = reset_info


def parse_rate_limit(text):
    patterns = [
        r'(\d+\s*시간\s*\d+\s*분)', r'(\d+\s*분)',
        r'(\d+h\s*\d+m)', r'(\d+m)', r'retry\s*in\s*([\d.]+\s*s)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


async def call_claude(prompt, model="claude-opus-4-6", system_prompt=None):
    """Call Claude via CLI (uses Pro plan quota)."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "text"]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()
    output = stdout.decode().strip()
    err = stderr.decode().strip()

    if proc.returncode != 0 or not output:
        combined = output + " " + err
        if any(kw in combined.lower() for kw in ["rate limit", "limit", "token", "quota", "exceeded"]):
            raise RateLimitError(combined, parse_rate_limit(combined))
        raise RuntimeError(f"Claude CLI error: {err or output or 'empty response'}")

    return output


def _run_applescript(script: str) -> str:
    """Run AppleScript and return result."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def _find_gemini_script() -> str:
    """AppleScript snippet that sets foundWin/foundTab to the Gemini tab across all windows."""
    return '''
    set foundWin to 0
    set foundTab to 0
    set winCount to count of windows
    repeat with w from 1 to winCount
        tell window w
            set tabCount to count of tabs
            repeat with i from 1 to tabCount
                if URL of tab i contains "gemini.google.com" then
                    set foundWin to w
                    set foundTab to i
                    exit repeat
                end if
            end repeat
        end tell
        if foundWin > 0 then exit repeat
    end repeat'''


def _run_on_gemini_tab(js: str) -> str:
    """Build AppleScript that runs JS on the Gemini tab across all windows."""
    escaped_js = js.replace('"', '\\"')
    return f'''
tell application "Whale"
    {_find_gemini_script()}
    if foundWin > 0 and foundTab > 0 then
        set result to execute tab foundTab of window foundWin javascript "{escaped_js}"
    else
        set result to "NO_GEMINI_TAB"
    end if
    return result
end tell
'''


async def _ensure_gemini_tab(new_chat: bool = True):
    """Find or create a Gemini tab across all windows, optionally navigate to fresh chat."""
    if new_chat:
        setup = '''
tell application "Whale"
    -- Close existing Gemini tabs across all windows
    set winCount to count of windows
    repeat with w from 1 to winCount
        tell window w
            set tabCount to count of tabs
            repeat with i from tabCount to 1 by -1
                if URL of tab i contains "gemini.google.com" then
                    close tab i
                end if
            end repeat
        end tell
    end repeat
    -- Open fresh tab in front window, switch back to original tab
    tell front window
        set activeIdx to active tab index
        make new tab with properties {URL:"https://gemini.google.com/app"}
        set active tab index to activeIdx
    end tell
end tell
'''
        await asyncio.to_thread(_run_applescript, setup)
    else:
        check = f'''
tell application "Whale"
    {_find_gemini_script()}
    if foundWin > 0 then
        return "FOUND"
    end if
    -- No Gemini tab found — create one in front window
    tell front window
        set activeIdx to active tab index
        make new tab with properties {{URL:"https://gemini.google.com/app"}}
        set active tab index to activeIdx
    end tell
    return "CREATED"
end tell
'''
        await asyncio.to_thread(_run_applescript, check)


async def call_gemini_web(prompt: str, new_chat: bool = True) -> str:
    """Call Gemini via Whale browser AppleScript automation.
    Uses a dedicated Gemini tab — does NOT touch the active tab.
    Uses base64 encoding to avoid multi-layer escaping issues.
    """

    # Base64 encode the prompt to avoid escaping hell (Python → f-string → AppleScript → JS)
    b64 = base64.b64encode(prompt.encode()).decode()

    if new_chat:
        await _ensure_gemini_tab(new_chat=True)

    # Wait for editor to be ready (poll up to 20 seconds)
    for _ in range(20):
        await asyncio.sleep(1)
        status = await asyncio.to_thread(_run_applescript,
            _run_on_gemini_tab("document.querySelector('.ql-editor[role=textbox]') ? 'READY' : 'LOADING'"))
        if status == "READY":
            break
    else:
        raise RuntimeError("Gemini 입력창 로딩 시간 초과")

    # Count existing responses before sending
    prev_count_str = await asyncio.to_thread(_run_applescript,
        _run_on_gemini_tab("document.querySelectorAll('.model-response-text').length.toString()"))
    prev_count = int(prev_count_str)

    # Activate Gemini tab to type & send, then switch back
    # (inactive tabs have unreliable execCommand)
    type_and_send = f'''
tell application "Whale"
    {_find_gemini_script()}
    if foundWin > 0 and foundTab > 0 then
        tell window foundWin
            set origIdx to active tab index
            set active tab index to foundTab
            delay 0.8
            execute tab foundTab javascript "var t = decodeURIComponent(Array.prototype.map.call(atob('{b64}'),function(c){{return '%'+('00'+c.charCodeAt(0).toString(16)).slice(-2);}}).join('')); var e = document.querySelector('.ql-editor[role=textbox]'); e.focus(); document.execCommand('selectAll',false,null); document.execCommand('insertText',false,t); 'TYPED';"
            delay 1
            execute tab foundTab javascript "var btns=document.querySelectorAll('button:not([disabled])');var btn=null;for(var i=0;i<btns.length;i++){{var lbl=btns[i].getAttribute('aria-label')||'';if(lbl==='메시지 보내기'||lbl==='Send message'){{btn=btns[i];break;}}}}if(btn){{btn.click();'CLICKED';}}else{{'NOT_FOUND';}}"
            delay 0.5
            set active tab index to origIdx
        end tell
    end if
end tell
'''
    await asyncio.to_thread(_run_applescript, type_and_send)

    # Poll for response completion using stable-length detection
    # (CSS/class-based loading indicators are unreliable — use length stability instead)
    stable_count = 0
    last_length = -1
    for attempt in range(90):  # max 180 seconds
        await asyncio.sleep(2)

        poll_js = f"var responseEls = document.querySelectorAll('.model-response-text'); if (responseEls.length <= {prev_count}) {{ '0'; }} else {{ responseEls[responseEls.length - 1].textContent.trim().length.toString(); }}"
        current_length_str = await asyncio.to_thread(_run_applescript, _run_on_gemini_tab(poll_js))
        try:
            current_length = int(current_length_str)
        except ValueError:
            current_length = 0

        if current_length == 0:
            stable_count = 0
            last_length = 0
            continue

        if current_length == last_length:
            stable_count += 1
            if stable_count >= 2:  # length unchanged for 4 seconds → done
                break
        else:
            stable_count = 0
            last_length = current_length
    else:
        raise RuntimeError("Gemini 응답 시간 초과 (180초)")

    # Read response in chunks to avoid AppleScript string truncation
    # First store full text length
    len_js = f"var els = document.querySelectorAll('.model-response-text'); els[els.length - 1].textContent.trim().length.toString();"
    total_len = int(await asyncio.to_thread(_run_applescript, _run_on_gemini_tab(len_js)))

    chunks = []
    chunk_size = 4000
    for offset in range(0, total_len, chunk_size):
        chunk_js = f"var els = document.querySelectorAll('.model-response-text'); els[els.length - 1].textContent.trim().substring({offset}, {offset + chunk_size});"
        chunk = await asyncio.to_thread(_run_applescript, _run_on_gemini_tab(chunk_js))
        chunks.append(chunk)

    return "".join(chunks)


def sse_event(event_type, data):
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


HISTORY_WINDOW = 2  # keep round 1 + last N exchanges to limit token growth


def trim_history(history):
    """Keep first 2 messages (round 1 opening + response) + last HISTORY_WINDOW exchanges.
    Drops middle rounds when debate gets long. Round 1 preserved to anchor Claude's position.
    """
    first = history[:2]
    rest = history[2:]
    max_rest = HISTORY_WINDOW * 2
    if len(rest) > max_rest:
        rest = rest[-max_rest:]
    return first + rest


_LANG_REMINDER = {
    "en": "IMPORTANT: You must respond in English.",
    "ko": "중요: 반드시 한국어로 응답하세요.",
    "es": "IMPORTANTE: Debes responder en español.",
}

def build_conversation(messages, lang="en"):
    """Build only the conversation history (for Claude CLI — system passed via --system-prompt)."""
    labels = PROMPT_ROLE_LABELS.get(lang, PROMPT_ROLE_LABELS["en"])
    parts = []
    for msg in trim_history(messages):
        role = labels[0] if msg["role"] == "user" else labels[1]
        parts.append(f"[{role}]\n{msg['content']}")
    parts.append(_LANG_REMINDER.get(lang, _LANG_REMINDER["en"]))
    return "\n\n".join(parts)

def build_prompt(system, messages, lang="en"):
    """Build full prompt (system + conversation) as a single string — used for Gemini web."""
    labels = PROMPT_ROLE_LABELS.get(lang, PROMPT_ROLE_LABELS["en"])
    parts = [system]
    for msg in trim_history(messages):
        role = labels[0] if msg["role"] == "user" else labels[1]
        parts.append(f"[{role}]\n{msg['content']}")
    parts.append(_LANG_REMINDER.get(lang, _LANG_REMINDER["en"]))
    return "\n\n".join(parts)


async def index(request: Request):
    resp = templates.TemplateResponse(request, "index.html", {
        "claude_models": CLAUDE_MODELS,
        "gemini_models": GEMINI_MODELS,
    })
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


async def save_debate(request: Request):
    body = await request.json()
    topic = body.get("topic", "무제")
    ts = int(time.time())
    slug = re.sub(r'[^\w가-힣]', '_', topic)[:30].strip('_')
    filename = f"{ts}_{slug}.json"
    filepath = DEBATES_DIR / filename
    data = {
        "id": filename,
        "topic": topic,
        "timestamp": ts,
        "claude_model": body.get("claude_model", ""),
        "gemini_model": body.get("gemini_model", ""),
        "rounds": body.get("rounds", 3),
        "last_round": body.get("last_round", 0),
        "research": body.get("research", ""),
        "claude_history": body.get("claude_history", []),
        "messages": body.get("messages", []),
        "transcript": body.get("transcript", ""),
        "conclusion": body.get("conclusion", ""),
    }
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return JSONResponse({"id": filename, "success": True})


async def list_debates(request: Request):
    files = sorted(DEBATES_DIR.glob("*.json"), reverse=True)
    debates = []
    for f in files:
        try:
            d = json.loads(f.read_text())
            debates.append({
                "id": d["id"],
                "topic": d.get("topic", ""),
                "timestamp": d.get("timestamp", 0),
                "rounds": d.get("rounds", 0),
                "last_round": d.get("last_round", 0),
            })
        except Exception:
            pass
    return JSONResponse({"debates": debates})


async def load_debate_detail(request: Request):
    debate_id = request.path_params["debate_id"]
    if "/" in debate_id or ".." in debate_id:
        return JSONResponse({"error": "Invalid id"}, status_code=400)
    filepath = DEBATES_DIR / debate_id
    if not filepath.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    if request.method == "DELETE":
        filepath.unlink()
        return JSONResponse({"success": True})
    return JSONResponse(json.loads(filepath.read_text()))


async def debate(request: Request):
    body = await request.json()
    topic = body.get("topic", "")
    rounds = int(body.get("rounds", 3))
    claude_model = body.get("claude_model", "claude-opus-4-6")
    gemini_model = body.get("gemini_model", "gemini-web")
    resume_from = body.get("resume_from", None)
    new_topic = body.get("new_topic", None)
    role_mode = body.get("role_mode", None)
    anti_anchor = body.get("anti_anchor", False)
    role_swap = body.get("role_swap", False)
    fast_conclusion = body.get("fast_conclusion", True)  # use Haiku for conclusion
    lang = body.get("lang", "en")
    if lang not in ("en", "ko", "es"):
        lang = "en"

    if claude_model not in CLAUDE_MODELS:
        claude_model = "claude-opus-4-6"

    async def generate():
        claude_name = CLAUDE_MODELS.get(claude_model, claude_model)
        # Use fast model for conclusion if enabled and user isn't already on haiku
        conclusion_model = "claude-sonnet-4-6"
        gemini_name = "Gemini (Web)"
        extra_research = ""
        conclusion = ""
        messages = []  # [{agent, round, content}]
        strings = DEBATE_STRINGS.get(lang, DEBATE_STRINGS["en"])
        respond_instruction = LANG_RESPOND.get(lang, LANG_RESPOND["en"])

        # ============================================
        # Resume mode: restore saved debate context
        # ============================================
        if resume_from:
            filepath = DEBATES_DIR / resume_from
            if not filepath.exists():
                yield sse_event("error", {"message": "⚠️ Saved debate not found."})
                yield sse_event("done", {})
                return

            saved = json.loads(filepath.read_text())
            saved_topic = saved.get("topic", topic)
            active_topic = new_topic if new_topic else saved_topic
            research_data = saved.get("research", "")
            claude_history = saved.get("claude_history", [])
            transcript = saved.get("transcript", "")
            saved_messages = saved.get("messages", [])
            last_round = saved.get("last_round", 0)
            messages = list(saved_messages)

            claude_system = build_system(CLAUDE_SYSTEM_TEMPLATE, active_topic, research_data, lang=lang)

            yield sse_event("loaded", {
                "topic": saved_topic,
                "new_topic": active_topic if new_topic else None,
                "research": research_data,
                "messages": saved_messages,
                "conclusion": saved.get("conclusion", ""),
                "last_round": last_round,
            })
            await asyncio.sleep(0)

            yield sse_event("thinking", {"agent": "gemini", "round": 0, "model": strings["thinking_context"], "action": "context_restore"})
            await asyncio.sleep(0)

            topic_notice = strings["context_topic_notice"].format(new_topic=new_topic) if new_topic else ""
            context_prompt = strings["context_restore"].format(
                saved_topic=saved_topic,
                research=research_data,
                transcript=transcript,
                topic_notice=topic_notice,
                rounds=rounds,
            )

            try:
                await call_gemini_web(context_prompt, new_chat=True)
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Gemini context restore error: {e}"})
                yield sse_event("done", {})
                return

            status_msg = strings["status_restored"]
            if new_topic:
                status_msg += strings["status_new_topic"].format(topic=new_topic)
            status_msg += strings["status_continue_from"].format(n=last_round + 1)
            yield sse_event("status", {"message": status_msg})

            gemini_response = ""
            for msg in reversed(saved_messages):
                if msg["agent"] == "gemini":
                    gemini_response = msg["content"]
                    break

            for round_num in range(last_round + 1, last_round + rounds + 1):
                yield sse_event("thinking", {"agent": "claude", "round": round_num, "model": claude_name, "action": "rebuttal"})
                await asyncio.sleep(0)

                extra_context = ""
                if extra_research:
                    extra_context = strings["extra_research_label"] + extra_research
                    extra_research = ""

                topic_prefix = strings["deeper_prefix"].format(topic=active_topic) if new_topic else ""
                claude_history.append({"role": "user", "content": f"{topic_prefix}[Gemini]\n{gemini_response}{extra_context}"})
                resume_prompt = build_conversation(claude_history, lang) + strings["rebuttal_suffix"]

                try:
                    claude_response = await call_claude(resume_prompt, claude_model, system_prompt=claude_system)
                except RateLimitError as e:
                    reset = f" (reset: {e.reset_info})" if e.reset_info else ""
                    yield sse_event("error", {"message": f"⚠️ Claude rate limit exceeded{reset}"})
                    yield sse_event("done", {})
                    return
                except Exception as e:
                    yield sse_event("error", {"message": f"⚠️ Claude error: {e}"})
                    yield sse_event("done", {})
                    return

                claude_response, extra_research = await _handle_data_request(claude_response, research_data, lang, claude_model)
                claude_history.append({"role": "assistant", "content": claude_response})
                transcript += f"## Claude (Round {round_num})\n{claude_response}\n\n"
                messages.append({"agent": "claude", "round": round_num, "content": claude_response})
                yield sse_event("message", {"agent": "claude", "round": round_num, "phase": "rebuttal", "content": claude_response})

                yield sse_event("thinking", {"agent": "gemini", "round": round_num, "model": gemini_name, "action": "rebuttal"})
                await asyncio.sleep(0)

                topic_prefix_g = strings["deeper_prefix"].format(topic=active_topic) if new_topic else ""
                gemini_rebuttal_text = topic_prefix_g + strings["gemini_rebuttal"].format(response=claude_response)

                try:
                    gemini_response = await call_gemini_web(gemini_rebuttal_text, new_chat=False)
                except Exception as e:
                    yield sse_event("error", {"message": f"⚠️ Gemini error: {e}"})
                    yield sse_event("done", {})
                    return

                transcript += f"## Gemini (Round {round_num})\n{gemini_response}\n\n"
                messages.append({"agent": "gemini", "round": round_num, "content": gemini_response})
                yield sse_event("message", {"agent": "gemini", "round": round_num, "phase": "rebuttal", "content": gemini_response})

            yield sse_event("thinking", {"agent": "conclusion", "round": 0, "model": claude_name, "action": "conclusion"})
            await asyncio.sleep(0)

            conclusion_prompt = CONCLUSION_PROMPT_TEMPLATE.format(topic=active_topic, transcript=transcript, respond_instruction=respond_instruction)
            try:
                conclusion = await call_claude(conclusion_prompt, conclusion_model)
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Claude conclusion error: {e}"})
                yield sse_event("done", {})
                return

            yield sse_event("conclusion", {"content": conclusion})
            yield sse_event("done", {
                "save_data": {
                    "topic": active_topic,
                    "claude_model": claude_model,
                    "gemini_model": gemini_model,
                    "rounds": last_round + rounds,
                    "last_round": last_round + rounds,
                    "research": research_data,
                    "claude_history": claude_history,
                    "messages": messages,
                    "transcript": transcript,
                    "conclusion": conclusion,
                }
            })
            return

        # ============================================
        # Normal flow
        # ============================================
        claude_history = []
        gemini_history = []
        transcript = ""
        research_data = ""

        # Phase 0: Gemini researches the topic via web search
        yield sse_event("thinking", {"agent": "gemini", "round": 0, "model": strings["thinking_research"], "action": "research"})
        await asyncio.sleep(0)

        try:
            research_prompt = GEMINI_RESEARCH_PROMPT.get(lang, GEMINI_RESEARCH_PROMPT["en"]).format(topic=topic)
            research_data = await call_gemini_web(research_prompt, new_chat=True)
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Research error: {e}"})
            yield sse_event("done", {})
            return

        yield sse_event("research", {"content": research_data})

        # Resolve role names and system prompts
        role = ROLE_PAIRS.get(role_mode) if role_mode else None
        if role:
            names = role["names"].get(lang, role["names"]["en"])
            if role_swap:
                claude_role_name = names[1]
                gemini_role_name = names[0]
                claude_role_desc = role["gemini_role"]
                gemini_role_desc = role["claude_role"]
            else:
                claude_role_name = names[0]
                gemini_role_name = names[1]
                claude_role_desc = role["claude_role"]
                gemini_role_desc = role["gemini_role"]
        else:
            claude_role_name = claude_name
            gemini_role_name = gemini_name
            claude_role_desc = None
            gemini_role_desc = None

        claude_system = build_system(CLAUDE_SYSTEM_TEMPLATE, topic, research_data, lang=lang, role_desc=claude_role_desc)
        gemini_system = build_system(GEMINI_SYSTEM_TEMPLATE, topic, research_data, lang=lang, role_desc=gemini_role_desc)

        opening_prompt = strings["opening"].format(topic=topic)

        # Phase 1: Opening statements

        # Claude Round 1
        yield sse_event("thinking", {"agent": "claude", "round": 1, "model": claude_role_name, "action": "analysis"})
        await asyncio.sleep(0)

        claude_history.append({"role": "user", "content": opening_prompt})
        try:
            prompt = build_conversation(claude_history, lang)
            claude_response = await call_claude(prompt, claude_model, system_prompt=claude_system)
        except RateLimitError as e:
            reset = f" (reset: {e.reset_info})" if e.reset_info else ""
            yield sse_event("error", {"message": f"⚠️ Claude rate limit exceeded{reset}"})
            yield sse_event("done", {})
            return
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Claude error: {e}"})
            yield sse_event("done", {})
            return

        claude_response, extra_research = await _handle_data_request(claude_response, research_data, lang, claude_model)
        claude_history.append({"role": "assistant", "content": claude_response})
        transcript += f"## Claude (Round 1 - Opening)\n{claude_response}\n\n"
        messages.append({"agent": "claude", "round": 1, "role": claude_role_name, "content": claude_response})
        yield sse_event("message", {"agent": "claude", "round": 1, "phase": "opening",
                                    "role": claude_role_name, "content": claude_response})

        # Gemini Round 1
        # anti_anchor=True: independent opening (Gemini doesn't see Claude's response)
        # anti_anchor=False: sequential (Gemini responds directly to Claude's opening)
        yield sse_event("thinking", {"agent": "gemini", "round": 1, "model": gemini_role_name, "action": "analysis"})
        await asyncio.sleep(0)

        if anti_anchor:
            gemini_opening = opening_prompt
        else:
            gemini_opening = strings["gemini_opening_response"].format(response=claude_response)

        gemini_history.append({"role": "user", "content": gemini_opening})
        try:
            gemini_prompt = build_prompt(gemini_system, gemini_history, lang)
            gemini_response = await call_gemini_web(gemini_prompt, new_chat=True)
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Gemini error: {e}"})
            yield sse_event("done", {})
            return

        gemini_history.append({"role": "assistant", "content": gemini_response})
        transcript += f"## Gemini (Round 1 - Opening)\n{gemini_response}\n\n"
        messages.append({"agent": "gemini", "round": 1, "role": gemini_role_name, "content": gemini_response})
        yield sse_event("message", {"agent": "gemini", "round": 1, "phase": "opening",
                                    "role": gemini_role_name, "content": gemini_response})

        # Phase 2: Debate rounds
        for round_num in range(2, rounds + 1):
            yield sse_event("thinking", {"agent": "claude", "round": round_num, "model": claude_role_name, "action": "rebuttal"})
            await asyncio.sleep(0)

            extra_context = ""
            if extra_research:
                extra_context = strings["extra_research_label"] + extra_research
                extra_research = ""

            claude_history.append({"role": "user", "content": f"[Gemini]\n{gemini_response}{extra_context}"})
            current_prompt = build_conversation(claude_history, lang) + strings["rebuttal_suffix"]

            try:
                claude_response = await call_claude(current_prompt, claude_model, system_prompt=claude_system)
            except RateLimitError as e:
                reset = f" (reset: {e.reset_info})" if e.reset_info else ""
                yield sse_event("error", {"message": f"⚠️ Claude rate limit exceeded{reset}. Debate progress saved."})
                yield sse_event("done", {})
                return
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Claude error: {e}"})
                yield sse_event("done", {})
                return

            claude_response, extra_research = await _handle_data_request(claude_response, research_data, lang, claude_model)
            claude_history.append({"role": "assistant", "content": claude_response})
            transcript += f"## Claude (Round {round_num})\n{claude_response}\n\n"
            messages.append({"agent": "claude", "round": round_num, "role": claude_role_name, "content": claude_response})
            yield sse_event("message", {"agent": "claude", "round": round_num, "phase": "rebuttal",
                                        "role": claude_role_name, "content": claude_response})

            yield sse_event("thinking", {"agent": "gemini", "round": round_num, "model": gemini_role_name, "action": "rebuttal"})
            await asyncio.sleep(0)

            gemini_rebuttal_text = strings["gemini_rebuttal"].format(response=claude_response)
            gemini_history.append({"role": "user", "content": gemini_rebuttal_text})

            try:
                gemini_response = await call_gemini_web(gemini_rebuttal_text, new_chat=False)
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Gemini error: {e}"})
                yield sse_event("done", {})
                return

            gemini_history.append({"role": "assistant", "content": gemini_response})
            transcript += f"## Gemini (Round {round_num})\n{gemini_response}\n\n"
            messages.append({"agent": "gemini", "round": round_num, "role": gemini_role_name, "content": gemini_response})
            yield sse_event("message", {"agent": "gemini", "round": round_num, "phase": "rebuttal",
                                        "role": gemini_role_name, "content": gemini_response})

        # Phase 3: Conclusion
        yield sse_event("thinking", {"agent": "conclusion", "round": 0, "model": claude_name, "action": "conclusion"})
        await asyncio.sleep(0)

        conclusion_prompt = CONCLUSION_PROMPT_TEMPLATE.format(topic=topic, transcript=transcript, respond_instruction=respond_instruction)
        try:
            conclusion = await call_claude(conclusion_prompt, conclusion_model)
        except RateLimitError as e:
            reset = f" (reset: {e.reset_info})" if e.reset_info else ""
            yield sse_event("error", {"message": f"⚠️ Claude rate limit exceeded{reset}. Skipping conclusion."})
            yield sse_event("done", {})
            return
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Claude conclusion error: {e}"})
            yield sse_event("done", {})
            return

        yield sse_event("conclusion", {"content": conclusion})
        yield sse_event("done", {
            "save_data": {
                "topic": topic,
                "claude_model": claude_model,
                "gemini_model": gemini_model,
                "rounds": rounds,
                "last_round": rounds,
                "research": research_data,
                "claude_history": claude_history,
                "messages": messages,
                "transcript": transcript,
                "conclusion": conclusion,
            }
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app = Starlette(
    routes=[
        Route("/", index),
        Route("/debate", debate, methods=["POST"]),
        Route("/save", save_debate, methods=["POST"]),
        Route("/debates", list_debates, methods=["GET"]),
        Route("/debates/{debate_id}", load_debate_detail, methods=["GET", "DELETE"]),
    ],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=5050, reload=True)
