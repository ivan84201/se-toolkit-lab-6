import sys
import json
from openai import OpenAI
import os
import requests
from urllib.parse import urlencode, urljoin
PROJECT_ROOT = os.getcwd()

def safe_path(path):
    normalized_path = os.path.normpath(path)
    full_path = os.path.abspath(os.path.join(PROJECT_ROOT, normalized_path))
    if not full_path.startswith(PROJECT_ROOT):
        raise ValueError("Access denied")
    return full_path

def list_files(path):
    try:
        full_path = safe_path(path)
        return "\n".join(os.listdir(full_path))
    except Exception as e:
        return f"Error: {str(e)}"

def read_file(path):
    try:
        full_path = safe_path(path)
        with open(full_path, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"

def query_api(method, path, base_url, api_key, body=None, query=None, use_auth=True):
    # ---- 1. Validate inputs ----
    if not method or not path:
        return json.dumps({
            "status_code": 400,
            "error": "Missing required 'method' or 'path'"
        })

    # Normalize method
    method = method.upper()

    # ---- 2. Validate required query params (endpoint-specific) ----
    if path.startswith("/analytics/completion-rate"):
        if not query or "lab" not in query:
            return json.dumps({
                "status_code": 400,
                "error": "Missing required query parameter: lab"
            })

    # ---- 3. Build base URL safely ----
    base_url = base_url.rstrip("/") + "/"
    path = path.lstrip("/")
    url = urljoin(base_url, path)

    # ---- 4. Attach query parameters safely ----
    if query:
        try:
            query_string = urlencode(query)
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query_string}"
        except Exception as e:
            return json.dumps({
                "status_code": 400,
                "error": f"Invalid query parameters: {str(e)}"
            })

    # ---- 5. Prepare headers ----
    headers = {
        "Content-Type": "application/json"
    }
    if use_auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"


    # ---- 6. Send request ----
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body if body else None,
            timeout=10
        )

        return json.dumps({
            "status_code": response.status_code,
            "body": response.text
        })

    except requests.exceptions.Timeout:
        return json.dumps({
            "status_code": 504,
            "error": "Request timed out"
        })

    except requests.exceptions.RequestException as e:
        return json.dumps({
            "status_code": 500,
            "error": f"Request failed: {str(e)}"
        })

def main():

    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files in a directory",
                "parameters": {
                    "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "description": "relative path from project root"
                },
                "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file contents",
                "parameters": {
                    "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "description": "relative path from project root"
                },
                "required": ["path"]
            }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "query_api",
                "description": "Send HTTP request to backend API",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "description": "HTTP method (GET, POST, etc.)"},
                        "path": {"type": "string", "description": "API path (e.g., /items/)"},
                        "description": "Absolute path",
                        "body": {"type": "string", "description": "JSON body as string"},
                        "query": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Query parameters as key-value pairs. NEVER put query params inside path.",
                            "additionalProperties": {
                                "type": "string"
                            },
                        },
                        "use_auth": {
                            "type": "boolean",
                            "description": "Whether to include API key in Authorization header (default true)"
                        }
                    },
                    "required": ["method", "path"]
                }
            }       
        },
        {
            "type": "function",
            "function": {
                "name": "provide_answer",
                "description": "Produce the final concise answer after all tool calls are done",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "final concise answer based on tool calls"},
                        "source": {"type": "string", "description": "source used for final answer. Always provide. Leave empty only in extreme cases where its not applicable."}
                    },
                    "required": ["answer"]
                }
            }
        }
    ]

    system_prompt = """
You are a strict Documentation and System Agent.

Your job is to answer questions ONLY by using tools. You must NEVER answer from prior knowledge.

--------------------------------
CORE BEHAVIOR (MANDATORY)
--------------------------------

1. You MUST call tools before answering.
2. You MUST NOT provide any plain text responses.
3. Every response MUST be a raw JSON tool call.
4. The final answer MUST be produced using provide_answer().
5. Maximum 10 tool calls total.

--------------------------------
TOOL USAGE STRATEGY
--------------------------------

For documentation questions:
- ALWAYS start with: list_files("wiki")
- Read relevant files using read_file
- Extract the exact answer from documentation

For system / API questions:
- Use query_api to get live data
- Example: counts, scores, dynamic values
- NEVER include query parameters inside the path string
- ALWAYS use the "query" field for query parameters

For code / implementation questions:
- Use list_files + read_file on source files (not wiki)
- To list source files use list_files with path "."

--------------------------------
SOURCE RULES (VERY IMPORTANT)
--------------------------------

- If answer comes from documentation:
  MUST include source in this format:
  "wiki/<file>.md#<section-anchor>"

- NEVER omit source for documentation answers

- If answer comes ONLY from query_api:
  source MAY be empty

- Do NOT invent sources

--------------------------------
TOOL DEFINITIONS
--------------------------------

list_files(path)
- Lists files in a directory

read_file(path)
- Reads file contents

query_api(method, path, body)
- Calls backend API
- Returns JSON string with status_code and body

provide_answer(answer, source)
- Final step ONLY
- answer: concise final answer
- source: required unless using only query_api
- Optionally set "use_auth" to False if no authorization is needed

--------------------------------
DECISION RULES
--------------------------------

- If you don’t know where the answer is → call list_files
- If documentation might exist → ALWAYS check wiki first
- Do NOT guess
- Do NOT skip tool usage

--------------------------------
FINAL STEP
--------------------------------

When you have enough information:
→ call provide_answer()

DO NOT output text
DO NOT explain reasoning
ONLY call tools

--------------------------------
TOOL CALL EXAMPLES
--------------------------------

List files:

{
  "tool": "list_files",
  "function": {
    "name": "list_files",
    "arguments": {"path": "backend/app/routers"}
  }
}

Read a file:

{
  "tool": "read_file",
  "function": {
    "name": "read_file",
    "arguments": {"path": "backend/app/routers/items.py"}
  }
}

Call backend API:

{
  "tool": "query_api",
  "function": {
    "name": "query_api",
    "arguments": {
      "method": "GET",
      "path": "/items/",
      "query": {"lab": "lab1"},
      "use_auth": true
    }
  }
}

Provide answer:

{
  "tool": "provide_answer",
  "function": {
    "name": "provide_answer",
    "arguments": {
      "answer": "The backend contains the following API router modules:\n\n- interactions.py — handles user interactions endpoints.\n- pipeline.py — handles data pipeline-related endpoints.\n- analytics.py — handles analytics endpoints.\n- learners.py — handles learner management endpoints.\n- items.py — handles item management endpoints.",
      "source": "backend/app/routers"
    }
  }
}
"""

    if len(sys.argv) < 2:
        print("No input provided")
        return

    user_input = sys.argv[1]

    config = {}
    with open(".env.agent.secret", "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()

    api_key = config.get("LLM_API_KEY")
    base_url = config.get("LLM_API_BASE")
    model = config.get("LLM_MODEL")

    config = {}
    with open(".env.docker.secret", "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()

    lms_api_key = config.get("LMS_API_KEY")
    agent_api_base_url = config.get("AGENT_API_BASE_URL", "http://localhost:42002")

    if not api_key or not base_url or not model:
        raise ValueError("Missing LLM environment variables")

    if not lms_api_key:
        raise ValueError("Missing LMS_API_KEY")

    client = OpenAI(api_key=api_key, base_url=base_url)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    tool_calls_log = []

    for _ in range(20):

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0,
            response_format={"type": "json_object"},
            function_call="auto"
        )

        message = response.choices[0].message

        tool_calls = getattr(message, "tool_calls", []) or []

        '''if not tool_calls:
            # Model did not produce a tool call, return safe JSON
            print(json.dumps({
                "answer": "Model did not return a tool call",
                "source": "unknown",
                "tool_calls": tool_calls_log
            }, indent=2))
            return'''
        

        # CASE 1: TOOL CALL
        if message.tool_calls:
            messages.append(message)

            for tool_call in message.tool_calls:
                raw_args = tool_call.function.arguments
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}

                name = tool_call.function.name

                if name == "list_files":
                    result = list_files(args["path"])
                elif name == "read_file":
                    result = read_file(args["path"])
                elif name == "query_api":
                    result = query_api(
                        args["method"],
                        args["path"],
                        base_url=agent_api_base_url,
                        api_key=lms_api_key,
                        body=args.get("body"),
                        query=args.get("query"),
                        use_auth=args.get("use_auth", True) 
                    )
                elif name == "provide_answer":
                    answer = args.get("answer", "")
                    source = args.get("source", "")

                    # Safety net: require at least one tool call
                    if not tool_calls_log:
                        messages.append({"role": "system", "content": "You must call tools before answering."})
                        continue

                    # Determine if query_api was used
                    used_query_api = any(tc["tool"] == "query_api" for tc in tool_calls_log)

                    # Enforce source requirement
                    if not used_query_api and not source:
                        messages.append({"role": "system", "content": "Final answer must include 'source' field when not using query_api."})
                        continue

                    output = {
                        "answer": answer,
                        "source": source if source else "",
                        "tool_calls": tool_calls_log
                    }

                    print(json.dumps(output, indent=2))
                    return
                else:
                    result = "Unknown tool"

                tool_calls_log.append({
                    "tool": name,
                    "args": args,
                    "result": result
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

            continue
        
        else:
            messages.append({
            "role": "system",
            "content": (
                "ERROR. Output MUST be a raw JSON tool call. If you want to provide final answer, use provide_answer function.")
            })

    output = {
        "answer": "Unable to find answer within tool call limit.",
        "source": "unknown",
        "tool_calls": tool_calls_log
    }

    print(json.dumps(output, indent=2))
if __name__ == "__main__":
    main()