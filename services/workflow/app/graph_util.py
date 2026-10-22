import copy


def render_template(template: str, run_input: str, previous: str) -> str:
    return (template or "").replace("{{input}}", run_input).replace("{{prev}}", previous)


def mask_graph(graph: dict) -> dict:
    cloned = copy.deepcopy(graph)
    for node in cloned.get("nodes", []):
        data = node.setdefault("data", {})
        if data.get("apiKey"):
            data["hasApiKey"] = True
            data["apiKey"] = ""
    return cloned


def merge_secrets(incoming: dict, previous: dict | None) -> dict:
    graph = copy.deepcopy(incoming)
    old_keys = {}
    if previous:
        for node in previous.get("nodes", []):
            secret = (node.get("data") or {}).get("apiKey") or ""
            if secret:
                old_keys[node.get("id")] = secret
    for node in graph.get("nodes", []):
        data = node.setdefault("data", {})
        api_key = data.get("apiKey") or ""
        if not api_key and data.get("hasApiKey"):
            api_key = old_keys.get(node.get("id"), "")
        if api_key:
            from app.security import encrypt_secret

            data["apiKey"] = encrypt_secret(api_key)
        data.pop("hasApiKey", None)
    return graph


def secrets_in(graph: dict) -> list[str]:
    from app.security import decrypt_secret

    values = []
    for node in graph.get("nodes", []):
        secret = decrypt_secret((node.get("data") or {}).get("apiKey") or "")
        if secret:
            values.append(secret)
    return values


def safe_error(exc: Exception, secrets: list[str]) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:500]
