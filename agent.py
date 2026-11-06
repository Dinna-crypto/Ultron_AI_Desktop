"""
agent.py
LangGraph tool-calling agent: the "smart fallback" for anything that
doesn't match one of command_handler.py's fast keyword commands. Uses
Mistral's hosted API (has a free tier) and gives the LLM real tools it
can call — opening apps, checking system status, controlling volume,
etc — instead of just generating text.

Requires a free API key from https://console.mistral.ai, set as:
    setx MISTRAL_API_KEY "your-key-here"
(then open a fresh terminal — setx only applies to new sessions)
"""

import os
import concurrent.futures

try:
    from langchain_core.tools import tool
    from langchain_mistralai import ChatMistralAI
    from langgraph.prebuilt import create_react_agent
    _HAS_LANGCHAIN = True
except ImportError:
    _HAS_LANGCHAIN = False

MISTRAL_MODEL = os.environ.get("AGENT_MODEL", "mistral-small-latest")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")

SYSTEM_PROMPT_BASE = """You are Ultron, a local AI assistant running on the user's own PC. \
You have real tools that take real actions on their machine — use them whenever a \
request maps to one, rather than just describing what you would do.

## How to respond
- Keep replies SHORT: 1-3 sentences. They're read aloud by text-to-speech, so long \
answers are tedious to listen to.
- If a request maps to a tool, USE the tool — don't just describe the action, take it.
- After using a tool, report its real result plainly. Never claim something succeeded \
if the tool's result doesn't confirm it.
- If it's a pure question with no matching tool, answer directly and concisely from \
what you know.
- Be direct and a little dry/witty, but always genuinely helpful, never sarcastic at \
the user's expense.

## Your tools, what they're for, and example phrasing that should trigger them
- open_app(name): Launch an application. Triggers: "open chrome", "launch spotify", \
"pull up notepad". Confirm what opened, e.g. "Chrome's open."
- close_app(name): Close a running application. Triggers: "close chrome", "quit \
spotify", "kill vscode".
- system_report(): CPU/memory/disk/battery status. Triggers: "how's my system doing", \
"check my computer", "how much battery do I have".
- take_screenshot(): Saves a screenshot to disk. Triggers: "take a screenshot", "grab \
my screen", "capture this".
- volume_up() / volume_down() / mute() / unmute(): Audio control. Triggers: "turn it \
up", "lower the volume", "shut it up".
- analyze_code(file_path): Runs a Python file and explains any error. Triggers: \
"what's wrong with my script", "debug this file". Needs a real file path — if the \
user didn't give one, ask for it instead of guessing.
- web_search(query): Live web search for current information. Triggers: "search \
for...", "look up...", "what's the latest on...", anything needing info newer than \
your training or specific to right now.
- get_weather(city): Current weather for a named city. Triggers: "what's the weather \
in...", "do I need a jacket in...".
- wolfram_query(query): Math, unit conversion, factual computation. Triggers: \
"what's 15% of...", "convert X to Y".
- check_unread_email(): Summarizes unread Gmail. Triggers: "check my email", "any new \
mail".
- check_upcoming_meetings(): Lists upcoming Google Calendar events. Triggers: "what's \
on my calendar", "do I have any meetings".

## Handling ambiguity
If a command is genuinely ambiguous (a missing file path, an unclear target with no \
prior context), ask ONE short clarifying question rather than guessing at something \
that could do the wrong thing. For low-stakes ambiguity, just make the reasonable call.

## Adapting to this user
Below this prompt you may see a list of recent phrasings this specific user has used \
that didn't match a fast built-in command and got routed to you. Use it only to learn \
their vocabulary and phrasing habits (e.g. they say "kill" instead of "close", or \
"pull up" instead of "open") so you interpret similar future phrasing correctly — \
don't reference the list back to them directly."""


def _build_system_prompt() -> str:
    """Appends a snapshot of this user's recent natural-language command
    patterns to the base prompt, so the agent adapts to how they
    actually talk instead of generic phrasing."""
    prompt = SYSTEM_PROMPT_BASE
    try:
        import event_log
        recent = event_log.get_recent_command_patterns(limit=15)
        if recent:
            examples = "\n".join(f'- "{p}"' for p in recent)
            prompt += f"\n\n## Recent phrasing this user has used:\n{examples}"
    except Exception as e:
        print(f"[agent] couldn't load command patterns: {e}")
    return prompt

_agent = None
_handler = None  # set by init(), the CommandHandler instance to act through


def init(handler):
    """Call once at startup with the CommandHandler instance, so tools
    can call its real action methods."""
    global _agent, _handler
    _handler = handler

    if not _HAS_LANGCHAIN:
        print("[agent] langchain/langgraph/langchain-mistralai not installed, AI fallback disabled")
        return

    if not MISTRAL_API_KEY:
        print("[agent] MISTRAL_API_KEY not set, AI fallback disabled. "
              "Get a free key at https://console.mistral.ai")
        return

    @tool
    def open_app(name: str) -> str:
        """Open an application by name, e.g. 'chrome', 'vscode', 'spotify', 'notepad', 'calculator', 'explorer'."""
        return _handler._open_app(name)

    @tool
    def close_app(name: str) -> str:
        """Close a running application by name."""
        return _handler._close_app(name)

    @tool
    def system_report() -> str:
        """Get a spoken summary of current CPU, memory, disk, and battery status."""
        return _handler._system_report()

    @tool
    def take_screenshot() -> str:
        """Take a screenshot and save it to disk."""
        return _handler._take_screenshot()

    @tool
    def volume_up() -> str:
        """Increase system volume."""
        return _handler._volume_step(0.10)

    @tool
    def volume_down() -> str:
        """Decrease system volume."""
        return _handler._volume_step(-0.10)

    @tool
    def mute() -> str:
        """Mute system audio."""
        return _handler._set_mute(True)

    @tool
    def unmute() -> str:
        """Unmute system audio."""
        return _handler._set_mute(False)

    @tool
    def analyze_code(file_path: str) -> str:
        """Run a Python file and explain any error it produces. Requires the full file path."""
        import code_analyzer
        if not os.path.exists(file_path):
            return f"No file found at {file_path}."
        return code_analyzer.analyze(file_path)

    @tool
    def web_search(query: str) -> str:
        """Search the live web for current information — news, facts, prices, anything not in your training data."""
        import web_search_tool
        return web_search_tool.search(query)

    @tool
    def get_weather(city: str) -> str:
        """Get the current weather for a named city."""
        import weather_tool
        return weather_tool.get_weather(city)

    @tool
    def wolfram_query(query: str) -> str:
        """Answer a math, unit-conversion, or factual/computational question using Wolfram Alpha. Good for things like 'what is 15% of 340' or 'convert 5 miles to km'."""
        import wolfram_tool
        return wolfram_tool.ask_wolfram(query)

    @tool
    def check_unread_email() -> str:
        """Check unread Gmail messages and summarize the senders and subjects."""
        import gmail_integration
        return gmail_integration.get_unread_summary()

    @tool
    def check_upcoming_meetings() -> str:
        """Check upcoming Google Calendar events/meetings."""
        import calendar_integration
        return calendar_integration.get_upcoming_summary()

    tools = [open_app, close_app, system_report, take_screenshot,
             volume_up, volume_down, mute, unmute, analyze_code,
             web_search, get_weather, wolfram_query,
             check_unread_email, check_upcoming_meetings]

    try:
        llm = ChatMistralAI(model=MISTRAL_MODEL, api_key=MISTRAL_API_KEY, temperature=0.3)
        _agent = create_react_agent(llm, tools, prompt=_build_system_prompt())
        print(f"[agent] LangGraph agent ready (Mistral API model: {MISTRAL_MODEL})")
    except Exception as e:
        print(f"[agent] failed to initialize: {e}")
        _agent = None


def run(text: str) -> str:
    """Runs the agent on free text and returns a short reply. Falls
    back to a plain explanation if the agent isn't initialized or the
    Mistral API isn't reachable — and gives up after 25 seconds instead
    of hanging forever (and freezing every other command with it)."""
    if not _HAS_LANGCHAIN:
        return ("I heard that, but the AI agent isn't installed. Run "
                "'pip install langchain langgraph langchain-mistralai' to enable it.")
    if _agent is None:
        return ("I heard that, but the AI agent isn't set up yet. Get a free API "
                "key at console.mistral.ai, set MISTRAL_API_KEY, and restart Ultron.")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_agent.invoke, {"messages": [("user", text)]})
            result = future.result(timeout=25)
        messages = result.get("messages", [])
        if messages:
            content = messages[-1].content
            return content if content else "I did that, but didn't get a text reply back."
        return "I processed that, but didn't get a clear response back."
    except concurrent.futures.TimeoutError:
        return "That's taking too long — the Mistral API isn't responding. Check your internet connection and API key."
    except Exception as e:
        print(f"[agent] error: {e}")
        return f"I ran into a problem thinking that through: {e}"