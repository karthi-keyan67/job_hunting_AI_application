import re
from collections.abc import Iterable


SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "postgresql": ("postgresql", "postgres"),
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "python": ("python",), "fastapi": ("fastapi",),
    "langchain": ("langchain",), "langgraph": ("langgraph",),
    "llamaindex": ("llamaindex", "llama index"),
    "retrieval augmented generation": ("retrieval-augmented generation", "retrieval augmented generation", "rag"),
    "machine learning": ("machine learning", "ml"),
    "large language models": ("large language model", "large language models", "llm", "llms"),
    "react": ("react", "reactjs", "react.js"), "node.js": ("node.js", "nodejs", "node js"),
    "c++": ("c++",), "c#": ("c#", "c sharp"), ".net": (".net", "dotnet"),
    "sql": ("sql",), "docker": ("docker",), "kubernetes": ("kubernetes", "k8s"),
    "aws": ("aws", "amazon web services"), "azure": ("azure", "microsoft azure"),
    "gcp": ("gcp", "google cloud platform"), "redis": ("redis",),
    "git": ("git",), "linux": ("linux",), "java": ("java",),
    "go": ("golang", "go language"), "rust": ("rust",), "django": ("django",),
    "flask": ("flask",), "pytorch": ("pytorch",), "tensorflow": ("tensorflow",),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "pandas": ("pandas",), "spark": ("apache spark", "spark"),
}


def normalize_skill(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip().casefold())
    for canonical, aliases in SKILL_ALIASES.items():
        if cleaned == canonical or cleaned in aliases:
            return canonical
    return cleaned


def normalize_skills(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(normalize_skill(value) for value in values if value and value.strip()))


def extract_resume_skills(text: str) -> tuple[list[str], dict[str, str]]:
    found: list[str] = []
    evidence: dict[str, str] = {}
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            pattern = re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                found.append(canonical)
                line = text[max(0, text.rfind("\n", 0, match.start()) + 1):text.find("\n", match.end()) if "\n" in text[match.end():] else len(text)].strip()
                evidence[canonical] = line[:500]
                break
    return list(dict.fromkeys(found)), evidence


def overlap_score(left: Iterable[str], right: Iterable[str]) -> float | None:
    a = {token for value in left for token in re.findall(r"[a-z0-9+#.]+", value.casefold()) if len(token) > 1}
    b = {token for value in right for token in re.findall(r"[a-z0-9+#.]+", value.casefold()) if len(token) > 1}
    if not a or not b:
        return None
    return 100 * len(a & b) / len(a)
