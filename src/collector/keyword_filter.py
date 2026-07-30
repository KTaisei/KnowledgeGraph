import wikipediaapi
from typing import List

def filter_skills_by_keyword(skills: List[str], keywords: List[str]) -> List[str]:
    """Filter a list of skill page titles, keeping only those whose Wikipedia
    page content contains at least one of the specified keywords.

    Args:
        skills: List of Wikipedia page titles representing candidate skills.
        keywords: List of keywords to search for within the page text.

    Returns:
        A filtered list of skill titles where the page text includes any keyword.
    """
    if not keywords:
        return skills
    wiki = wikipediaapi.Wikipedia(user_agent="KnowledgeGraphCollector/1.0 (no-llm; local research tool)", language="ja")
    filtered: List[str] = []
    for skill in skills:
        try:
            page = wiki.page(skill)
            if not page.exists():
                continue
            text = page.text or ""
            if any(kw in text for kw in keywords):
                filtered.append(skill)
        except Exception:
            continue
    return filtered
