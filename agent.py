import sys
import json
from openai import OpenAI
import os

PROJECT_ROOT = os.getcwd()

def safe_path(path):
    full_path = os.path.abspath(os.path.join(PROJECT_ROOT, path))
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
                    "path": {"type": "string"}
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
                    "path": {"type": "string"}
                },
                "required": ["path"]
            }
        }
    }
]

    system_prompt = """You are a documentation agent.

    You MUST:
    - Use list_files to explore the wiki directory
    - Use read_file to read relevant files
    - Find the exact answer from documentation
    - Include source as: file_path#section-anchor

    Final output MUST be valid JSON in this format:
    {
    "answer": "...",
    "source": "wiki/file.md#section"
    }

    Rules:
    - Do NOT guess
    - Always use tools before answering
    - Final answer must be concise
    - ALWAYS start by calling list_files with path="wiki"
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

    if not api_key or not base_url or not model:
        raise ValueError("One of API_KEY, LLM_API_BASE, or LLM_MODEL is missing in .env.agent.secret")

    client = OpenAI(api_key=api_key, base_url=base_url)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    tool_calls_log = []

    for _ in range(10):

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0,
            response_format={"type": "json_object"}
        )

        message = response.choices[0].message

    # CASE 1: TOOL CALL
        if message.tool_calls:
            messages.append(message)

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if name == "list_files":
                    result = list_files(args["path"])
                elif name == "read_file":
                    result = read_file(args["path"])
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

        # ✅ CASE 2: FINAL ANSWER
        else:
            final_text = message.content

            # Expect JSON from model
            try:
                parsed = json.loads(final_text)
                answer = parsed.get("answer", "")
                source = parsed.get("source", "")
            except:
                answer = final_text
                source = ""

            output = {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log
            }

            print(json.dumps(output, indent=2))
            return

    output = {
        "answer": "Unable to find answer within tool call limit.",
        "source": "unknown",
        "tool_calls": tool_calls_log
    }

    print(json.dumps(output, indent=2))
if __name__ == "__main__":
    main()