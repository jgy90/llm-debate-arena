import os
import json
import asyncio
import re
import subprocess
import base64
import time
from pathlib import Path

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

GEMINI_RESEARCH_PROMPT = """다음 주제에 대해 최신 데이터와 자료를 조사해주세요.

주제: {topic}

다음을 포함해서 조사해주세요:
- 최신 통계, 수치, 데이터
- 관련 뉴스 및 전문가 의견
- 핵심 팩트와 근거 자료
- 다양한 관점에서의 분석 자료

조사 결과만 객관적으로 정리해주세요. 한국어로 응답하세요."""

CLAUDE_SYSTEM_TEMPLATE = """Debate: Claude vs Gemini | 주제: {topic}

[참고 자료]
{research}

규칙: 한국어 응답. 자료의 구체적 수치를 근거로 사용. 300-500자. 추가 자료 필요 시 마지막 줄에 [자료요청]: <내용>."""

GEMINI_SYSTEM_TEMPLATE = """Debate: Gemini vs Claude | 주제: {topic}

[참고 자료]
{research}

규칙: 한국어 응답. 자료의 구체적 수치를 근거로 사용. 웹 검색으로 추가 근거 보강 가능. 300-500자."""

ANTI_SYCOPHANCY_RULES = """
- 상대방 주장에 쉽게 동의하지 마세요. 동의하지 않는다면 구체적 근거와 함께 명확히 반론하세요.
- 압박을 받아도 새로운 증거나 논리 없이는 기존 입장을 포기하지 마세요.
- 부분 동의는 허용하지만, 여전히 동의하지 않는 핵심 지점을 반드시 논증하세요."""

ROLE_PAIRS = {
    "bull_bear": {
        "claude_name": "강세론자 (Bull)",
        "gemini_name": "약세론자 (Bear)",
        "claude_role": "당신은 강세론자(Bull) 역할입니다. 긍정적 전망, 성장 가능성, 기회 요인에 초점을 맞춰 주장하세요. 비관적 시각에는 강하게 반론하세요.",
        "gemini_role": "당신은 약세론자(Bear) 역할입니다. 리스크, 하락 요인, 위협 요소에 초점을 맞춰 주장하세요. 낙관적 시각에는 강하게 반론하세요.",
    },
    "optimist_pessimist": {
        "claude_name": "낙관론자",
        "gemini_name": "비관론자",
        "claude_role": "당신은 낙관론자 역할입니다. 긍정적 측면, 기회, 발전 가능성을 중심으로 주장하세요.",
        "gemini_role": "당신은 비관론자 역할입니다. 문제점, 위험, 부정적 측면을 중심으로 주장하세요.",
    },
    "pro_con": {
        "claude_name": "찬성측",
        "gemini_name": "반대측",
        "claude_role": "당신은 찬성측 역할입니다. 이 주제를 강력히 지지하는 논거를 제시하세요.",
        "gemini_role": "당신은 반대측 역할입니다. 이 주제에 강력히 반대하는 논거를 제시하세요.",
    },
    "tradition_innovation": {
        "claude_name": "전통적 관점",
        "gemini_name": "혁신적 관점",
        "claude_role": "당신은 전통적·보수적 관점의 역할입니다. 검증된 방식, 안정성, 기존 질서의 가치를 강조하세요.",
        "gemini_role": "당신은 혁신적·진보적 관점의 역할입니다. 변화, 혁신, 새로운 패러다임의 필요성을 강조하세요.",
    },
}


RESEARCH_MAX_CHARS = 2000  # truncate research in system prompt to save tokens
CLAUDE_FAST_MODEL = "claude-haiku-4-5-20251001"  # used for simple tasks (conclusion)


def build_system(base_template, topic, research, role_desc=None):
    """Build system prompt with optional role + always-on anti-sycophancy.
    Research is truncated to RESEARCH_MAX_CHARS to limit token usage.
    """
    truncated = research[:RESEARCH_MAX_CHARS] + "\n...(이하 생략)" if len(research) > RESEARCH_MAX_CHARS else research
    system = base_template.format(topic=topic, research=truncated)
    if role_desc:
        system += f"\n\n[역할 지정]\n{role_desc}"
    system += ANTI_SYCOPHANCY_RULES
    return system


CONCLUSION_PROMPT_TEMPLATE = """You are a neutral moderator summarizing a debate between Claude (Anthropic) and Gemini (Google).

Topic: {topic}

Full debate transcript:
{transcript}

Please provide a comprehensive conclusion in Korean that:
1. Summarizes the key points of agreement
2. Summarizes the key points of disagreement
3. Synthesizes the strongest arguments from both sides
4. Provides a balanced final assessment

Format with clear headers and be thorough but concise."""


async def _handle_data_request(claude_response, existing_research):
    """Parse Claude's response for [자료요청]: lines and fetch additional data via Gemini."""
    lines = claude_response.split("\n")
    request_line = None
    for i, line in enumerate(lines):
        if line.strip().startswith("[자료요청]:"):
            request_line = line.strip()[len("[자료요청]:"):].strip()
            # Remove the request line from response
            clean_lines = lines[:i]
            # Keep any lines after the request that aren't empty
            remaining = [l for l in lines[i+1:] if l.strip()]
            clean_lines.extend(remaining)
            claude_response = "\n".join(clean_lines).strip()
            break

    if not request_line:
        return claude_response, ""

    try:
        extra_prompt = f"다음 주제에 대해 추가 자료를 조사해주세요:\n\n{request_line}\n\n기존 조사 내용을 참고하되, 새로운 데이터와 자료를 중심으로 조사해주세요. 한국어로 응답하세요."
        extra_research = await call_gemini_web(extra_prompt)
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


async def call_claude(prompt, model="claude-opus-4-6"):
    """Call Claude via CLI (uses Pro plan quota)."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--model", model,
        "--output-format", "text",
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


def _run_on_gemini_tab(js: str) -> str:
    """Build AppleScript that runs JS on the Gemini tab (not the active tab)."""
    escaped_js = js.replace('"', '\\"')
    return f'''
tell application "Whale"
    tell front window
        set geminiTab to 0
        set tabCount to count of tabs
        repeat with i from 1 to tabCount
            if URL of tab i contains "gemini.google.com" then
                set geminiTab to i
                exit repeat
            end if
        end repeat
        if geminiTab > 0 then
            set result to execute tab geminiTab javascript "{escaped_js}"
        else
            set result to "NO_GEMINI_TAB"
        end if
    end tell
    return result
end tell
'''


async def _ensure_gemini_tab(new_chat: bool = True):
    """Find or create a Gemini tab, optionally navigate to fresh chat."""
    if new_chat:
        # Close any existing Gemini tab and open a fresh one, then switch back
        setup = '''
tell application "Whale"
    tell front window
        set activeIdx to active tab index
        -- close existing gemini tabs
        set tabCount to count of tabs
        repeat with i from tabCount to 1 by -1
            if URL of tab i contains "gemini.google.com" then
                close tab i
                if i < activeIdx then
                    set activeIdx to activeIdx - 1
                end if
            end if
        end repeat
        -- open fresh gemini tab
        make new tab with properties {URL:"https://gemini.google.com/app"}
        -- switch back to original tab
        set active tab index to activeIdx
    end tell
end tell
'''
        await asyncio.to_thread(_run_applescript, setup)
    else:
        # Just make sure a Gemini tab exists
        check = '''
tell application "Whale"
    tell front window
        set tabCount to count of tabs
        repeat with i from 1 to tabCount
            if URL of tab i contains "gemini.google.com" then
                return "FOUND"
            end if
        end repeat
        -- no gemini tab, create one
        set activeIdx to active tab index
        make new tab with properties {URL:"https://gemini.google.com/app"}
        set active tab index to activeIdx
        return "CREATED"
    end tell
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

    # Briefly activate Gemini tab to type & send, then switch back
    # (inactive tabs have unreliable execCommand and button rendering)
    type_and_send = f'''
tell application "Whale"
    tell front window
        set origIdx to active tab index
        set geminiTab to 0
        set tabCount to count of tabs
        repeat with i from 1 to tabCount
            if URL of tab i contains "gemini.google.com" then
                set geminiTab to i
                exit repeat
            end if
        end repeat
        if geminiTab > 0 then
            set active tab index to geminiTab
            delay 0.5
            execute tab geminiTab javascript "var t = decodeURIComponent(Array.prototype.map.call(atob('{b64}'),function(c){{return '%'+('00'+c.charCodeAt(0).toString(16)).slice(-2);}}).join('')); var e = document.querySelector('.ql-editor[role=textbox]'); e.focus(); document.execCommand('selectAll',false,null); document.execCommand('insertText',false,t); 'TYPED';"
            delay 1
            execute tab geminiTab javascript "var btns = document.querySelectorAll('button[aria-label]'); for(var i=0;i<btns.length;i++){{ if(btns[i].getAttribute('aria-label').indexOf('보내기')>=0 && !btns[i].disabled){{ btns[i].click(); break; }} }}"
            delay 0.5
            set active tab index to origIdx
        end if
    end tell
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


def build_prompt(system, messages):
    parts = [system]
    for msg in trim_history(messages):
        role = "상대방" if msg["role"] == "user" else "나"
        parts.append(f"[{role}]\n{msg['content']}")
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

    if claude_model not in CLAUDE_MODELS:
        claude_model = "claude-opus-4-6"

    async def generate():
        claude_name = CLAUDE_MODELS.get(claude_model, claude_model)
        # Use fast model for conclusion if enabled and user isn't already on haiku
        conclusion_model = CLAUDE_FAST_MODEL if fast_conclusion and claude_model != CLAUDE_FAST_MODEL else claude_model
        gemini_name = "Gemini Pro (웹)"
        extra_research = ""
        conclusion = ""
        messages = []  # [{agent, round, content}]

        # ============================================
        # Resume mode: restore saved debate context
        # ============================================
        if resume_from:
            filepath = DEBATES_DIR / resume_from
            if not filepath.exists():
                yield sse_event("error", {"message": "⚠️ 저장된 토론을 찾을 수 없습니다."})
                yield sse_event("done", {})
                return

            saved = json.loads(filepath.read_text())
            saved_topic = saved.get("topic", topic)
            active_topic = new_topic if new_topic else saved_topic  # topic for new rounds
            research_data = saved.get("research", "")
            claude_history = saved.get("claude_history", [])
            transcript = saved.get("transcript", "")
            saved_messages = saved.get("messages", [])
            last_round = saved.get("last_round", 0)
            messages = list(saved_messages)

            # Claude system uses active_topic so it knows the new focus
            claude_system = CLAUDE_SYSTEM_TEMPLATE.format(topic=active_topic, research=research_data)

            # Emit loaded event so frontend can restore UI
            yield sse_event("loaded", {
                "topic": saved_topic,
                "new_topic": active_topic if new_topic else None,
                "research": research_data,
                "messages": saved_messages,
                "conclusion": saved.get("conclusion", ""),
                "last_round": last_round,
            })
            await asyncio.sleep(0)

            # Restore Gemini context in a fresh chat
            yield sse_event("thinking", {"agent": "gemini", "round": 0, "model": "Gemini 컨텍스트 복원"})
            await asyncio.sleep(0)

            topic_notice = ""
            if new_topic:
                topic_notice = f"\n\n이번에는 심화 주제로 토론을 이어갑니다: {new_topic}"

            context_prompt = f"""이전 토론을 이어서 진행합니다.

기존 주제: {saved_topic}

이전 자료 조사 결과:
{research_data}

지금까지의 토론 내용:
{transcript}{topic_notice}

이제 {rounds}라운드 더 이어서 진행합니다. 준비되면 "네, 확인했습니다. 계속 진행하겠습니다."라고 답해주세요."""

            try:
                await call_gemini_web(context_prompt, new_chat=True)
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Gemini 컨텍스트 복원 오류: {e}"})
                yield sse_event("done", {})
                return

            status_msg = f"이전 토론 복원 완료."
            if new_topic:
                status_msg += f" 새 주제: {new_topic}"
            status_msg += f" {last_round + 1}라운드부터 계속합니다."
            yield sse_event("status", {"message": status_msg})

            # Get last Gemini response to use as starting point
            gemini_response = ""
            for msg in reversed(saved_messages):
                if msg["agent"] == "gemini":
                    gemini_response = msg["content"]
                    break

            # Run additional rounds
            for round_num in range(last_round + 1, last_round + rounds + 1):
                # Claude
                yield sse_event("thinking", {"agent": "claude", "round": round_num, "model": claude_name})
                await asyncio.sleep(0)

                extra_context = ""
                if extra_research:
                    extra_context = f"\n\n[추가 조사 자료]\n{extra_research}"
                    extra_research = ""

                topic_prefix = f"[심화 주제: {active_topic}]\n\n" if new_topic else ""
                claude_history.append({"role": "user", "content": f"{topic_prefix}[Gemini]\n{gemini_response}{extra_context}"})
                resume_prompt = build_prompt(claude_system, claude_history) + "\n\n반론하고 새 관점을 추가하세요."

                try:
                    claude_response = await call_claude(resume_prompt, claude_model)
                except RateLimitError as e:
                    reset = f" (리셋: {e.reset_info})" if e.reset_info else ""
                    yield sse_event("error", {"message": f"⚠️ Claude 토큰 한도 초과{reset}"})
                    yield sse_event("done", {})
                    return
                except Exception as e:
                    yield sse_event("error", {"message": f"⚠️ Claude 오류: {e}"})
                    yield sse_event("done", {})
                    return

                claude_response, extra_research = await _handle_data_request(claude_response, research_data)
                claude_history.append({"role": "assistant", "content": claude_response})
                transcript += f"## Claude ({round_num}라운드)\n{claude_response}\n\n"
                messages.append({"agent": "claude", "round": round_num, "content": claude_response})
                yield sse_event("message", {"agent": "claude", "round": round_num, "phase": "rebuttal", "content": claude_response})

                # Gemini
                yield sse_event("thinking", {"agent": "gemini", "round": round_num, "model": gemini_name})
                await asyncio.sleep(0)

                topic_prefix_g = f"[심화 주제: {active_topic}]\n\n" if new_topic else ""
                gemini_rebuttal = f"{topic_prefix_g}상대방(Claude)의 주장입니다:\n\n{claude_response}\n\n이에 대해 반론하거나, 동의하는 부분은 보충하고, 새로운 관점을 추가해주세요."

                try:
                    gemini_response = await call_gemini_web(gemini_rebuttal, new_chat=False)
                except Exception as e:
                    yield sse_event("error", {"message": f"⚠️ Gemini 오류: {e}"})
                    yield sse_event("done", {})
                    return

                transcript += f"## Gemini ({round_num}라운드)\n{gemini_response}\n\n"
                messages.append({"agent": "gemini", "round": round_num, "content": gemini_response})
                yield sse_event("message", {"agent": "gemini", "round": round_num, "phase": "rebuttal", "content": gemini_response})

            # Conclusion
            yield sse_event("thinking", {"agent": "conclusion", "round": 0, "model": claude_name})
            await asyncio.sleep(0)

            conclusion_prompt = CONCLUSION_PROMPT_TEMPLATE.format(topic=active_topic, transcript=transcript)
            try:
                conclusion = await call_claude(conclusion_prompt, conclusion_model)
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Claude 결론 생성 오류: {e}"})
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

        # Phase 0: Gemini researches the topic
        yield sse_event("thinking", {"agent": "gemini", "round": 0, "model": "Gemini 리서치"})
        await asyncio.sleep(0)

        try:
            research_prompt = GEMINI_RESEARCH_PROMPT.format(topic=topic)
            research_data = await call_gemini_web(research_prompt)
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Gemini 자료조사 오류: {e}"})
            yield sse_event("done", {})
            return

        yield sse_event("research", {"content": research_data})

        # Resolve role names and system prompts
        role = ROLE_PAIRS.get(role_mode) if role_mode else None
        if role:
            if role_swap:
                claude_role_name = role["gemini_name"]
                gemini_role_name = role["claude_name"]
                claude_role_desc = role["gemini_role"]
                gemini_role_desc = role["claude_role"]
            else:
                claude_role_name = role["claude_name"]
                gemini_role_name = role["gemini_name"]
                claude_role_desc = role["claude_role"]
                gemini_role_desc = role["gemini_role"]
        else:
            claude_role_name = claude_name
            gemini_role_name = gemini_name
            claude_role_desc = None
            gemini_role_desc = None

        claude_system = build_system(CLAUDE_SYSTEM_TEMPLATE, topic, research_data, claude_role_desc)
        gemini_system = build_system(GEMINI_SYSTEM_TEMPLATE, topic, research_data, gemini_role_desc)

        opening_prompt = f"주제: {topic}\n\n이 주제에 대해 당신의 분석과 입장을 제시해주세요. 현재 상황 분석, 주요 요인, 전망을 포함해주세요."

        # Phase 1: Opening statements

        # Claude Round 1
        yield sse_event("thinking", {"agent": "claude", "round": 1, "model": claude_role_name})
        await asyncio.sleep(0)

        claude_history.append({"role": "user", "content": opening_prompt})
        try:
            prompt = build_prompt(claude_system, claude_history)
            claude_response = await call_claude(prompt, claude_model)
        except RateLimitError as e:
            reset = f" (리셋: {e.reset_info})" if e.reset_info else ""
            yield sse_event("error", {"message": f"⚠️ Claude 토큰 한도 초과{reset}"})
            yield sse_event("done", {})
            return
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Claude 오류: {e}"})
            yield sse_event("done", {})
            return

        claude_response, extra_research = await _handle_data_request(claude_response, research_data)
        claude_history.append({"role": "assistant", "content": claude_response})
        transcript += f"## Claude (1라운드 - 개회)\n{claude_response}\n\n"
        messages.append({"agent": "claude", "round": 1, "role": claude_role_name, "content": claude_response})
        yield sse_event("message", {"agent": "claude", "round": 1, "phase": "opening",
                                    "role": claude_role_name, "content": claude_response})

        # Gemini Round 1
        # anti_anchor=True: independent opening (Gemini doesn't see Claude's response)
        # anti_anchor=False: sequential (Gemini responds directly to Claude's opening)
        yield sse_event("thinking", {"agent": "gemini", "round": 1, "model": gemini_role_name})
        await asyncio.sleep(0)

        if anti_anchor:
            gemini_opening = opening_prompt
        else:
            gemini_opening = f"상대방(Claude)의 개회 발언입니다:\n\n{claude_response}\n\n이에 대해 당신의 입장을 제시하고 반론하세요."

        gemini_history.append({"role": "user", "content": gemini_opening})
        try:
            gemini_prompt = build_prompt(gemini_system, gemini_history)
            gemini_response = await call_gemini_web(gemini_prompt, new_chat=True)
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Gemini 오류: {e}"})
            yield sse_event("done", {})
            return

        gemini_history.append({"role": "assistant", "content": gemini_response})
        transcript += f"## Gemini (1라운드 - 개회)\n{gemini_response}\n\n"
        messages.append({"agent": "gemini", "round": 1, "role": gemini_role_name, "content": gemini_response})
        yield sse_event("message", {"agent": "gemini", "round": 1, "phase": "opening",
                                    "role": gemini_role_name, "content": gemini_response})

        # Phase 2: Debate rounds
        for round_num in range(2, rounds + 1):
            # Claude responds
            yield sse_event("thinking", {"agent": "claude", "round": round_num, "model": claude_role_name})
            await asyncio.sleep(0)

            extra_context = ""
            if extra_research:
                extra_context = f"\n\n[추가 조사 자료]\n{extra_research}"
                extra_research = ""

            # Store compact version in history; send full instruction only for current turn
            claude_history.append({"role": "user", "content": f"[Gemini]\n{gemini_response}{extra_context}"})
            current_prompt = build_prompt(claude_system, claude_history) + "\n\n반론하고 새 관점을 추가하세요."

            try:
                claude_response = await call_claude(current_prompt, claude_model)
            except RateLimitError as e:
                reset = f" (리셋: {e.reset_info})" if e.reset_info else ""
                yield sse_event("error", {"message": f"⚠️ Claude 토큰 한도 초과{reset}. 현재까지의 토론 내용을 확인하세요."})
                yield sse_event("done", {})
                return
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Claude 오류: {e}"})
                yield sse_event("done", {})
                return

            claude_response, extra_research = await _handle_data_request(claude_response, research_data)
            claude_history.append({"role": "assistant", "content": claude_response})
            transcript += f"## Claude ({round_num}라운드)\n{claude_response}\n\n"
            messages.append({"agent": "claude", "round": round_num, "role": claude_role_name, "content": claude_response})
            yield sse_event("message", {"agent": "claude", "round": round_num, "phase": "rebuttal",
                                        "role": claude_role_name, "content": claude_response})

            # Gemini responds
            yield sse_event("thinking", {"agent": "gemini", "round": round_num, "model": gemini_role_name})
            await asyncio.sleep(0)

            gemini_rebuttal = f"상대방(Claude)의 주장입니다:\n\n{claude_response}\n\n이에 대해 반론하거나, 동의하는 부분은 보충하고, 새로운 관점을 추가해주세요."
            gemini_history.append({"role": "user", "content": gemini_rebuttal})

            try:
                gemini_response = await call_gemini_web(gemini_rebuttal, new_chat=False)
            except Exception as e:
                yield sse_event("error", {"message": f"⚠️ Gemini 오류: {e}"})
                yield sse_event("done", {})
                return

            gemini_history.append({"role": "assistant", "content": gemini_response})
            transcript += f"## Gemini ({round_num}라운드)\n{gemini_response}\n\n"
            messages.append({"agent": "gemini", "round": round_num, "role": gemini_role_name, "content": gemini_response})
            yield sse_event("message", {"agent": "gemini", "round": round_num, "phase": "rebuttal",
                                        "role": gemini_role_name, "content": gemini_response})

        # Phase 3: Conclusion
        yield sse_event("thinking", {"agent": "conclusion", "round": 0, "model": claude_name})
        await asyncio.sleep(0)

        conclusion_prompt = CONCLUSION_PROMPT_TEMPLATE.format(topic=topic, transcript=transcript)
        try:
            conclusion = await call_claude(conclusion_prompt, conclusion_model)
        except RateLimitError as e:
            reset = f" (리셋: {e.reset_info})" if e.reset_info else ""
            yield sse_event("error", {"message": f"⚠️ Claude 토큰 한도 초과{reset}. 결론 생성을 건너뜁니다."})
            yield sse_event("done", {})
            return
        except Exception as e:
            yield sse_event("error", {"message": f"⚠️ Claude 결론 생성 오류: {e}"})
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
